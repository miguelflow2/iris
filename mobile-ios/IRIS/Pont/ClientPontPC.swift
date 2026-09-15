// ClientPontPC.swift — le client du service IRIS resté sur l'ordinateur.
//
// Portage en Swift de backend/iris/mobile_static/js/api.js : mêmes routes, même serrure
// (Authorization: Bearer <session>), mêmes deux refus 401 distingués (IRIS verrouillée ou session
// refusée). Ce qui change par rapport à la page web : la session vit dans le Trousseau, et le
// WebSocket porte le jeton dans l'en-tête (une app sait le faire, un navigateur non) — le jeton
// n'apparaît donc jamais dans une adresse.
//
// Chemin réseau, dit tel quel dans Profil › Ordinateur et Mode hors ligne : l'app joint l'ordinateur
// DIRECTEMENT, par son adresse Tailscale (dehors) ou le réseau local (maison). Elle ne passe PAS par le
// relais VELA : sans Tailscale, elle ne joint pas l'ordinateur. Le relais ne sert ici qu'au partage de vue.
//
// Verrouillage : l'état « verrouillée » est GARDÉ sur l'iPhone (UserDefaults), pas seulement en mémoire.
// Le verrou sert quand les lunettes — donc souvent le téléphone — sont perdues : relancer l'app sans
// réseau ne doit pas rouvrir l'accès aux cours gardés. Il n'est levé que par une réponse 2xx de
// /api/status, c'est-à-dire un ordinateur qui répond et n'est plus verrouillé.

import Foundation
import Observation
import os

/// Ce qu'un refus HTTP doit changer dans l'état du pont (séparé du classement, pour le tester).
enum EffetRefus: Equatable {
    case aucun
    /// 401 dont le détail dit « verrouillée » : écran de verrouillage, SANS effacer la session.
    case verrouiller(String)
    /// 401 de session refusée (révoquée, expirée) : on oublie la session de cet iPhone.
    case oublierSession
    /// 401 detail {code: "efface_a_distance"} : la session a été révoquée PAR un effacement à distance, que
    /// l'iPhone n'a pas vu en direct (app en arrière-plan, cas normal d'un téléphone perdu). On oublie la
    /// session, on garde le verrou et on retire les copies gardées sur l'iPhone.
    case effacement
}

@MainActor
@Observable
final class ClientPontPC: ServicePontPC {
    private(set) var etat: EtatConnexionPC = .nonConfigure
    private(set) var adresse: URL?
    private(set) var nomProprietaire: String = ""
    /// Vrai si l'adresse est en http (réseau local) : l'interface l'affiche.
    private(set) var liaisonNonChiffree = false
    private(set) var derniereReponse: Date?

    @ObservationIgnored private var session: String?
    @ObservationIgnored private let urlSession: URLSession
    @ObservationIgnored private var ecouteurs: [UUID: @MainActor (EvenementPC) -> Void] = [:]
    @ObservationIgnored private var flux: FluxEvenements?
    @ObservationIgnored private var surveillance: Task<Void, Never>?
    @ObservationIgnored private let journal = Logger(subsystem: "ca.velaglass.iris", category: "pont")

    /// IRIS a été vue verrouillée et aucun 2xx de /api/status ne l'a encore démentie. Survit au relancement.
    private(set) var verrouPersistant: Bool
    /// Raison affichée par l'écran de verrouillage (dernière connue).
    private(set) var raisonVerrou: String
    /// Verrouillée ET ordinateur injoignable à la dernière vérification : l'écran de verrouillage le dit
    /// (l'état reste .verrouille, jamais .horsLigne). nil dès qu'une réponse HTTP arrive.
    private(set) var injoignablePendantVerrou: String? = nil
    /// Nombre d'ouvertures de la liaison d'événements : une coupure brève entre deux sondages de la
    /// conversation se voit à ce compteur, même si la liaison est de nouveau ouverte.
    @ObservationIgnored private(set) var ouverturesFlux = 0
    /// La cause du verrou (GET /api/confiance/verrou/etat) a été lue pour ce verrou.
    @ObservationIgnored private var causeVerrouLue = false

    /// Appelé quand l'ordinateur annonce un effacement à distance (verrou.etat raison « effacement »), ou
    /// qu'une session est refusée alors qu'IRIS était verrouillée (l'effacement révoque les sessions).
    @ObservationIgnored var surEffacementDistant: (@MainActor () -> Void)?

    private enum Cles {
        static let adresse = "iris_adresse_pc"
        static let nom = "iris_nom_proprietaire"
        static let session = "session-pc"
        static let verrouille = "iris_verrouille"
        static let raisonVerrou = "iris_verrou_raison"
    }

    static let raisonVerrouParDefaut = "IRIS est verrouillée. Déverrouillez-la avec le mot de passe du propriétaire."
    nonisolated static let raisonEffacement = "Les données d'IRIS ont été effacées à distance et IRIS est verrouillée. Les cours gardés sur cet iPhone ont été retirés."
    /// Code du 401 d'une session révoquée par un effacement à distance (main.py, CODE_EFFACE_A_DISTANCE).
    nonisolated static let codeEffaceADistance = "efface_a_distance"

    init() {
        let configuration = URLSessionConfiguration.default
        configuration.waitsForConnectivity = false
        configuration.requestCachePolicy = .reloadIgnoringLocalCacheData
        configuration.urlCache = nil
        configuration.timeoutIntervalForRequest = 30
        urlSession = URLSession(configuration: configuration)

        if let texte = UserDefaults.standard.string(forKey: Cles.adresse), let url = URL(string: texte) {
            adresse = url
            liaisonNonChiffree = url.scheme?.lowercased() == "http"
        }
        nomProprietaire = UserDefaults.standard.string(forKey: Cles.nom) ?? ""
        session = Trousseau.lire(compte: Cles.session)
        verrouPersistant = UserDefaults.standard.bool(forKey: Cles.verrouille)
        raisonVerrou = UserDefaults.standard.string(forKey: Cles.raisonVerrou) ?? Self.raisonVerrouParDefaut
        if verrouPersistant && adresse != nil {
            // Relancée verrouillée : on reste derrière l'écran de verrouillage, réseau ou pas.
            etat = .verrouille(raison: raisonVerrou)
        } else {
            etat = adresse == nil ? .nonConfigure : (session == nil ? .motDePasseRequis : .connexion)
        }

        let flux = FluxEvenements(urlSession: urlSession)
        flux.fournirRequete = { [weak self] in self?.requeteWebSocket() }
        flux.surEvenement = { [weak self] evenement in self?.diffuser(evenement) }
        flux.surEtat = { [weak self] ouvert in self?.fluxChange(ouvert: ouvert) }
        flux.surRefus = { [weak self] raison in
            // Liaison forte le temps de la tâche : une capture faible ne doit pas être reprise
            // dans une tâche concurrente.
            guard let self else { return }
            Task { @MainActor in await self.apresRefusWebSocket(raison) }
        }
        self.flux = flux
    }

    var evenementsOuverts: Bool { flux?.ouvert ?? false }
    var aUneSession: Bool { session != nil }

    // MARK: - Adresse et connexion

    /// Valide l'adresse saisie. HTTPS obligatoire, sauf réseau local ou adresse Tailscale en IP
    /// (100.64.0.0/10), où le tunnel chiffre déjà le trajet.
    nonisolated static func normaliserAdresse(_ saisie: String) throws -> URL {
        var texte = saisie.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !texte.isEmpty else { throw ErreurPont.adresseAbsente }
        if !texte.contains("://") { texte = "https://" + texte }
        while texte.hasSuffix("/") { texte.removeLast() }
        guard var composants = URLComponents(string: texte),
              let schema = composants.scheme?.lowercased(),
              let hote = composants.host, !hote.isEmpty else {
            throw ErreurPont.refus(statut: 0, message: "Adresse illisible. Exemple : https://bureau.tail1234.ts.net", detail: nil)
        }
        guard schema == "https" || schema == "http" else {
            throw ErreurPont.refus(statut: 0, message: "L'adresse doit commencer par https://", detail: nil)
        }
        if schema == "http" && !estAdresseLocale(hote) {
            throw ErreurPont.refus(
                statut: 0,
                message: "Hors du réseau local, l'adresse doit être en https:// (adresse Tailscale « ….ts.net »). Sinon, le mot de passe voyagerait en clair.",
                detail: nil)
        }
        composants.path = ""
        composants.query = nil
        composants.fragment = nil
        guard let url = composants.url else {
            throw ErreurPont.refus(statut: 0, message: "Adresse illisible.", detail: nil)
        }
        return url
    }

    nonisolated static func estAdresseLocale(_ hote: String) -> Bool {
        let h = hote.lowercased()
        if h == "localhost" || h.hasSuffix(".local") || !h.contains(".") { return true }
        let octets = h.split(separator: ".").compactMap { Int($0) }
        guard octets.count == 4, octets.allSatisfy({ (0...255).contains($0) }) else { return false }
        switch (octets[0], octets[1]) {
        case (10, _), (127, _), (192, 168), (169, 254): return true
        case (172, 16...31): return true
        case (100, 64...127): return true   // plage des adresses Tailscale
        default: return false
        }
    }

    /// Premier branchement : vérifie que l'adresse répond, qu'un mot de passe existe, puis ouvre une
    /// session (30 jours) rangée dans le Trousseau.
    func connecter(adresse saisie: String, motDePasse: String) async throws {
        let url = try Self.normaliserAdresse(saisie)
        adresse = url
        liaisonNonChiffree = url.scheme?.lowercased() == "http"
        UserDefaults.standard.set(url.absoluteString, forKey: Cles.adresse)
        etat = .connexion

        struct Sante: Decodable { let ok: Bool?; let name: String? }
        let sante: Sante
        do {
            sante = try await requete(.get, "/api/health", corps: nil, parametres: [], delai: 12)
        } catch ErreurPont.decodage {
            etat = .horsLigne(raison: "Cette adresse répond, mais ce n'est pas IRIS.")
            throw ErreurPont.refus(statut: 0, message: "Cette adresse répond, mais ce n'est pas IRIS.", detail: nil)
        }
        guard sante.name == "IRIS" else {
            etat = .horsLigne(raison: "Cette adresse répond, mais ce n'est pas IRIS.")
            throw ErreurPont.refus(statut: 0, message: "Cette adresse répond, mais ce n'est pas IRIS.", detail: nil)
        }

        let compte: EtatCompte = try await requete(.get, "/api/compte", corps: nil, parametres: [], delai: 12)
        guard compte.configure else {
            etat = .motDePasseRequis
            throw ErreurPont.refus(
                statut: 409,
                message: "Aucun mot de passe n'est encore créé sur ton ordinateur. Crée-le dans l'application IRIS de l'ordinateur (Mon profil › Compte et sécurité), puis reviens ici.",
                detail: nil)
        }

        let reponse: ReponseConnexion
        do {
            reponse = try await requete(.post, "/api/compte/connexion", corps: DemandeConnexion(motDePasse: motDePasse),
                                        parametres: [], delai: 20)
        } catch ErreurPont.nonConnecte {
            etat = .motDePasseRequis
            throw ErreurPont.nonConnecte("Mot de passe incorrect.")
        }
        guard Trousseau.ecrire(reponse.session, compte: Cles.session) else {
            etat = .motDePasseRequis
            throw ErreurPont.refus(statut: 0, message: "Le Trousseau de l'iPhone a refusé de garder la session.", detail: nil)
        }
        session = reponse.session
        nomProprietaire = reponse.nom ?? ""
        UserDefaults.standard.set(nomProprietaire, forKey: Cles.nom)
        await verifier()
    }

    /// Oublie la session de CET iPhone seulement. Volontairement pas /api/compte/deconnexion, qui
    /// révoque les sessions de tous les appareils.
    func oublierSession() {
        Trousseau.effacer(compte: Cles.session)
        session = nil
        flux?.arreter()
        etat = adresse == nil ? .nonConfigure : .motDePasseRequis
    }

    // MARK: - Verrou gardé sur l'iPhone

    private func poserVerrou(_ raison: String) {
        raisonVerrou = raison
        verrouPersistant = true
        UserDefaults.standard.set(true, forKey: Cles.verrouille)
        UserDefaults.standard.set(raison, forKey: Cles.raisonVerrou)
        etat = .verrouille(raison: raison)
        flux?.arreter()
    }

    /// Seul chemin qui lève le verrou gardé : une réponse 2xx de /api/status.
    private func leverVerrou() {
        causeVerrouLue = false
        injoignablePendantVerrou = nil
        guard verrouPersistant else { return }
        verrouPersistant = false
        UserDefaults.standard.removeObject(forKey: Cles.verrouille)
        UserDefaults.standard.removeObject(forKey: Cles.raisonVerrou)
    }

    /// Verrou vu par un 401 (événement manqué : WebSocket fermé, app en arrière-plan) : on demande sa cause,
    /// une fois par verrou, par la route permise pendant le verrou. Un effacement à distance retire aussi
    /// les copies gardées sur cet iPhone.
    private func lireCauseVerrou() async {
        guard verrouPersistant, !causeVerrouLue, session != nil else { return }
        causeVerrouLue = true
        guard let lu: EtatVerrou = try? await requete(.get, "/api/confiance/verrou/etat", corps: nil,
                                                      parametres: [], delai: 12),
              lu.verrouille, lu.raison == "effacement" else { return }
        let raison = Self.raisonEffacement
        raisonVerrou = raison
        UserDefaults.standard.set(raison, forKey: Cles.raisonVerrou)
        etat = .verrouille(raison: raison)
        surEffacementDistant?()
    }

    func oublierAdresse() {
        oublierSession()
        UserDefaults.standard.removeObject(forKey: Cles.adresse)
        adresse = nil
        liaisonNonChiffree = false
        etat = .nonConfigure
    }

    // MARK: - Joignabilité

    func verifier() async {
        guard adresse != nil else { etat = .nonConfigure; return }
        guard session != nil else { etat = .motDePasseRequis; return }
        // On garde l'état affiché pendant la vérification (hors ligne, verrouillée) : le remplacer
        // par « connexion » ferait clignoter l'écran de verrouillage toutes les 20 s.
        if etat == .nonConfigure || etat == .motDePasseRequis { etat = .connexion }
        do {
            let _: ReponseIgnoree = try await requete(.get, "/api/status", corps: nil, parametres: [], delai: 12)
            leverVerrou()
            etat = .connecte(evenements: evenementsOuverts)
            flux?.demarrer()
        } catch ErreurPont.verrouillee(let raison) {
            // Après un effacement (session oubliée), traduireRefus a déjà posé le verrou avec sa vraie raison.
            if session != nil {
                poserVerrou(raison)
                await lireCauseVerrou()
            }
        } catch ErreurPont.nonConnecte {
            // traduireRefus a déjà oublié la session (et prévenu d'un effacement si IRIS était verrouillée).
            if verrouPersistant { etat = .verrouille(raison: raisonVerrou) } else { etat = .motDePasseRequis }
        } catch ErreurPont.injoignable(let raison) {
            if verrouPersistant {
                etat = .verrouille(raison: raisonVerrou)
                injoignablePendantVerrou = raison
            } else {
                etat = .horsLigne(raison: raison)
            }
        } catch is CancellationError {
            return
        } catch {
            // Une réponse HTTP, même une erreur, prouve que l'ordinateur est là — mais pas qu'il est
            // déverrouillé : seul un 2xx de /api/status lève le verrou gardé.
            if verrouPersistant {
                etat = .verrouille(raison: raisonVerrou)
            } else {
                etat = .connecte(evenements: evenementsOuverts)
                flux?.demarrer()
            }
        }
    }

    /// Au premier plan : revérifie toutes les 20 s tant que l'ordinateur est injoignable, verrouillé,
    /// ou que les événements sont fermés (le WebSocket se reconnecte seul ; ceci rattrape le HTTP).
    func demarrerSurveillance() {
        surveillance?.cancel()
        surveillance = Task { [weak self] in
            while !Task.isCancelled {
                guard let self else { return }
                switch self.etat {
                case .horsLigne, .connexion, .verrouille:
                    // Verrouillée : le WebSocket est fermé, seul le HTTP dira qu'elle a été
                    // déverrouillée sur l'ordinateur.
                    await self.verifier()
                case .connecte(let evenements) where !evenements:
                    await self.verifier()
                default:
                    break
                }
                try? await Task.sleep(for: .seconds(20))
            }
        }
    }

    /// En arrière-plan : iOS coupe de toute façon les liaisons ; on les ferme proprement.
    func suspendre() {
        surveillance?.cancel()
        surveillance = nil
        flux?.arreter()
        if case .connecte = etat { etat = .connecte(evenements: false) }
    }

    // MARK: - Requêtes

    func requete<R: Decodable>(_ methode: MethodeHTTP, _ chemin: String, corps: (any Encodable)?,
                               parametres: [URLQueryItem], delai: TimeInterval) async throws -> R {
        var donnees: Data?
        if let corps {
            do {
                donnees = try JSONIRIS.encodeur.encode(corps)
            } catch {
                throw ErreurPont.decodage("corps non encodable (\(error.localizedDescription))")
            }
        }
        let (data, _) = try await requeteBrute(methode, chemin, corps: donnees,
                                               typeContenu: donnees == nil ? nil : "application/json",
                                               parametres: parametres, delai: delai)
        if let ignoree = ReponseIgnoree() as? R { return ignoree }
        do {
            return try JSONIRIS.decodeur.decode(R.self, from: data)
        } catch {
            journal.error("réponse illisible pour \(chemin, privacy: .public) : \(String(describing: error), privacy: .public)")
            throw ErreurPont.decodage(Self.decrire(error))
        }
    }

    func requeteBrute(_ methode: MethodeHTTP, _ chemin: String, corps: Data?, typeContenu: String?,
                      parametres: [URLQueryItem], delai: TimeInterval) async throws -> (Data, HTTPURLResponse) {
        guard let base = adresse else { throw ErreurPont.adresseAbsente }
        guard var composants = URLComponents(url: base, resolvingAgainstBaseURL: false) else {
            throw ErreurPont.adresseAbsente
        }
        composants.path = chemin
        composants.queryItems = parametres.isEmpty ? nil : parametres
        guard let url = composants.url else {
            throw ErreurPont.refus(statut: 0, message: "Chemin invalide : \(chemin)", detail: nil)
        }
        var req = URLRequest(url: url, cachePolicy: .reloadIgnoringLocalCacheData, timeoutInterval: delai)
        req.httpMethod = methode.rawValue
        req.setValue("application/json", forHTTPHeaderField: "Accept")
        if let corps {
            req.httpBody = corps
            req.setValue(typeContenu ?? "application/json", forHTTPHeaderField: "Content-Type")
        }
        if let session {
            req.setValue("Bearer \(session)", forHTTPHeaderField: "Authorization")
        }

        let data: Data
        let reponse: URLResponse
        do {
            (data, reponse) = try await urlSession.data(for: req)
        } catch let erreur as URLError {
            if erreur.code == .cancelled { throw CancellationError() }
            let message = Self.message(pour: erreur, delai: delai)
            if erreur.code != .timedOut {
                // Un délai dépassé sur une requête lente ne prouve pas que l'ordinateur est parti.
                // Verrouillée : on ne remplace JAMAIS l'écran de verrouillage par « hors ligne ».
                if !chemin.hasPrefix("/api/compte/connexion") && !verrouPersistant {
                    if case .verrouille = etat {} else { etat = .horsLigne(raison: message) }
                }
                flux?.arreter()
            }
            throw ErreurPont.injoignable(message)
        } catch is CancellationError {
            throw CancellationError()
        } catch {
            throw ErreurPont.injoignable("L'ordinateur ne répond pas (\(error.localizedDescription)).")
        }
        guard let http = reponse as? HTTPURLResponse else {
            throw ErreurPont.injoignable("Réponse inattendue de l'ordinateur.")
        }
        derniereReponse = Date()
        injoignablePendantVerrou = nil
        if case .horsLigne = etat, session != nil { etat = .connecte(evenements: evenementsOuverts) }
        if http.statusCode >= 400 {
            throw traduireRefus(statut: http.statusCode, data: data, chemin: chemin)
        }
        return (data, http)
    }

    private func traduireRefus(statut: Int, data: Data, chemin: String) -> ErreurPont {
        let (erreur, effet) = Self.classerRefus(statut: statut, data: data, chemin: chemin)
        switch effet {
        case .aucun:
            break
        case .verrouiller(let raison):
            poserVerrou(raison)
        case .effacement:
            Trousseau.effacer(compte: Cles.session)
            session = nil
            poserVerrou(Self.raisonEffacement)
            causeVerrouLue = true
            surEffacementDistant?()
        case .oublierSession:
            // Session révoquée ou expirée : on l'oublie ici, le mot de passe sera redemandé. Si IRIS était
            // verrouillée, la révocation vient très probablement d'un effacement à distance : les copies
            // gardées sur l'iPhone partent aussi.
            Trousseau.effacer(compte: Cles.session)
            session = nil
            flux?.arreter()
            if verrouPersistant {
                surEffacementDistant?()
                etat = .verrouille(raison: raisonVerrou)
            } else {
                etat = .motDePasseRequis
            }
        }
        return erreur
    }

    /// Classe un refus HTTP du service sans rien modifier (fonction pure, testée dans IRISTests).
    nonisolated static func classerRefus(statut: Int, data: Data, chemin: String) -> (ErreurPont, EffetRefus) {
        // Décodeur SANS conversion de clés : on garde les noms exacts du service dans `detail`.
        let objet = try? JSONDecoder().decode([String: ValeurJSON].self, from: data)
        let detail = objet?["detail"]
        let message = messageDe(detail: detail, statut: statut)
        let code = detail?["code"]?.texte

        if statut == 401 {
            if code == Self.codeEffaceADistance {
                return (.verrouillee(Self.raisonEffacement), .effacement)
            }
            if message.localizedCaseInsensitiveContains("verrouill") {
                return (.verrouillee(message), .verrouiller(message))
            }
            if chemin.hasPrefix("/api/compte/connexion") {
                return (.nonConnecte(message), .aucun)
            }
            return (.nonConnecte(message), .oublierSession)
        }
        if statut == 428, code == "lunettes_requises", let refus: RefusLunettes = relire(detail) {
            return (.lunettesRequises(refus), .aucun)
        }
        if statut == 403, code == "consentement", let refus: RefusConsentement = relire(detail) {
            return (.consentement(refus), .aucun)
        }
        return (.refus(statut: statut, message: message, detail: detail), .aucun)
    }

    nonisolated static func relire<T: Decodable>(_ valeur: ValeurJSON?) -> T? {
        guard let valeur, let data = try? JSONEncoder().encode(valeur) else { return nil }
        return try? JSONIRIS.decodeur.decode(T.self, from: data)
    }

    nonisolated static func messageDe(detail: ValeurJSON?, statut: Int) -> String {
        if let texte = detail?.texte, !texte.trimmingCharacters(in: .whitespaces).isEmpty { return texte }
        if let message = detail?["message"]?.texte, !message.isEmpty { return message }
        if case .tableau = detail { return "IRIS a refusé la demande : données incomplètes ou invalides." }
        return "L'ordinateur a répondu par une erreur (\(statut))."
    }

    nonisolated static func message(pour erreur: URLError, delai: TimeInterval) -> String {
        switch erreur.code {
        case .notConnectedToInternet, .dataNotAllowed:
            return "Cet iPhone n'a pas de connexion Internet."
        case .timedOut:
            return "L'ordinateur n'a pas répondu dans les \(Int(delai)) secondes."
        case .cannotFindHost, .dnsLookupFailed:
            return "Adresse introuvable : vérifie que Tailscale est connecté sur cet iPhone et sur l'ordinateur."
        case .cannotConnectToHost, .networkConnectionLost:
            return "L'ordinateur ne répond pas : éteint, en veille, IRIS fermée, ou Tailscale coupé."
        case .secureConnectionFailed, .serverCertificateUntrusted, .serverCertificateHasBadDate,
             .serverCertificateNotYetValid, .serverCertificateHasUnknownRoot, .clientCertificateRejected:
            return "Connexion sécurisée refusée : vérifie l'adresse https de l'ordinateur."
        case .appTransportSecurityRequiresSecureConnection:
            return "iOS exige une adresse https pour joindre cet ordinateur."
        default:
            return "L'ordinateur ne répond pas (\(erreur.localizedDescription))."
        }
    }

    nonisolated private static func decrire(_ erreur: Error) -> String {
        guard let e = erreur as? DecodingError else { return erreur.localizedDescription }
        switch e {
        case .keyNotFound(let cle, _): return "champ « \(cle.stringValue) » absent"
        case .typeMismatch(_, let c), .valueNotFound(_, let c), .dataCorrupted(let c):
            return c.codingPath.map { $0.stringValue }.joined(separator: ".") + " : " + c.debugDescription
        @unknown default: return String(describing: e)
        }
    }

    // MARK: - Événements

    func abonner(_ ecouteur: @escaping @MainActor (EvenementPC) -> Void) -> AbonnementEvenements {
        let id = UUID()
        ecouteurs[id] = ecouteur
        return AbonnementEvenements { [weak self] in
            guard let self else { return }
            Task { @MainActor in self.ecouteurs[id] = nil }
        }
    }

    private func diffuser(_ evenement: EvenementPC) {
        switch evenement.type {
        case "hello":
            etat = .connecte(evenements: true)
        case "verrou.etat":
            let cause = evenement.champs["raison"]?.texte
            if evenement.champs["verrouille"]?.booleen == true {
                let raison: String
                switch cause {
                case "distance":
                    raison = "IRIS est verrouillée à distance. Déverrouillez-la avec le mot de passe du propriétaire."
                case "effacement":
                    raison = Self.raisonEffacement
                default:
                    raison = Self.raisonVerrouParDefaut
                }
                poserVerrou(raison)
                causeVerrouLue = true
                if cause == "effacement" { surEffacementDistant?() }
            } else if evenement.champs["verrouille"]?.booleen == false, verrouPersistant {
                // Déverrouillée sur l'ordinateur : /api/status doit le confirmer avant de lever le verrou gardé.
                Task { await self.verifier() }
            }
        default:
            break
        }
        for ecouteur in Array(ecouteurs.values) {
            ecouteur(evenement)
        }
    }

    private func fluxChange(ouvert: Bool) {
        if ouvert { ouverturesFlux += 1 }
        if case .connecte = etat { etat = .connecte(evenements: ouvert) }
    }

    /// WebSocket refusé (code 4401 ou poignée de main refusée) : on demande au HTTP pourquoi, une
    /// seule fois, au lieu de reboucler.
    private func apresRefusWebSocket(_ raison: String) async {
        if raison.localizedCaseInsensitiveContains("effacée à distance") {
            // La phrase du WebSocket ne porte pas le code : le HTTP le rend (401 efface_a_distance).
            await verifier()
            return
        }
        if raison.localizedCaseInsensitiveContains("verrouill") {
            poserVerrou(Self.raisonVerrouParDefaut)
            return
        }
        await verifier()
    }

    private func requeteWebSocket() -> URLRequest? {
        guard let base = adresse, let session,
              var composants = URLComponents(url: base, resolvingAgainstBaseURL: false) else { return nil }
        composants.scheme = composants.scheme?.lowercased() == "http" ? "ws" : "wss"
        composants.path = "/ws"
        guard let url = composants.url else { return nil }
        var req = URLRequest(url: url)
        req.setValue("Bearer \(session)", forHTTPHeaderField: "Authorization")
        req.timeoutInterval = 20
        return req
    }

    // MARK: - Déverrouillage (chemin permis pendant le verrou)

    func deverrouiller(motDePasse: String) async throws {
        let _: EtatVerrou = try await requete(.post, "/api/confiance/deverrouiller",
                                              corps: DemandeDeverrouillage(motDePasse: motDePasse),
                                              parametres: [], delai: 60)
        etat = .connexion
        await verifier()
    }
}
