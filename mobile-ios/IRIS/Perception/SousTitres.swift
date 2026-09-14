// SousTitres.swift — sous-titres en direct, reconnus SUR l'iPhone, affichés en texte géant.
//
// Pour une personne malentendante : ce que capte le micro des lunettes (ou de l'iPhone) s'écrit à
// l'écran au fil de la parole. La reconnaissance est exigée sur l'appareil (requiresOnDeviceRecognition) :
// si l'iPhone n'a pas la langue hors ligne, on le dit au lieu de basculer en ligne.
//
// Découpage : une ligne est close après ~1,6 s de silence, ou toutes les 50 s (une tâche de reconnaissance
// ne doit pas grossir sans fin) ; la tâche suivante est ouverte AVANT que la précédente rende son texte
// final, pour ne rien perdre entre les deux.
//
// Rien n'est conservé : les lignes vivent en mémoire vive tant que l'écran est ouvert, puis sont oubliées.
// Les partager est un geste explicite (bouton « Partager le texte »).

import AVFoundation
import Foundation
import Observation
import Speech
import UIKit

/// La requête de reconnaissance en cours, lue par le fil audio : protégée par un verrou.
final class BoiteRequeteParole {
    private let verrou = NSLock()
    private var requete: SFSpeechAudioBufferRecognitionRequest?

    @discardableResult
    func remplacer(par nouvelle: SFSpeechAudioBufferRecognitionRequest?) -> SFSpeechAudioBufferRecognitionRequest? {
        verrou.lock()
        defer { verrou.unlock() }
        let ancienne = requete
        requete = nouvelle
        return ancienne
    }

    func ajouter(_ tampon: AVAudioPCMBuffer) {
        verrou.lock()
        let r = requete
        verrou.unlock()
        r?.append(tampon)
    }
}

@MainActor
@Observable
final class SousTitresTelephone {
    struct Ligne: Identifiable, Hashable {
        let id = UUID()
        let date: Date
        let texte: String
    }

    private(set) var actif = false
    private(set) var lignes: [Ligne] = []
    private(set) var partiel = ""
    private(set) var erreur: String?
    /// Vrai quand aucun son n'arrive depuis plusieurs secondes alors que l'écoute tourne.
    private(set) var attenteMicro = false
    private(set) var langue: String
    private(set) var taille: Double

    static let limite = "Reconnaissance faite sur cet iPhone, sans envoi du son. La précision baisse avec le bruit, les accents marqués, plusieurs voix en même temps et les noms propres. Le texte n'est pas conservé : il disparaît quand tu quittes l'écran. Pendant les sous-titres, « Dis-moi Iris » est en pause."

    static let langues: [(code: String, nom: String)] = [("fr-CA", "Français"), ("en-CA", "Anglais")]

    @ObservationIgnored private let micro: MicroPerception
    @ObservationIgnored private let voix: any ServiceVoix
    @ObservationIgnored private let garde: GardeCapture
    @ObservationIgnored private let boite = BoiteRequeteParole()
    @ObservationIgnored private var reconnaisseur: SFSpeechRecognizer?
    @ObservationIgnored private var taches: [Int: SFSpeechRecognitionTask] = [:]
    @ObservationIgnored private var segmentCourant = 0
    @ObservationIgnored private var textesSegments: [Int: String] = [:]
    @ObservationIgnored private var derniereModification = Date()
    @ObservationIgnored private var debutSegment = Date()
    @ObservationIgnored private var veilleur: Task<Void, Never>?
    @ObservationIgnored private var erreursRecentes: [Date] = []

    private static let cleLangue = "iris_sous_titres_langue"
    private static let cleTaille = "iris_sous_titres_taille"
    private static let silenceFinLigne: TimeInterval = 1.6
    private static let dureeSegmentMax: TimeInterval = 50
    private static let lignesMax = 300

    init(micro: MicroPerception, voix: any ServiceVoix, garde: GardeCapture) {
        self.micro = micro
        self.voix = voix
        self.garde = garde
        langue = UserDefaults.standard.string(forKey: Self.cleLangue) ?? "fr-CA"
        let tailleLue = UserDefaults.standard.double(forKey: Self.cleTaille)
        taille = tailleLue >= 20 ? tailleLue : 40
    }

    func choisirLangue(_ code: String) {
        guard code != langue else { return }
        langue = code
        UserDefaults.standard.set(code, forKey: Self.cleLangue)
    }

    func choisirTaille(_ valeur: Double) {
        taille = min(max(valeur, 20), 120)
        UserDefaults.standard.set(taille, forKey: Self.cleTaille)
    }

    // MARK: - Démarrer / arrêter

    func demarrer() async throws {
        guard !actif else { return }
        if let refus = garde.refus(fonction: "sous_titres") { throw refus }
        if let raison = await voix.demanderAutorisations() {
            throw ErreurVoix.autorisationRefusee(raison)
        }
        guard let reco = SFSpeechRecognizer(locale: Locale(identifier: langue)), reco.supportsOnDeviceRecognition else {
            throw ErreurVoix.langueNonReconnue(langue)
        }
        guard reco.isAvailable else {
            throw ErreurMicro.occupe("La reconnaissance vocale est momentanément indisponible sur cet iPhone.")
        }
        reconnaisseur = reco
        erreur = nil
        erreursRecentes.removeAll()
        let boite = self.boite
        do {
            try micro.abonner("sous-titres", surFormat: { [weak self] _ in
                // Nouveau format (lunettes branchées ou retirées) : une requête ne change pas de format en route.
                self?.ouvrirSegment()
            }, bloc: { tampon, _ in
                boite.ajouter(tampon)
            })
        } catch {
            boite.remplacer(par: nil)?.endAudio()
            for tache in taches.values { tache.cancel() }
            taches.removeAll()
            textesSegments.removeAll()
            throw error
        }
        actif = true
        EveilEcran.activer("sous-titres")
        demarrerVeilleur()
    }

    func arreter() {
        guard actif else { return }
        actif = false
        veilleur?.cancel()
        veilleur = nil
        micro.desabonner("sous-titres")
        boite.remplacer(par: nil)?.endAudio()
        // Ce qui a été entendu mais pas encore clos devient une ligne ; les rappels tardifs sont ignorés.
        for numero in textesSegments.keys.sorted() {
            let texte = (textesSegments[numero] ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
            if !texte.isEmpty { ajouterLigne(texte) }
        }
        let fini = Array(taches.values)
        taches.removeAll()
        textesSegments.removeAll()
        for tache in fini { tache.cancel() }
        partiel = ""
        attenteMicro = false
        EveilEcran.desactiver("sous-titres")
    }

    func effacer() {
        lignes.removeAll()
        partiel = ""
    }

    /// Tout le texte, pour le partager par un geste explicite.
    var texteComplet: String {
        let format = DateFormatter()
        format.locale = Locale(identifier: "fr_CA")
        format.dateFormat = "HH:mm:ss"
        return lignes.map { "[\(format.string(from: $0.date))] \($0.texte)" }.joined(separator: "\n")
    }

    // MARK: - Segments de reconnaissance

    private func ouvrirSegment() {
        guard let reco = reconnaisseur else { return }
        let requete = SFSpeechAudioBufferRecognitionRequest()
        requete.requiresOnDeviceRecognition = true
        requete.shouldReportPartialResults = true
        requete.addsPunctuation = true
        requete.taskHint = .dictation
        segmentCourant += 1
        let numero = segmentCourant
        textesSegments[numero] = ""
        debutSegment = Date()
        derniereModification = Date()
        // La nouvelle requête reçoit le son tout de suite ; l'ancienne finit de rendre son texte.
        boite.remplacer(par: requete)?.endAudio()
        taches[numero] = reco.recognitionTask(with: requete, resultHandler: Self.gestionnaire(self, segment: numero))
        partiel = ""
    }

    nonisolated private static func gestionnaire(_ proprietaire: SousTitresTelephone, segment: Int)
        -> (SFSpeechRecognitionResult?, Error?) -> Void {
        return { [weak proprietaire] resultat, erreur in
            let texte = resultat?.bestTranscription.formattedString
            let final = resultat?.isFinal ?? false
            let echec = erreur != nil
            Task { @MainActor in
                proprietaire?.recu(segment: segment, texte: texte, final: final, echec: echec)
            }
        }
    }

    private func recu(segment: Int, texte: String?, final: Bool, echec: Bool) {
        // Segment déjà clos (arrêt, ou résultat en double) : rien à faire.
        guard taches[segment] != nil else { return }
        if let texte, texte != textesSegments[segment] {
            textesSegments[segment] = texte
            if segment == segmentCourant {
                partiel = texte
                derniereModification = Date()
                attenteMicro = false
            }
        }
        guard final || echec else { return }
        let clos = (textesSegments.removeValue(forKey: segment) ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
        taches[segment] = nil
        if !clos.isEmpty {
            ajouterLigne(clos)
        }
        guard segment == segmentCourant, actif else { return }
        partiel = ""
        if echec {
            // « Rien entendu » ou reconnaissance coupée : on rouvre, mais sans boucler en rafale.
            let maintenant = Date()
            erreursRecentes = erreursRecentes.filter { maintenant.timeIntervalSince($0) < 30 } + [maintenant]
            if erreursRecentes.count > 8 {
                erreur = "La reconnaissance s'est arrêtée plusieurs fois de suite. Touche « Démarrer » pour réessayer."
                arreter()
                return
            }
        }
        ouvrirSegment()
    }

    private func ajouterLigne(_ texte: String) {
        lignes.append(Ligne(date: Date(), texte: texte))
        if lignes.count > Self.lignesMax {
            lignes.removeFirst(lignes.count - Self.lignesMax)
        }
    }

    /// Clôt la ligne après un silence ou un segment trop long ; signale l'absence de son.
    private func demarrerVeilleur() {
        veilleur?.cancel()
        veilleur = Task { [weak self] in
            while !Task.isCancelled {
                try? await Task.sleep(for: .milliseconds(400))
                guard let self, self.actif else { return }
                let maintenant = Date()
                let silence = maintenant.timeIntervalSince(self.derniereModification)
                let longueur = maintenant.timeIntervalSince(self.debutSegment)
                if (!self.partiel.isEmpty && silence >= Self.silenceFinLigne) || longueur >= Self.dureeSegmentMax {
                    self.ouvrirSegment()
                }
                self.attenteMicro = self.micro.registre.secondesSansSon > 3
            }
        }
    }
}
