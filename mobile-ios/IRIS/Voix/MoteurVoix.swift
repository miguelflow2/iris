// MoteurVoix.swift — écouter et parler sur l'iPhone, en passant par les lunettes.
//
// Ce qui est fait, et ses limites réelles :
// - la reconnaissance se fait SUR L'IPHONE (requiresOnDeviceRecognition) : le son ne part ni chez
//   Apple ni chez VELA ; seul le texte reconnu part à l'ordinateur. Si l'iPhone n'a pas la
//   reconnaissance sur l'appareil pour une langue, on le dit au lieu de basculer en ligne ;
// - « Dis-moi Iris » est écouté seulement quand l'app est AU PREMIER PLAN. iOS ne permet à aucune
//   app tierce d'écouter un mot d'activation écran verrouillé ou en arrière-plan : c'est réservé à
//   Siri (voir mobile-ios/REALITE-IOS.md, point 8). La session de reconnaissance est relancée toutes
//   les ~55 s, par prudence envers les limites de durée d'une tâche de reconnaissance ;
// - pendant que l'iPhone parle, il n'écoute pas (sinon IRIS s'entendrait elle-même) ;
// - le débit suit tts_rate/185, mais la voix d'iOS plafonne : au-delà d'environ 2×, elle ne va pas
//   plus vite (AVSpeechUtteranceMaximumSpeechRate).
//
// Les rappels de Speech et d'AVFoundation arrivent sur des files quelconques : ils sont fabriqués
// par des fonctions `nonisolated` et ne touchent l'état qu'après un saut sur le MainActor.

import AVFoundation
import Foundation
import Observation
import Speech
import UIKit

enum ErreurVoix: Error, LocalizedError {
    case autorisationRefusee(String)
    case langueNonReconnue(String)
    case micro(String)
    case rienEntendu
    case interrompu

    var errorDescription: String? {
        switch self {
        case .autorisationRefusee(let m), .micro(let m):
            return m
        case .langueNonReconnue(let langue):
            return "Cet iPhone ne reconnaît pas la parole en \(MoteurVoix.nomLangue(langue)) sans Internet. Écris la phrase, ou ajoute la langue dans Réglages › Général › Clavier › Dictée."
        case .rienEntendu:
            return "Je n'ai rien entendu."
        case .interrompu:
            return "Écoute arrêtée."
        }
    }
}

@MainActor
@Observable
final class MoteurVoix: ServiceVoix {
    private(set) var etat: EtatVoix = .inactive
    private(set) var partiel: String = ""
    /// L'utilisateur a demandé l'écoute de « Dis-moi Iris » (réglage local, retenu sur l'iPhone).
    private(set) var motActivationVoulu: Bool
    /// Dernière phrase dite par IRIS sur cet iPhone, pour « Relire ».
    private(set) var derniereParole: String = ""

    /// Multiplicateur de débit (tts_rate / 185), mis à jour depuis les réglages du PC.
    var debitUtilisateur: Double = 1.0
    var motActivation: String = "Dis-moi Iris"
    /// Langue d'IRIS pour la reconnaissance et la voix (BCP 47).
    var langueIRIS: String = "fr-CA"

    /// Commande entendue après le mot d'activation -> phrase à lire (nil : rien à dire).
    @ObservationIgnored var surCommande: (@MainActor (String) async -> String?)?
    /// Garde appelée avant d'écouter : nil si la voix est permise, sinon la raison (lunettes absentes…).
    @ObservationIgnored var refusVoix: (@MainActor () -> String?)?

    @ObservationIgnored private let synthese = AVSpeechSynthesizer()
    @ObservationIgnored private let delegue = DelegueSynthese()
    @ObservationIgnored private let moteurAudio = AVAudioEngine()
    @ObservationIgnored private var reconnaisseur: SFSpeechRecognizer?
    @ObservationIgnored private var requeteReco: SFSpeechAudioBufferRecognitionRequest?
    @ObservationIgnored private var tacheReco: SFSpeechRecognitionTask?
    @ObservationIgnored private var generation = 0
    @ObservationIgnored private var relance: Task<Void, Never>?
    @ObservationIgnored private var veilleur: Task<Void, Never>?
    @ObservationIgnored private var attentePhrase: AttentePhrase?
    @ObservationIgnored private var auPremierPlan = true
    @ObservationIgnored private var parleEnCours = 0
    @ObservationIgnored private var commandeEnTraitement = false
    @ObservationIgnored private var erreursRecentes: [Date] = []
    @ObservationIgnored private var derniereModification = Date()
    @ObservationIgnored private var debutCommande = Date()
    @ObservationIgnored private var debutSession = Date()
    @ObservationIgnored private var observateurs: [NSObjectProtocol] = []

    private static let cleMotActivation = "iris_mot_activation_voulu"
    private static let dureeSession: Duration = .seconds(55)
    private static let silenceFinCommande: TimeInterval = 1.4
    private static let attenteCommandeVide: TimeInterval = 7
    private static let dureeCommandeMax: TimeInterval = 30

    init() {
        motActivationVoulu = UserDefaults.standard.bool(forKey: Self.cleMotActivation)
        synthese.delegate = delegue
        let centre = NotificationCenter.default
        observateurs.append(centre.addObserver(forName: AVAudioSession.interruptionNotification,
                                               object: nil, queue: .main) { [weak self] note in
            let brut = note.userInfo?[AVAudioSessionInterruptionTypeKey] as? UInt
            guard let self else { return }
            Task { @MainActor in self.interruption(debut: brut == AVAudioSession.InterruptionType.began.rawValue) }
        })
        observateurs.append(centre.addObserver(forName: AVAudioSession.routeChangeNotification,
                                               object: nil, queue: .main) { [weak self] note in
            let brut = note.userInfo?[AVAudioSessionRouteChangeReasonKey] as? UInt
            guard let self else { return }
            Task { @MainActor in self.routeChangee(raison: brut) }
        })
    }

    // MARK: - Autorisations

    func demanderAutorisations() async -> String? {
        let micro = await AVAudioApplication.requestRecordPermission()
        guard micro else {
            return "Micro refusé pour IRIS. Réglages › IRIS › Micro."
        }
        let statut = await Self.demanderReconnaissance()
        switch statut {
        case .authorized:
            return nil
        case .denied:
            return "Reconnaissance vocale refusée pour IRIS. Réglages › IRIS › Reconnaissance vocale."
        case .restricted:
            return "La reconnaissance vocale est bloquée sur cet iPhone (restrictions ou gestion de l'appareil)."
        case .notDetermined:
            return "Autorisation de reconnaissance vocale non accordée."
        @unknown default:
            return "Autorisation de reconnaissance vocale inconnue."
        }
    }

    nonisolated private static func demanderReconnaissance() async -> SFSpeechRecognizerAuthorizationStatus {
        let actuel = SFSpeechRecognizer.authorizationStatus()
        if actuel != .notDetermined { return actuel }
        return await withCheckedContinuation { continuation in
            SFSpeechRecognizer.requestAuthorization { statut in
                continuation.resume(returning: statut)
            }
        }
    }

    // MARK: - Parler

    func parler(_ texte: String, langue: String?, debit: Double?) async {
        let propre = texte.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !propre.isEmpty else { return }
        let reprendreVeille = etat == .veille
        if etat == .veille { fermerReconnaissance() }
        do {
            try SessionAudio.activer()
        } catch {
            // Sans session audio, AVSpeechSynthesizer tente quand même la sortie par défaut.
        }
        let enonce = AVSpeechUtterance(string: propre)
        let code = langue ?? langueIRIS
        enonce.voice = Self.voix(pour: code)
        enonce.rate = Self.debitApple(facteur: debit ?? debitUtilisateur)
        derniereParole = propre
        parleEnCours += 1
        etat = .parle
        await withCheckedContinuation { (continuation: CheckedContinuation<Void, Never>) in
            delegue.attendre(enonce, continuation)
            synthese.speak(enonce)
        }
        parleEnCours -= 1
        if parleEnCours == 0 && etat == .parle {
            etat = commandeEnTraitement ? .reflexion : .inactive
        }
        if reprendreVeille { await relancerVeille() }
    }

    func arreterParole() {
        if synthese.isSpeaking {
            synthese.stopSpeaking(at: .immediate)
        }
    }

    nonisolated static func voix(pour code: String) -> AVSpeechSynthesisVoice? {
        let prefixe = String(code.prefix(2)).lowercased()
        let candidates = AVSpeechSynthesisVoice.speechVoices()
        let exactes = candidates.filter { $0.language.caseInsensitiveCompare(code) == .orderedSame }
        let proches = candidates.filter { $0.language.lowercased().hasPrefix(prefixe) }
        // Meilleure qualité d'abord (premium > améliorée > par défaut).
        let tri: (AVSpeechSynthesisVoice, AVSpeechSynthesisVoice) -> Bool = { $0.quality.rawValue > $1.quality.rawValue }
        return exactes.sorted(by: tri).first ?? proches.sorted(by: tri).first ?? AVSpeechSynthesisVoice(language: code)
    }

    nonisolated static func voixDisponible(pour code: String) -> Bool {
        let prefixe = String(code.prefix(2)).lowercased()
        return AVSpeechSynthesisVoice.speechVoices().contains { $0.language.lowercased().hasPrefix(prefixe) }
    }

    nonisolated static func debitApple(facteur: Double) -> Float {
        let borne = min(max(facteur, 0.5), 3.0)
        let valeur = AVSpeechUtteranceDefaultSpeechRate * Float(borne)
        return min(max(valeur, AVSpeechUtteranceMinimumSpeechRate), AVSpeechUtteranceMaximumSpeechRate)
    }

    /// Le débit réellement appliqué, en multiplicateur, pour l'afficher honnêtement.
    nonisolated static func facteurReel(facteur: Double) -> Double {
        Double(debitApple(facteur: facteur) / AVSpeechUtteranceDefaultSpeechRate)
    }

    // MARK: - Écouter une phrase (interprète, bouton « Parler »)

    func ecouterUnePhrase(langue: String, delaiMax: TimeInterval) async throws -> String {
        if let raison = await demanderAutorisations() { throw ErreurVoix.autorisationRefusee(raison) }
        let veilleAvant = motActivationVoulu
        attentePhrase?.conclure(.failure(ErreurVoix.interrompu))
        fermerReconnaissance()
        arreterParole()

        if etat == .veille || etat == .commande { etat = .inactive }

        let attente = AttentePhrase()
        attentePhrase = attente
        partiel = ""
        do {
            try ouvrirReconnaissance(langue: langue, ponctuation: true, surResultat: { [weak self] texte, _, final in
                guard let self else { return }
                if texte != attente.dernierTexte {
                    attente.dernierTexte = texte
                    attente.derniereModification = Date()
                    self.partiel = texte
                }
                if final, !texte.isEmpty { attente.conclure(.success(texte)) }
            }, surErreur: { _ in
                if attente.dernierTexte.isEmpty {
                    attente.conclure(.failure(ErreurVoix.rienEntendu))
                } else {
                    attente.conclure(.success(attente.dernierTexte))
                }
            })
        } catch {
            attentePhrase = nil
            if veilleAvant { Task { await self.relancerVeille() } }
            throw error
        }
        etat = .commande
        let debut = Date()
        veilleur = Task {
            while !attente.termine {
                try? await Task.sleep(for: .milliseconds(250))
                if Task.isCancelled { return }
                let silence = Date().timeIntervalSince(attente.derniereModification)
                if !attente.dernierTexte.isEmpty && silence >= Self.silenceFinCommande + 0.1 {
                    attente.conclure(.success(attente.dernierTexte))
                } else if attente.dernierTexte.isEmpty && Date().timeIntervalSince(debut) >= delaiMax {
                    attente.conclure(.failure(ErreurVoix.rienEntendu))
                } else if Date().timeIntervalSince(debut) >= Self.dureeCommandeMax {
                    attente.conclure(.success(attente.dernierTexte))
                }
            }
        }

        let resultat: Result<String, Error>
        do {
            let texte = try await withCheckedThrowingContinuation { (continuation: CheckedContinuation<String, Error>) in
                attente.attacher(continuation)
            }
            resultat = .success(texte)
        } catch {
            resultat = .failure(error)
        }
        if attentePhrase === attente {
            attentePhrase = nil
            fermerReconnaissance()
            etat = .inactive
            partiel = ""
        }
        if veilleAvant { Task { await self.relancerVeille() } }
        return try resultat.get()
    }

    /// Bouton « Arrêter » pendant une écoute dirigée.
    func annulerEcoute() {
        attentePhrase?.conclure(.failure(ErreurVoix.interrompu))
    }

    // MARK: - Mot d'activation (premier plan seulement)

    func demarrerMotActivation() {
        motActivationVoulu = true
        UserDefaults.standard.set(true, forKey: Self.cleMotActivation)
        erreursRecentes.removeAll()
        Task { await relancerVeille() }
    }

    func arreterMotActivation() {
        motActivationVoulu = false
        UserDefaults.standard.set(false, forKey: Self.cleMotActivation)
        if attentePhrase == nil && (etat == .veille || etat == .commande) {
            fermerReconnaissance()
            etat = .inactive
            partiel = ""
        } else if case .indisponible = etat {
            etat = .inactive
        }
    }

    /// L'app passe en arrière-plan : on coupe le micro (iOS ne permet pas mieux, et on ne le veut pas).
    func passerEnArrierePlan() {
        auPremierPlan = false
        attentePhrase?.conclure(.failure(ErreurVoix.interrompu))
        if etat == .veille || etat == .commande {
            fermerReconnaissance()
            etat = .inactive
            partiel = ""
        }
    }

    func revenirAuPremierPlan() {
        auPremierPlan = true
        if motActivationVoulu { Task { await relancerVeille() } }
    }

    /// (Re)lance l'écoute du mot d'activation si toutes les conditions sont réunies.
    func relancerVeille() async {
        guard motActivationVoulu, auPremierPlan, attentePhrase == nil, parleEnCours == 0, !commandeEnTraitement else { return }
        if let refus = refusVoix?() {
            fermerReconnaissance()
            etat = .indisponible(raison: refus)
            // La condition peut changer (lunettes connectées, PC revenu) : on réessaie plus tard.
            relance?.cancel()
            relance = Task { [weak self] in
                try? await Task.sleep(for: .seconds(15))
                if Task.isCancelled { return }
                await self?.relancerVeille()
            }
            return
        }
        if let raison = await demanderAutorisations() {
            etat = .indisponible(raison: raison)
            return
        }
        guard motActivationVoulu, auPremierPlan, attentePhrase == nil, parleEnCours == 0, !commandeEnTraitement else { return }
        do {
            try ouvrirReconnaissance(langue: langueIRIS, ponctuation: false, surResultat: { [weak self] _, segments, final in
                self?.resultatVeille(segments: segments, final: final)
            }, surErreur: { [weak self] _ in
                self?.erreurVeille()
            })
            etat = .veille
            partiel = ""
            debutSession = Date()
            relance?.cancel()
            relance = Task { [weak self] in
                try? await Task.sleep(for: Self.dureeSession)
                guard let self, !Task.isCancelled else { return }
                // Nouvelle tâche : relanceProgrammee annule `relance`, donc la tâche courante.
                Task { await self.relanceProgrammee() }
            }
        } catch {
            etat = .indisponible(raison: error.localizedDescription)
        }
    }

    private func relanceProgrammee() async {
        guard etat == .veille else { return }
        fermerReconnaissance()
        await relancerVeille()
    }

    private func resultatVeille(segments: [String], final: Bool) {
        guard etat == .veille || etat == .commande else { return }
        guard let commande = MotActivation.commande(apres: segments, motActivation: motActivation) else {
            if final && etat == .veille {
                fermerReconnaissance()
                Task { await relancerVeille() }
            }
            return
        }
        if etat == .veille {
            etat = .commande
            debutCommande = Date()
            relance?.cancel()
            signalerReveil()
            demarrerVeilleurCommande()
        }
        if commande != partiel {
            partiel = commande
            derniereModification = Date()
        }
        if final {
            if commande.isEmpty {
                // La session s'est close juste après « Dis-moi Iris » : on rouvre une écoute où tout
                // ce qui est dit est la commande, sans redemander le mot d'activation.
                ouvrirEcouteCommande()
            } else {
                Task { await terminerCommande() }
            }
        }
    }

    private func ouvrirEcouteCommande() {
        do {
            try ouvrirReconnaissance(langue: langueIRIS, ponctuation: false, surResultat: { [weak self] texte, _, final in
                guard let self, self.etat == .commande else { return }
                if texte != self.partiel {
                    self.partiel = texte
                    self.derniereModification = Date()
                }
                if final && !texte.isEmpty { Task { await self.terminerCommande() } }
            }, surErreur: { [weak self] _ in
                self?.erreurVeille()
            })
            etat = .commande
            debutCommande = Date()
            demarrerVeilleurCommande()
        } catch {
            etat = .indisponible(raison: error.localizedDescription)
        }
    }

    /// Le mot d'activation a été entendu : une vibration (l'écran n'est pas forcément regardé).
    private func signalerReveil() {
        let retour = UIImpactFeedbackGenerator(style: .medium)
        retour.impactOccurred()
    }

    private func demarrerVeilleurCommande() {
        veilleur?.cancel()
        derniereModification = Date()
        veilleur = Task { [weak self] in
            while !Task.isCancelled {
                try? await Task.sleep(for: .milliseconds(250))
                guard let self, !Task.isCancelled, self.etat == .commande, self.attentePhrase == nil else { return }
                let maintenant = Date()
                // Toujours dans une NOUVELLE tâche : terminerCommande ferme la reconnaissance, ce qui
                // annule ce veilleur ; l'envoi au PC fait dans une tâche annulée échouerait aussitôt.
                if !self.partiel.isEmpty && maintenant.timeIntervalSince(self.derniereModification) >= Self.silenceFinCommande {
                    Task { await self.terminerCommande() }
                    return
                }
                if self.partiel.isEmpty && maintenant.timeIntervalSince(self.debutCommande) >= Self.attenteCommandeVide {
                    self.fermerReconnaissance()
                    self.etat = .inactive
                    Task { await self.relancerVeille() }
                    return
                }
                if maintenant.timeIntervalSince(self.debutCommande) >= Self.dureeCommandeMax {
                    Task { await self.terminerCommande() }
                    return
                }
            }
        }
    }

    private func terminerCommande() async {
        guard etat == .commande, attentePhrase == nil, !commandeEnTraitement else { return }
        let commande = partiel.trimmingCharacters(in: .whitespacesAndNewlines)
        fermerReconnaissance()
        guard !commande.isEmpty else {
            etat = .inactive
            await relancerVeille()
            return
        }
        commandeEnTraitement = true
        etat = .reflexion
        let reponse = await surCommande?(commande)
        commandeEnTraitement = false
        partiel = ""
        if let reponse, !reponse.isEmpty {
            await parler(reponse, langue: nil, debit: nil)
        }
        if etat == .reflexion || etat == .parle { etat = .inactive }
        await relancerVeille()
    }

    private func erreurVeille() {
        let maintenant = Date()
        // Seules les sessions qui échouent dès l'ouverture comptent : une session qui s'arrête après un
        // long silence est normale et se relance simplement.
        erreursRecentes = erreursRecentes.filter { maintenant.timeIntervalSince($0) < 30 }
        if maintenant.timeIntervalSince(debutSession) < 3 { erreursRecentes.append(maintenant) }
        if etat == .commande && !partiel.isEmpty {
            Task { await terminerCommande() }
            return
        }
        fermerReconnaissance()
        guard erreursRecentes.count <= 5 else {
            etat = .indisponible(raison: "La reconnaissance vocale s'est arrêtée plusieurs fois de suite. Touche « Dis-moi Iris » pour réessayer.")
            motActivationVoulu = false
            UserDefaults.standard.set(false, forKey: Self.cleMotActivation)
            return
        }
        etat = .inactive
        relance?.cancel()
        relance = Task { [weak self] in
            try? await Task.sleep(for: .seconds(1))
            if Task.isCancelled { return }
            await self?.relancerVeille()
        }
    }

    private func interruption(debut: Bool) {
        if debut {
            // Appel entrant, alarme… : le micro nous est retiré.
            attentePhrase?.conclure(.failure(ErreurVoix.interrompu))
            if etat == .veille || etat == .commande {
                fermerReconnaissance()
                etat = .inactive
            }
        } else if motActivationVoulu {
            Task { await relancerVeille() }
        }
    }

    private func routeChangee(raison brut: UInt?) {
        // Lunettes connectées ou retirées pendant l'écoute : le format du micro change, et un
        // robinet posé avec l'ancien format ferait planter le moteur audio. On relance proprement.
        // Seulement pour un appareil branché ou retiré : notre propre réglage de la session
        // (changement de catégorie) déclenche aussi cet avis, et relancer ici bouclerait sans fin.
        guard let brut, let raison = AVAudioSession.RouteChangeReason(rawValue: brut),
              raison == .newDeviceAvailable || raison == .oldDeviceUnavailable else { return }
        guard etat == .veille, attentePhrase == nil else { return }
        fermerReconnaissance()
        Task { await relancerVeille() }
    }

    // MARK: - Reconnaissance (commun)

    private func ouvrirReconnaissance(langue: String, ponctuation: Bool,
                                      surResultat: @escaping @MainActor (String, [String], Bool) -> Void,
                                      surErreur: @escaping @MainActor (Error) -> Void) throws {
        fermerReconnaissance()
        guard let reco = SFSpeechRecognizer(locale: Locale(identifier: langue)) else {
            throw ErreurVoix.langueNonReconnue(langue)
        }
        guard reco.supportsOnDeviceRecognition else {
            throw ErreurVoix.langueNonReconnue(langue)
        }
        guard reco.isAvailable else {
            throw ErreurVoix.micro("La reconnaissance vocale est momentanément indisponible sur cet iPhone.")
        }
        do {
            try SessionAudio.activer()
        } catch {
            throw ErreurVoix.micro("Le micro est occupé par une autre app ou un appel.")
        }

        let requete = SFSpeechAudioBufferRecognitionRequest()
        requete.requiresOnDeviceRecognition = true
        requete.shouldReportPartialResults = true
        requete.taskHint = ponctuation ? .dictation : .search
        requete.addsPunctuation = ponctuation

        let entree = moteurAudio.inputNode
        let format = entree.outputFormat(forBus: 0)
        guard format.sampleRate > 0, format.channelCount > 0 else {
            throw ErreurVoix.micro("Aucun micro disponible.")
        }
        entree.removeTap(onBus: 0)
        entree.installTap(onBus: 0, bufferSize: 1024, format: format, block: Self.robinet(vers: requete))
        moteurAudio.prepare()
        do {
            try moteurAudio.start()
        } catch {
            entree.removeTap(onBus: 0)
            throw ErreurVoix.micro("Le micro n'a pas pu démarrer (\(error.localizedDescription)).")
        }

        generation += 1
        reconnaisseur = reco
        requeteReco = requete
        tacheReco = reco.recognitionTask(with: requete,
                                         resultHandler: Self.gestionnaire(moteur: self, generation: generation,
                                                                          surResultat: surResultat, surErreur: surErreur))
    }

    nonisolated private static func robinet(vers requete: SFSpeechAudioBufferRecognitionRequest) -> AVAudioNodeTapBlock {
        return { tampon, _ in
            requete.append(tampon)
        }
    }

    nonisolated private static func gestionnaire(
        moteur: MoteurVoix, generation: Int,
        surResultat: @escaping @MainActor (String, [String], Bool) -> Void,
        surErreur: @escaping @MainActor (Error) -> Void
    ) -> (SFSpeechRecognitionResult?, Error?) -> Void {
        return { [weak moteur] resultat, erreur in
            let texte = resultat?.bestTranscription.formattedString
            let segments = resultat?.bestTranscription.segments.map { $0.substring } ?? []
            let final = resultat?.isFinal ?? false
            let erreurRecue = erreur
            guard let moteurFort = moteur else { return }
            Task { @MainActor in
                guard moteurFort.generation == generation else { return }
                if let texte { surResultat(texte, segments, final) }
                if let erreurRecue, !(final && texte != nil) { surErreur(erreurRecue) }
            }
        }
    }

    private func fermerReconnaissance() {
        generation += 1
        relance?.cancel()
        relance = nil
        if attentePhrase == nil {
            veilleur?.cancel()
            veilleur = nil
        }
        tacheReco?.cancel()
        tacheReco = nil
        requeteReco?.endAudio()
        requeteReco = nil
        if moteurAudio.isRunning {
            moteurAudio.stop()
        }
        moteurAudio.inputNode.removeTap(onBus: 0)
        reconnaisseur = nil
    }

    // MARK: - Langues

    nonisolated static func nomLangue(_ code: String) -> String {
        switch code.prefix(2).lowercased() {
        case "fr": return "français"
        case "en": return "anglais"
        case "es": return "espagnol"
        case "pt": return "portugais"
        case "it": return "italien"
        case "de": return "allemand"
        default: return code
        }
    }

    /// Code court du service (« en ») -> langue de reconnaissance et de voix de l'iPhone.
    nonisolated static func localePreferee(_ code: String) -> String {
        let candidates: [String]
        switch code.prefix(2).lowercased() {
        case "fr": candidates = ["fr-CA", "fr-FR"]
        case "en": candidates = ["en-CA", "en-US", "en-GB"]
        case "es": candidates = ["es-MX", "es-US", "es-ES"]
        case "pt": candidates = ["pt-BR", "pt-PT"]
        case "it": candidates = ["it-IT"]
        case "de": candidates = ["de-DE"]
        default: candidates = [code]
        }
        for candidate in candidates {
            if let reco = SFSpeechRecognizer(locale: Locale(identifier: candidate)), reco.supportsOnDeviceRecognition {
                return candidate
            }
        }
        return candidates.first ?? code
    }
}

// MARK: - Attente d'une phrase

@MainActor
private final class AttentePhrase {
    private var continuation: CheckedContinuation<String, Error>?
    private var resultat: Result<String, Error>?
    var dernierTexte = ""
    var derniereModification = Date()

    var termine: Bool { resultat != nil }

    func attacher(_ continuation: CheckedContinuation<String, Error>) {
        if let resultat {
            continuation.resume(with: resultat)
        } else {
            self.continuation = continuation
        }
    }

    func conclure(_ nouveau: Result<String, Error>) {
        guard resultat == nil else { return }
        resultat = nouveau
        continuation?.resume(with: nouveau)
        continuation = nil
    }
}

// MARK: - Fin de lecture

/// AVSpeechSynthesizer prévient par délégué ; on transforme ces rappels en `await`.
final class DelegueSynthese: NSObject, AVSpeechSynthesizerDelegate {
    private var attentes: [ObjectIdentifier: CheckedContinuation<Void, Never>] = [:]
    private let verrou = NSLock()

    func attendre(_ enonce: AVSpeechUtterance, _ continuation: CheckedContinuation<Void, Never>) {
        verrou.lock()
        attentes[ObjectIdentifier(enonce)] = continuation
        verrou.unlock()
    }

    private func finir(_ enonce: AVSpeechUtterance) {
        verrou.lock()
        let continuation = attentes.removeValue(forKey: ObjectIdentifier(enonce))
        verrou.unlock()
        continuation?.resume()
    }

    func speechSynthesizer(_ synthesizer: AVSpeechSynthesizer, didFinish utterance: AVSpeechUtterance) {
        finir(utterance)
    }

    func speechSynthesizer(_ synthesizer: AVSpeechSynthesizer, didCancel utterance: AVSpeechUtterance) {
        finir(utterance)
    }
}
