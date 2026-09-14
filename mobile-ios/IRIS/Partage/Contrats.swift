// Contrats.swift — les interfaces partagées de l'app iPhone IRIS (VELA).
//
// Écrit par l'équipe ios-cœur le 2026-09-13, EN PREMIER, pour que l'équipe ios-perception
// (dossiers Perception/ et Ecrans/Accessibilite/) puisse écrire en parallèle sans attendre.
// Ce fichier fixe les FORMES, pas les détails internes. Il n'a pas été compilé ici (Windows,
// pas de Xcode) : il n'utilise que Foundation et SwiftUI d'iOS 17.
//
// Règles de décodage, pour tout le projet :
//  - le service du PC parle en snake_case ; on décode avec `JSONIRIS.decodeur`
//    (keyDecodingStrategy = .convertFromSnakeCase) et on encode avec `JSONIRIS.encodeur`
//    (.convertToSnakeCase). Donc les propriétés Swift sont en camelCase SANS CodingKeys
//    (« duree_ms » -> dureeMs, « url_spectateur » -> urlSpectateur). Attention : la stratégie
//    s'applique aussi aux clés des dictionnaires [String: …].
//  - presque tout est optionnel au-delà du cœur : le code du service fait foi, et une réponse
//    enrichie demain ne doit pas faire planter l'app aujourd'hui.
//  - les champs de vérité (note, limite, limites, avertissement, phrase, memoireSuspendue, raison,
//    local, empechement, texteConsentement, noteLegale) s'AFFICHENT tels quels quand ils sont là.
//
// Qui écrit quoi :
//  - ios-cœur : ServicePontPC (Pont/), ServiceVoix (Voix/), l'attestation des lunettes auprès du
//    PC toutes les 60 s (Pont/AttestationLunettes.swift, qui LIT ServiceLunettes.etat), l'app,
//    les onglets, IA, Profil, Interprète, Cours, Mode hors ligne.
//  - ios-perception : ServiceLunettes (CoreBluetooth), ServiceVision, ServiceAlertes,
//    ServiceGuidage, et l'écran de l'onglet Accessibilité ; le tout exposé par une classe
//    fabrique trouvée à l'exécution (voir FabriquePerception plus bas), pour que l'app compile
//    et démarre même si ce module manque.

import Foundation
import SwiftUI

// MARK: - JSON

enum JSONIRIS {
    /// Décodeur commun : snake_case du service -> camelCase Swift.
    static var decodeur: JSONDecoder {
        let d = JSONDecoder()
        d.keyDecodingStrategy = .convertFromSnakeCase
        return d
    }

    /// Encodeur commun : camelCase Swift -> snake_case attendu par FastAPI.
    static var encodeur: JSONEncoder {
        let e = JSONEncoder()
        e.keyEncodingStrategy = .convertToSnakeCase
        return e
    }
}

/// Valeur JSON quelconque, pour les champs dont la forme varie (détails d'erreur, événements).
enum ValeurJSON: Codable, Hashable, Sendable {
    case texte(String)
    case nombre(Double)
    case booleen(Bool)
    case objet([String: ValeurJSON])
    case tableau([ValeurJSON])
    case nul

    init(from decoder: Decoder) throws {
        let c = try decoder.singleValueContainer()
        if c.decodeNil() { self = .nul; return }
        // L'ordre compte : un booléen JSON ne doit pas devenir un nombre.
        if let b = try? c.decode(Bool.self) { self = .booleen(b); return }
        if let n = try? c.decode(Double.self) { self = .nombre(n); return }
        if let s = try? c.decode(String.self) { self = .texte(s); return }
        if let o = try? c.decode([String: ValeurJSON].self) { self = .objet(o); return }
        if let t = try? c.decode([ValeurJSON].self) { self = .tableau(t); return }
        throw DecodingError.dataCorruptedError(in: c, debugDescription: "valeur JSON illisible")
    }

    func encode(to encoder: Encoder) throws {
        var c = encoder.singleValueContainer()
        switch self {
        case .texte(let s): try c.encode(s)
        case .nombre(let n): try c.encode(n)
        case .booleen(let b): try c.encode(b)
        case .objet(let o): try c.encode(o)
        case .tableau(let t): try c.encode(t)
        case .nul: try c.encodeNil()
        }
    }

    var texte: String? { if case .texte(let s) = self { return s }; return nil }
    var nombre: Double? { if case .nombre(let n) = self { return n }; return nil }
    var booleen: Bool? { if case .booleen(let b) = self { return b }; return nil }
    subscript(_ cle: String) -> ValeurJSON? { if case .objet(let o) = self { return o[cle] }; return nil }
}

/// Horodatage que le service rend tantôt en secondes epoch (nombre), tantôt en ISO 8601 (texte).
struct Horodatage: Codable, Hashable, Sendable {
    let date: Date?
    let brut: String

    init(from decoder: Decoder) throws {
        let c = try decoder.singleValueContainer()
        if let n = try? c.decode(Double.self) {
            date = Date(timeIntervalSince1970: n)
            brut = String(n)
        } else if let s = try? c.decode(String.self) {
            brut = s
            // Un nombre écrit en texte (copie gardée sur l'iPhone, réencodée) reste des secondes epoch.
            if let n = Double(s) { date = Date(timeIntervalSince1970: n) } else { date = Horodatage.lireISO(s) }
        } else {
            throw DecodingError.dataCorruptedError(in: c, debugDescription: "horodatage illisible")
        }
    }

    func encode(to encoder: Encoder) throws {
        var c = encoder.singleValueContainer()
        if let n = Double(brut) { try c.encode(n) } else { try c.encode(brut) }
    }

    /// Valeur numérique brute quand le service a envoyé un nombre (secondes).
    var secondes: Double? { Double(brut) }

    private static func lireISO(_ s: String) -> Date? {
        let f = ISO8601DateFormatter()
        f.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        if let d = f.date(from: s) { return d }
        f.formatOptions = [.withInternetDateTime]
        if let d = f.date(from: s) { return d }
        // Le service Python écrit souvent « 2026-09-13T14:05:12 » sans fuseau : heure locale du PC.
        let local = DateFormatter()
        local.locale = Locale(identifier: "en_US_POSIX")
        for format in ["yyyy-MM-dd'T'HH:mm:ss.SSSSSS", "yyyy-MM-dd'T'HH:mm:ss", "yyyy-MM-dd"] {
            local.dateFormat = format
            if let d = local.date(from: s) { return d }
        }
        return nil
    }
}

// MARK: - Erreurs du pont

/// Refus « lunettes requises » (428) : detail {code, fonction, message, acheter_url}.
struct RefusLunettes: Codable, Hashable, Sendable {
    let code: String
    let fonction: String?
    let message: String
    let acheterUrl: String?
}

/// Refus de consentement (403) : detail {code: "consentement", data_type, label, message}.
struct RefusConsentement: Codable, Hashable, Sendable {
    let code: String
    let dataType: String?
    let label: String?
    let message: String?
}

enum ErreurPont: Error, LocalizedError, Equatable {
    /// Aucune adresse de PC n'est réglée dans Profil.
    case adresseAbsente
    /// Pas de session (ou session expirée) : il faut le mot de passe du propriétaire.
    case nonConnecte(String)
    /// IRIS est verrouillée (401 dont le détail contient « verrouillée », ou verrou.etat).
    case verrouillee(String)
    /// Le PC ne répond pas (réseau, Tailscale éteint, PC en veille).
    case injoignable(String)
    /// 428 : la fonction exige les lunettes VELA.
    case lunettesRequises(RefusLunettes)
    /// 403 code « consentement ».
    case consentement(RefusConsentement)
    /// Tout autre refus du service, avec son code HTTP et sa phrase exacte (à afficher telle quelle).
    case refus(statut: Int, message: String, detail: ValeurJSON?)
    /// Réponse reçue mais de forme inattendue.
    case decodage(String)

    var errorDescription: String? {
        switch self {
        case .adresseAbsente:
            return "Aucune adresse d'ordinateur n'est réglée. Ouvre Profil › Ordinateur."
        case .nonConnecte(let m), .verrouillee(let m), .injoignable(let m):
            return m
        case .lunettesRequises(let r):
            return r.message
        case .consentement(let r):
            return r.message ?? "Cette action demande ton consentement dans l'application IRIS de l'ordinateur."
        case .refus(_, let message, _):
            return message
        case .decodage(let m):
            return "Réponse de l'ordinateur illisible : \(m)"
        }
    }

    /// Code HTTP quand il existe (409, 422, 423, 429…).
    var statut: Int? {
        switch self {
        case .refus(let s, _, _): return s
        case .lunettesRequises: return 428
        case .consentement: return 403
        case .nonConnecte, .verrouillee: return 401
        default: return nil
        }
    }
}

// MARK: - Pont vers le PC (implémenté par ios-cœur)

enum MethodeHTTP: String, Sendable {
    case get = "GET", post = "POST", put = "PUT", patch = "PATCH", delete = "DELETE"
}

enum EtatConnexionPC: Equatable, Sendable {
    /// Aucune adresse réglée.
    case nonConfigure
    /// Adresse réglée, pas de session : écran de mot de passe.
    case motDePasseRequis
    case connexion
    /// Session valide, PC joignable ; `evenements` dit si le WebSocket est ouvert.
    case connecte(evenements: Bool)
    /// PC injoignable : l'app bascule en mode hors ligne (fonctions locales seulement).
    case horsLigne(raison: String)
    /// IRIS verrouillée : écran de verrouillage, reconnexion suspendue.
    case verrouille(raison: String)

    var estConnecte: Bool { if case .connecte = self { return true }; return false }
}

/// Un événement du bus du PC reçu par /ws : {"type": …, "ts": …, …champs à plat}.
/// ATTENTION (erratum) : album.nouveau et alerte.sonore portent « genre », jamais « type » ;
/// pas_a_pas.etat {session: {…}} et entrainement.etat {seance: {…}} sont imbriqués.
struct EvenementPC: Sendable {
    let type: String
    let ts: Double?
    let champs: [String: ValeurJSON]
    /// Le JSON brut, pour décoder l'événement entier dans un modèle : `evt.decoder(TourInterprete.self)`.
    let brut: Data

    func decoder<T: Decodable>(_ modele: T.Type) -> T? {
        try? JSONIRIS.decodeur.decode(modele, from: brut)
    }
}

/// Jeton d'abonnement : `annuler()` au démontage de l'écran.
final class AbonnementEvenements {
    private var fin: (() -> Void)?
    init(_ fin: @escaping () -> Void) { self.fin = fin }
    func annuler() { fin?(); fin = nil }
    deinit { fin?() }
}

@MainActor
protocol ServicePontPC: AnyObject {
    var etat: EtatConnexionPC { get }
    /// Adresse Tailscale du PC, p. ex. https://bureau.tail1234.ts.net (jamais une 192.168.*).
    var adresse: URL? { get }
    /// Nom du propriétaire renvoyé par la connexion, pour l'affichage.
    var nomProprietaire: String { get }

    /// Requête JSON authentifiée (Authorization: Bearer <session>, jamais le jeton dans l'URL).
    /// Lève ErreurPont. `corps` est encodé en snake_case.
    func requete<R: Decodable>(_ methode: MethodeHTTP, _ chemin: String, corps: (any Encodable)?,
                               parametres: [URLQueryItem], delai: TimeInterval) async throws -> R

    /// Requête brute (binaire, texte, CSV, markdown). Lève ErreurPont sur un statut ≥ 400.
    func requeteBrute(_ methode: MethodeHTTP, _ chemin: String, corps: Data?, typeContenu: String?,
                      parametres: [URLQueryItem], delai: TimeInterval) async throws -> (Data, HTTPURLResponse)

    /// S'abonner aux événements du PC (tous types ; filtrer sur `type`). Appelé sur le MainActor.
    func abonner(_ ecouteur: @escaping @MainActor (EvenementPC) -> Void) -> AbonnementEvenements

    /// Vérifie immédiatement la joignabilité (GET /api/health puis /api/status).
    func verifier() async
}

extension ServicePontPC {
    func get<R: Decodable>(_ chemin: String, parametres: [URLQueryItem] = [], delai: TimeInterval = 20) async throws -> R {
        return try await requete(.get, chemin, corps: nil, parametres: parametres, delai: delai)
    }
    func post<R: Decodable>(_ chemin: String, corps: (any Encodable)? = nil, delai: TimeInterval = 30) async throws -> R {
        let envoye: any Encodable = corps ?? CorpsVide()
        return try await requete(.post, chemin, corps: envoye, parametres: [], delai: delai)
    }
    func patch<R: Decodable>(_ chemin: String, corps: any Encodable, delai: TimeInterval = 20) async throws -> R {
        return try await requete(.patch, chemin, corps: corps, parametres: [], delai: delai)
    }
    func delete<R: Decodable>(_ chemin: String, parametres: [URLQueryItem] = [], delai: TimeInterval = 20) async throws -> R {
        return try await requete(.delete, chemin, corps: nil, parametres: parametres, delai: delai)
    }
}

/// Corps « {} » : FastAPI accepte un objet vide là où tous les champs ont une valeur par défaut.
struct CorpsVide: Codable, Sendable {}

/// Réponse dont on ignore le contenu (« {"ok": true} », « {"supprime": …} »).
struct ReponseIgnoree: Decodable, Sendable {
    init() {}
    init(from decoder: Decoder) throws {}
}

// MARK: - Voix (implémentée par ios-cœur)

enum EtatVoix: Equatable, Sendable {
    case inactive
    /// Écoute du mot d'activation « Dis-moi Iris », app au premier plan seulement.
    case veille
    /// Écoute d'une commande après le mot d'activation (ou après un appui).
    case commande
    /// Commande envoyée, en attente de la réponse du PC.
    case reflexion
    case parle
    /// Micro ou reconnaissance refusés, ou reconnaissance sur l'appareil indisponible pour la langue.
    case indisponible(raison: String)
}

@MainActor
protocol ServiceVoix: AnyObject {
    var etat: EtatVoix { get }
    /// Texte partiel de la reconnaissance en cours (affichage en direct).
    var partiel: String { get }

    /// Demande les autorisations micro + reconnaissance. Rend nil si accordées, sinon la raison.
    func demanderAutorisations() async -> String?

    /// Lit un texte. `langue` BCP 47 (« fr-CA », « en-US ») ; nil = langue d'IRIS.
    /// `debit` = multiplicateur (tts_rate / 185) ; nil = réglage de l'utilisateur.
    /// Se termine quand la phrase est finie ou interrompue.
    func parler(_ texte: String, langue: String?, debit: Double?) async
    func arreterParole()

    /// Écoute UNE phrase dans la langue donnée (reconnaissance sur l'appareil exigée) et rend le
    /// texte final. Lève si le micro est indisponible ou si rien n'est entendu avant `delaiMax`.
    func ecouterUnePhrase(langue: String, delaiMax: TimeInterval) async throws -> String

    /// Mot d'activation au premier plan. Suspendu pendant `ecouterUnePhrase` et pendant la parole.
    func demarrerMotActivation()
    func arreterMotActivation()
}

extension ServiceVoix {
    func parler(_ texte: String) async { await parler(texte, langue: nil, debit: nil) }
}

// MARK: - Lunettes (implémentées par ios-perception)

struct AppareilLunettes: Identifiable, Hashable, Sendable {
    /// Identifiant CoreBluetooth (CBPeripheral.identifier.uuidString).
    let id: String
    let nom: String
    let rssi: Int?
}

struct EtatLunettes: Equatable, Sendable {
    var connectees: Bool = false
    var nom: String? = nil
    /// Identifiant stable envoyé au PC dans l'attestation (le PC refuse 403 d'autres lunettes).
    var identifiant: String? = nil
    var batterie: Int? = nil
    /// Phrase à afficher (« Bluetooth éteint », « recherche… ») ; nil si rien à dire.
    var message: String? = nil
    /// La caméra des lunettes est-elle prouvée utilisable sur ce matériel ? Faux tant que la trame
    /// n'est pas confirmée : la vision prend alors la photo avec le téléphone, et le DIT.
    var cameraConfirmee: Bool = false
}

/// Image prête à envoyer au PC.
struct ImageCapturee: Sendable {
    let donnees: Data
    let typeMedia: String   // « image/jpeg »
    /// D'où vient réellement la photo, à dire à l'utilisateur.
    let provenance: ProvenanceImage

    var pourEnvoi: ImageEnvoyee { ImageEnvoyee(mediaType: typeMedia, data: donnees.base64EncodedString()) }
}

enum ProvenanceImage: String, Codable, Sendable {
    case lunettes, telephone, bibliotheque
}

@MainActor
protocol ServiceLunettes: AnyObject {
    var etat: EtatLunettes { get }
    var appareilsTrouves: [AppareilLunettes] { get }
    /// Appelé à chaque changement d'état (connexion, déconnexion, batterie). RÉSERVÉ à ios-cœur :
    /// l'attestation auprès du PC (Pont/AttestationLunettes.swift) s'y branche ; un écran qui veut
    /// suivre l'état lit `etat` (classe @Observable) au lieu de remplacer ce rappel.
    var surChangement: (@MainActor (EtatLunettes) -> Void)? { get set }

    func rechercher()
    func arreterRecherche()
    func connecter(_ appareil: AppareilLunettes) async throws
    func deconnecter()
    /// Photo par la caméra des lunettes. Lève une erreur au message exact tant que le protocole
    /// n'est pas confirmé sur le vrai matériel.
    func prendrePhoto() async throws -> ImageCapturee
}

// MARK: - Vision d'accessibilité (implémentée par ios-perception) — interface A

struct ModeVision: Codable, Identifiable, Hashable, Sendable {
    let id: String
    let nom: String
    let description: String?
    let local: Bool?
    let limite: String?
    let phrases: [String]?
}

struct ReponseModesVision: Codable, Sendable {
    let modes: [ModeVision]
}

struct ImageEnvoyee: Codable, Hashable, Sendable {
    let mediaType: String
    let data: String
}

/// POST /api/accessibilite/decrire. DEHORS, envoyer parler=false et lire la réponse sur
/// l'iPhone : parler=true fait parler le haut-parleur du PC resté à la maison.
struct DemandeDescription: Encodable, Sendable {
    let mode: String
    let source: String          // "lunettes" | "ecran" | "image"
    let image: ImageEnvoyee?
    let question: String?
    let parler: Bool
    let memoriser: Bool
}

struct ResultatVision: Codable, Sendable {
    let ok: Bool?
    let mode: String
    let source: String
    let texte: String
    let chemin: String?
    let dureeMs: Int?
    let local: Bool?
    let note: String?
    let memoireSuspendue: String?
}

struct SouvenirTrouve: Codable, Identifiable, Hashable, Sendable {
    let id: String
    let texte: String
    let date: String?
}

struct ReponseOuEst: Codable, Sendable {
    let reponse: String
    let souvenirs: [SouvenirTrouve]?
    let local: Bool?
    let note: String?
}

enum SourceVision: Sendable {
    /// Caméra des lunettes (409 honnête tant qu'elle n'est pas confirmée).
    case lunettes
    /// Caméra du téléphone, en secours, dit clairement.
    case telephone
    /// Écran du PC.
    case ecranPC
    case image(ImageCapturee)
}

@MainActor
protocol ServiceVision: AnyObject {
    func modes() async throws -> [ModeVision]
    /// Prend l'image selon la source, appelle /api/accessibilite/decrire (parler=false) et lit la
    /// réponse avec ServiceVoix si `lireAVoixHaute`.
    func decrire(mode: String, source: SourceVision, question: String?, lireAVoixHaute: Bool) async throws -> ResultatVision
    func ouEst(_ question: String) async throws -> ReponseOuEst
}

// MARK: - Alertes sonores (implémentées par ios-perception)

/// Forme de l'événement alerte.sonore du PC (« genre », jamais « type »), réutilisée pour les
/// alertes détectées sur le téléphone.
struct AlerteSonore: Codable, Identifiable, Hashable, Sendable {
    var id: String { "\(genre)-\(ts ?? 0)" }
    let genre: String
    let libelle: String
    let confiance: Double?
    let ts: Double?
    let test: Bool?
}

struct TypeAlerte: Codable, Identifiable, Hashable, Sendable {
    let id: String
    let libelle: String
    let actif: Bool?
}

@MainActor
protocol ServiceAlertes: AnyObject {
    var actives: Bool { get }
    var types: [TypeAlerte] { get }
    var dernieres: [AlerteSonore] { get }
    /// Limite réelle à afficher (précision, latence, app au premier plan…).
    var limite: String { get }
    var surAlerte: (@MainActor (AlerteSonore) -> Void)? { get set }
    func activer(types: [String]) async throws
    func desactiver()
}

// MARK: - Guidage (implémenté par ios-perception)

struct PositionTelephone: Codable, Hashable, Sendable {
    let lat: Double
    let lon: Double
    let precisionM: Double?
}

struct EtapeGuidage: Codable, Hashable, Sendable {
    let texte: String
    let distanceM: Double?
}

@MainActor
protocol ServiceGuidage: AnyObject {
    /// Phrase de limite à afficher (précision GPS, réseau requis, mention OpenStreetMap…).
    var limite: String { get }
    var guidageActif: Bool { get }
    var etapes: [EtapeGuidage] { get }
    func positionActuelle() async throws -> PositionTelephone
    /// « Où suis-je ? » : une phrase, honnête sur la précision.
    func ouSuisJe() async throws -> String
    func guider(vers destination: String) async throws
    func arreterGuidage()
}

// MARK: - Fabrique de la perception (écrite par ios-perception, trouvée à l'exécution)

@MainActor
protocol ServicesPerception: AnyObject {
    var lunettes: any ServiceLunettes { get }
    var vision: any ServiceVision { get }
    var alertes: any ServiceAlertes { get }
    var guidage: any ServiceGuidage { get }
    /// Contenu de l'onglet Accessibilité (Ecrans/Accessibilite/).
    func ecranAccessibilite() -> AnyView
    /// Écran d'appairage des lunettes (« Connecter mes lunettes »).
    func ecranLunettes() -> AnyView
}

/// L'équipe ios-perception écrit :
///   @objc(IRISFabriquePerception) final class FabriquePerceptionIRIS: NSObject, FabriquePerception { … }
/// L'app la cherche par NSClassFromString(NOM_FABRIQUE_PERCEPTION). Absente = l'app démarre quand
/// même, l'onglet Accessibilité dit que le module n'est pas inclus dans cette version.
let NOM_FABRIQUE_PERCEPTION = "IRISFabriquePerception"

protocol FabriquePerception: AnyObject {
    @MainActor static func creer(pont: any ServicePontPC, voix: any ServiceVoix) -> any ServicesPerception
}

// MARK: - Compte, statut, présence des lunettes

struct EtatCompte: Codable, Sendable {
    let configure: Bool
    let nom: String?
}

struct ReponseConnexion: Codable, Sendable {
    let session: String
    let nom: String?
}

struct DemandeConnexion: Encodable, Sendable {
    let motDePasse: String
}

/// GET /api/lunettes/presence
struct PresenceLunettes: Codable, Sendable {
    let presentes: Bool
    let source: String?
    let verrouActif: Bool?
    let nom: String?
    let attestationAgeS: Double?
    let apercuRestant: Int?
    let apercuTotal: Int?
    let acheterUrl: String?
    let limite: String?
}

/// POST /api/lunettes/attestation
struct DemandeAttestation: Encodable, Sendable {
    let nom: String
    let identifiant: String
    let batterie: Int?
    let source: String   // "iphone"
}

// MARK: - Conversation avec IRIS (chat)

struct Conversation: Codable, Identifiable, Sendable {
    let id: String
    let title: String?
    let messages: [MessageChat]?
}

struct MessageChat: Codable, Identifiable, Hashable, Sendable {
    let id: String
    let conversationId: String?
    let role: String            // "user" | "assistant"
    let text: String?
    let createdAt: String?
    let meta: MetaMessageHashable?
}

/// Sous-ensemble hachable de meta (le reste — usage, outils, réflexion — n'est pas affiché).
struct MetaMessageHashable: Codable, Hashable, Sendable {
    let error: String?
    let source: String?
}

struct NouvelleConversation: Encodable, Sendable {
    let title: String
    let agent: String
}

struct EnvoiMessage: Encodable, Sendable {
    let text: String
    let agent: String
    let images: [ImageEnvoyee]
}

struct ReponseEnvoiMessage: Codable, Sendable {
    let accepted: Bool?
    let conversationId: String?
}

struct ReponseConfirmation: Encodable, Sendable {
    let confirmId: String
    let approved: Bool
}

// MARK: - C. Cours

/// Ligne de transcription d'un cours : « ts » est un nombre de secondes (cours.transcription).
struct LigneTranscription: Codable, Hashable, Sendable {
    let ts: Double?
    let texte: String
}

struct CoursResume: Codable, Identifiable, Hashable, Sendable {
    let id: String
    let titre: String
    let matiere: String?
    let debut: Horodatage?
    let fin: Horodatage?
    let dureeS: Double?
    let lignes: Int?
    let fiches: Bool?
    let questions: Bool?
    let audio: String?
    let actif: Bool?
    /// "direct" | "import"
    let source: String?
    /// "termine", "transcription" (import en cours)…
    let etat: String?
    let progression: Double?
    let erreur: String?
}

struct ListeCours: Codable, Sendable {
    let cours: [CoursResume]
}

struct QuestionCours: Codable, Hashable, Sendable {
    let question: String?
    let reponse: String?
    let type: String?
    let difficulte: Int?
}

struct CoursDetail: Codable, Identifiable, Sendable {
    let id: String
    let titre: String
    let matiere: String?
    let debut: Horodatage?
    let fin: Horodatage?
    let dureeS: Double?
    let transcription: [LigneTranscription]?
    let fiches: String?
    let questions: [QuestionCours]?
    let audio: String?
    let actif: Bool?
    let etat: String?
    let progression: Double?
    let erreur: String?
    let note: String?
}

// MARK: - F. Interprète

struct LangueInterprete: Codable, Identifiable, Hashable, Sendable {
    var id: String { code }
    let code: String      // « en », « es », « pt », « it », « de » (NOMS_LANGUES de traduction.py)
    let nom: String
    /// Voix disponible sur le PC (pas sur l'iPhone : l'app vérifie AVSpeechSynthesisVoice elle-même).
    let voix: Bool?
}

struct TourInterprete: Codable, Hashable, Sendable {
    let ts: Double?
    let qui: String            // "moi" | "autre"
    let original: String
    let traduction: String
    let latenceMs: Int?
}

struct EtatInterprete: Codable, Sendable {
    let actif: Bool
    let langueMoi: String?
    let langueAutre: String?
    let langueAutreNom: String?
    let sortieAutre: String?
    let tours: [TourInterprete]?
    let langues: [LangueInterprete]?
    let empechement: String?
    let empechementBloquant: Bool?
    let avertissements: [String]?
    let latenceMoyenneMs: Int?
    let phrase: String?
}

/// POST /api/interprete/texte. « langue » = langue de L'AUTRE personne, quel que soit « qui ».
/// DEHORS, ne JAMAIS appeler /api/interprete/demarrer (micro du PC à la maison).
struct DemandeTraduction: Encodable, Sendable {
    let qui: String
    let texte: String
    let langue: String?
}

struct ReponseTraduction: Codable, Sendable {
    let traduction: String
    let langueSource: String?
    let langueCible: String?
    let latenceMs: Int?
    let avertissement: String?
    let doute: Bool?
    let local: Bool?
}

// MARK: - G. Quotidien

struct SectionsResume: Codable, Sendable {
    let fait: [String]?
    let reste: [String]?
    let rappels: [String]?
    let aRetenir: [String]?
}

struct ResumeJour: Codable, Sendable {
    let date: String
    let texte: String
    let sections: SectionsResume?
    let local: Bool?
    let note: String?
}

struct RappelContexte: Codable, Identifiable, Hashable, Sendable {
    let id: String
    let personne: String
    let texte: String
    let creeLe: Horodatage?
    let declencheLe: Horodatage?
    let declencheur: String?
}

struct ListeRappelsContexte: Codable, Sendable {
    let rappels: [RappelContexte]
}

struct LigneRecu: Codable, Hashable, Sendable {
    let libelle: String
    let montant: Double?
}

struct Recu: Codable, Identifiable, Sendable {
    /// nil quand la mémoire est suspendue (reçu analysé mais non enregistré).
    let id: String?
    let date: String?
    let commercant: String?
    let sousTotal: Double?
    let tps: Double?
    let tvq: Double?
    let tvh: Double?
    let total: Double?
    let devise: String?
    let creeLe: String?
    let categorie: String?
    let moyenPaiement: String?
    let lignes: [LigneRecu]?
    let confiance: Double?
    let imageNom: String?
    let local: Bool?
    let enregistre: Bool?
    let note: String?
}

// MARK: - H. Assistants

struct EtapePasAPas: Codable, Hashable, Sendable {
    let n: Int
    let texte: String
    let minuteurS: Int?
}

struct SessionPasAPas: Codable, Sendable {
    let id: String?
    let sujet: String?
    let type: String?
    let etapes: [EtapePasAPas]?
    let index: Int?
    let actif: Bool
    let limite: String?
    let phrase: String?
}

/// GET /api/entrainement/etat : sans séance, seulement {actif: false, limite}.
struct SeanceEntrainement: Codable, Sendable {
    let id: String?
    let exercice: String?
    let series: Int?
    let seriesCibles: Int?
    let reposS: Int?
    let reposRestantS: Double?
    let debut: Horodatage?
    let actif: Bool
    let enPause: Bool?
    let dureeS: Double?
    let limite: String?
    let memoireSuspendue: String?
    let phrase: String?
}

struct ProduitVu: Codable, Sendable {
    let nom: String?
    let marque: String?
    let format: String?
    let codeBarres: String?
    let prixVu: String?
}

struct OffrePrix: Codable, Hashable, Sendable {
    let marchand: String?
    let prix: Double?
    let devise: String?
    let url: String?
    let extrait: String?
}

struct ComparaisonPrix: Codable, Sendable {
    let produit: ProduitVu?
    let offres: [OffrePrix]?
    let resume: String?
    let avertissement: String?
    let local: Bool?
    let phrase: String?
}

// MARK: - I. Confiance

struct EtatEmpreinteVocale: Codable, Sendable {
    let enregistree: Bool
    let echantillons: Int?
    let actif: Bool?
    let seuil: Int?
    let consentementBiometrique: Bool?
    let limite: String?
    let texteConsentement: String?
    let noteLegale: String?
}

struct ZoneSansMemoire: Codable, Identifiable, Hashable, Sendable {
    let id: String
    let nom: String
    let lat: Double
    let lon: Double
    let rayonM: Double
}

struct ZoneActive: Codable, Hashable, Sendable {
    let id: String?
    let nom: String?
}

struct ReponseZones: Codable, Sendable {
    let zones: [ZoneSansMemoire]
    let zoneActive: ZoneActive?
    let limite: String?
}

struct NouvelleZone: Encodable, Sendable {
    let nom: String
    let lat: Double
    let lon: Double
    let rayonM: Double
}

/// POST /api/confiance/zone : le téléphone évalue sa position lui-même et n'envoie QUE l'identifiant.
struct SignalZone: Encodable, Sendable {
    let zoneId: String?
    let source: String   // "telephone"
}

struct EtatInvite: Codable, Sendable {
    let actif: Bool
    let depuis: Horodatage?
    let jusqua: Horodatage?
    let minutesRestantes: Int?
    let phrase: String?
    let limite: String?
}

struct DemandeInvite: Encodable, Sendable {
    let minutes: Int?
}

struct EtatVerrou: Codable, Sendable {
    let verrouille: Bool
    let depuis: Horodatage?
    let raison: String?
    let actifDistance: Bool?
    let codeDefini: Bool?
    let motDePasseDefini: Bool?
    let limite: String?
}

struct DemandeDeverrouillage: Encodable, Sendable {
    let motDePasse: String
}

// MARK: - J. Vision partagée

struct DemandePartage: Encodable, Sendable {
    let source: String          // "lunettes" | "ecran" | "telephone"
    let intervalleS: Double?
}

struct ReponsePartage: Codable, Sendable {
    let code: String?
    let urlSpectateur: String?
    let expireA: Horodatage?
    let source: String?
    let jetonEmetteur: String?
    let wsEmetteur: String?
}

struct EtatPartage: Codable, Sendable {
    let actif: Bool
    let code: String?
    let urlSpectateur: String?
    let source: String?
    let spectateurs: Int?
    let imagesEnvoyees: Int?
    let fpsReel: Double?
    let expireA: Horodatage?
    let expireDansS: Int?
    let raison: String?
    let note: String?
    let limites: [String]?
}

// MARK: - Réglages utiles au téléphone (sous-ensemble de GET /api/settings)

struct ReglagesIRIS: Codable, Sendable {
    let userName: String?
    let assistantName: String?
    let wakeWord: String?
    let retentionDays: Int?
    let language: String?
    let ttsRate: Int?
    let verbosite: String?
    let interfaceGrandTexte: Bool?
    let privacyMode: Bool?
    let localOnly: Bool?
    let interpreteLangue: String?
    let modeInviteMinutes: Int?
}

/// PATCH /api/settings : seuls les champs non nuls partent (FastAPI n'applique que ceux-là).
struct PatchReglages: Encodable, Sendable {
    var ttsRate: Int? = nil
    var verbosite: String? = nil
    var interfaceGrandTexte: Bool? = nil
}
