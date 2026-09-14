// Guidage.swift — « Où suis-je ? » et « Guide-moi » à pied, depuis l'iPhone.
//
// Pourquoi sur l'iPhone et pas sur l'ordinateur : dehors, l'ordinateur est resté à la maison et ne sait
// rien de la rue. La position du GPS de l'iPhone sert à trouver l'adresse et l'itinéraire auprès du
// service de cartes intégré à iOS ; elle n'est JAMAIS envoyée à IRIS ni à l'ordinateur, et rien n'est
// conservé.
//
// Le suivi : l'étape courante est franchie quand on arrive à une douzaine de mètres de son extrémité ;
// un préavis est dit à 40 m ; si la position s'écarte de plus de 35 m du trajet deux fois de suite (et que
// le GPS est assez précis pour en juger), l'itinéraire est recalculé (au plus toutes les 20 s). Quand le
// GPS est trop imprécis (plus de 65 m), les consignes de virage sont suspendues et on le dit : une annonce
// « tourne à gauche » tomberait n'importe où.
//
// Limites réelles, affichées : ni obstacle, ni travaux, ni feu pour piétons ; précision de 5 à 50 m, pire
// entre les grands immeubles ; réseau requis pour chercher et calculer ; instructions dans la langue de
// l'iPhone ; écran verrouillé, la position continue (indicateur de position d'iOS) mais iOS peut couper
// les annonces vocales.

import CoreLocation
import Foundation
import MapKit
import Observation
import UIKit

enum ErreurGuidage: Error, LocalizedError {
    case positionRefusee
    case positionIndisponible
    case destinationIntrouvable(String)
    case itineraireImpossible(String)
    case reseau(String)
    case accordRequis

    var errorDescription: String? {
        switch self {
        case .accordRequis:
            return "Accepte d'abord l'envoi de la position au service de cartes d'iOS : sans lui, ni adresse ni trajet."
        case .positionRefusee:
            return "Position refusée pour IRIS : Réglages › IRIS › Position › « Pendant l'utilisation »."
        case .positionIndisponible:
            return "Position introuvable pour l'instant : le GPS ne capte pas (intérieur, tunnel). Réessaie à découvert."
        case .destinationIntrouvable(let texte):
            return "Je ne trouve aucun lieu pour « \(texte) » près d'ici. Essaie avec l'adresse complète."
        case .itineraireImpossible(let message):
            return "Aucun itinéraire à pied n'a pu être calculé : \(message)"
        case .reseau(let message):
            return "Le service de cartes ne répond pas (réseau requis) : \(message)"
        }
    }
}

/// Un lieu proposé après une recherche, avec sa distance à vol d'oiseau.
struct LieuTrouve: Identifiable {
    let id = UUID()
    let element: MKMapItem
    let nom: String
    let adresse: String
    let distanceM: Double?
}

@MainActor
@Observable
final class GuidageAPied: ServiceGuidage {
    private(set) var guidageActif = false
    private(set) var etapes: [EtapeGuidage] = []
    private(set) var indexEtape = 0
    private(set) var destinationNom: String?
    private(set) var distanceProchaineM: Double?
    private(set) var distanceRestanteM: Double?
    private(set) var dureePrevueS: Double?
    private(set) var precisionM: Double?
    /// Phrase d'état à afficher (« GPS imprécis… », « recalcul… »).
    private(set) var etatTexte: String?
    private(set) var derniereConsigne: String?
    private(set) var erreur: String?
    private(set) var autorisation: CLAuthorizationStatus
    /// Accord explicite, retenu sur cet iPhone, pour envoyer la position au service de cartes d'iOS.
    private(set) var accordCartes: Bool

    let limite = "Guidage à pied d'après le GPS de l'iPhone et le service de cartes intégré à iOS : il faut du réseau pour trouver un lieu et calculer le trajet. Il ne voit ni les obstacles, ni les travaux, ni les feux pour piétons, et la position peut dévier de 5 à 50 mètres, surtout entre les grands immeubles. Garde ta canne ou ton chien guide et ta prudence habituelle. Les distances et durées sont des estimations. Les instructions sont dans la langue de l'iPhone. La position n'est envoyée ni à IRIS ni à ton ordinateur."

    static let texteAccord = "Pour trouver une adresse et calculer un trajet, la position de l'iPhone et la destination sont envoyées au service de cartes intégré à iOS. Elles ne sont envoyées ni à IRIS ni à ton ordinateur, et IRIS n'en conserve rien."

    static let mentionCartes = "Données cartographiques : fournisseurs du service de cartes d'iOS, dont, selon la région, © contributeurs OpenStreetMap (licence ODbL)."

    @ObservationIgnored private let voix: any ServiceVoix
    @ObservationIgnored private let garde: GardeCapture
    @ObservationIgnored private let gestionnaire: CLLocationManager
    @ObservationIgnored private let delegue = DelegueGuidage()
    @ObservationIgnored private var itineraire: MKRoute?
    @ObservationIgnored private var etapesRoute: [MKRoute.Step] = []
    @ObservationIgnored private var destination: MKMapItem?
    @ObservationIgnored private var derniere: CLLocation?
    @ObservationIgnored private var preavisDit: Int = -1
    @ObservationIgnored private var ecartsDeSuite = 0
    @ObservationIgnored private var dernierRecalcul = Date.distantPast
    @ObservationIgnored private var recalculEnCours = false
    @ObservationIgnored private var attentesAutorisation: [CheckedContinuation<Void, Never>] = []

    private static let cleAccord = "iris_guidage_accord"
    private static let distancePreavisM = 40.0
    private static let distanceEtapeMinM = 12.0
    private static let ecartMaxM = 35.0
    private static let precisionUtileM = 65.0
    private static let arriveeM = 15.0
    private static let recalculMinS = 20.0

    init(voix: any ServiceVoix, garde: GardeCapture) {
        self.voix = voix
        self.garde = garde
        // Lu sur une variable locale : une classe ne peut pas lire ses propriétés avant de les avoir toutes
        // initialisées.
        let manager = CLLocationManager()
        gestionnaire = manager
        accordCartes = UserDefaults.standard.bool(forKey: GuidageAPied.cleAccord)
        autorisation = manager.authorizationStatus
        gestionnaire.delegate = delegue
        gestionnaire.desiredAccuracy = kCLLocationAccuracyBest
        gestionnaire.activityType = .fitness
        gestionnaire.distanceFilter = 3
        gestionnaire.pausesLocationUpdatesAutomatically = false
        delegue.surAutorisation = { [weak self] statut in
            self?.autorisationChangee(statut)
        }
        delegue.surPosition = { [weak self] position in
            self?.suivre(position)
        }
        delegue.surErreur = { [weak self] message in
            self?.etatTexte = message
        }
    }

    // MARK: - Accord, autorisation et position

    func donnerAccordCartes(_ accord: Bool) {
        accordCartes = accord
        UserDefaults.standard.set(accord, forKey: Self.cleAccord)
    }

    private func autorisationChangee(_ statut: CLAuthorizationStatus) {
        autorisation = statut
        guard statut != .notDetermined else { return }
        let attentes = attentesAutorisation
        attentesAutorisation.removeAll()
        for attente in attentes { attente.resume() }
    }

    private func assurerAutorisation() async throws {
        if gestionnaire.authorizationStatus == .notDetermined {
            await withCheckedContinuation { (suite: CheckedContinuation<Void, Never>) in
                attentesAutorisation.append(suite)
                gestionnaire.requestWhenInUseAuthorization()
            }
        }
        let statut = gestionnaire.authorizationStatus
        guard statut == .authorizedWhenInUse || statut == .authorizedAlways else { throw ErreurGuidage.positionRefusee }
    }

    /// Meilleure position obtenue en quelques secondes : la première à 30 m près, sinon la plus précise vue.
    func positionActuelle() async throws -> PositionTelephone {
        let lue = try await localiser()
        return PositionTelephone(lat: lue.coordinate.latitude, lon: lue.coordinate.longitude, precisionM: lue.horizontalAccuracy)
    }

    private func localiser(delaiMax: TimeInterval = 10) async throws -> CLLocation {
        try await assurerAutorisation()
        if guidageActif, let derniere, Date().timeIntervalSince(derniere.timestamp) < 5, derniere.horizontalAccuracy <= 30 {
            return derniere
        }
        let trouvee = await withTaskGroup(of: CLLocation?.self) { groupe -> CLLocation? in
            groupe.addTask {
                var meilleure: CLLocation?
                do {
                    for try await mise in CLLocationUpdate.liveUpdates(.fitness) {
                        guard let lue = mise.location, lue.horizontalAccuracy >= 0 else { continue }
                        if meilleure == nil || lue.horizontalAccuracy < meilleure!.horizontalAccuracy {
                            meilleure = lue
                        }
                        if lue.horizontalAccuracy <= 30 { return lue }
                        if Task.isCancelled { return meilleure }
                    }
                } catch {
                    return meilleure
                }
                return meilleure
            }
            groupe.addTask {
                try? await Task.sleep(for: .seconds(delaiMax))
                return nil
            }
            let premiere = await groupe.next() ?? nil
            groupe.cancelAll()
            return premiere
        }
        guard let trouvee else { throw ErreurGuidage.positionIndisponible }
        precisionM = trouvee.horizontalAccuracy
        return trouvee
    }

    // MARK: - Où suis-je ?

    func ouSuisJe() async throws -> String {
        if let refus = garde.refus(fonction: "ou_suis_je") { throw refus }
        guard accordCartes else { throw ErreurGuidage.accordRequis }
        let position = try await localiser()
        let precision = position.horizontalAccuracy
        var phrase: String
        do {
            let lieux = try await CLGeocoder().reverseGeocodeLocation(position, preferredLocale: Locale(identifier: "fr_CA"))
            if let lieu = lieux.first {
                phrase = Self.phraseAdresse(lieu)
            } else {
                phrase = "Je n'ai pas trouvé d'adresse pour cette position."
            }
        } catch {
            phrase = "Adresse introuvable (réseau requis). Coordonnées : \(Self.coordonnees(position.coordinate))."
        }
        if precision > 50 {
            phrase += " Position approximative, à environ \(NombresFr.distance(precision)) près : l'adresse peut être celle d'un bâtiment voisin."
        } else {
            phrase += " Position précise à environ \(NombresFr.distance(precision))."
        }
        if position.speed > 0.7, position.courseAccuracy >= 0, position.courseAccuracy < 45 {
            phrase += " Tu te déplaces vers \(Self.direction(position.course))."
        }
        return phrase
    }

    static func phraseAdresse(_ lieu: CLPlacemark) -> String {
        var morceaux: [String] = []
        if let rue = lieu.thoroughfare {
            if let numero = lieu.subThoroughfare { morceaux.append("\(numero), \(rue)") } else { morceaux.append(rue) }
        } else if let nom = lieu.name {
            morceaux.append(nom)
        }
        var phrase = morceaux.isEmpty ? "Je ne trouve pas le nom de la rue ici" : "Tu es près du \(morceaux.joined())"
        if let ville = lieu.locality {
            phrase += ", à \(ville)"
        }
        phrase += "."
        if let interet = lieu.areasOfInterest?.first {
            phrase += " Lieu à proximité : \(interet)."
        }
        return phrase
    }

    static func coordonnees(_ c: CLLocationCoordinate2D) -> String {
        let lat = NombresFr.decimal(abs(c.latitude), chiffres: 5) + (c.latitude >= 0 ? " nord" : " sud")
        let lon = NombresFr.decimal(abs(c.longitude), chiffres: 5) + (c.longitude >= 0 ? " est" : " ouest")
        return "\(lat), \(lon)"
    }

    static func direction(_ cap: CLLocationDirection) -> String {
        let noms = ["le nord", "le nord-est", "l'est", "le sud-est", "le sud", "le sud-ouest", "l'ouest", "le nord-ouest"]
        let index = Int(((cap.truncatingRemainder(dividingBy: 360) + 22.5) / 45).rounded(.down)) % 8
        return noms[max(0, index)]
    }

    // MARK: - Recherche d'un lieu

    func rechercher(_ texte: String) async throws -> [LieuTrouve] {
        let requeteTexte = texte.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !requeteTexte.isEmpty else { return [] }
        guard accordCartes else { throw ErreurGuidage.accordRequis }
        let position = try? await localiser(delaiMax: 6)
        let demande = MKLocalSearch.Request()
        demande.naturalLanguageQuery = requeteTexte
        demande.resultTypes = [.address, .pointOfInterest]
        if let position {
            demande.region = MKCoordinateRegion(center: position.coordinate, latitudinalMeters: 30_000, longitudinalMeters: 30_000)
        }
        let reponse: MKLocalSearch.Response
        do {
            reponse = try await MKLocalSearch(request: demande).start()
        } catch {
            let code = (error as NSError).code
            if code == Int(MKError.placemarkNotFound.rawValue) || code == Int(MKError.directionsNotFound.rawValue) {
                throw ErreurGuidage.destinationIntrouvable(requeteTexte)
            }
            throw ErreurGuidage.reseau(error.localizedDescription)
        }
        let lieux = reponse.mapItems.prefix(6).map { element -> LieuTrouve in
            let distance = position.flatMap { p in element.placemark.location.map { p.distance(from: $0) } }
            return LieuTrouve(element: element, nom: element.name ?? "Lieu sans nom",
                              adresse: element.placemark.title ?? "", distanceM: distance)
        }
        guard !lieux.isEmpty else { throw ErreurGuidage.destinationIntrouvable(requeteTexte) }
        return Array(lieux)
    }

    // MARK: - Guide-moi

    func guider(vers destination: String) async throws {
        let lieux = try await rechercher(destination)
        guard let premier = lieux.first else { throw ErreurGuidage.destinationIntrouvable(destination) }
        try await guider(vers: premier)
    }

    func guider(vers lieu: LieuTrouve) async throws {
        if let refus = garde.refus(fonction: "guidage") { throw refus }
        guard accordCartes else { throw ErreurGuidage.accordRequis }
        erreur = nil
        let position = try await localiser()
        let route = try await calculer(depuis: position, vers: lieu.element)
        destination = lieu.element
        destinationNom = lieu.nom
        appliquer(route)
        guidageActif = true
        ecartsDeSuite = 0
        EveilEcran.activer("guidage")
        gestionnaire.allowsBackgroundLocationUpdates = true
        gestionnaire.showsBackgroundLocationIndicator = true
        gestionnaire.startUpdatingLocation()
        var phrase = "Itinéraire à pied vers \(lieu.nom) : \(NombresFr.distance(route.distance)), environ \(NombresFr.duree(route.expectedTravelTime))."
        if let premiere = etapes.first {
            phrase += " \(premiere.texte)."
        }
        dire(phrase)
    }

    func arreterGuidage() {
        guard guidageActif else { return }
        guidageActif = false
        gestionnaire.stopUpdatingLocation()
        gestionnaire.allowsBackgroundLocationUpdates = false
        EveilEcran.desactiver("guidage")
        etatTexte = nil
        dire("Guidage arrêté.")
    }

    /// Redit la consigne en cours et la distance jusqu'à elle.
    func repeter() {
        guard guidageActif, indexEtape < etapes.count else { return }
        var phrase = etapes[indexEtape].texte
        if let distance = distanceProchaineM {
            phrase = "Dans \(NombresFr.distance(distance)) : \(phrase)"
        }
        dire(phrase)
    }

    private func calculer(depuis position: CLLocation, vers cible: MKMapItem) async throws -> MKRoute {
        let demande = MKDirections.Request()
        demande.source = MKMapItem(placemark: MKPlacemark(coordinate: position.coordinate))
        demande.destination = cible
        demande.transportType = .walking
        demande.requestsAlternateRoutes = false
        do {
            let reponse = try await MKDirections(request: demande).calculate()
            guard let route = reponse.routes.first else { throw ErreurGuidage.itineraireImpossible("aucun trajet rendu") }
            return route
        } catch let erreur as ErreurGuidage {
            throw erreur
        } catch {
            let code = (error as NSError).code
            if code == Int(MKError.directionsNotFound.rawValue) {
                throw ErreurGuidage.itineraireImpossible("aucun chemin piéton connu entre ici et ce lieu")
            }
            throw ErreurGuidage.reseau(error.localizedDescription)
        }
    }

    private func appliquer(_ route: MKRoute) {
        itineraire = route
        // La première étape d'iOS est souvent vide (« départ ») : on ne garde que les consignes dites.
        etapesRoute = route.steps.filter { !$0.instructions.trimmingCharacters(in: .whitespaces).isEmpty }
        etapes = etapesRoute.map { EtapeGuidage(texte: $0.instructions, distanceM: $0.distance) }
        indexEtape = 0
        preavisDit = -1
        distanceRestanteM = route.distance
        dureePrevueS = route.expectedTravelTime
        distanceProchaineM = etapesRoute.first?.distance
        derniereConsigne = etapes.first?.texte
    }

    // MARK: - Suivi de la position

    private func suivre(_ position: CLLocation) {
        derniere = position
        precisionM = position.horizontalAccuracy
        guard guidageActif, let route = itineraire, position.horizontalAccuracy >= 0 else { return }
        let point = MKMapPoint(position.coordinate)

        // Arrivée : à 15 m de la fin du trajet, selon le GPS.
        if let fin = Self.dernierPoint(route.polyline) {
            let reste = point.distance(to: fin)
            if reste <= max(Self.arriveeM, min(position.horizontalAccuracy, 25)) {
                guidageActif = false
                gestionnaire.stopUpdatingLocation()
                gestionnaire.allowsBackgroundLocationUpdates = false
                EveilEcran.desactiver("guidage")
                etatTexte = "Arrivée selon le GPS."
                dire("Tu es arrivé à destination, selon le GPS. Vérifie autour de toi.")
                return
            }
        }

        guard position.horizontalAccuracy <= Self.precisionUtileM else {
            etatTexte = "GPS imprécis (environ \(NombresFr.distance(position.horizontalAccuracy)) près) : consignes de virage en pause."
            return
        }
        etatTexte = nil

        // Écart au trajet : recalcul après deux mesures fiables de suite.
        let ecart = Self.distance(de: point, a: route.polyline)
        if ecart > Self.ecartMaxM && position.horizontalAccuracy <= 30 {
            ecartsDeSuite += 1
            if ecartsDeSuite >= 2 && Date().timeIntervalSince(dernierRecalcul) >= Self.recalculMinS && !recalculEnCours {
                recalculer(depuis: position)
                return
            }
        } else {
            ecartsDeSuite = 0
        }

        guard indexEtape < etapesRoute.count else { return }
        let etape = etapesRoute[indexEtape]
        guard let finEtape = Self.dernierPoint(etape.polyline) else { return }
        let distance = point.distance(to: finEtape)
        distanceProchaineM = distance
        let apres = etapesRoute.dropFirst(indexEtape + 1).reduce(0) { $0 + $1.distance }
        distanceRestanteM = distance + apres

        let seuil = max(Self.distanceEtapeMinM, min(position.horizontalAccuracy, 25))
        if distance <= seuil {
            indexEtape += 1
            if indexEtape < etapesRoute.count {
                let suivante = etapesRoute[indexEtape].instructions
                derniereConsigne = suivante
                if preavisDit != indexEtape {
                    dire(suivante)
                } else {
                    dire("Maintenant : \(suivante)")
                }
            }
        } else if distance <= Self.distancePreavisM, preavisDit != indexEtape + 1, indexEtape + 1 < etapesRoute.count {
            preavisDit = indexEtape + 1
            dire("Dans \(NombresFr.distance(distance)) : \(etapesRoute[indexEtape + 1].instructions)")
        }
    }

    private func recalculer(depuis position: CLLocation) {
        guard let destination else { return }
        recalculEnCours = true
        dernierRecalcul = Date()
        ecartsDeSuite = 0
        etatTexte = "Tu sembles t'écarter du trajet : recalcul de l'itinéraire…"
        dire("Tu sembles t'écarter du trajet. Je recalcule.")
        Task { [weak self] in
            guard let self else { return }
            defer { self.recalculEnCours = false }
            do {
                let route = try await self.calculer(depuis: position, vers: destination)
                guard self.guidageActif else { return }
                self.appliquer(route)
                self.etatTexte = nil
                if let premiere = self.etapes.first {
                    self.dire("Nouvel itinéraire : \(NombresFr.distance(route.distance)). \(premiere.texte).")
                }
            } catch {
                self.etatTexte = "Recalcul impossible : \(error.localizedDescription) L'ancien trajet reste affiché."
            }
        }
    }

    private func dire(_ phrase: String) {
        derniereConsigne = phrase
        Annonce.urgent(phrase, voix: voix)
    }

    // MARK: - Géométrie

    static func dernierPoint(_ ligne: MKPolyline) -> MKMapPoint? {
        guard ligne.pointCount > 0 else { return nil }
        return ligne.points()[ligne.pointCount - 1]
    }

    /// Distance (m) d'un point au trajet : projection sur chaque segment, en coordonnées de carte (planes à
    /// l'échelle d'une rue), puis distance réelle entre le point et sa projection.
    static func distance(de point: MKMapPoint, a ligne: MKPolyline) -> Double {
        let n = ligne.pointCount
        guard n > 0 else { return .infinity }
        let points = ligne.points()
        if n == 1 { return point.distance(to: points[0]) }
        var meilleure = Double.infinity
        for i in 0..<(n - 1) {
            let a = points[i], b = points[i + 1]
            let dx = b.x - a.x, dy = b.y - a.y
            let longueur2 = dx * dx + dy * dy
            var t = 0.0
            if longueur2 > 0 {
                t = ((point.x - a.x) * dx + (point.y - a.y) * dy) / longueur2
                t = min(1, max(0, t))
            }
            let projection = MKMapPoint(x: a.x + t * dx, y: a.y + t * dy)
            meilleure = min(meilleure, point.distance(to: projection))
        }
        return meilleure
    }
}

/// Délégué de CLLocationManager (créé sur le fil principal, il y rappelle).
final class DelegueGuidage: NSObject, CLLocationManagerDelegate {
    var surAutorisation: (@MainActor (CLAuthorizationStatus) -> Void)?
    var surPosition: (@MainActor (CLLocation) -> Void)?
    var surErreur: (@MainActor (String) -> Void)?

    func locationManagerDidChangeAuthorization(_ manager: CLLocationManager) {
        let statut = manager.authorizationStatus
        MainActor.assumeIsolated { surAutorisation?(statut) }
    }

    func locationManager(_ manager: CLLocationManager, didUpdateLocations locations: [CLLocation]) {
        guard let derniere = locations.last else { return }
        MainActor.assumeIsolated { surPosition?(derniere) }
    }

    func locationManager(_ manager: CLLocationManager, didFailWithError error: Error) {
        let code = (error as? CLError)?.code
        let message: String
        switch code {
        case .denied?:
            message = "Position refusée pour IRIS : Réglages › IRIS › Position."
        case .locationUnknown?:
            message = "Position momentanément inconnue : le GPS cherche."
        default:
            message = "Position indisponible : \(error.localizedDescription)"
        }
        MainActor.assumeIsolated { surErreur?(message) }
    }
}
