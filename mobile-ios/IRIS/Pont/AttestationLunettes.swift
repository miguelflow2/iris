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
    /// L'ordinateur connaît ces lunettes mais pas CET iPhone (403 « pas encore associé ») : l'écran Lunettes
    /// propose alors l'association, avec le mot de passe du propriétaire (POST /api/lunettes/association).
    private(set) var associationRequise = false

    @ObservationIgnored private let pont: ClientPontPC
    @ObservationIgnored private var lunettes: (any ServiceLunettes)?
    @ObservationIgnored private var boucle: Task<Void, Never>?
    @ObservationIgnored private var abonnement: AbonnementEvenements?
    @ObservationIgnored private var dernierEssai: Date?
    @ObservationIgnored private var derniereLecturePresence: Date?
    @ObservationIgnored private var attesteesAuPC = false
    /// Identifiant envoyé dans la DERNIÈRE attestation acceptée. Retenu à part : à la déconnexion (ou après
    /// « oublier ») l'état Bluetooth n'a plus d'identifiant, et le retrait doit pourtant nommer CET appareil.
    @ObservationIgnored private var identifiantAtteste: String?
    @ObservationIgnored private var enCours = false

    static let intervalle: TimeInterval = 60
    /// Au-delà, la présence lue ne fait plus foi (EnvironnementIRIS.lunettesPresentes) : premier plan, elle
    /// est relue toutes les 30 s ; en arrière-plan, jamais.
    static let fraicheurPresence: TimeInterval = 180

    /// La dernière présence lue a moins de 3 minutes.
    var presenceFraiche: Bool {
        derniereLecturePresence.map { Date().timeIntervalSince($0) <= Self.fraicheurPresence } ?? false
    }

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

    /// Associe CET iPhone aux lunettes que l'ordinateur connaît déjà, avec le mot de passe du propriétaire,
    /// puis atteste aussitôt. Lève l'erreur du service telle quelle (403 mot de passe, 409 paire inconnue…).
    func associer(motDePasse: String) async throws {
        guard let etat = lunettes?.etat, etat.connectees, etat.verifiees, let nom = etat.nom, !nom.isEmpty else {
            throw ErreurPont.refus(statut: 0, message: "Connecte d'abord tes lunettes VELA à cet iPhone.", detail: nil)
        }
        let corps = DemandeAssociation(nom: nom, identifiant: etat.identifiant ?? "", motDePasse: motDePasse)
        let _: ReponseIgnoree = try await pont.post("/api/lunettes/association", corps: corps, delai: 20)
        associationRequise = false
        erreur = nil
        dernierEssai = nil
        await tic(force: true)
    }

    /// Paramètres du retrait (DELETE /api/lunettes/attestation?identifiant=…). Sans identifiant, le service
    /// efface l'attestation de N'IMPORTE QUEL appareil : un iPhone qui perd ses lunettes effacerait celle
    /// qu'un Android (ou un autre téléphone) relié aux lunettes vient de donner. Avec lui, le service ignore
    /// le retrait quand l'attestation en cours vient d'un autre appareil (lunettes_presence.retirer_attestation).
    /// L'identifiant est CBPeripheral.identifier.uuidString (hexadécimal et tirets) ; URLComponents
    /// (ClientPontPC.requeteBrute) l'insère dans la requête.
    nonisolated static func parametresRetrait(identifiant: String?) -> [URLQueryItem] {
        let id = (identifiant ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
        return id.isEmpty ? [] : [URLQueryItem(name: "identifiant", value: String(id.prefix(120)))]
    }

    /// Le refus dit-il que cet appareil n'est pas encore associé ? (phrase du service, lunettes_presence.py)
    nonisolated static func demandeAssociation(_ erreur: Error) -> Bool {
        guard let pont = erreur as? ErreurPont, case .refus(let statut, let message, _) = pont else { return false }
        return statut == 403 && message.localizedCaseInsensitiveContains("pas encore associ")
    }

    private func tic(force: Bool) async {
        guard !enCours, pont.etat.estConnecte else { return }
        enCours = true
        defer { enCours = false }

        let etat = lunettes?.etat
        // Relié ne suffit pas : seul un appareil qui expose un service connu des lunettes VELA est attesté
        // (un bracelet « SmartBand » relié ne doit pas débloquer IRIS sur l'ordinateur).
        if let etat, etat.connectees, etat.verifiees, let nom = etat.nom, !nom.isEmpty {
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
                    identifiantAtteste = corps.identifiant
                    erreur = nil
                    associationRequise = false
                } catch {
                    erreur = error.localizedDescription
                    associationRequise = Self.demandeAssociation(error)
                    // Refusée : la présence connue de l'ordinateur est relue tout de suite, plutôt que de laisser
                    // l'iPhone croire 30 s de plus à une présence qu'il a lui-même attestée.
                    derniereLecturePresence = nil
                }
            }
        } else if attesteesAuPC {
            do {
                let lue: PresenceLunettes = try await pont.delete(
                    "/api/lunettes/attestation",
                    parametres: Self.parametresRetrait(identifiant: identifiantAtteste ?? etat?.identifiant),
                    delai: 15)
                presence = lue
                derniereLecturePresence = Date()
            } catch {
                // Si le retrait échoue, l'attestation expire seule au bout de 150 s côté service.
            }
            attesteesAuPC = false
            identifiantAtteste = nil
            derniereAttestation = nil
        }
        if !(etat?.connectees == true && etat?.verifiees == true) {
            // Plus rien à attester : un ancien refus (« autres lunettes ») ne doit pas rester affiché.
            erreur = nil
            associationRequise = false
        }

        let vieille = derniereLecturePresence.map { Date().timeIntervalSince($0) > 30 } ?? true
        if vieille { await rafraichirPresence() }
    }
}
