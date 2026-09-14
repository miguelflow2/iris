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

    let limite = "Détection faite sur cet iPhone par le classifieur de sons d'iOS, sans envoi du son. Il peut se tromper : la musique ou la télévision déclenchent parfois une fausse alerte, un son lointain ou étouffé peut être manqué. Compte environ 1 à 3 secondes entre le son et l'alerte. L'écoute tourne app ouverte, ou en arrière-plan tant qu'iOS garde le micro actif ; un appel ou Siri l'interrompt. Pendant les alertes, « Dis-moi Iris » est en pause. Ne remplace pas un avertisseur de fumée adapté (lumineux ou vibrant)."

    @ObservationIgnored var surAlerte: (@MainActor (AlerteSonore) -> Void)?

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
            case "settings.updated":
                if evenement.champs["settings"]?["privacy_mode"]?.booleen == true, self.actives {
                    self.desactiver()
                    self.erreur = GardeCapture.messageConfidentiel
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
        surAlerte?(alerte)
    }
}
