// ConversationIRIS.swift — parler à IRIS : l'aller-retour avec le chat de l'ordinateur.
//
// Portage de la conversation de la page téléphone (mobile_static/js/coeur.js) : on s'abonne aux
// événements AVANT d'envoyer, on attend chat.done (ou chat.error, ou chat.consent_required) et, SEULEMENT
// quand la liaison d'événements a été coupée pendant l'attente, on sonde GET /api/conversations/{id}
// (toutes les 4 s tant qu'elle est coupée, puis une dernière fois à son retour). Cette route rend toute la
// conversation, déchiffrée message par message sur l'ordinateur : la sonder en continu coûtait données
// mobiles, batterie et calcul pour rien. La latence est MESURÉE sur l'iPhone et affichée ; elle n'est
// jamais promise.
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
    /// Au-delà, une conversation neuve est ouverte : chaque GET de la conversation rend tous ses messages.
    static let messagesMax = 50
    private static let intervalleSondage: Duration = .seconds(4)

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

    /// Une phrase traitée par l'app elle-même (mode invité) : affichée dans le fil comme les autres, avec
    /// d'où vient la réponse.
    func ajouterEchangeLocal(demande: String, reponse: String) {
        let propre = demande.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !propre.isEmpty else { return }
        bulles.append(Bulle(role: .moi, texte: propre))
        bulles.append(Bulle(role: .info, texte: reponse,
                            meta: "Traité par l'app iPhone avec la route de ton ordinateur, sans le moteur VELA."))
        if bulles.count > 80 { bulles.removeFirst(bulles.count - 80) }
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

            // Si la liaison d'événements était ouverte à l'envoi et le reste, chat.done arrive par elle : aucun
            // sondage. Coupée à un moment de l'attente, un événement a pu se perdre : on sonde tant qu'elle
            // l'est, et une fois de plus à son retour (l'événement a pu tomber pendant la coupure).
            // Une coupure brève entre deux sondages (liaison refermée puis rouverte) se voit au compteur
            // d'ouvertures du pont.
            let ouverteALEnvoi = pont.evenementsOuverts
            let ouverturesALEnvoi = pont.ouverturesFlux
            let sondage = Task { [weak self] in
                var rattrapageDu = !ouverteALEnvoi
                var ouverturesVues = ouverturesALEnvoi
                while !attente.termine {
                    try? await Task.sleep(for: Self.intervalleSondage)
                    if Task.isCancelled || attente.termine { return }
                    if Date().timeIntervalSince(debut) > Self.attenteMax {
                        attente.conclure(.expire)
                        return
                    }
                    guard let self else { return }
                    let ouverte = self.pont.evenementsOuverts
                    if self.pont.ouverturesFlux != ouverturesVues {
                        ouverturesVues = self.pont.ouverturesFlux
                        rattrapageDu = true
                    }
                    if ouverte && !rattrapageDu { continue }
                    rattrapageDu = !ouverte
                    guard let conv: Conversation = try? await self.pont.get("/api/conversations/\(convId)", delai: 20) else {
                        continue
                    }
                    if let nouveau = conv.messages?.last(where: { $0.role == "assistant" && !attente.connus.contains($0.id) }) {
                        let contenu = (nouveau.text ?? "").isEmpty ? (nouveau.meta?.error ?? "") : (nouveau.text ?? "")
                        if !contenu.isEmpty { attente.conclure(.texte(contenu)) }
                    } else if let phrase = AttenteReponse.phraseIssueNonGardee(conv.issueNonGardee, connus: attente.connus) {
                        // Fin SANS message (consentement requis…) : l'événement s'est perdu pendant la coupure, mais
                        // l'ordinateur la garde en mémoire pour ce sondage. Sans elle : 3 minutes, puis un faux motif.
                        attente.conclure(.erreur(phrase))
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

    // MARK: - Commande parlée dans les lunettes

    enum IssueCommandeVocale: Equatable {
        /// Phrase à lire (réponse, refus exact), vide s'il n'y a rien à dire.
        case phrase(String)
        /// L'ordinateur ne connaît pas POST /api/voix/commande (version antérieure au 2026-09-14) : l'appelant
        /// se replie sur l'ancien chemin (commandes locales, puis chat).
        case routeAbsente
    }

    /// Une commande DITE dans les lunettes : POST /api/voix/commande. Sur l'ordinateur, elle passe par les mêmes
    /// interceptions qu'une commande dite à son micro (« étape suivante », « série terminée », « mode invité »…),
    /// avec la règle de la voix, au lieu d'arriver au modèle comme un message écrit, qui pouvait répondre
    /// « d'accord » sans rien faire. La réponse est SYNCHRONE : un consentement manquant est dit même quand la
    /// liaison d'événements est fermée.
    func envoyerCommandeVocale(_ texte: String) async -> IssueCommandeVocale {
        let propre = texte.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !propre.isEmpty else { return .phrase("") }
        guard !occupe else { return .phrase("IRIS répond déjà à une demande : attends la fin, puis redis-le.") }
        occupe = true
        defer { occupe = false }

        let bulleDemande = Bulle(role: .moi, texte: propre)
        let bulleReponse = Bulle(role: .iris, texte: "IRIS réfléchit…", enAttente: true)
        bulles.append(bulleDemande)
        bulles.append(bulleReponse)
        if bulles.count > 80 { bulles.removeFirst(bulles.count - 80) }
        let debut = Date()

        // La conversation de l'iPhone est nommée pour que les confirmations (chat.confirm) de cette commande
        // s'affichent ici. Illisible : l'ordinateur prend sa propre conversation vocale.
        let convId = try? await assurerConversation(titre: propre).0
        do {
            let reponse: ReponseCommandeVocale
            do {
                reponse = try await pont.post("/api/voix/commande",
                                              corps: DemandeCommandeVocale(texte: propre, source: "iphone", conversationId: convId),
                                              delai: 120)
            } catch let erreur where convId != nil && Self.conversationIntrouvable(erreur) {
                // Conversation effacée sur l'ordinateur entre-temps : sa conversation vocale fait l'affaire.
                conversationId = nil
                UserDefaults.standard.removeObject(forKey: Self.cleConversation)
                reponse = try await pont.post("/api/voix/commande",
                                              corps: DemandeCommandeVocale(texte: propre, source: "iphone", conversationId: nil),
                                              delai: 120)
            }
            let phrase = Self.phraseCommandeVocale(reponse)
            let mesure = "Réponse en \(FormatIRIS.secondes(ms: Date().timeIntervalSince(debut) * 1000)), mesuré sur cet iPhone."
            if Self.estUnRefus(reponse) {
                majBulle(bulleReponse.id, texte: phrase, enAttente: false, meta: mesure, role: .info)
            } else {
                majBulle(bulleReponse.id, texte: phrase.isEmpty ? "(fait, rien à dire)" : phrase, enAttente: false, meta: mesure)
            }
            return .phrase(phrase)
        } catch {
            if Self.routeVocaleAbsente(error) {
                bulles.removeAll { $0.id == bulleDemande.id || $0.id == bulleReponse.id }
                return .routeAbsente
            }
            let message: String
            if let erreurPont = error as? ErreurPont, case .injoignable = erreurPont {
                message = "Commande non envoyée : l'ordinateur ne répond pas."
            } else {
                message = error.localizedDescription
            }
            majBulle(bulleReponse.id, texte: message, enAttente: false, role: .info)
            return .phrase(message)
        }
    }

    /// La phrase à lire pour une réponse de /api/voix/commande (fonction pure, testée dans IRISTests).
    nonisolated static func phraseCommandeVocale(_ reponse: ReponseCommandeVocale) -> String {
        let texte = (reponse.texte ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
        if let type = reponse.consentementRequis, !type.isEmpty, texte.isEmpty {
            return AttenteReponse.phraseConsentement(label: type)
        }
        return texte
    }

    /// Refus (consentement, lunettes, micro de la maison, voix non vérifiée) : affiché comme une information.
    nonisolated static func estUnRefus(_ reponse: ReponseCommandeVocale) -> Bool {
        reponse.consentementRequis != nil || reponse.lunettesRequises == true || reponse.refus != nil
    }

    /// 404 de FastAPI pour une route inconnue (« Not Found ») : ordinateur trop ancien. Pas la 404
    /// « conversation introuvable » de la route elle-même.
    nonisolated static func routeVocaleAbsente(_ erreur: Error) -> Bool {
        guard let pont = erreur as? ErreurPont, case .refus(let statut, let message, _) = pont else { return false }
        return statut == 404 && message.trimmingCharacters(in: .whitespaces).caseInsensitiveCompare("Not Found") == .orderedSame
    }

    nonisolated static func conversationIntrouvable(_ erreur: Error) -> Bool {
        guard let pont = erreur as? ErreurPont, case .refus(let statut, let message, _) = pont else { return false }
        return statut == 404 && message.localizedCaseInsensitiveContains("conversation introuvable")
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
                // Chaque lecture de la conversation rend TOUS ses messages (500 au plus, déchiffrés un à
                // un sur l'ordinateur) : au-delà de 50, on en ouvre une neuve pour garder ces lectures
                // légères sur données mobiles.
                if messages.count < Self.messagesMax {
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

/// Non privée pour les tests (IRISTests) : c'est elle qui décide quand une demande est finie.
@MainActor
final class AttenteReponse {
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
        case "chat.consent_required":
            // Le service ne publie alors ni chat.done ni chat.error : sans ce cas, l'attente durait 3 minutes
            // et finissait sur une fausse raison (« connexion perdue »).
            conclure(.erreur(Self.phraseConsentement(label: evenement.champs["label"]?.texte ?? "cette donnée")))
        default:
            break
        }
    }

    nonisolated static func phraseConsentement(label: String) -> String {
        "IRIS a besoin de ton accord pour « \(label) » : donne-le dans l'application IRIS de l'ordinateur, onglet Confidentialité."
    }

    /// La phrase qui conclut une demande finie sans message, lue par sondage (`issue_non_gardee`), ou nil si
    /// l'issue manque ou concerne une demande plus ancienne (son message était déjà connu avant l'envoi).
    nonisolated static func phraseIssueNonGardee(_ issue: IssueNonGardee?, connus: Set<String>) -> String? {
        guard let issue, let apres = issue.apres, !apres.isEmpty, !connus.contains(apres) else { return nil }
        if let consentement = issue.consentement {
            return phraseConsentement(label: consentement.label ?? consentement.dataType ?? "cette donnée")
        }
        let message = (issue.message ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
        return message.isEmpty ? "IRIS n'a pas pu répondre." : message
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
