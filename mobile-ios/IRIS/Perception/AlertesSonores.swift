// AlertesSonores.swift — prévenir d'un son important (alarme, sirène, klaxon, sonnette…) par vibration,
// notification et voix, avec le classifieur de sons intégré à iOS (SoundAnalysis), SUR l'iPhone.
//
// Ce qui est fait :
// - le son du micro (celui des lunettes quand elles sont reliées en mains libres) passe dans
//   SNClassifySoundRequest(.version1) par fenêtres d'environ une seconde, qui se chevauchent de moitié ;
// - chaque type d'alerte correspond à une ou plusieurs classes du classifieur. Les identifiants sont
//   VÉRIFIÉS à l'exécution contre knownClassifications : un type dont aucune classe n'existe sur cet
//   iPhone est affiché « indisponible », jamais simulé ;
// - anti-rebond : il faut une confiance au-dessus du seuil (réglé par la sensibilité) sur une ou deux
//   fenêtres de suite selon le type, puis 10 secondes de silence pour le même type.
//
// Limites réelles, affichées : le classifieur se trompe (faux positifs avec la musique ou la télévision,
// sons lointains manqués) ; la détection prend environ 1 à 3 secondes ; l'écoute tourne app ouverte, ou en
// arrière-plan tant qu'iOS garde le micro actif (un appel ou Siri l'interrompt) ; « ton prénom » n'est pas
// détecté sur l'iPhone. Rien n'est enregistré : le son est analysé puis oublié.
//
// Lunettes d'abord, aussi dans la durée : l'activation exige les lunettes, et le veilleur les revérifie
// chaque seconde. Absentes 10 minutes de suite, les alertes s'arrêtent seules et IRIS le dit à voix haute.
// Pourquoi pas tout de suite : une coupure Bluetooth de quelques secondes (lunettes posées, rangées un
// instant) ne doit pas laisser une personne malentendante sans alerte en pleine rue. Le délai de
// 10 minutes est une proposition, à faire trancher par Miguel.
//
// En arrière-plan, le pont vers l'ordinateur est fermé : le mode confidentiel et le verrou ne peuvent plus
// arriver par événement. Le veilleur redemande GET /api/settings environ chaque minute et arrête les alertes
// si l'un ou l'autre est actif (voir sonderEnArrierePlan).

import AVFoundation
import Foundation
import Observation
import SoundAnalysis
import UIKit
import UserNotifications

/// Un type d'alerte et les classes du classifieur d'iOS qui le déclenchent.
struct DefinitionAlerte: Identifiable, Hashable {
    let id: String
    let libelle: String
    let annonce: String
    let classes: [String]
    let seuilBase: Double
    let fenetresRequises: Int
}

/// Observateur des résultats : appelé sur la file d'analyse, il ne garde rien et passe des valeurs simples.
final class ObservateurSons: NSObject, SNResultsObserving {
    var surResultat: (([(String, Double)]) -> Void)?
    var surEchec: ((String) -> Void)?

    func request(_ request: SNRequest, didProduce result: SNResult) {
        guard let classement = result as? SNClassificationResult else { return }
        let valeurs = classement.classifications.map { ($0.identifier, $0.confidence) }
        surResultat?(valeurs)
    }

    func request(_ request: SNRequest, didFailWithError error: Error) {
        surEchec?(error.localizedDescription)
    }

    func requestDidComplete(_ request: SNRequest) {}
}

/// L'analyseur courant, lu par le fil audio : protégé par un verrou, analysé sur une file dédiée.
final class BoiteAnalyseur {
    private let verrou = NSLock()
    private var analyseur: SNAudioStreamAnalyzer?
    let file = DispatchQueue(label: "ca.velaglass.iris.alertes.analyse")

    func remplacer(par nouveau: SNAudioStreamAnalyzer?) {
        verrou.lock()
        let ancien = analyseur
        analyseur = nouveau
        verrou.unlock()
        if let ancien {
            file.async { ancien.removeAllRequests() }
        }
    }

    func analyser(_ tampon: AVAudioPCMBuffer, _ quand: AVAudioTime) {
        verrou.lock()
        let a = analyseur
        verrou.unlock()
        guard let a else { return }
        file.async {
            a.analyze(tampon, atAudioFramePosition: quand.sampleTime)
        }
    }
}

/// Présente les notifications d'IRIS même app ouverte (sinon iOS les garde silencieuses au premier plan).
final class PresentateurNotifications: NSObject, UNUserNotificationCenterDelegate {
    func userNotificationCenter(_ center: UNUserNotificationCenter, willPresent notification: UNNotification,
                                withCompletionHandler completionHandler: @escaping (UNNotificationPresentationOptions) -> Void) {
        completionHandler([.banner, .sound, .list])
    }
}

@MainActor
@Observable
final class AlertesSonoresTelephone: ServiceAlertes {
    private(set) var actives = false
    private(set) var types: [TypeAlerte] = []
    private(set) var dernieres: [AlerteSonore] = []
    /// Alertes détectées par l'ordinateur (événement alerte.sonore), affichées à part.
    private(set) var dernieresOrdinateur: [AlerteSonore] = []
    /// Types sans aucune classe dans le classifieur de cet iPhone.
    private(set) var indisponibles: Set<String> = []
    private(set) var erreur: String?
    private(set) var attenteMicro = false
    private(set) var sensibilite: Double
    private(set) var voixActive: Bool
    private(set) var notificationsPermises: Bool?

    let limite = "Détection faite sur cet iPhone par le classifieur de sons d'iOS, sans envoi du son. Il peut se tromper : la musique ou la télévision déclenchent parfois une fausse alerte, un son lointain ou étouffé peut être manqué. Compte environ 1 à 3 secondes entre le son et l'alerte. L'écoute tourne app ouverte, ou en arrière-plan tant qu'iOS garde le micro actif ; un appel ou Siri l'interrompt. Pendant les alertes, « Dis-moi Iris », « Parler à IRIS », l'interprète et les dictées sont en pause. Sans lunettes VELA présentes pendant 10 minutes de suite, les alertes s'arrêtent seules et IRIS le dit. En arrière-plan, l'iPhone redemande à ton ordinateur environ chaque minute si le mode confidentiel ou le verrou est actif : l'arrêt peut donc prendre jusqu'à une minute environ, et si l'ordinateur ne répond pas, les alertes continuent. Ne remplace pas un avertisseur de fumée adapté (lumineux ou vibrant)."

    /// La dernière alerte signalée, essais compris : la racine de l'app l'observe pour le plein écran.
    private(set) var derniereSignalee: AlerteSonore?
    /// Depuis quand les lunettes manquent pendant que les alertes tournent (nil : présentes).
    private(set) var lunettesAbsentesDepuis: Date?

    nonisolated static let delaiSansLunettes: TimeInterval = 600
    nonisolated static let messageArretSansLunettes = "Lunettes absentes depuis 10 minutes : alertes sonores arrêtées."

    @ObservationIgnored private let micro: MicroPerception
    @ObservationIgnored private let voix: any ServiceVoix
    @ObservationIgnored private let garde: GardeCapture
    @ObservationIgnored private let boite = BoiteAnalyseur()
    @ObservationIgnored private let observateur = ObservateurSons()
    @ObservationIgnored private let presentateur = PresentateurNotifications()
    @ObservationIgnored private var requete: SNClassifySoundRequest?
    @ObservationIgnored private var typesChoisis: Set<String>
    @ObservationIgnored private var consecutives: [String: Int] = [:]
    @ObservationIgnored private var derniereAlerte: [String: Date] = [:]
    @ObservationIgnored private var abonnement: AbonnementEvenements?
    @ObservationIgnored private var veilleur: Task<Void, Never>?
    @ObservationIgnored private let pont: any ServicePontPC
    @ObservationIgnored private var dernierSondageArrierePlan: Date?
    @ObservationIgnored private var sondageEnCours = false

    /// En arrière-plan, le WebSocket et la surveillance du pont sont fermés (ClientPontPC.suspendre) : ni
    /// settings.updated (mode confidentiel) ni verrou.etat n'arrivent. Le micro, lui, continue d'analyser.
    /// Les alertes redemandent donc elles-mêmes, à cet intervalle, l'état de l'ordinateur.
    nonisolated static let intervalleSondageArrierePlan: TimeInterval = 60

    enum DecisionSondage: Equatable {
        case continuer, confidentiel, verrou
    }

    private static let cleTypes = "iris_alertes_types"
    private static let cleSensibilite = "iris_alertes_sensibilite"
    private static let cleVoix = "iris_alertes_voix"
    private static let silenceMemeType: TimeInterval = 10

    /// Les cinq sons de l'ordinateur (mêmes identifiants) plus deux que le classifieur d'iOS connaît.
    /// Identifiants de classes vérifiés contre la liste publiée de la version 1 ; revérifiés à l'exécution.
    static let catalogue: [DefinitionAlerte] = [
        DefinitionAlerte(id: "alarme", libelle: "Alarme (détecteur de fumée)", annonce: "Son d'alarme détecté.",
                         classes: ["smoke_detector", "fire_alarm"], seuilBase: 0.55, fenetresRequises: 2),
        DefinitionAlerte(id: "sirene", libelle: "Sirène de véhicule d'urgence", annonce: "Sirène détectée.",
                         classes: ["siren", "police_siren", "ambulance_siren", "fire_engine_siren", "civil_defense_siren"],
                         seuilBase: 0.55, fenetresRequises: 2),
        DefinitionAlerte(id: "klaxon", libelle: "Klaxon", annonce: "Klaxon détecté.",
                         classes: ["car_horn", "air_horn", "truck_horn"], seuilBase: 0.6, fenetresRequises: 1),
        DefinitionAlerte(id: "sonnette", libelle: "Sonnette", annonce: "Sonnette détectée.",
                         classes: ["door_bell", "doorbell"], seuilBase: 0.6, fenetresRequises: 1),
        DefinitionAlerte(id: "porte", libelle: "Coups frappés (porte)", annonce: "Coups frappés détectés.",
                         classes: ["knock"], seuilBase: 0.6, fenetresRequises: 1),
        DefinitionAlerte(id: "bebe", libelle: "Pleurs de bébé", annonce: "Pleurs de bébé détectés.",
                         classes: ["baby_crying"], seuilBase: 0.6, fenetresRequises: 2),
        DefinitionAlerte(id: "verre", libelle: "Verre brisé", annonce: "Bruit de verre brisé détecté.",
                         classes: ["glass_breaking"], seuilBase: 0.6, fenetresRequises: 1),
    ]

    init(micro: MicroPerception, voix: any ServiceVoix, garde: GardeCapture, pont: any ServicePontPC) {
        self.micro = micro
        self.voix = voix
        self.garde = garde
        self.pont = pont
        let enregistres = UserDefaults.standard.stringArray(forKey: Self.cleTypes)
        typesChoisis = Set(enregistres ?? ["alarme", "sirene", "klaxon", "sonnette", "porte"])
        let s = UserDefaults.standard.object(forKey: Self.cleSensibilite) as? Double
        sensibilite = s ?? 50
        voixActive = UserDefaults.standard.object(forKey: Self.cleVoix) as? Bool ?? true
        types = Self.catalogue.map { TypeAlerte(id: $0.id, libelle: $0.libelle, actif: typesChoisis.contains($0.id)) }

        observateur.surResultat = { [weak self] valeurs in
            Task { @MainActor in self?.juger(valeurs) }
        }
        observateur.surEchec = { [weak self] message in
            Task { @MainActor in self?.erreur = "Analyse des sons interrompue : \(message)" }
        }
        abonnement = pont.abonner { [weak self] evenement in
            guard let self else { return }
            switch evenement.type {
            case "alerte.sonore":
                if let alerte = evenement.decoder(AlerteSonore.self) {
                    self.dernieresOrdinateur.insert(alerte, at: 0)
                    if self.dernieresOrdinateur.count > 20 { self.dernieresOrdinateur.removeLast() }
                }
            default:
                break
            }
        }
    }

    // MARK: - Réglages

    func choisir(type id: String, actif: Bool) {
        if actif { typesChoisis.insert(id) } else { typesChoisis.remove(id) }
        UserDefaults.standard.set(Array(typesChoisis).sorted(), forKey: Self.cleTypes)
        types = Self.catalogue.map { TypeAlerte(id: $0.id, libelle: $0.libelle, actif: typesChoisis.contains($0.id)) }
        consecutives[id] = 0
    }

    func choisirSensibilite(_ valeur: Double) {
        sensibilite = min(max(valeur, 0), 100)
        UserDefaults.standard.set(sensibilite, forKey: Self.cleSensibilite)
    }

    func choisirVoix(_ active: Bool) {
        voixActive = active
        UserDefaults.standard.set(active, forKey: Self.cleVoix)
    }

    /// Seuil de confiance d'un type : sensibilité 100 = seuil abaissé de 0,2 ; 0 = relevé de 0,2.
    func seuil(pour definition: DefinitionAlerte) -> Double {
        min(0.9, max(0.3, definition.seuilBase + (50 - sensibilite) / 100 * 0.4))
    }

    // MARK: - Activer / désactiver

    func activer(types choisis: [String]) async throws {
        if let refus = garde.refus(fonction: "alertes_sonores") { throw refus }
        guard await AVAudioApplication.requestRecordPermission() else { throw ErreurMicro.refuse }
        if !choisis.isEmpty {
            typesChoisis = Set(choisis)
            UserDefaults.standard.set(Array(typesChoisis).sorted(), forKey: Self.cleTypes)
            types = Self.catalogue.map { TypeAlerte(id: $0.id, libelle: $0.libelle, actif: typesChoisis.contains($0.id)) }
        }
        let nouvelle: SNClassifySoundRequest
        do {
            nouvelle = try SNClassifySoundRequest(classifierIdentifier: .version1)
        } catch {
            throw ErreurMicro.occupe("Le classifieur de sons d'iOS n'est pas disponible sur cet iPhone (\(error.localizedDescription)).")
        }
        nouvelle.overlapFactor = 0.5
        let connues = Set(nouvelle.knownClassifications)
        indisponibles = Set(Self.catalogue.filter { !$0.classes.contains(where: connues.contains) }.map(\.id))
        requete = nouvelle

        do {
            let granted = try await UNUserNotificationCenter.current().requestAuthorization(options: [.alert, .sound])
            notificationsPermises = granted
        } catch {
            notificationsPermises = false
        }
        if UNUserNotificationCenter.current().delegate == nil {
            UNUserNotificationCenter.current().delegate = presentateur
        }

        let boite = self.boite
        try micro.abonner("alertes", surFormat: { [weak self] format in
            self?.nouvelAnalyseur(format)
        }, bloc: { tampon, quand in
            boite.analyser(tampon, quand)
        })
        consecutives.removeAll()
        actives = true
        erreur = nil
        lunettesAbsentesDepuis = nil
        dernierSondageArrierePlan = nil
        demarrerVeilleur()
    }

    func desactiver() {
        guard actives else { return }
        actives = false
        veilleur?.cancel()
        veilleur = nil
        micro.desabonner("alertes")
        boite.remplacer(par: nil)
        consecutives.removeAll()
        attenteMicro = false
        lunettesAbsentesDepuis = nil
    }

    /// Arrêt imposé (mode confidentiel, verrou, lunettes absentes) : la raison reste affichée.
    func desactiver(raison: String) {
        guard actives else { return }
        desactiver()
        erreur = raison
    }

    /// Faut-il arrêter faute de lunettes ? Fonction pure (testée) : absentes depuis au moins le délai.
    nonisolated static func doitArreterSansLunettes(absentesDepuis: Date?, maintenant: Date,
                                                   delai: TimeInterval) -> Bool {
        guard let absentesDepuis else { return false }
        return maintenant.timeIntervalSince(absentesDepuis) >= delai
    }

    /// Faut-il sonder l'ordinateur maintenant ? Fonction pure (testée) : en arrière-plan seulement, pont réglé,
    /// au plus une fois par intervalle.
    nonisolated static func doitSonderArrierePlan(enArrierePlan: Bool, pontConfigure: Bool, dernier: Date?,
                                                  maintenant: Date) -> Bool {
        guard enArrierePlan, pontConfigure else { return false }
        guard let dernier else { return true }
        return maintenant.timeIntervalSince(dernier) >= intervalleSondageArrierePlan
    }

    /// Ce que dit le sondage (GET /api/settings) : mode confidentiel → arrêt ; 401 « verrouillée » (verrou ou
    /// effacement à distance) → arrêt ; toute autre erreur (ordinateur injoignable, session expirée) → on
    /// continue, faute de savoir : c'est écrit dans `limite`. Fonction pure (testée).
    nonisolated static func decisionSondage(privacyMode: Bool?, erreur: Error?) -> DecisionSondage {
        if let erreur {
            if let pont = erreur as? ErreurPont, case .verrouillee = pont { return .verrou }
            return .continuer
        }
        return privacyMode == true ? .confidentiel : .continuer
    }

    private func sonderEnArrierePlan() async {
        guard !sondageEnCours else { return }
        sondageEnCours = true
        defer { sondageEnCours = false }
        dernierSondageArrierePlan = Date()
        var decision = DecisionSondage.continuer
        do {
            let lus: ReglagesIRIS = try await pont.get("/api/settings", delai: 10)
            decision = Self.decisionSondage(privacyMode: lus.privacyMode, erreur: nil)
        } catch {
            decision = Self.decisionSondage(privacyMode: nil, erreur: error)
        }
        guard actives else { return }
        switch decision {
        case .continuer:
            break
        case .confidentiel:
            desactiver(raison: GardeCapture.messageConfidentiel)
        case .verrou:
            desactiver(raison: GardeCapture.messageVerrou)
        }
    }

    private func nouvelAnalyseur(_ format: AVAudioFormat) {
        guard requete != nil else { return }
        let analyseur = SNAudioStreamAnalyzer(format: format)
        do {
            // Une requête neuve par analyseur : l'ancien est vidé sur sa file, sans course entre les deux.
            let neuve = try SNClassifySoundRequest(classifierIdentifier: .version1)
            neuve.overlapFactor = 0.5
            try analyseur.add(neuve, withObserver: observateur)
            boite.remplacer(par: analyseur)
        } catch {
            erreur = "Le classifieur de sons refuse ce format de micro (\(error.localizedDescription))."
            boite.remplacer(par: nil)
        }
    }

    private func demarrerVeilleur() {
        veilleur?.cancel()
        veilleur = Task { [weak self] in
            while !Task.isCancelled {
                try? await Task.sleep(for: .seconds(1))
                guard let self, self.actives else { return }
                self.attenteMicro = self.micro.registre.secondesSansSon > 3
                let maintenant = Date()
                if Self.doitSonderArrierePlan(enArrierePlan: UIApplication.shared.applicationState == .background,
                                              pontConfigure: self.pont.adresse != nil,
                                              dernier: self.dernierSondageArrierePlan, maintenant: maintenant) {
                    // Sans attendre dans la boucle : le délai de 10 s ne doit pas retarder le contrôle des lunettes.
                    Task { await self.sonderEnArrierePlan() }
                }
                if self.garde.lunettesPresentes {
                    self.lunettesAbsentesDepuis = nil
                } else if self.lunettesAbsentesDepuis == nil {
                    self.lunettesAbsentesDepuis = maintenant
                }
                if Self.doitArreterSansLunettes(absentesDepuis: self.lunettesAbsentesDepuis, maintenant: maintenant,
                                                delai: Self.delaiSansLunettes) {
                    self.desactiver(raison: Self.messageArretSansLunettes)
                    Annonce.urgent(Self.messageArretSansLunettes, voix: self.voix)
                    return
                }
            }
        }
    }

    // MARK: - Décision

    private func juger(_ valeurs: [(String, Double)]) {
        guard actives else { return }
        let confiances = Dictionary(valeurs, uniquingKeysWith: { max($0, $1) })
        let maintenant = Date()
        for definition in Self.catalogue where typesChoisis.contains(definition.id) && !indisponibles.contains(definition.id) {
            let confiance = definition.classes.compactMap { confiances[$0] }.max() ?? 0
            if confiance >= seuil(pour: definition) {
                consecutives[definition.id, default: 0] += 1
            } else {
                consecutives[definition.id] = 0
                continue
            }
            guard (consecutives[definition.id] ?? 0) >= definition.fenetresRequises else { continue }
            if let derniere = derniereAlerte[definition.id], maintenant.timeIntervalSince(derniere) < Self.silenceMemeType {
                continue
            }
            derniereAlerte[definition.id] = maintenant
            consecutives[definition.id] = 0
            prevenir(definition, confiance: confiance, test: false)
        }
    }

    /// Essai de la FAÇON de prévenir (vibration, notification, voix) : ne teste pas la détection.
    func essayerAvertissement() {
        guard let definition = Self.catalogue.first else { return }
        prevenir(definition, confiance: nil, test: true)
    }

    private func prevenir(_ definition: DefinitionAlerte, confiance: Double?, test: Bool) {
        let alerte = AlerteSonore(genre: definition.id, libelle: definition.libelle, confiance: confiance,
                                  ts: Date().timeIntervalSince1970, test: test)
        if !test {
            dernieres.insert(alerte, at: 0)
            if dernieres.count > 30 { dernieres.removeLast() }
        }
        let phrase = test ? "Essai d'avertissement : voici comment IRIS te prévient." : definition.annonce
        Haptique.alerte()
        if voixActive {
            Annonce.urgent(phrase, voix: voix)
        }
        let contenu = UNMutableNotificationContent()
        contenu.title = test ? "IRIS · essai" : "IRIS · alerte sonore"
        contenu.body = test ? phrase : "\(definition.annonce) (\(definition.libelle))"
        contenu.sound = .default
        let demande = UNNotificationRequest(identifier: "iris-alerte-\(UUID().uuidString)", content: contenu, trigger: nil)
        UNUserNotificationCenter.current().add(demande) { _ in }
        derniereSignalee = alerte
    }
}
