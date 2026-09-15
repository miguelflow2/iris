// SurveillanceZones.swift — les zones sans mémoire, surveillées par l'iPhone lui-même.
//
// L'ordinateur connaît la liste des zones (centre, rayon). L'iPhone confie ces cercles à CLMonitor
// (iOS 17), qui réveille l'app à l'entrée ou à la sortie, même fermée, et IRIS envoie à l'ordinateur
// SEULEMENT l'identifiant de la zone où l'iPhone se trouve, ou « aucune »
// (POST /api/confiance/zone {zone_id, source: "telephone"}). La position ne quitte pas l'iPhone,
// sauf quand l'utilisateur crée une zone centrée là où il est.
//
// Limites réelles, affichées dans l'écran des zones :
// - iOS surveille au plus 20 régions par app : au-delà, les plus petites zones passent en premier ;
// - la détection d'entrée ou de sortie peut prendre plusieurs minutes, et reste grossière sous ~100 m ;
// - en arrière-plan, il faut l'autorisation de position « Toujours » ;
// - si l'ordinateur est injoignable au moment où l'iPhone entre dans une zone, la mémoire n'est PAS
//   suspendue tant que le signal n'a pas pu partir ; il repart dès que la liaison revient.

import CoreLocation
import Foundation
import Observation
import UIKit

@MainActor
@Observable
final class SurveillanceZones {
    private(set) var zones: [ZoneSansMemoire] = []
    private(set) var zoneActiveServeur: ZoneActive?
    private(set) var limiteServeur: String?
    private(set) var autorisation: CLAuthorizationStatus
    private(set) var surveillanceActive: Bool
    /// Zones où l'iPhone se trouve selon CLMonitor.
    private(set) var zonesDedans: Set<String> = []
    private(set) var zonesNonSurveillees = 0
    private(set) var dernierSignal: String?
    private(set) var signalEnAttente = false
    private(set) var erreur: String?

    @ObservationIgnored private let pont: ClientPontPC
    @ObservationIgnored private let gestionnaire = CLLocationManager()
    @ObservationIgnored private let delegue = DelegueAutorisation()
    @ObservationIgnored private var moniteur: CLMonitor?
    @ObservationIgnored private var tacheEvenements: Task<Void, Never>?
    @ObservationIgnored private var abonnement: AbonnementEvenements?

    static let limiteRegionsIOS = 20
    private static let nomMoniteur = "iris-zones-sans-memoire"
    private static let cleActive = "iris_zones_surveillance_active"
    private static let cleDerniereZone = "iris_zones_derniere_signalee"

    static let limiteIPhone = "iOS surveille au plus 20 zones par app. L'entrée ou la sortie peut être détectée avec plusieurs minutes de retard et reste imprécise sous environ 100 m. Pour que ça marche app fermée, la position doit être permise « Toujours ». Si ton ordinateur ne répond pas au moment où tu entres dans une zone, la mémoire n'est suspendue qu'une fois le signal parti."

    init(pont: ClientPontPC) {
        self.pont = pont
        autorisation = gestionnaire.authorizationStatus
        surveillanceActive = UserDefaults.standard.bool(forKey: Self.cleActive)
        gestionnaire.delegate = delegue
        delegue.surChangement = { [weak self] statut in
            self?.autorisation = statut
        }
        abonnement = pont.abonner { [weak self] evenement in
            guard let self, evenement.type == "zone.etat" else { return }
            if evenement.champs["dans_zone"]?.booleen == true, let nom = evenement.champs["zone_nom"]?.texte {
                self.zoneActiveServeur = ZoneActive(id: nil, nom: nom)
            } else if evenement.champs["dans_zone"]?.booleen == false {
                self.zoneActiveServeur = nil
            }
        }
        if surveillanceActive {
            // Au lancement, y compris quand iOS relance l'app en arrière-plan pour un événement de
            // zone : le moniteur doit être recréé tôt, sous le même nom, pour recevoir l'événement.
            Task { await self.demarrerMoniteur() }
        }
    }

    // MARK: - Liste des zones (sur l'ordinateur)

    func charger() async {
        do {
            let reponse: ReponseZones = try await pont.get("/api/confiance/zones")
            appliquer(reponse)
            erreur = nil
            await reconcilier()
        } catch {
            erreur = error.localizedDescription
        }
    }

    private func appliquer(_ reponse: ReponseZones) {
        zones = reponse.zones
        zoneActiveServeur = reponse.zoneActive
        limiteServeur = reponse.limite
    }

    func ajouterIci(nom: String, rayonM: Double) async throws {
        let position = try await Self.positionActuelle()
        let _: ReponseIgnoree = try await pont.post(
            "/api/confiance/zones",
            corps: NouvelleZone(nom: nom, lat: position.coordinate.latitude, lon: position.coordinate.longitude, rayonM: rayonM))
        await charger()
    }

    func supprimer(_ zone: ZoneSansMemoire) async {
        do {
            let reponse: ReponseZones = try await pont.delete("/api/confiance/zones/\(zone.id)")
            appliquer(reponse)
            erreur = nil
            await reconcilier()
        } catch {
            erreur = error.localizedDescription
        }
    }

    // MARK: - Surveillance

    func activerSurveillance() async {
        surveillanceActive = true
        UserDefaults.standard.set(true, forKey: Self.cleActive)
        // iOS propose d'abord « Pendant l'utilisation », puis, plus tard, de passer à « Toujours ».
        if gestionnaire.authorizationStatus == .notDetermined {
            gestionnaire.requestWhenInUseAuthorization()
        } else if gestionnaire.authorizationStatus == .authorizedWhenInUse {
            gestionnaire.requestAlwaysAuthorization()
        }
        await demarrerMoniteur()
        await charger()
    }

    func demanderToujours() {
        gestionnaire.requestAlwaysAuthorization()
    }

    /// Première question d'iOS (« Pendant l'utilisation »), sans activer la surveillance.
    func demanderPosition() {
        gestionnaire.requestWhenInUseAuthorization()
    }

    func desactiverSurveillance() async {
        surveillanceActive = false
        UserDefaults.standard.set(false, forKey: Self.cleActive)
        tacheEvenements?.cancel()
        tacheEvenements = nil
        if let moniteur {
            for identifiant in await moniteur.identifiers {
                await moniteur.remove(identifiant)
            }
        }
        zonesDedans.removeAll()
        // Surveillance coupée : on retire le signal de ce téléphone plutôt que de laisser une
        // suspension que plus rien ne lèverait.
        await envoyerSignal(zoneId: nil, force: true)
    }

    private func demarrerMoniteur() async {
        if moniteur == nil {
            moniteur = await CLMonitor(Self.nomMoniteur)
        }
        guard let moniteur else { return }
        // État connu au lancement (les enregistrements de CLMonitor survivent à l'app).
        var dedans: Set<String> = []
        for identifiant in await moniteur.identifiers {
            if let enregistrement = await moniteur.record(for: identifiant),
               enregistrement.lastEvent.state == .satisfied {
                dedans.insert(identifiant)
            }
        }
        zonesDedans = dedans
        tacheEvenements?.cancel()
        tacheEvenements = Task { [weak self] in
            do {
                for try await evenement in await moniteur.events {
                    guard let self else { return }
                    await self.traiter(identifiant: evenement.identifier, state: evenement.state)
                }
            } catch {
                self?.erreur = "Surveillance des zones interrompue : \(error.localizedDescription)"
            }
        }
        await signalerSiChange()
    }

    private func traiter(identifiant: String, state: CLMonitor.EventState) async {
        switch state {
        case .satisfied:
            zonesDedans.insert(identifiant)
        case .unsatisfied:
            zonesDedans.remove(identifiant)
        default:
            // .unknown / non surveillée : on ne conclut rien (prudence : on ne lève pas une suspension).
            break
        }
        await signalerSiChange()
    }

    /// Met les cercles de CLMonitor en accord avec la liste de l'ordinateur.
    private func reconcilier() async {
        guard surveillanceActive, let moniteur else { return }
        let triees = zones.sorted { $0.rayonM < $1.rayonM }
        let surveillees = Array(triees.prefix(Self.limiteRegionsIOS))
        zonesNonSurveillees = max(0, zones.count - surveillees.count)
        let voulus = Set(surveillees.map(\.id))
        let existants = Set(await moniteur.identifiers)
        for zone in surveillees where !existants.contains(zone.id) {
            let condition = CLMonitor.CircularGeographicCondition(
                center: CLLocationCoordinate2D(latitude: zone.lat, longitude: zone.lon),
                radius: zone.rayonM)
            await moniteur.add(condition, identifier: zone.id, assuming: .unsatisfied)
        }
        for identifiant in existants where !voulus.contains(identifiant) {
            await moniteur.remove(identifiant)
            zonesDedans.remove(identifiant)
        }
        await signalerSiChange()
    }

    private func zoneCourante() -> String? {
        Self.zoneCourante(zones: zones, dedans: zonesDedans)
    }

    /// La zone à signaler : la plus petite de celles où l'iPhone se trouve. Fonction pure (IRISTests).
    nonisolated static func zoneCourante(zones: [ZoneSansMemoire], dedans: Set<String>) -> String? {
        let candidates = zones.filter { dedans.contains($0.id) }.sorted { $0.rayonM < $1.rayonM }
        if let premiere = candidates.first { return premiere.id }
        // Liste pas encore chargée (réveil en arrière-plan) : on garde l'identifiant tel quel.
        return zones.isEmpty ? dedans.sorted().first : nil
    }

    private func signalerSiChange() async {
        guard surveillanceActive else { return }
        await envoyerSignal(zoneId: zoneCourante(), force: false)
    }

    /// Réessaie un signal resté en attente (appelé quand la liaison avec l'ordinateur revient).
    func reessayer() async {
        guard signalEnAttente || surveillanceActive else { return }
        await envoyerSignal(zoneId: surveillanceActive ? zoneCourante() : nil, force: signalEnAttente)
    }

    private func envoyerSignal(zoneId: String?, force: Bool) async {
        let cle = zoneId ?? ""
        let precedente = UserDefaults.standard.string(forKey: Self.cleDerniereZone)
        guard force || signalEnAttente || precedente != cle else { return }
        guard pont.aUneSession else { signalEnAttente = true; return }

        // Réveillée en arrière-plan, l'app n'a que quelques secondes : on les demande explicitement.
        let tache = UIApplication.shared.beginBackgroundTask(withName: "iris-zone", expirationHandler: nil)
        defer { if tache != .invalid { UIApplication.shared.endBackgroundTask(tache) } }
        do {
            let reponse: ReponseZones = try await pont.post("/api/confiance/zone",
                                                            corps: SignalZone(zoneId: zoneId, source: "telephone"), delai: 15)
            appliquer(reponse)
            UserDefaults.standard.set(cle, forKey: Self.cleDerniereZone)
            signalEnAttente = false
            erreur = nil
            let nom = zones.first(where: { $0.id == zoneId })?.nom
            dernierSignal = zoneId == nil
                ? "Signalé à l'ordinateur : hors de toute zone."
                : "Signalé à l'ordinateur : dans la zone « \(nom ?? "?") »."
        } catch ErreurPont.refus(let statut, _, _) where statut == 404 {
            // Zone supprimée sur l'ordinateur entre-temps : la liste sera rechargée.
            signalEnAttente = false
            await charger()
        } catch {
            signalEnAttente = true
            erreur = "Signal de zone non envoyé : \(error.localizedDescription) Nouvel essai au retour de la liaison."
        }
    }

    // MARK: - Position ponctuelle (création d'une zone ici)

    /// Première position assez précise (100 m ou mieux), ou une erreur au bout de `delaiMax`.
    static func positionActuelle(delaiMax: TimeInterval = 15) async throws -> CLLocation {
        let statut = CLLocationManager().authorizationStatus
        guard statut == .authorizedWhenInUse || statut == .authorizedAlways else {
            throw ErreurPont.refus(statut: 0, message: "Position non permise pour IRIS : Réglages › IRIS › Position.", detail: nil)
        }
        let position = try await withThrowingTaskGroup(of: CLLocation?.self) { groupe -> CLLocation? in
            groupe.addTask {
                for try await mise in CLLocationUpdate.liveUpdates() {
                    if let lue = mise.location, lue.horizontalAccuracy >= 0, lue.horizontalAccuracy <= 100 {
                        return lue
                    }
                }
                return nil
            }
            groupe.addTask {
                try await Task.sleep(for: .seconds(delaiMax))
                return nil
            }
            let premiere = try await groupe.next() ?? nil
            groupe.cancelAll()
            return premiere
        }
        guard let position else {
            throw ErreurPont.refus(statut: 0, message: "Position indisponible ou trop imprécise (plus de 100 m) : réessaie à découvert.", detail: nil)
        }
        return position
    }
}

/// CLLocationManager prévient par délégué, sur le fil principal (il a été créé sur le MainActor).
final class DelegueAutorisation: NSObject, CLLocationManagerDelegate {
    var surChangement: (@MainActor (CLAuthorizationStatus) -> Void)?

    func locationManagerDidChangeAuthorization(_ manager: CLLocationManager) {
        let statut = manager.authorizationStatus
        let rappel = surChangement
        Task { @MainActor in rappel?(statut) }
    }
}
