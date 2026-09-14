// PartageVue.swift — « Partager ma vue » : un proche voit, dans son navigateur, ce que filme l'iPhone.
//
// Le chemin réel (interface J) : l'ordinateur crée la session sur le relais VELA (il détient le jeton
// d'appareil) et rend à l'iPhone un jeton émetteur (POST /api/partage/demarrer, source « telephone ») ;
// l'iPhone envoie ensuite ses images JPEG DIRECTEMENT au relais par WebSocket, sans passer par
// l'ordinateur, qui ne voit pas ces images. Le proche ouvre le lien /voir/<code> ; ce qu'il écrit revient
// ici et est lu à voix haute (« Message de votre proche : … »).
//
// Ce qui est mesuré et affiché, jamais promis : 1 à 5 images par seconde selon le réseau (la cadence
// baisse quand un envoi traîne ou que le relais refuse une image, et remonte quand tout va bien), cadence
// réellement reçue par le relais, nombre de personnes qui regardent, données envoyées.
//
// Règles de confiance : caméra ouverte AVANT de créer le lien (un refus de caméra ne laisse pas de lien
// orphelin) ; le jeton part dans le premier message, jamais dans l'adresse ; rien n'est enregistré, ni
// ici, ni sur le relais. La caméra des lunettes n'envoie pas de vidéo : c'est la caméra de l'iPhone, en
// secours, et l'écran le dit. iOS coupe la caméra en arrière-plan : le proche voit alors la dernière image.

import Foundation
import Observation
import UIKit

/// Réponse complète de POST /api/partage/demarrer (le contrat commun n'en garde qu'une partie).
private struct ReponseDemarragePartage: Decodable {
    let code: String?
    let urlSpectateur: String?
    let jetonEmetteur: String?
    let wsEmetteur: String?
    let expireDansS: Double?
    let note: String?
    let limites: [String]?
}

private struct ReponseProlongation: Decodable {
    let expireDansS: Double?
}

struct MessageProche: Identifiable, Hashable {
    let id = UUID()
    let date: Date
    let texte: String
}

@MainActor
@Observable
final class PartageVueTelephone {
    enum Phase: Equatable {
        case repos
        case demarrage(String)
        case actif
    }

    private(set) var phase: Phase = .repos
    private(set) var code: String?
    private(set) var urlSpectateur: URL?
    private(set) var spectateurs = 0
    private(set) var imagesEnvoyees = 0
    private(set) var octetsEnvoyes = 0
    private(set) var cadenceRelais: Double = 0
    private(set) var cadenceVisee: Double = 4
    private(set) var expireFin: Date?
    private(set) var messages: [MessageProche] = []
    private(set) var limitesServeur: [String] = []
    private(set) var noteServeur: String?
    /// Phrase d'état (« caméra coupée par iOS… », « reconnexion… »).
    private(set) var statut: String?
    private(set) var erreur: Error?
    private(set) var lireMessages = true

    static let noteSecours = "La caméra des lunettes arrive ; en attendant, les images viennent de la caméra arrière de ton iPhone."
    static let limiteLocale = "Ce n'est pas une vidéo en direct : quelques images par seconde, avec du retard. Ce partage ne remplace pas une aide sur place pour traverser une rue, un escalier ou un danger immédiat. Il consomme des données mobiles. iOS coupe la caméra quand l'app quitte l'écran."

    @ObservationIgnored private let pont: any ServicePontPC
    @ObservationIgnored private let voix: any ServiceVoix
    @ObservationIgnored private let camera: CameraTelephone
    @ObservationIgnored private let garde: GardeCapture
    @ObservationIgnored private var socket: URLSessionWebSocketTask?
    @ObservationIgnored private var jeton: String?
    @ObservationIgnored private var urlEmetteur: URL?
    @ObservationIgnored private var taches: [Task<Void, Never>] = []
    @ObservationIgnored private var niveau = 1
    @ObservationIgnored private var derniereBaisse = Date.distantPast
    @ObservationIgnored private var dernierProbleme = Date.distantPast
    @ObservationIgnored private var reconnexions = 0
    @ObservationIgnored private var preavisDit = false
    @ObservationIgnored private var arretVoulu = false

    /// Du plus riche au plus léger : côté (px), qualité JPEG, images par seconde. Départ au deuxième.
    private static let niveaux: [(cote: CGFloat, qualite: CGFloat, ips: Double)] = [
        (960, 0.65, 5), (960, 0.6, 4), (800, 0.55, 3), (640, 0.5, 2), (480, 0.45, 1),
    ]
    private static let tailleMax = 290_000
    private static let fermeturesDefinitives: Set<Int> = [4000, 4003, 4004, 4010]
    private static let reconnexionsMax = 6

    init(pont: any ServicePontPC, voix: any ServiceVoix, camera: CameraTelephone, garde: GardeCapture) {
        self.pont = pont
        self.voix = voix
        self.camera = camera
        self.garde = garde
        camera.surInterruption = { [weak self] coupee in
            Task { @MainActor in
                guard let self, self.phase == .actif else { return }
                self.statut = coupee
                    ? "Caméra coupée par iOS (app quittée, appel ou autre app) : ton proche voit la dernière image."
                    : nil
            }
        }
    }

    func choisirLectureMessages(_ lire: Bool) {
        lireMessages = lire
    }

    // MARK: - Démarrer

    func demarrer() async {
        guard phase == .repos else { return }
        erreur = nil
        statut = nil
        if let refus = garde.refus(fonction: "vision_partagee") {
            erreur = refus
            return
        }
        guard garde.ordinateurJoignable else {
            erreur = ErreurPont.injoignable("Le lien de partage est créé par ton ordinateur : il doit répondre. Réessaie quand il est joignable.")
            return
        }
        arretVoulu = false
        phase = .demarrage("Ouverture de la caméra…")
        do {
            try await camera.demarrer(pour: "partage")
        } catch {
            phase = .repos
            erreur = error
            return
        }

        phase = .demarrage("Création du lien par ton ordinateur…")
        let reponse: ReponseDemarragePartage
        do {
            reponse = try await pont.post("/api/partage/demarrer", corps: DemandePartage(source: "telephone", intervalleS: nil), delai: 45)
        } catch {
            camera.arreter(pour: "partage")
            phase = .repos
            erreur = error
            return
        }
        guard let jetonRecu = reponse.jetonEmetteur, let adresse = reponse.wsEmetteur.flatMap({ URL(string: $0) }),
              let codeRecu = reponse.code else {
            camera.arreter(pour: "partage")
            phase = .repos
            erreur = ErreurPont.decodage("ton ordinateur n'a pas rendu d'accès émetteur pour ce téléphone ; mets IRIS à jour sur l'ordinateur.")
            await arreterSurOrdinateur()
            return
        }
        jeton = jetonRecu
        urlEmetteur = adresse
        code = codeRecu
        urlSpectateur = reponse.urlSpectateur.flatMap({ URL(string: $0) })
        expireFin = Date().addingTimeInterval(reponse.expireDansS ?? 1800)
        noteServeur = reponse.note
        limitesServeur = reponse.limites ?? []

        phase = .demarrage("Connexion au relais VELA…")
        do {
            try await connecter()
        } catch {
            await terminer(message: nil, fermerSurOrdinateur: true)
            erreur = error
            return
        }
        phase = .actif
        reconnexions = 0
        niveau = 1
        imagesEnvoyees = 0
        octetsEnvoyes = 0
        preavisDit = false
        messages.removeAll()
        EveilEcran.activer("partage")
        taches.append(Task { [weak self] in await self?.emettre() })
        taches.append(Task { [weak self] in await self?.horloge() })
        let annonce = "Partage démarré. Code : \(Self.codeEpele(codeRecu)). Envoie le lien à ton proche."
        Annonce.resultat(annonce, voix: voix)
    }

    // MARK: - Relais

    private func connecter() async throws {
        guard let urlEmetteur, let jeton else { throw ErreurPont.decodage("accès émetteur manquant") }
        let ws = URLSession.shared.webSocketTask(with: urlEmetteur)
        ws.maximumMessageSize = 1_000_000
        ws.resume()
        let bonjour = "{\"type\":\"hello\",\"jeton\":\"\(Self.echapper(jeton))\",\"role\":\"emetteur\",\"source\":\"telephone\"}"
        try await ws.send(.string(bonjour))

        // Attendre « pret » au plus 15 secondes.
        let delai = Task {
            try? await Task.sleep(for: .seconds(15))
            if !Task.isCancelled { ws.cancel(with: .goingAway, reason: nil) }
        }
        defer { delai.cancel() }
        while true {
            let message: URLSessionWebSocketTask.Message
            do {
                message = try await ws.receive()
            } catch {
                let codeFermeture = ws.closeCode.rawValue
                if Self.fermeturesDefinitives.contains(codeFermeture) {
                    throw ErreurPont.refus(statut: 0, message: "Le relais VELA a refusé ce partage (expiré ou remplacé). Démarre un nouveau partage.", detail: nil)
                }
                throw ErreurPont.injoignable("Le relais VELA ne répond pas. Vérifie les données mobiles de l'iPhone.")
            }
            guard case .string(let texte) = message, let objet = Self.lireJSON(texte) else { continue }
            let type = objet["type"] as? String
            if type == "pret" {
                socket = ws
                traiter(objet)
                taches.append(Task { [weak self] in await self?.lire(ws) })
                taches.append(Task { [weak self] in await self?.pinger(ws) })
                return
            }
            if type == "refus" || type == "fin" {
                ws.cancel(with: .normalClosure, reason: nil)
                throw ErreurPont.refus(statut: 0, message: (objet["message"] as? String) ?? "Partage introuvable ou expiré.", detail: nil)
            }
        }
    }

    private func lire(_ ws: URLSessionWebSocketTask) async {
        while !Task.isCancelled {
            let message: URLSessionWebSocketTask.Message
            do {
                message = try await ws.receive()
            } catch {
                await connexionPerdue(ws)
                return
            }
            if case .string(let texte) = message, let objet = Self.lireJSON(texte) {
                traiter(objet)
            }
        }
    }

    private func pinger(_ ws: URLSessionWebSocketTask) async {
        while !Task.isCancelled {
            try? await Task.sleep(for: .seconds(20))
            if Task.isCancelled || socket !== ws { return }
            try? await ws.send(.string("{\"type\":\"ping\"}"))
        }
    }

    private func traiter(_ objet: [String: Any]) {
        if let reste = Self.nombre(objet["expire_dans_s"]) {
            let nouvelle = Date().addingTimeInterval(max(0, reste))
            if let actuelle = expireFin, nouvelle.timeIntervalSince(actuelle) > 60 { preavisDit = false }
            expireFin = nouvelle
        }
        switch objet["type"] as? String {
        case "pret":
            spectateurs = Int(Self.nombre(objet["spectateurs"]) ?? 0)
        case "stats":
            spectateurs = Int(Self.nombre(objet["spectateurs"]) ?? Double(spectateurs))
            cadenceRelais = Self.nombre(objet["fps_reel"]) ?? cadenceRelais
        case "spectateurs":
            let nombre = Int(Self.nombre(objet["nombre"]) ?? 0)
            if nombre > spectateurs {
                // Savoir qu'on est regardé fait partie de la confiance : c'est dit à chaque arrivée.
                Annonce.resultat("Une personne regarde maintenant ton partage.", voix: voix)
            }
            spectateurs = nombre
        case "message":
            let texte = ((objet["texte"] as? String) ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
            guard !texte.isEmpty else { return }
            messages.append(MessageProche(date: Date(), texte: String(texte.prefix(500))))
            if messages.count > 20 { messages.removeFirst(messages.count - 20) }
            let phrase = "Message de votre proche : \(texte)"
            if lireMessages {
                Annonce.urgent(phrase, voix: voix)
            } else {
                Annonce.voiceOver(phrase)
            }
        case "refus":
            let raison = objet["raison"] as? String
            if raison == "taille" || raison == "debit" {
                baisser()
            }
        case "fin":
            let message = (objet["message"] as? String) ?? "Le partage est terminé."
            Task { await self.terminer(message: message, fermerSurOrdinateur: false) }
        default:
            break
        }
    }

    private func connexionPerdue(_ ws: URLSessionWebSocketTask) async {
        guard socket === ws else { return }
        socket = nil
        guard phase == .actif, !arretVoulu else { return }
        let codeFermeture = ws.closeCode.rawValue
        if Self.fermeturesDefinitives.contains(codeFermeture) {
            let message = codeFermeture == 4000
                ? "Un autre appareil émet maintenant pour ce partage : l'iPhone a cessé d'envoyer ses images."
                : "Le relais VELA a fermé ce partage (expiré ou arrêté)."
            await terminer(message: message, fermerSurOrdinateur: false)
            return
        }
        while phase == .actif && !arretVoulu {
            if let expireFin, Date() >= expireFin {
                await terminer(message: "Le partage a expiré : 30 minutes sont passées sans prolongation.", fermerSurOrdinateur: true)
                return
            }
            guard reconnexions < Self.reconnexionsMax else {
                await terminer(message: "Connexion au relais VELA perdue trop longtemps : le partage est arrêté.", fermerSurOrdinateur: true)
                return
            }
            reconnexions += 1
            statut = "Connexion au relais perdue : nouvel essai (\(reconnexions)/\(Self.reconnexionsMax))…"
            let attente = min(15.0, pow(2.0, Double(reconnexions - 1)))
            try? await Task.sleep(for: .seconds(attente))
            guard phase == .actif, !arretVoulu else { return }
            do {
                try await connecter()
                reconnexions = 0
                statut = nil
                return
            } catch {
                continue
            }
        }
    }

    // MARK: - Émission des images

    private func emettre() async {
        var dernierEnvoi = Date.distantPast
        var stableDepuis = Date()
        while !Task.isCancelled && phase == .actif {
            let reglage = Self.niveaux[niveau]
            cadenceVisee = reglage.ips
            let intervalle = 1.0 / reglage.ips
            let attente = intervalle - Date().timeIntervalSince(dernierEnvoi)
            if attente > 0 {
                try? await Task.sleep(for: .milliseconds(Int(attente * 1000)))
            }
            guard phase == .actif, let ws = socket else {
                try? await Task.sleep(for: .milliseconds(300))
                continue
            }
            let camera = self.camera
            let jpeg = await Task.detached(priority: .userInitiated) {
                camera.imageJPEG(coteMax: reglage.cote, qualite: reglage.qualite)
            }.value
            dernierEnvoi = Date()
            guard let jpeg, (camera.ageDerniereImage ?? 99) < 2 else { continue }
            guard jpeg.count <= Self.tailleMax else {
                baisser()
                continue
            }
            let debutEnvoi = Date()
            do {
                try await ws.send(.data(jpeg))
            } catch {
                continue   // la lecture verra la coupure et se chargera de la reconnexion
            }
            imagesEnvoyees += 1
            octetsEnvoyes += jpeg.count
            // Un envoi qui traîne : le réseau ne suit plus cette cadence.
            if Date().timeIntervalSince(debutEnvoi) > intervalle * 1.5 {
                baisser()
                stableDepuis = Date()
            } else if Date().timeIntervalSince(stableDepuis) > 8 && Date().timeIntervalSince(dernierProbleme) > 8 && niveau > 0 {
                niveau -= 1
                stableDepuis = Date()
            }
        }
    }

    private func baisser() {
        dernierProbleme = Date()
        guard Date().timeIntervalSince(derniereBaisse) > 2, niveau < Self.niveaux.count - 1 else { return }
        niveau += 1
        derniereBaisse = Date()
    }

    private func horloge() async {
        while !Task.isCancelled && phase == .actif {
            try? await Task.sleep(for: .seconds(1))
            guard phase == .actif, let expireFin else { continue }
            let reste = expireFin.timeIntervalSinceNow
            if reste <= 0 {
                await terminer(message: "Le partage a expiré : 30 minutes sont passées sans prolongation.", fermerSurOrdinateur: true)
                return
            }
            if reste <= 120 && !preavisDit {
                preavisDit = true
                Annonce.urgent("Le partage se termine dans deux minutes. Touche « Prolonger » pour le garder.", voix: voix)
            }
        }
    }

    // MARK: - Prolonger, arrêter

    func prolonger() async {
        guard phase == .actif else { return }
        if let refus = garde.refus(fonction: "vision_partagee") {
            erreur = refus
            return
        }
        do {
            let r: ReponseProlongation = try await pont.post("/api/partage/prolonger", corps: CorpsVide(), delai: 20)
            if let reste = r.expireDansS { expireFin = Date().addingTimeInterval(reste) }
            preavisDit = false
            statut = "Partage prolongé de 30 minutes."
        } catch ErreurPont.injoignable {
            // Ordinateur injoignable : le relais accepte aussi la prolongation demandée par l'émetteur.
            if let socket {
                try? await socket.send(.string("{\"type\":\"renouveler\"}"))
                statut = "Prolongation demandée directement au relais."
            }
        } catch {
            erreur = error
        }
    }

    func arreter() async {
        guard phase != .repos else { return }
        arretVoulu = true
        await terminer(message: "Partage arrêté.", fermerSurOrdinateur: true)
    }

    private func terminer(message: String?, fermerSurOrdinateur: Bool) async {
        let etaitActif = phase != .repos
        phase = .repos
        let aAnnuler = taches
        taches.removeAll()
        let ancienSocket = socket
        socket = nil
        jeton = nil
        camera.arreter(pour: "partage")
        EveilEcran.desactiver("partage")
        // Le nettoyage réseau tourne dans une tâche neuve : terminer() peut être appelée depuis une des
        // tâches du partage, déjà annulée, où chaque requête échouerait aussitôt sans prévenir personne.
        let pont = self.pont
        await Task {
            if let ancienSocket {
                try? await ancienSocket.send(.string("{\"type\":\"fin\"}"))
                ancienSocket.cancel(with: .normalClosure, reason: nil)
            }
            if fermerSurOrdinateur {
                do {
                    let _: ReponseIgnoree = try await pont.post("/api/partage/arreter", corps: CorpsVide(), delai: 15)
                } catch {
                    // Ordinateur injoignable : le message « fin » envoyé au relais a déjà fermé la session,
                    // et elle expire seule au bout de 30 minutes sinon.
                }
            }
        }.value
        for tache in aAnnuler { tache.cancel() }
        code = nil
        urlSpectateur = nil
        expireFin = nil
        spectateurs = 0
        cadenceRelais = 0
        statut = message
        if etaitActif, let message {
            Annonce.resultat(message, voix: voix)
        }
    }

    /// Ferme la session du côté de l'ordinateur (qui ferme le lien sur le relais). Un échec n'empêche rien :
    /// la session expire seule sur le relais au bout de 30 minutes.
    private func arreterSurOrdinateur() async {
        do {
            let _: ReponseIgnoree = try await pont.post("/api/partage/arreter", corps: CorpsVide(), delai: 15)
        } catch {
            // Ordinateur injoignable : le message « fin » envoyé au relais a déjà fermé la session.
        }
    }

    // MARK: - Outils

    /// « K 7 M 2 » : un code dicté caractère par caractère, pour le lire à un proche au téléphone.
    static func codeEpele(_ code: String) -> String {
        code.map { String($0) }.joined(separator: " ")
    }

    private static func echapper(_ texte: String) -> String {
        texte.replacingOccurrences(of: "\\", with: "\\\\").replacingOccurrences(of: "\"", with: "\\\"")
    }

    private static func lireJSON(_ texte: String) -> [String: Any]? {
        guard let donnees = texte.data(using: .utf8) else { return nil }
        return (try? JSONSerialization.jsonObject(with: donnees)) as? [String: Any]
    }

    private static func nombre(_ valeur: Any?) -> Double? {
        if let n = valeur as? NSNumber { return n.doubleValue }
        if let s = valeur as? String { return Double(s) }
        return nil
    }
}
