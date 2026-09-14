// ConversationIRIS.swift — parler à IRIS : l'aller-retour avec le chat de l'ordinateur.
//
// Portage de la conversation de la page téléphone (mobile_static/js/coeur.js) : on s'abonne aux
// événements AVANT d'envoyer, on attend chat.done (ou chat.error) et, parce que la liaison peut être
// coupée, on sonde aussi GET /api/conversations/{id}. La latence est MESURÉE sur l'iPhone et
// affichée ; elle n'est jamais promise.
//
// Les confirmations demandées par IRIS (chat.confirm : « j'envoie ce courriel ? ») s'affichent ici
// et se répondent par POST /api/chat/confirm. Sans elles, une action à confirmer tournerait 180 s
// puis serait refusée sans rien dire.

import Foundation
import Observation

@MainActor
@Observable
final class ConversationIRIS {
    enum Role: Hashable { case moi, iris, info }

    struct Bulle: Identifiable, Hashable {
        let id = UUID()
        var role: Role
        var texte: String
        var meta: String?
        var enAttente = false
    }

    struct DemandeAccord: Identifiable, Hashable {
        let id: String
        let titre: String
        let detail: String
    }

    private(set) var bulles: [Bulle] = []
    private(set) var occupe = false
    var accordDemande: DemandeAccord?

    @ObservationIgnored private let pont: ClientPontPC
    @ObservationIgnored private var conversationId: String?
    @ObservationIgnored private var abonnement: AbonnementEvenements?
    @ObservationIgnored var surAccordDemande: (@MainActor (DemandeAccord) -> Void)?

    private static let cleConversation = "iris_conversation_iphone"
    private static let attenteMax: TimeInterval = 180

    init(pont: ClientPontPC) {
        self.pont = pont
        conversationId = UserDefaults.standard.string(forKey: Self.cleConversation)
        abonnement = pont.abonner { [weak self] evenement in
            self?.evenementGlobal(evenement)
        }
    }

    private func evenementGlobal(_ evenement: EvenementPC) {
        guard let conv = conversationId, evenement.champs["conversation_id"]?.texte == conv else { return }
        switch evenement.type {
        case "chat.confirm":
            guard let id = evenement.champs["confirm_id"]?.texte else { return }
            let titre = evenement.champs["title"]?.texte ?? "IRIS demande ton accord."
            let detailBrut = evenement.champs["detail"]
            let detail: String
            if let texte = detailBrut?.texte {
                detail = texte
            } else if let valeur = detailBrut, valeur != .nul, let data = try? JSONEncoder().encode(valeur) {
                detail = String(data: data, encoding: .utf8) ?? ""
            } else {
                detail = ""
            }
            let demande = DemandeAccord(id: id, titre: titre, detail: detail)
            accordDemande = demande
            surAccordDemande?(demande)
        case "chat.confirm_closed":
            if accordDemande?.id == evenement.champs["confirm_id"]?.texte { accordDemande = nil }
        default:
            break
        }
    }

    func repondreAccord(_ demande: DemandeAccord, accepte: Bool) async {
        accordDemande = nil
        do {
            let _: ReponseIgnoree = try await pont.post("/api/chat/confirm",
                                                        corps: ReponseConfirmation(confirmId: demande.id, approved: accepte))
            if !accepte { ajouterInfo("Action refusée : IRIS ne la fera pas.") }
        } catch {
            ajouterInfo(error.localizedDescription)
        }
    }

    func effacerFil() {
        bulles.removeAll()
    }

    private func ajouterInfo(_ texte: String) {
        bulles.append(Bulle(role: .info, texte: texte))
    }

    /// Envoie une demande et attend la réponse. Rend le texte à lire (réponse ou refus), ou nil.
    @discardableResult
    func envoyer(_ texte: String) async -> String? {
        let propre = texte.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !propre.isEmpty, !occupe else { return nil }
        occupe = true
        defer { occupe = false }

        bulles.append(Bulle(role: .moi, texte: propre))
        let bulleReponse = Bulle(role: .iris, texte: "IRIS réfléchit…", enAttente: true)
        bulles.append(bulleReponse)
        if bulles.count > 80 { bulles.removeFirst(bulles.count - 80) }
        let debut = Date()

        do {
            let (convId, connus) = try await assurerConversation(titre: propre)
            let attente = AttenteReponse(convId: convId, connus: connus)
            // À l'écoute AVANT l'envoi : une réponse très rapide ne doit pas passer entre les mailles.
            let abonnementReponse = pont.abonner { [weak self] evenement in
                guard let self else { return }
                attente.recevoir(evenement, debut: debut) { flux in
                    self.majBulle(bulleReponse.id, texte: flux, enAttente: false)
                }
            }
            defer { abonnementReponse.annuler() }

            let _: ReponseEnvoiMessage = try await pont.post(
                "/api/conversations/\(convId)/messages",
                corps: EnvoiMessage(text: propre, agent: "auto", images: []), delai: 20)

            let sondage = Task { [weak self] in
                while !attente.termine {
                    let evenementsOuverts = self?.pont.evenementsOuverts ?? false
                    try? await Task.sleep(for: .seconds(evenementsOuverts ? 6 : 1.5))
                    if Task.isCancelled || attente.termine { return }
                    if Date().timeIntervalSince(debut) > Self.attenteMax {
                        attente.conclure(.expire)
                        return
                    }
                    guard let self else { return }
                    if let conv: Conversation = try? await self.pont.get("/api/conversations/\(convId)", delai: 20),
                       let nouveau = conv.messages?.last(where: { $0.role == "assistant" && !attente.connus.contains($0.id) }) {
                        let contenu = (nouveau.text ?? "").isEmpty ? (nouveau.meta?.error ?? "") : (nouveau.text ?? "")
                        if !contenu.isEmpty { attente.conclure(.texte(contenu)) }
                    }
                }
            }
            let issue = await attente.attendre()
            sondage.cancel()

            switch issue {
            case .texte(let reponse):
                let total = Date().timeIntervalSince(debut) * 1000
                var meta = "Réponse en \(FormatIRIS.secondes(ms: total))"
                if let premier = attente.premierMotMs {
                    meta += " (premiers mots après \(FormatIRIS.secondes(ms: premier)))"
                }
                meta += ", mesuré sur cet iPhone."
                majBulle(bulleReponse.id, texte: reponse.isEmpty ? "(réponse vide)" : reponse, enAttente: false, meta: meta)
                return reponse
            case .erreur(let message):
                majBulle(bulleReponse.id, texte: message, enAttente: false, role: .info)
                return message
            case .expire:
                let message = "IRIS n'a pas répondu en 3 minutes. L'ordinateur a peut-être perdu sa connexion : réessaie."
                majBulle(bulleReponse.id, texte: message, enAttente: false, role: .info)
                return message
            }
        } catch {
            let message: String
            if let erreurPont = error as? ErreurPont, case .injoignable = erreurPont {
                message = "Message non envoyé : l'ordinateur ne répond pas."
            } else {
                message = error.localizedDescription
            }
            majBulle(bulleReponse.id, texte: message, enAttente: false, role: .info)
            return message
        }
    }

    private func majBulle(_ id: UUID, texte: String, enAttente: Bool, meta: String? = nil, role: Role? = nil) {
        guard let index = bulles.firstIndex(where: { $0.id == id }) else { return }
        bulles[index].texte = texte
        bulles[index].enAttente = enAttente
        if let meta { bulles[index].meta = meta }
        if let role { bulles[index].role = role }
    }

    private func assurerConversation(titre: String) async throws -> (String, Set<String>) {
        if let id = conversationId {
            do {
                let conv: Conversation = try await pont.get("/api/conversations/\(id)", delai: 20)
                let messages = conv.messages ?? []
                // Le service ne renvoie que les 500 premiers messages : au-delà, une réponse neuve
                // deviendrait invisible au sondage. On en ouvre une neuve bien avant.
                if messages.count < 400 {
                    return (id, Set(messages.map(\.id)))
                }
            } catch ErreurPont.refus(let statut, _, _) where statut == 404 {
                // Conversation effacée sur l'ordinateur : on en ouvre une autre.
            }
        }
        let nouvelle: Conversation = try await pont.post(
            "/api/conversations",
            corps: NouvelleConversation(title: String(titre.prefix(40)), agent: "auto"), delai: 20)
        conversationId = nouvelle.id
        UserDefaults.standard.set(nouvelle.id, forKey: Self.cleConversation)
        return (nouvelle.id, [])
    }
}

// MARK: - Attente d'une réponse

@MainActor
private final class AttenteReponse {
    enum Issue { case texte(String), erreur(String), expire }

    let convId: String
    let connus: Set<String>
    private(set) var premierMotMs: Double?
    private var flux = ""
    private var issue: Issue?
    private var continuation: CheckedContinuation<Issue, Never>?

    init(convId: String, connus: Set<String>) {
        self.convId = convId
        self.connus = connus
    }

    var termine: Bool { issue != nil }

    func recevoir(_ evenement: EvenementPC, debut: Date, surFlux: (String) -> Void) {
        guard !termine, evenement.champs["conversation_id"]?.texte == convId else { return }
        switch evenement.type {
        case "chat.delta":
            if premierMotMs == nil { premierMotMs = Date().timeIntervalSince(debut) * 1000 }
            flux += evenement.champs["text"]?.texte ?? ""
            surFlux(flux)
        case "chat.done":
            let message = evenement.champs["message"]
            guard message?["role"]?.texte == "assistant",
                  let id = message?["id"]?.texte, !connus.contains(id) else { return }
            let texte = message?["text"]?.texte ?? ""
            let erreur = message?["meta"]?["error"]?.texte ?? ""
            conclure(.texte(texte.isEmpty ? erreur : texte))
        case "chat.error":
            conclure(.erreur(evenement.champs["message"]?.texte ?? "IRIS n'a pas pu répondre."))
        default:
            break
        }
    }

    func conclure(_ nouvelle: Issue) {
        guard issue == nil else { return }
        issue = nouvelle
        continuation?.resume(returning: nouvelle)
        continuation = nil
    }

    func attendre() async -> Issue {
        if let issue { return issue }
        return await withCheckedContinuation { continuation in
            self.continuation = continuation
        }
    }
}
