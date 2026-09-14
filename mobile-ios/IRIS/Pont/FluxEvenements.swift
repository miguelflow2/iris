// FluxEvenements.swift — le WebSocket /ws du service IRIS, avec reconnexion.
//
// Mêmes règles que la page téléphone (api.js), apprises à nos dépens :
// - un tunnel coupe volontiers une liaison muette : ping toutes les 25 s ;
// - plus rien depuis 70 s : la liaison est morte sans le dire, on la ferme ;
// - un refus (verrouillage : code 4401 ; session refusée : poignée de main 403) ne doit pas être
//   rouvert en rafale : les essais s'espacent jusqu'à 30 s, et le client HTTP va demander pourquoi.

import Foundation

@MainActor
final class FluxEvenements {
    private(set) var ouvert = false

    var fournirRequete: () -> URLRequest? = { nil }
    var surEvenement: (EvenementPC) -> Void = { _ in }
    var surEtat: (Bool) -> Void = { _ in }
    var surRefus: (String) -> Void = { _ in }

    private let urlSession: URLSession
    private var boucle: Task<Void, Never>?
    /// Identifie la boucle en cours : une ancienne boucle annulée ne doit pas effacer la nouvelle.
    private var jetonBoucle = UUID()
    private var tache: URLSessionWebSocketTask?
    private var voulu = false
    private var essais = 0
    private var derniereActivite = Date()

    private static let intervallePing: Duration = .seconds(25)
    private static let silenceMax: TimeInterval = 70
    private static let codeRefus = 4401

    init(urlSession: URLSession) {
        self.urlSession = urlSession
    }

    func demarrer() {
        voulu = true
        guard boucle == nil else { return }
        essais = 0
        let jeton = UUID()
        jetonBoucle = jeton
        boucle = Task { [weak self] in
            await self?.executer(jeton: jeton)
        }
    }

    func arreter() {
        voulu = false
        jetonBoucle = UUID()
        boucle?.cancel()
        boucle = nil
        tache?.cancel(with: .goingAway, reason: nil)
        tache = nil
        changer(ouvert: false)
    }

    private func executer(jeton: UUID) async {
        defer { if jetonBoucle == jeton { boucle = nil } }
        while voulu && !Task.isCancelled && jetonBoucle == jeton {
            guard let requete = fournirRequete() else { return }
            let ws = urlSession.webSocketTask(with: requete)
            ws.maximumMessageSize = 8 * 1024 * 1024
            tache = ws
            derniereActivite = Date()
            ws.resume()

            let veilleur = Task { [weak self] in
                await self?.surveiller(ws)
            }
            var recu = false
            do {
                while !Task.isCancelled {
                    let message = try await ws.receive()
                    derniereActivite = Date()
                    if !recu {
                        recu = true
                        essais = 0
                        changer(ouvert: true)
                    }
                    switch message {
                    case .string(let texte):
                        traiter(Data(texte.utf8))
                    case .data(let donnees):
                        traiter(donnees)
                    @unknown default:
                        break
                    }
                }
            } catch {
                // Fermé : réseau coupé, refus, ou arrêt voulu. Le code de fermeture dit lequel.
            }
            veilleur.cancel()

            let code = ws.closeCode.rawValue
            let raison = ws.closeReason.flatMap { String(data: $0, encoding: .utf8) } ?? ""
            let statutPoignee = (ws.response as? HTTPURLResponse)?.statusCode
            if tache === ws { tache = nil }
            guard jetonBoucle == jeton else { return }
            changer(ouvert: false)
            guard voulu, !Task.isCancelled else { return }

            if code == Self.codeRefus || (!recu && (statutPoignee == 401 || statutPoignee == 403)) {
                essais = max(essais, 4)
                surRefus(raison)
            }
            let delai = min(30.0, 1.5 * pow(2.0, Double(min(essais, 5))))
            essais += 1
            try? await Task.sleep(for: .seconds(delai))
        }
    }

    private func surveiller(_ ws: URLSessionWebSocketTask) async {
        while !Task.isCancelled {
            try? await Task.sleep(for: Self.intervallePing)
            if Task.isCancelled { return }
            if Date().timeIntervalSince(derniereActivite) > Self.silenceMax {
                ws.cancel(with: .goingAway, reason: nil)
                return
            }
            // Le service répond « pong » : c'est lui qui prouve que la liaison vit.
            try? await ws.send(.string("{\"type\":\"ping\"}"))
        }
    }

    private func traiter(_ donnees: Data) {
        // Décodeur SANS conversion de clés : les champs gardent leurs noms exacts du service.
        guard let objet = try? JSONDecoder().decode([String: ValeurJSON].self, from: donnees),
              let type = objet["type"]?.texte else { return }
        if type == "pong" { return }
        surEvenement(EvenementPC(type: type, ts: objet["ts"]?.nombre, champs: objet, brut: donnees))
    }

    private func changer(ouvert nouveau: Bool) {
        guard ouvert != nouveau else { return }
        ouvert = nouveau
        surEtat(nouveau)
    }
}
