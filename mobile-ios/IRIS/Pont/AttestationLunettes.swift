// AttestationLunettes.swift — dire à l'ordinateur « les lunettes VELA sont connectées à cet iPhone ».
//
// Règle « lunettes d'abord » (Miguel, 2026-09-13) : dehors, le PC ne voit pas les lunettes ; c'est
// l'app iPhone appairée qui l'atteste (POST /api/lunettes/attestation). L'attestation vaut 150 s
// côté service ; on la renouvelle toutes les 60 s tant que les lunettes sont connectées, et on la
// retire (DELETE) dès qu'elles se déconnectent.
//
// Limite réelle, dite dans Profil : iOS suspend l'app en arrière-plan. Environ 2 minutes et demie
// après, l'attestation expire et l'ordinateur ne voit plus les lunettes.

import Foundation
import Observation

@MainActor
@Observable
final class AttestationLunettes {
    /// Dernier état de présence connu du service (GET /api/lunettes/presence ou événement).
    private(set) var presence: PresenceLunettes?
    private(set) var derniereAttestation: Date?
    /// Refus du service à afficher tel quel (p. ex. 403 « Ces lunettes ne sont pas celles associées… »).
    private(set) var erreur: String?

    @ObservationIgnored private let pont: ClientPontPC
    @ObservationIgnored private var lunettes: (any ServiceLunettes)?
    @ObservationIgnored private var boucle: Task<Void, Never>?
    @ObservationIgnored private var abonnement: AbonnementEvenements?
    @ObservationIgnored private var dernierEssai: Date?
    @ObservationIgnored private var derniereLecturePresence: Date?
    @ObservationIgnored private var attesteesAuPC = false
    @ObservationIgnored private var enCours = false

    static let intervalle: TimeInterval = 60

    init(pont: ClientPontPC, lunettes: (any ServiceLunettes)?) {
        self.pont = pont
        self.lunettes = lunettes
        abonnement = pont.abonner { [weak self] evenement in
            guard let self, evenement.type == "lunettes.presence" else { return }
            if let lue = evenement.decoder(PresenceLunettes.self) {
                self.presence = lue
                self.derniereLecturePresence = Date()
            }
        }
        lunettes?.surChangement = { [weak self] _ in
            guard let self else { return }
            Task { @MainActor in await self.tic(force: true) }
        }
    }

    func demarrer() {
        guard boucle == nil else { return }
        boucle = Task { [weak self] in
            while !Task.isCancelled {
                await self?.tic(force: false)
                try? await Task.sleep(for: .seconds(10))
            }
        }
    }

    func arreter() {
        boucle?.cancel()
        boucle = nil
    }

    /// Rafraîchit la présence connue du service (après un envoi de message, à l'ouverture d'un écran).
    func rafraichirPresence() async {
        guard pont.etat.estConnecte else { return }
        do {
            let lue: PresenceLunettes = try await pont.get("/api/lunettes/presence", delai: 12)
            presence = lue
            derniereLecturePresence = Date()
        } catch {
            // Présence illisible : on garde la dernière connue, l'écran dit « état inconnu ».
        }
    }

    private func tic(force: Bool) async {
        guard !enCours, pont.etat.estConnecte else { return }
        enCours = true
        defer { enCours = false }

        let etat = lunettes?.etat
        if let etat, etat.connectees, let nom = etat.nom, !nom.isEmpty {
            let echu = derniereAttestation.map { Date().timeIntervalSince($0) >= Self.intervalle } ?? true
            let essaiRecent = dernierEssai.map { Date().timeIntervalSince($0) < Self.intervalle } ?? false
            if (echu && !essaiRecent) || (force && !attesteesAuPC) {
                dernierEssai = Date()
                do {
                    let corps = DemandeAttestation(nom: nom, identifiant: etat.identifiant ?? "",
                                                   batterie: etat.batterie, source: "iphone")
                    let lue: PresenceLunettes = try await pont.post("/api/lunettes/attestation", corps: corps, delai: 15)
                    presence = lue
                    derniereAttestation = Date()
                    derniereLecturePresence = Date()
                    attesteesAuPC = true
                    erreur = nil
                } catch {
                    erreur = error.localizedDescription
                }
            }
        } else if attesteesAuPC {
            do {
                let lue: PresenceLunettes = try await pont.delete("/api/lunettes/attestation", delai: 15)
                presence = lue
                derniereLecturePresence = Date()
            } catch {
                // Si le retrait échoue, l'attestation expire seule au bout de 150 s côté service.
            }
            attesteesAuPC = false
            derniereAttestation = nil
        }

        let vieille = derniereLecturePresence.map { Date().timeIntervalSince($0) > 30 } ?? true
        if vieille { await rafraichirPresence() }
    }
}
