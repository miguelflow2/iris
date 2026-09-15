// EnvironnementIRIS.swift — l'objet unique qui relie les services de l'app.
//
// Un singleton sur le MainActor, et pas un @State de la vue racine : quand iOS relance l'app EN
// ARRIÈRE-PLAN pour une zone sans mémoire, aucune scène n'est créée, mais la surveillance des zones
// et le pont vers l'ordinateur doivent exister. Le délégué d'application le crée donc au lancement.

import Foundation
import Observation
import SwiftUI

enum Onglet: Hashable {
    case accueil, ia, accessibilite, profil
}

@MainActor
@Observable
final class EnvironnementIRIS {
    static let partage = EnvironnementIRIS()

    let pont: ClientPontPC
    let voix: MoteurVoix
    let conversation: ConversationIRIS
    let attestation: AttestationLunettes
    let zones: SurveillanceZones
    let coursHorsLigne: CoursHorsLigne
    /// Services de l'équipe perception (lunettes, vision, alertes, guidage), nil si le module n'est
    /// pas inclus dans cette version de l'app.
    let perception: (any ServicesPerception)?

    private(set) var reglages: ReglagesIRIS?
    var ongletChoisi: Onglet = .accueil
    /// Posé par le raccourci Siri « Parle à IRIS » : l'app écoute dès qu'elle est à l'écran.
    var ecouteDemandeeAuLancement = false

    @ObservationIgnored private var abonnementReglages: AbonnementEvenements?
    /// Vrai une fois les effets du mode confidentiel appliqués (écoute coupée, captures arrêtées) : on ne
    /// les rejoue pas à chaque réglage reçu, sinon chaque mise à jour couperait la parole en cours.
    @ObservationIgnored private var confidentielApplique = false

    static let urlAchat = URL(string: "https://velaglass.ca/lunettes.html")!
    static let messageConfidentiel = "Le mode confidentiel est actif sur ton ordinateur : IRIS n'écoute rien."
    private static let pauseConfidentiel = "confidentiel"

    private init() {
        let pont = ClientPontPC()
        let voix = MoteurVoix()
        self.pont = pont
        self.voix = voix
        conversation = ConversationIRIS(pont: pont)
        let coursHorsLigne = CoursHorsLigne()
        self.coursHorsLigne = coursHorsLigne
        zones = SurveillanceZones(pont: pont)

        if let classe = NSClassFromString(NOM_FABRIQUE_PERCEPTION) as? any FabriquePerception.Type {
            perception = classe.creer(pont: pont, voix: voix)
        } else {
            perception = nil
        }
        attestation = AttestationLunettes(pont: pont, lunettes: perception?.lunettes)

        voix.refusVoix = { [weak self] in self?.raisonVoixImpossible() }
        voix.refusEcoute = { [weak self] in self?.raisonEcouteImpossible() }
        voix.microOccupe = { [weak self] in self?.perception?.microOccupePar }
        voix.surCommande = { [weak self] commande in
            guard let self else { return nil }
            // Commande PARLÉE : chemin de la voix (interceptions de l'ordinateur), pas celui de l'écrit.
            return await self.demanderAVoix(commande)
        }
        conversation.surAccordDemande = { [weak self] demande in
            guard let self else { return }
            Task { await self.voix.parler("IRIS demande ton accord : \(demande.titre)") }
        }
        // Effacement à distance vu par le pont : les copies de cours gardées sur cet iPhone partent aussi.
        pont.surEffacementDistant = {
            for garde in coursHorsLigne.gardes {
                coursHorsLigne.retirer(garde.id)
            }
        }
        abonnementReglages = pont.abonner { [weak self] evenement in
            guard let self else { return }
            switch evenement.type {
            case "settings.updated":
                if let reglages = evenement.champs["settings"].flatMap({ try? JSONEncoder().encode($0) })
                    .flatMap({ try? JSONIRIS.decodeur.decode(ReglagesIRIS.self, from: $0) }) {
                    self.appliquer(reglages)
                }
            case "verrou.etat" where evenement.champs["verrouille"]?.booleen == true:
                // IRIS verrouillée : l'écoute en cours est coupée net. relancerVeille la ferme (la garde
                // refuse) et réessaie seule toutes les 15 s : elle repart après le déverrouillage.
                self.voix.annulerEcoute()
                self.voix.arreterParole()
                Task { await self.voix.relancerVeille() }
            default:
                break
            }
        }
    }

    // MARK: - Lunettes d'abord

    /// Lunettes VELA présentes pour IRIS.
    ///
    /// Quand l'ordinateur répond et que sa présence a été lue, C'EST LUI QUI FAIT FOI : il peut refuser
    /// l'attestation (autres lunettes que la paire associée, 403) alors que l'iPhone est bien relié à un
    /// appareil. Une présence attestée par un téléphone n'est crue que si des lunettes VÉRIFIÉES sont
    /// reliées à cet iPhone en ce moment (sinon elle est périmée : l'attestation vit 150 s sur l'ordinateur
    /// et l'app ne la relit plus en arrière-plan). Sans ordinateur, seul l'état Bluetooth local vérifié
    /// compte (fonctions 100 % iPhone).
    var lunettesPresentes: Bool {
        let etatLocal = perception?.lunettes.etat
        let localesVerifiees = etatLocal?.connectees == true && etatLocal?.verifiees == true
        // Une présence lue il y a plus de 3 minutes ne fait plus foi : en arrière-plan, l'app ne la relit plus
        // (des alertes sonores tourneraient sinon des heures sur un « vues par l'ordinateur » périmé).
        if pont.etat.estConnecte, let presence = attestation.presence, attestation.presenceFraiche {
            guard presence.presentes else { return false }
            if ["telephone", "iphone", "android"].contains(presence.source ?? "") {
                return localesVerifiees
            }
            return true
        }
        return localesVerifiees
    }

    /// Pourquoi la voix ne peut pas écouter maintenant (nil si elle le peut).
    func raisonVoixImpossible() -> String? {
        switch pont.etat {
        case .nonConfigure:
            return "Relie d'abord ton ordinateur (Profil › Ordinateur)."
        case .motDePasseRequis:
            return "Connecte-toi à ton ordinateur avec ton mot de passe (Profil › Ordinateur)."
        case .horsLigne(let raison):
            return "Ton ordinateur ne répond pas : \(raison)"
        case .verrouille:
            return "IRIS est verrouillée."
        case .connexion, .connecte:
            break
        }
        if pont.verrouPersistant {
            return "IRIS est verrouillée."
        }
        if reglages?.privacyMode == true {
            return Self.messageConfidentiel
        }
        if !lunettesPresentes {
            return "Connecte tes lunettes VELA pour parler à IRIS."
        }
        return nil
    }

    /// Pourquoi une écoute dirigée (« Parler », dictée d'une destination ou d'une question) ne peut pas
    /// ouvrir le micro maintenant. Mêmes règles que toute capture, sans exiger l'ordinateur : la dictée du
    /// guidage à pied marche hors ligne ; une demande à IRIS, elle, échouera plus loin avec sa vraie raison.
    func raisonEcouteImpossible() -> String? {
        if pont.verrouPersistant {
            return "IRIS est verrouillée."
        }
        if case .verrouille = pont.etat {
            return "IRIS est verrouillée."
        }
        if reglages?.privacyMode == true {
            return Self.messageConfidentiel
        }
        if !lunettesPresentes {
            return "Connecte tes lunettes VELA pour utiliser le micro avec IRIS."
        }
        return nil
    }

    // MARK: - Demandes à IRIS

    /// Une commande DITE dans les lunettes (après « Dis-moi Iris ») : POST /api/voix/commande, qui applique sur
    /// l'ordinateur les interceptions vocales (mode invité, pas à pas, entraînement, vision, résumé…) et la règle
    /// de la voix, et rend la réponse (ou le consentement manquant) de façon synchrone. Sur un ordinateur qui ne
    /// connaît pas encore cette route (404 « Not Found »), repli sur l'ancien chemin : commandes locales, puis chat.
    func demanderAVoix(_ texte: String) async -> String? {
        switch await conversation.envoyerCommandeVocale(texte) {
        case .phrase(let phrase):
            return phrase.isEmpty ? nil : phrase
        case .routeAbsente:
            return await demander(texte)
        }
    }

    /// Une demande ÉCRITE (ou une commande parlée sur un ordinateur ancien) : d'abord les phrases que l'app
    /// traite elle-même (mode invité), sinon le chat de l'ordinateur. Rend la phrase à lire, ou nil.
    func demander(_ texte: String) async -> String? {
        if let reponse = await commandeLocale(texte) {
            conversation.ajouterEchangeLocal(demande: texte, reponse: reponse)
            return reponse
        }
        return await conversation.envoyer(texte)
    }

    /// nil si la phrase ne concerne pas l'app ; sinon la phrase à dire (résultat ou refus exact).
    func commandeLocale(_ texte: String) async -> String? {
        guard let commande = CommandesLocales.reconnaitre(texte) else { return nil }
        switch commande {
        case .activerModeInvite:
            do {
                let etat: EtatInvite = try await pont.post("/api/confiance/invite/activer", corps: DemandeInvite(minutes: nil))
                return etat.phrase ?? CommandesLocales.phraseInviteActive(jusqua: etat.jusqua?.date,
                                                                         concis: reglages?.verbosite == "concis")
            } catch {
                return "Mode invité non activé : \(error.localizedDescription)"
            }
        case .quitterModeInvite:
            // Refusé à la voix, comme sur l'ordinateur sans verrou vocal (mode_invite.py) : l'iPhone ne sait
            // pas qui parle dans les lunettes. On lit seulement l'état pour dire l'heure de fin.
            do {
                let etat: EtatInvite = try await pont.get("/api/confiance/invite")
                return CommandesLocales.phraseSortieRefusee(actif: etat.actif, jusqua: etat.jusqua?.date)
            } catch {
                return CommandesLocales.phraseSortieRefusee(actif: nil, jusqua: nil)
            }
        }
    }

    // MARK: - Cycle de vie

    func auPremierPlan() async {
        voix.revenirAuPremierPlan()
        await pont.verifier()
        pont.demarrerSurveillance()
        attestation.demarrer()
        if pont.etat.estConnecte {
            await chargerReglages()
            await zones.reessayer()
        }
        coursHorsLigne.purger(retentionJours: reglages?.retentionDays)
        // L'écran IA consomme la demande (il remet le drapeau à faux quand il commence à écouter).
        if ecouteDemandeeAuLancement { ongletChoisi = .ia }
    }

    func enArrierePlan() {
        voix.passerEnArrierePlan()
        pont.suspendre()
        attestation.arreter()
    }

    // MARK: - Réglages partagés avec l'ordinateur

    func chargerReglages() async {
        do {
            let lus: ReglagesIRIS = try await pont.get("/api/settings")
            appliquer(lus)
        } catch {
            // Réglages illisibles : on garde les derniers connus ; les écrans affichent l'erreur au besoin.
        }
    }

    func modifierReglages(_ patch: PatchReglages) async throws {
        let lus: ReglagesIRIS = try await pont.patch("/api/settings", corps: patch)
        appliquer(lus)
    }

    private func appliquer(_ lus: ReglagesIRIS) {
        reglages = lus
        voix.debitUtilisateur = Double(lus.ttsRate ?? 185) / 185.0
        if let mot = lus.wakeWord, !mot.trimmingCharacters(in: .whitespaces).isEmpty {
            voix.motActivation = mot
        }
        if let langue = lus.language, langue.lowercased().hasPrefix("fr") {
            voix.langueIRIS = "fr-CA"
        }
        // Règle 4 : mode confidentiel, tout s'arrête et refuse de démarrer — sur l'iPhone aussi.
        if lus.privacyMode == true {
            if !confidentielApplique {
                confidentielApplique = true
                voix.annulerEcoute()
                voix.arreterParole()
                voix.suspendreVeille(cle: Self.pauseConfidentiel, raison: Self.messageConfidentiel)
                perception?.suspendreCaptures(raison: Self.messageConfidentiel)
            }
        } else if confidentielApplique {
            confidentielApplique = false
            voix.reprendreVeille(cle: Self.pauseConfidentiel)
        }
    }

    var grandTexte: Bool { reglages?.interfaceGrandTexte ?? false }
}
