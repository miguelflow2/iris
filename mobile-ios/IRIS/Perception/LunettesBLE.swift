// LunettesBLE.swift — les lunettes VELA reliées à l'iPhone par Bluetooth basse énergie (CoreBluetooth).
//
// Ce que ce service fait, et ses limites réelles :
// - il cherche les lunettes (annonces dont le nom ou les services ressemblent à ceux de la famille VELA),
//   s'y connecte, s'abonne à leurs notifications et lit la batterie (caractéristique standard si elle
//   existe, sinon la trame maison 0xBC, seule source observée sur la vraie paire) ;
// - il retient la paire et la reconnecte seul quand elle revient à portée (reconnexion automatique
//   d'iOS 17 et restauration d'état : iOS peut relancer l'app en arrière-plan pour ça) ;
// - le son (micro et haut-parleur des lunettes) ne passe PAS par ici : c'est le Bluetooth classique,
//   appairé dans Réglages › Bluetooth. Une app ne peut pas faire cet appairage-là à la place d'iOS ;
// - la caméra : service ae00 repéré s'il existe, mais la commande photo est REFUSÉE tant que l'en-tête de
//   trame n'est pas confirmé sur le vrai matériel (voir TramesLunettes.swift). Un accès d'exploration du
//   propriétaire existe pour la valider : l'argument de lancement Xcode « -iris_lunettes_exploration YES ».
//   Il n'apparaît dans aucun écran ni dans aucun message.
//
// Protocole non prouvé sur tous les modèles : une paire qui n'annonce ni batterie standard ni trame 0xBC
// reste connectée, avec « batterie inconnue ».

import CoreBluetooth
import Foundation
import Observation
import os

enum ErreurLunettes: Error, LocalizedError {
    case bluetooth(String)
    case introuvables
    case nonConnectees
    case delaiConnexion
    case connexion(String)
    case cameraAbsente
    case protocoleNonConfirme
    case photoEnCours
    case photoSansImage(paquets: Int)
    case photoSansReponse(secondes: Int)

    var errorDescription: String? {
        switch self {
        case .bluetooth(let message), .connexion(let message):
            return message
        case .introuvables:
            return "Ces lunettes ne sont plus visibles. Allume-les ou sors-les de l'étui, rapproche-les de l'iPhone, puis relance la recherche."
        case .nonConnectees:
            return "Les lunettes ne sont pas connectées à cet iPhone."
        case .delaiConnexion:
            return "Les lunettes n'ont pas répondu en 20 secondes. Vérifie qu'elles sont allumées, à moins de 2 mètres, et qu'aucune autre app ne les utilise."
        case .cameraAbsente:
            return "Ces lunettes n'exposent pas l'interface caméra (service ae00). C'est normal sur une paire audio : elle n'a pas de caméra."
        case .protocoleNonConfirme:
            return "La commande photo des lunettes est identifiée, mais l'en-tête exact de la trame n'est pas encore confirmé sur le vrai matériel. Par prudence, IRIS n'écrit pas d'octets non prouvés dans les lunettes."
        case .photoEnCours:
            return "Une photo des lunettes est déjà en cours. Attends qu'elle se termine."
        case .photoSansImage(let paquets):
            return "Commande envoyée, \(paquets) paquet(s) reçu(s) des lunettes, mais aucune image décodable n'a pu être reconstituée."
        case .photoSansReponse(let secondes):
            return "Commande envoyée, aucune réponse des lunettes en \(secondes) secondes."
        }
    }
}

@MainActor
@Observable
final class LunettesBLE: ServiceLunettes {
    private(set) var etat = EtatLunettes()
    private(set) var appareilsTrouves: [AppareilLunettes] = []
    private(set) var rechercheEnCours = false
    private(set) var connexionEnCours = false
    private(set) var etatBluetooth: CBManagerState = .unknown
    /// Services vus sur la paire connectée : dit quel modèle on a vraiment en main.
    private(set) var servicesVus: [String] = []
    private(set) var cameraExposee = false
    private(set) var canalCommandeVu = false
    private(set) var derniereErreur: String?
    /// Nom de la paire retenue sur cet iPhone (reconnexion automatique).
    private(set) var paireMemorisee: String?
    /// Méthode employée pour la dernière photo réussie (exploration seulement).
    private(set) var derniereMethodePhoto: String?

    @ObservationIgnored var surChangement: (@MainActor (EtatLunettes) -> Void)?

    @ObservationIgnored private var central: CBCentralManager?
    @ObservationIgnored private let delegue = DelegueBluetoothLunettes()
    @ObservationIgnored private var vus: [UUID: CBPeripheral] = [:]
    @ObservationIgnored private var courant: CBPeripheral?
    @ObservationIgnored private var attenteConnexion: CheckedContinuation<Void, Error>?
    @ObservationIgnored private var rechercheVoulue = false
    @ObservationIgnored private var finRecherche: Task<Void, Never>?
    @ObservationIgnored private var ecritureCamera: CBCharacteristic?
    @ObservationIgnored private var notificationCamera: CBCharacteristic?
    @ObservationIgnored private var collecteur: CollecteurPhoto?
    @ObservationIgnored private var photoReussie = false
    @ObservationIgnored private var dernierEtatPublie: EtatLunettes?
    @ObservationIgnored private let journal = Logger(subsystem: "ca.velaglass.iris", category: "lunettes")

    private enum Cles {
        static let identifiant = "iris_lunettes_identifiant"
        static let nom = "iris_lunettes_nom"
        static let reconnexion = "iris_lunettes_reconnexion"
        static let exploration = "iris_lunettes_exploration"
    }

    static let identifiantRestauration = "ca.velaglass.iris.lunettes"
    static let delaiPhotoS = 20

    /// Accès d'exploration du propriétaire : seulement par argument de lancement dans Xcode
    /// (« -iris_lunettes_exploration YES »), jamais depuis un écran.
    static var explorationPermise: Bool {
        UserDefaults.standard.bool(forKey: Cles.exploration)
    }

    init() {
        paireMemorisee = UserDefaults.standard.string(forKey: Cles.nom)
        delegue.proprietaire = self
        #if DEBUG
        assert(TramesLunettes.autoVerifier(), "Le portage Swift du protocole 0xBC ne relit plus les trames observées.")
        #endif
        // Créé dès le lancement seulement si le Bluetooth est déjà permis ou qu'une paire est retenue
        // (restauration d'état). Sinon, iOS demanderait l'accès au Bluetooth au tout premier lancement,
        // avant que l'utilisateur ait demandé quoi que ce soit.
        if CBCentralManager.authorization == .allowedAlways || UserDefaults.standard.string(forKey: Cles.identifiant) != nil {
            creerCentral()
        }
    }

    private func creerCentral() {
        guard central == nil else { return }
        central = CBCentralManager(delegate: delegue, queue: .main, options: [
            CBCentralManagerOptionRestoreIdentifierKey: Self.identifiantRestauration,
            CBCentralManagerOptionShowPowerAlertKey: false,
        ])
    }

    // MARK: - Recherche

    func rechercher() {
        creerCentral()
        rechercheVoulue = true
        derniereErreur = nil
        guard let central, central.state == .poweredOn else {
            if etat.message == nil { etat.message = "Préparation du Bluetooth…" }
            publier()
            return
        }
        lancerRecherche(central)
    }

    private func lancerRecherche(_ central: CBCentralManager) {
        rechercheVoulue = false
        // Des lunettes déjà reliées à l'iPhone n'émettent plus d'annonce : on les retrouve par leurs services.
        for p in central.retrieveConnectedPeripherals(withServices: UUIDLunettes.servicesConnus) {
            ajouterTrouve(p, nom: p.name, rssi: nil, services: UUIDLunettes.servicesConnus)
        }
        // Recherche sans filtre de service : ces lunettes n'annoncent pas toujours leurs services. Elle ne
        // marche qu'app ouverte (iOS l'exige), ce qui est le cas de l'écran d'appairage.
        central.scanForPeripherals(withServices: nil, options: [CBCentralManagerScanOptionAllowDuplicatesKey: false])
        rechercheEnCours = true
        finRecherche?.cancel()
        finRecherche = Task { [weak self] in
            try? await Task.sleep(for: .seconds(15))
            if Task.isCancelled { return }
            self?.arreterRecherche()
        }
    }

    func arreterRecherche() {
        rechercheVoulue = false
        finRecherche?.cancel()
        finRecherche = nil
        if central?.isScanning == true { central?.stopScan() }
        if rechercheEnCours && appareilsTrouves.isEmpty && !etat.connectees {
            derniereErreur = "Aucune paire de lunettes VELA trouvée. Allume-les ou sors-les de l'étui, rapproche-les de l'iPhone, puis relance la recherche."
        }
        rechercheEnCours = false
    }

    private func ajouterTrouve(_ p: CBPeripheral, nom: String?, rssi: Int?, services: [CBUUID]) {
        let bas = (nom ?? "").lowercased()
        let parNom = UUIDLunettes.indicesNom.contains { bas.contains($0) }
        let parService = services.contains { UUIDLunettes.servicesConnus.contains($0) }
        guard parNom || parService else { return }
        vus[p.identifier] = p
        let affiche = (nom?.trimmingCharacters(in: .whitespaces).isEmpty == false) ? nom! : "Lunettes (sans nom)"
        // 127 : iOS n'a pas pu mesurer la force du signal.
        let appareil = AppareilLunettes(id: p.identifier.uuidString, nom: affiche, rssi: rssi == 127 ? nil : rssi)
        if let index = appareilsTrouves.firstIndex(where: { $0.id == appareil.id }) {
            appareilsTrouves[index] = appareil
        } else {
            appareilsTrouves.append(appareil)
        }
        appareilsTrouves.sort { ($0.rssi ?? -999) > ($1.rssi ?? -999) }
    }

    // MARK: - Connexion

    func connecter(_ appareil: AppareilLunettes) async throws {
        creerCentral()
        guard let central else { throw ErreurLunettes.bluetooth("Bluetooth indisponible sur cet iPhone.") }
        guard central.state == .poweredOn else {
            throw ErreurLunettes.bluetooth(etat.message ?? "Bluetooth indisponible : active-le dans le Centre de contrôle.")
        }
        guard !connexionEnCours else { throw ErreurLunettes.connexion("Une connexion aux lunettes est déjà en cours.") }
        let uuid = UUID(uuidString: appareil.id)
        guard let p = uuid.flatMap({ vus[$0] }) ?? uuid.flatMap({ central.retrievePeripherals(withIdentifiers: [$0]).first }) else {
            throw ErreurLunettes.introuvables
        }
        arreterRecherche()
        if let ancien = courant, ancien.identifier != p.identifier, ancien.state != .disconnected {
            central.cancelPeripheralConnection(ancien)
        }
        p.delegate = delegue
        courant = p
        connexionEnCours = true
        defer { connexionEnCours = false }
        derniereErreur = nil
        etat.message = "Connexion à « \(appareil.nom) »…"
        publier()

        if p.state != .connected {
            do {
                try await withCheckedThrowingContinuation { (suite: CheckedContinuation<Void, Error>) in
                    attenteConnexion = suite
                    central.connect(p, options: [CBConnectPeripheralOptionEnableAutoReconnect: true])
                    Task { [weak self] in
                        try? await Task.sleep(for: .seconds(20))
                        self?.expirerConnexion(p)
                    }
                }
            } catch {
                derniereErreur = error.localizedDescription
                etat.message = error.localizedDescription
                publier()
                throw error
            }
        } else {
            preparerConnectee(p)
        }
        UserDefaults.standard.set(p.identifier.uuidString, forKey: Cles.identifiant)
        UserDefaults.standard.set(appareil.nom, forKey: Cles.nom)
        UserDefaults.standard.set(true, forKey: Cles.reconnexion)
        paireMemorisee = appareil.nom
        journal.info("lunettes connectées")
    }

    private func expirerConnexion(_ p: CBPeripheral) {
        guard let suite = attenteConnexion, courant?.identifier == p.identifier, p.state != .connected else { return }
        attenteConnexion = nil
        central?.cancelPeripheralConnection(p)
        suite.resume(throwing: ErreurLunettes.delaiConnexion)
    }

    func deconnecter() {
        UserDefaults.standard.set(false, forKey: Cles.reconnexion)
        if let p = courant, p.state != .disconnected {
            central?.cancelPeripheralConnection(p)
        }
        marquerDeconnectees(message: nil)
        publier()
    }

    /// Oublie la paire retenue sur cet iPhone (plus de reconnexion automatique).
    func oublier() {
        deconnecter()
        UserDefaults.standard.removeObject(forKey: Cles.identifiant)
        UserDefaults.standard.removeObject(forKey: Cles.nom)
        paireMemorisee = nil
        courant = nil
        etat = EtatLunettes()
        publier()
    }

    /// Demande sans délai à iOS de relier la paire retenue : la connexion se fait dès qu'elle réapparaît,
    /// même app en arrière-plan.
    private func reconnecterMemorisee() {
        guard let central, central.state == .poweredOn,
              UserDefaults.standard.bool(forKey: Cles.reconnexion),
              let texte = UserDefaults.standard.string(forKey: Cles.identifiant),
              let uuid = UUID(uuidString: texte) else { return }
        if let courant, courant.state == .connected || courant.state == .connecting { return }
        guard let p = courant ?? central.retrievePeripherals(withIdentifiers: [uuid]).first else { return }
        p.delegate = delegue
        courant = p
        central.connect(p, options: [CBConnectPeripheralOptionEnableAutoReconnect: true])
        if !etat.connectees {
            etat.message = "En attente des lunettes « \(paireMemorisee ?? p.name ?? "VELA") » : elles se relieront seules à leur retour."
            publier()
        }
    }

    private func preparerConnectee(_ p: CBPeripheral) {
        p.delegate = delegue
        etat.connectees = true
        etat.nom = p.name ?? paireMemorisee ?? "Lunettes VELA"
        etat.identifiant = p.identifier.uuidString
        etat.message = nil
        servicesVus = []
        cameraExposee = false
        canalCommandeVu = false
        ecritureCamera = nil
        notificationCamera = nil
        p.discoverServices(nil)
        publier()
    }

    private func marquerDeconnectees(message: String?) {
        etat.connectees = false
        etat.batterie = nil
        etat.message = message
        ecritureCamera = nil
        notificationCamera = nil
    }

    private var cameraConfirmee: Bool {
        cameraExposee && (ProtocoleCamera.enteteConfirme || (Self.explorationPermise && photoReussie))
    }

    private func publier() {
        etat.cameraConfirmee = etat.connectees && cameraConfirmee
        guard dernierEtatPublie != etat else { return }
        dernierEtatPublie = etat
        surChangement?(etat)
    }

    // MARK: - Photo (refusée tant que le protocole n'est pas confirmé)

    func prendrePhoto() async throws -> ImageCapturee {
        guard let p = courant, p.state == .connected, etat.connectees else { throw ErreurLunettes.nonConnectees }
        guard let ecriture = ecritureCamera, let notification = notificationCamera else { throw ErreurLunettes.cameraAbsente }
        guard ProtocoleCamera.enteteConfirme || Self.explorationPermise else { throw ErreurLunettes.protocoleNonConfirme }
        guard collecteur == nil else { throw ErreurLunettes.photoEnCours }

        let c = CollecteurPhoto()
        collecteur = c
        defer { collecteur = nil }
        if !notification.isNotifying {
            p.setNotifyValue(true, for: notification)
        }
        let trame = ProtocoleCamera.trameHypothese(charge: ProtocoleCamera.chargePhoto, type: ProtocoleCamera.typeCamera)
        let type: CBCharacteristicWriteType = ecriture.properties.contains(.write) ? .withResponse : .withoutResponse
        let taille = max(20, p.maximumWriteValueLength(for: type))
        var debut = 0
        while debut < trame.count {
            let fin = min(debut + taille, trame.count)
            p.writeValue(Data(trame[debut..<fin]), for: ecriture, type: type)
            debut = fin
        }
        journal.info("photo : trame hypothèse écrite (\(TramesLunettes.hexa(trame), privacy: .public))")

        let depart = Date()
        while Date().timeIntervalSince(depart) < Double(Self.delaiPhotoS) {
            if c.termine { break }
            try await Task.sleep(for: .milliseconds(200))
            guard courant?.state == .connected else { throw ErreurLunettes.nonConnectees }
        }
        guard let assemblee = c.assembler() else {
            if c.paquets.isEmpty { throw ErreurLunettes.photoSansReponse(secondes: Self.delaiPhotoS) }
            throw ErreurLunettes.photoSansImage(paquets: c.paquets.count)
        }
        let (image, methode) = assemblee
        photoReussie = true
        derniereMethodePhoto = methode
        publier()
        return ImageCapturee(donnees: image, typeMedia: "image/jpeg", provenance: .lunettes)
    }

    // MARK: - Rappels du délégué (fil principal)

    fileprivate func bluetoothChange(_ central: CBCentralManager) {
        etatBluetooth = central.state
        switch central.state {
        case .poweredOn:
            if !etat.connectees { etat.message = nil }
            if rechercheVoulue { lancerRecherche(central) }
            reconnecterMemorisee()
        case .poweredOff:
            marquerDeconnectees(message: "Bluetooth éteint : active-le dans le Centre de contrôle pour relier les lunettes.")
            rechercheEnCours = false
        case .unauthorized:
            marquerDeconnectees(message: "Bluetooth refusé pour IRIS : Réglages › IRIS › Bluetooth.")
            rechercheEnCours = false
        case .unsupported:
            marquerDeconnectees(message: "Cet appareil ne gère pas le Bluetooth basse énergie.")
        case .resetting:
            etat.message = "Le Bluetooth de l'iPhone redémarre…"
        case .unknown:
            break
        @unknown default:
            break
        }
        publier()
    }

    fileprivate func restaurer(_ peripheriques: [CBPeripheral]) {
        let retenu = UserDefaults.standard.string(forKey: Cles.identifiant)
        guard let p = peripheriques.first(where: { $0.identifier.uuidString == retenu }) ?? peripheriques.first else { return }
        p.delegate = delegue
        vus[p.identifier] = p
        courant = p
        if p.state == .connected {
            preparerConnectee(p)
        }
    }

    fileprivate func decouvert(_ p: CBPeripheral, annonce: [String: Any], rssi: NSNumber) {
        let nom = (annonce[CBAdvertisementDataLocalNameKey] as? String) ?? p.name
        let services = (annonce[CBAdvertisementDataServiceUUIDsKey] as? [CBUUID]) ?? []
        ajouterTrouve(p, nom: nom, rssi: rssi.intValue, services: services)
    }

    fileprivate func connectee(_ p: CBPeripheral) {
        guard p.identifier == courant?.identifier else { return }
        preparerConnectee(p)
        if let suite = attenteConnexion {
            attenteConnexion = nil
            suite.resume()
        }
    }

    fileprivate func echecConnexion(_ p: CBPeripheral, erreur: Error?) {
        guard p.identifier == courant?.identifier else { return }
        let message = "Connexion aux lunettes impossible" + (erreur.map { " : \($0.localizedDescription)" } ?? ".")
        etat.message = message
        derniereErreur = message
        if let suite = attenteConnexion {
            attenteConnexion = nil
            suite.resume(throwing: ErreurLunettes.connexion(message))
        }
        publier()
    }

    fileprivate func deconnectee(_ p: CBPeripheral, reconnexionSysteme: Bool, erreur: Error?) {
        guard p.identifier == courant?.identifier else { return }
        let voulue = !UserDefaults.standard.bool(forKey: Cles.reconnexion)
        let message: String?
        if voulue {
            message = nil
        } else if reconnexionSysteme {
            message = "Lunettes hors de portée : iOS les reliera de nouveau dès leur retour."
        } else {
            message = "Lunettes déconnectées" + (erreur.map { " (\($0.localizedDescription))." } ?? ".")
        }
        marquerDeconnectees(message: message)
        if let suite = attenteConnexion {
            attenteConnexion = nil
            suite.resume(throwing: ErreurLunettes.connexion(erreur?.localizedDescription ?? "Connexion perdue."))
        }
        if !voulue && !reconnexionSysteme {
            reconnecterMemorisee()
        }
        publier()
    }

    fileprivate func servicesDecouverts(_ p: CBPeripheral, erreur: Error?) {
        guard p.identifier == courant?.identifier else { return }
        if let erreur {
            derniereErreur = "Services des lunettes illisibles : \(erreur.localizedDescription)"
            publier()
            return
        }
        let services = p.services ?? []
        servicesVus = services.map { $0.uuid.uuidString }
        cameraExposee = services.contains { $0.uuid == UUIDLunettes.serviceCamera }
        canalCommandeVu = services.contains { $0.uuid == UUIDLunettes.serviceCommande }
        for service in services {
            p.discoverCharacteristics(nil, for: service)
        }
        publier()
    }

    fileprivate func caracteristiquesDecouvertes(_ p: CBPeripheral, service: CBService, erreur: Error?) {
        guard p.identifier == courant?.identifier, erreur == nil else { return }
        for c in service.characteristics ?? [] {
            if c.uuid == UUIDLunettes.ecritureCamera { ecritureCamera = c }
            if c.uuid == UUIDLunettes.notificationCamera { notificationCamera = c }
            // S'abonner (écrire le descripteur de notification) ne commande rien aux lunettes : c'est ce que
            // fait aussi l'ordinateur (glasses.py). Aucune écriture n'est faite sur les caractéristiques.
            if c.properties.contains(.notify) || c.properties.contains(.indicate) {
                p.setNotifyValue(true, for: c)
            }
            if c.uuid == UUIDLunettes.niveauBatterie, c.properties.contains(.read) {
                p.readValue(for: c)
            }
        }
        publier()
    }

    fileprivate func valeurRecue(_ p: CBPeripheral, caracteristique: CBCharacteristic, erreur: Error?) {
        guard p.identifier == courant?.identifier, erreur == nil, let donnees = caracteristique.value else { return }
        let octets = [UInt8](donnees)
        if caracteristique.uuid == UUIDLunettes.notificationCamera, let collecteur {
            collecteur.ajouter(octets)
            return
        }
        if caracteristique.uuid == UUIDLunettes.niveauBatterie {
            if let premier = octets.first, premier <= 100 { majBatterie(Int(premier)) }
            return
        }
        if let niveau = TramesLunettes.batterie(octets) {
            majBatterie(niveau)
        }
    }

    fileprivate func nomChange(_ p: CBPeripheral) {
        guard p.identifier == courant?.identifier, etat.connectees, let nom = p.name else { return }
        etat.nom = nom
        publier()
    }

    private func majBatterie(_ niveau: Int) {
        guard etat.batterie != niveau else { return }
        etat.batterie = niveau
        publier()
    }
}

// MARK: - Délégué CoreBluetooth

/// Délégué séparé (NSObject) : CoreBluetooth rappelle sur la file principale (queue: .main), donc on
/// peut entrer dans le MainActor sans saut de fil.
final class DelegueBluetoothLunettes: NSObject, CBCentralManagerDelegate, CBPeripheralDelegate {
    weak var proprietaire: LunettesBLE?

    func centralManagerDidUpdateState(_ central: CBCentralManager) {
        MainActor.assumeIsolated { proprietaire?.bluetoothChange(central) }
    }

    func centralManager(_ central: CBCentralManager, willRestoreState dict: [String: Any]) {
        let peripheriques = dict[CBCentralManagerRestoredStatePeripheralsKey] as? [CBPeripheral] ?? []
        for p in peripheriques { p.delegate = self }
        MainActor.assumeIsolated { proprietaire?.restaurer(peripheriques) }
    }

    func centralManager(_ central: CBCentralManager, didDiscover peripheral: CBPeripheral,
                        advertisementData: [String: Any], rssi RSSI: NSNumber) {
        MainActor.assumeIsolated { proprietaire?.decouvert(peripheral, annonce: advertisementData, rssi: RSSI) }
    }

    func centralManager(_ central: CBCentralManager, didConnect peripheral: CBPeripheral) {
        MainActor.assumeIsolated { proprietaire?.connectee(peripheral) }
    }

    func centralManager(_ central: CBCentralManager, didFailToConnect peripheral: CBPeripheral, error: Error?) {
        MainActor.assumeIsolated { proprietaire?.echecConnexion(peripheral, erreur: error) }
    }

    /// iOS 17 : appelé à la place de la version sans `isReconnecting` quand il est implémenté.
    func centralManager(_ central: CBCentralManager, didDisconnectPeripheral peripheral: CBPeripheral,
                        timestamp: CFAbsoluteTime, isReconnecting: Bool, error: Error?) {
        MainActor.assumeIsolated {
            proprietaire?.deconnectee(peripheral, reconnexionSysteme: isReconnecting, erreur: error)
        }
    }

    func centralManager(_ central: CBCentralManager, didDisconnectPeripheral peripheral: CBPeripheral, error: Error?) {
        MainActor.assumeIsolated {
            proprietaire?.deconnectee(peripheral, reconnexionSysteme: false, erreur: error)
        }
    }

    func peripheral(_ peripheral: CBPeripheral, didDiscoverServices error: Error?) {
        MainActor.assumeIsolated { proprietaire?.servicesDecouverts(peripheral, erreur: error) }
    }

    func peripheral(_ peripheral: CBPeripheral, didDiscoverCharacteristicsFor service: CBService, error: Error?) {
        MainActor.assumeIsolated { proprietaire?.caracteristiquesDecouvertes(peripheral, service: service, erreur: error) }
    }

    func peripheral(_ peripheral: CBPeripheral, didUpdateValueFor characteristic: CBCharacteristic, error: Error?) {
        MainActor.assumeIsolated { proprietaire?.valeurRecue(peripheral, caracteristique: characteristic, erreur: error) }
    }

    func peripheralDidUpdateName(_ peripheral: CBPeripheral) {
        MainActor.assumeIsolated { proprietaire?.nomChange(peripheral) }
    }
}
