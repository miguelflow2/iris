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

    static let urlAchat = URL(string: "https://velaglass.ca/lunettes.html")!

    private init() {
        let pont = ClientPontPC()
        let voix = MoteurVoix()
        self.pont = pont
        self.voix = voix
        conversation = ConversationIRIS(pont: pont)
        coursHorsLigne = CoursHorsLigne()
        zones = SurveillanceZones(pont: pont)

        if let classe = NSClassFromString(NOM_FABRIQUE_PERCEPTION) as? any FabriquePerception.Type {
            perception = classe.creer(pont: pont, voix: voix)
        } else {
            perception = nil
        }
        attestation = AttestationLunettes(pont: pont, lunettes: perception?.lunettes)

        voix.refusVoix = { [weak self] in self?.raisonVoixImpossible() }
        voix.surCommande = { [weak self] commande in
            guard let self else { return nil }
            return await self.conversation.envoyer(commande)
        }
        conversation.surAccordDemande = { [weak self] demande in
            guard let self else { return }
            Task { await self.voix.parler("IRIS demande ton accord : \(demande.titre)") }
        }
        abonnementReglages = pont.abonner { [weak self] evenement in
            guard let self else { return }
            if evenement.type == "settings.updated",
               let reglages = evenement.champs["settings"].flatMap({ try? JSONEncoder().encode($0) })
                .flatMap({ try? JSONIRIS.decodeur.decode(ReglagesIRIS.self, from: $0) }) {
                self.appliquer(reglages)
            }
        }
    }

    // MARK: - Lunettes d'abord

    /// Lunettes connectées à cet iPhone (CoreBluetooth) ou présentes selon l'ordinateur (vues par le
    /// PC, attestées par cet iPhone).
    var lunettesPresentes: Bool {
        if perception?.lunettes.etat.connectees == true { return true }
        if pont.etat.estConnecte, attestation.presence?.presentes == true { return true }
        return false
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
        if !lunettesPresentes {
            return "Connecte tes lunettes VELA pour parler à IRIS."
        }
        return nil
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
    }

    var grandTexte: Bool { reglages?.interfaceGrandTexte ?? false }
}
