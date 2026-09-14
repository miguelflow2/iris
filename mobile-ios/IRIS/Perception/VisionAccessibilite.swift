// VisionAccessibilite.swift — « Qu'est-ce qu'il y a devant moi ? », « Lis-moi ça », billets, objet,
// couleur, personnes, affichage : l'interface A du service IRIS, vue depuis l'iPhone.
//
// Le chemin réel, mode par mode :
// - lecture, affichage, couleur : l'iPhone lit ou estime SEUL d'abord (rien ne part). Si l'iPhone ne lit
//   rien et que l'ordinateur répond, la photo part à l'ordinateur ; un bouton permet aussi de demander
//   explicitement une lecture plus fine à IRIS ;
// - scène, objet, billets, personnes : ces descriptions exigent le moteur VELA, donc l'ordinateur
//   (POST /api/accessibilite/decrire, source « image », parler=false : dehors, le haut-parleur du PC
//   resté à la maison ne doit pas parler). Si l'ordinateur ne répond pas, refuse l'envoi (consentement,
//   mode 100 % local) ou tombe en panne, un REPLI LOCAL limité est rendu, et la note le dit en clair ;
// - écran : décrit l'écran de l'ordinateur, qui fait tout.
//
// L'image : caméra des lunettes quand sa commande est confirmée sur le vrai matériel ; sinon caméra de
// l'iPhone, EN SECOURS, et c'est dit (« la caméra des lunettes arrive… »). Rien n'est enregistré sur
// l'iPhone : la photo reste en mémoire vive le temps de l'écran.

import CoreGraphics
import Foundation
import Observation
import UIKit

enum StrategieVision {
    /// Local d'abord pour lecture, affichage et couleur ; ordinateur d'abord pour le reste, avec repli local.
    case auto
    /// Demande explicite à IRIS sur l'ordinateur (pas de repli silencieux : l'erreur est montrée).
    case ordinateur
}

/// Un mode tel que l'iPhone le propose (titres identiques à ceux de l'ordinateur, limites propres à l'iPhone).
struct ModeVisionTelephone: Identifiable, Hashable {
    let id: String
    let titre: String
    /// Titre court pour la barre de navigation.
    let court: String
    let icone: String
    let bouton: String
    let consigne: String
    let localDabord: Bool
    let limite: String

    static let tous: [ModeVisionTelephone] = [
        ModeVisionTelephone(id: "scene", titre: "Qu'est-ce qu'il y a devant moi ?", court: "Devant moi", icone: "eye",
                            bouton: "Photographier et décrire",
                            consigne: "Tiens l'iPhone à hauteur de poitrine, caméra vers l'avant, puis touche le bouton.",
                            localDabord: false,
                            limite: "Décrit une photo prise il y a quelques secondes : ce n'est ni une surveillance en direct ni une alerte d'obstacle. La description complète exige ton ordinateur ; sans lui, seulement des catégories générales."),
        ModeVisionTelephone(id: "lecture", titre: "Lis-moi ça", court: "Lire", icone: "text.viewfinder",
                            bouton: "Photographier et lire",
                            consigne: "Tiens le texte à 20 ou 30 cm de la caméra, bien éclairé, puis touche le bouton.",
                            localDabord: true,
                            limite: "Lu sur cet iPhone d'abord, sans envoi. Les colonnes côte à côte peuvent se mêler et l'écriture à la main est mal lue."),
        ModeVisionTelephone(id: "billets", titre: "C'est quel billet ?", court: "Billets", icone: "banknote",
                            bouton: "Photographier les billets",
                            consigne: "Pose les billets à plat, un à un ou étalés sans se chevaucher, puis touche le bouton.",
                            localDabord: false,
                            limite: "Reconnaissance complète (billets et pièces, total) par ton ordinateur. Un billet plié ou mal éclairé peut être mal lu : vérifie un montant important. Sans l'ordinateur, estimation d'après les chiffres imprimés seulement."),
        ModeVisionTelephone(id: "objet", titre: "C'est quoi cet objet ?", court: "Objet", icone: "shippingbox",
                            bouton: "Photographier l'objet",
                            consigne: "Tiens l'objet à 30 cm, étiquette vers la caméra, puis touche le bouton.",
                            localDabord: false,
                            limite: "Un produit peu connu ou mal cadré peut être mal reconnu. La marque et le produit exact exigent ton ordinateur ; sur l'iPhone seul : code-barres, texte visible et catégories générales."),
        ModeVisionTelephone(id: "couleur", titre: "C'est quelle couleur ?", court: "Couleur", icone: "paintpalette",
                            bouton: "Photographier la couleur",
                            consigne: "Remplis le centre de l'image avec la couleur à identifier, puis touche le bouton.",
                            localDabord: true,
                            limite: "Estimée sur cet iPhone, au centre de l'image seulement. L'éclairage peut fausser la couleur ; les motifs se décrivent avec ton ordinateur."),
        ModeVisionTelephone(id: "personnes", titre: "Qui est devant moi ?", court: "Personnes", icone: "person.2",
                            bouton: "Photographier et décrire",
                            consigne: "Tiens l'iPhone vers les personnes, puis touche le bouton.",
                            localDabord: false,
                            limite: "IRIS ne reconnaît personne et ne présume ni l'âge, ni l'origine, ni l'état de santé. Expression, vêtements et gestes exigent ton ordinateur ; sur l'iPhone seul, un nombre et une position."),
        ModeVisionTelephone(id: "affichage", titre: "C'est quel bus ?", court: "Affichage", icone: "bus",
                            bouton: "Photographier l'affichage",
                            consigne: "Vise le numéro du bus, le panneau ou l'écran d'attente, puis touche le bouton.",
                            localDabord: true,
                            limite: "Lu sur cet iPhone d'abord : texte brut, du plus grand au plus petit. Un affichage lointain ou lumineux peut être illisible ; IRIS le dit plutôt que de deviner."),
        ModeVisionTelephone(id: "ecran", titre: "Décris l'écran de mon ordinateur", court: "Écran de l'ordinateur", icone: "desktopcomputer",
                            bouton: "Décrire l'écran",
                            consigne: "Ton ordinateur capture son propre écran et le décrit.",
                            localDabord: false,
                            limite: "C'est l'écran de ton ordinateur, pas celui de l'iPhone (iOS ne laisse aucune app lire l'écran des autres). Il doit répondre."),
    ]

    static func pour(_ id: String) -> ModeVisionTelephone? {
        tous.first { $0.id == id }
    }
}

/// Résultat complet pour l'écran : la réponse du contrat, plus d'où vient l'image et la photo gardée en
/// mémoire vive (pour « Demander à IRIS » sans reprendre de photo).
struct AnalyseVision {
    let resultat: ResultatVision
    let provenance: ProvenanceImage?
    let image: ImageCapturee?
    let parOrdinateur: Bool
    /// « La caméra des lunettes arrive ; en attendant… » quand la photo vient de l'iPhone.
    let noteSecours: String?
    /// Durée totale mesurée sur l'iPhone, photo comprise.
    let dureeTotaleMs: Int
}

private struct DemandeOuEst: Encodable {
    let question: String
}

@MainActor
@Observable
final class VisionAccessibilite: ServiceVision {
    private(set) var enCours = false
    /// Étape affichée pendant l'analyse (« Photo… », « Envoi à ton ordinateur… »).
    private(set) var etape: String?

    static let noteSecoursCamera = "La caméra des lunettes arrive ; en attendant, la photo est prise avec ton iPhone."

    @ObservationIgnored private let pont: any ServicePontPC
    @ObservationIgnored private let voix: any ServiceVoix
    @ObservationIgnored private let lunettes: LunettesBLE
    @ObservationIgnored private let camera: CameraTelephone
    @ObservationIgnored private let garde: GardeCapture
    @ObservationIgnored private var modesOrdinateur: [ModeVision]?

    init(pont: any ServicePontPC, voix: any ServiceVoix, lunettes: LunettesBLE, camera: CameraTelephone, garde: GardeCapture) {
        self.pont = pont
        self.voix = voix
        self.lunettes = lunettes
        self.camera = camera
        self.garde = garde
    }

    // MARK: - Contrat ServiceVision

    func modes() async throws -> [ModeVision] {
        if garde.ordinateurJoignable {
            if let modesOrdinateur { return modesOrdinateur }
            if let reponse: ReponseModesVision = try? await pont.get("/api/accessibilite/modes", delai: 15) {
                modesOrdinateur = reponse.modes
                return reponse.modes
            }
        }
        return ModeVisionTelephone.tous.map {
            ModeVision(id: $0.id, nom: $0.titre, description: $0.consigne, local: $0.localDabord, limite: $0.limite, phrases: nil)
        }
    }

    func decrire(mode: String, source: SourceVision, question: String?, lireAVoixHaute: Bool) async throws -> ResultatVision {
        let analyse = try await analyser(mode: mode, source: source, question: question, strategie: .auto)
        if lireAVoixHaute {
            Task { await voix.parler(analyse.resultat.texte) }
        }
        return analyse.resultat
    }

    /// « Où ai-je posé… » : cherche dans les souvenirs réels de l'ordinateur (pas une capture : permis sans lunettes).
    func ouEst(_ question: String) async throws -> ReponseOuEst {
        try await pont.post("/api/accessibilite/ou-est", corps: DemandeOuEst(question: question), delai: 45)
    }

    // MARK: - Analyse

    func analyser(mode: String, source: SourceVision, question: String?, strategie: StrategieVision) async throws -> AnalyseVision {
        guard !enCours else {
            throw ErreurPont.refus(statut: 409, message: "Une description est déjà en cours.", detail: nil)
        }
        guard let config = ModeVisionTelephone.pour(mode) else {
            throw ErreurPont.refus(statut: 422, message: "Mode de description inconnu : « \(mode) ».", detail: nil)
        }
        if let refus = garde.refus(fonction: "vision_\(mode)") { throw refus }
        enCours = true
        defer {
            enCours = false
            etape = nil
        }
        let debut = Date()
        let questionPropre = question.map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }.flatMap { $0.isEmpty ? nil : $0 }

        if mode == "ecran" {
            etape = "Ton ordinateur capture son écran…"
            let r: ResultatVision = try await pont.post(
                "/api/accessibilite/decrire",
                corps: DemandeDescription(mode: mode, source: "ecran", image: nil, question: questionPropre, parler: false, memoriser: true),
                delai: 75)
            return AnalyseVision(resultat: r, provenance: nil, image: nil, parOrdinateur: true, noteSecours: nil,
                                 dureeTotaleMs: Self.ms(depuis: debut))
        }

        etape = "Photo…"
        let (image, secours) = try await obtenirImage(source)
        Haptique.tic()
        etape = "Analyse…"
        let donnees = image.donnees
        let normalisee = await Task.detached(priority: .userInitiated) {
            ImagesJPEG.normaliser(donnees, coteMax: 1600, qualite: 0.8)
        }.value
        guard let normalisee else {
            throw ErreurPont.refus(statut: 422, message: "Image illisible : format non reconnu.", detail: nil)
        }
        let imageCG = normalisee.0
        let envoi = ImageCapturee(donnees: normalisee.1, typeMedia: "image/jpeg", provenance: image.provenance)

        let ordinateurPossible = garde.ordinateurJoignable && !garde.localSeulement
        var noteRepli: String?
        if strategie == .auto && !ordinateurPossible {
            noteRepli = garde.localSeulement
                ? "Mode 100 % local actif : analyse faite sur cet iPhone seulement."
                : "Ton ordinateur ne répond pas : analyse faite sur cet iPhone seulement."
        }

        // 1) Sur l'iPhone d'abord (lecture, affichage, couleur), ou quand l'ordinateur est hors d'atteinte.
        if strategie == .auto && (config.localDabord || !ordinateurPossible) {
            etape = "Lecture sur l'iPhone…"
            let local = await Self.analyseLocale(mode: mode, image: imageCG)
            let rienLu = !local.utile && config.localDabord && ordinateurPossible
            if !rienLu {
                return fabriquerLocal(mode: mode, texte: local.texte, note: [noteRepli, local.note], image: envoi,
                                      secours: secours, debut: debut)
            }
        }

        // 2) L'ordinateur (moteur VELA).
        etape = "Envoi à ton ordinateur…"
        do {
            let r: ResultatVision = try await pont.post(
                "/api/accessibilite/decrire",
                corps: DemandeDescription(mode: mode, source: "image", image: envoi.pourEnvoi, question: questionPropre,
                                          parler: false, memoriser: true),
                delai: 75)
            return AnalyseVision(resultat: r, provenance: envoi.provenance, image: envoi, parOrdinateur: true,
                                 noteSecours: secours, dureeTotaleMs: Self.ms(depuis: debut))
        } catch {
            guard strategie == .auto, let raison = Self.raisonDeRepli(error) else { throw error }
            etape = "Analyse sur l'iPhone…"
            let local = await Self.analyseLocale(mode: mode, image: imageCG)
            return fabriquerLocal(mode: mode, texte: local.texte, note: [raison, local.note], image: envoi,
                                  secours: secours, debut: debut)
        }
    }

    private func fabriquerLocal(mode: String, texte: String, note: [String?], image: ImageCapturee,
                                secours: String?, debut: Date) -> AnalyseVision {
        let duree = Self.ms(depuis: debut)
        let noteJointe = note.compactMap { $0 }.joined(separator: " ")
        let resultat = ResultatVision(ok: true, mode: mode, source: "image", texte: texte, chemin: nil, dureeMs: duree,
                                      local: true, note: noteJointe.isEmpty ? nil : noteJointe, memoireSuspendue: nil)
        return AnalyseVision(resultat: resultat, provenance: image.provenance, image: image, parOrdinateur: false,
                             noteSecours: secours, dureeTotaleMs: duree)
    }

    /// Quand l'échec de l'ordinateur autorise un repli sur l'iPhone, la phrase qui le dit ; nil sinon.
    /// Jamais de repli qui contournerait une décision de l'utilisateur : mode confidentiel, verrou, lunettes.
    static func raisonDeRepli(_ erreur: Error) -> String? {
        guard let pont = erreur as? ErreurPont else {
            return "Ton ordinateur n'a pas pu répondre : analyse faite sur cet iPhone seulement."
        }
        switch pont {
        case .injoignable, .adresseAbsente:
            return "Ton ordinateur ne répond pas : analyse faite sur cet iPhone seulement."
        case .consentement(let refus):
            return (refus.message ?? "Tu n'as pas donné ton accord pour envoyer des images au moteur VELA.")
                + " Analyse faite sur cet iPhone seulement (l'accord se donne sur l'ordinateur, dans IRIS › Confidentialité)."
        case .refus(let statut, let message, _):
            if statut == 409 && message.localizedCaseInsensitiveContains("confidentiel") { return nil }
            if statut == 409 || statut >= 500 {
                return "\(message) Analyse faite sur cet iPhone seulement."
            }
            return nil
        case .decodage:
            return "Réponse de l'ordinateur illisible : analyse faite sur cet iPhone seulement."
        case .nonConnecte, .verrouillee, .lunettesRequises:
            return nil
        }
    }

    // MARK: - Image

    private func obtenirImage(_ source: SourceVision) async throws -> (ImageCapturee, String?) {
        switch source {
        case .image(let fournie):
            return (fournie, nil)
        case .telephone:
            return (try await photoTelephone(), nil)
        case .lunettes:
            if lunettes.etat.cameraConfirmee {
                do {
                    return (try await lunettes.prendrePhoto(), nil)
                } catch {
                    let photo = try await photoTelephone()
                    return (photo, "La photo des lunettes a échoué (\(error.localizedDescription)) : elle a été prise avec ton iPhone.")
                }
            }
            return (try await photoTelephone(), Self.noteSecoursCamera)
        case .ecranPC:
            throw ErreurPont.refus(statut: 422, message: "L'écran se décrit avec le mode « écran ».", detail: nil)
        }
    }

    private func photoTelephone() async throws -> ImageCapturee {
        guard UIApplication.shared.applicationState != .background else { throw ErreurCamera.arrierePlan }
        return try await camera.prendrePhoto()
    }

    private static func ms(depuis debut: Date) -> Int {
        Int(Date().timeIntervalSince(debut) * 1000)
    }

    // MARK: - Repli local, mode par mode

    struct ResultatLocal {
        let texte: String
        let utile: Bool
        let note: String
    }

    nonisolated static func analyseLocale(mode: String, image: CGImage) async -> ResultatLocal {
        await Task.detached(priority: .userInitiated) {
            VisionAccessibilite.analyseLocaleSynchrone(mode: mode, image: image)
        }.value
    }

    nonisolated static func analyseLocaleSynchrone(mode: String, image: CGImage) -> ResultatLocal {
        switch mode {
        case "lecture":
            let lignes = AnalyseImageLocale.lireTexte(image)
            guard !lignes.isEmpty else {
                return ResultatLocal(texte: "Je ne vois aucun texte lisible.", utile: false,
                                     note: "Lecture faite sur cet iPhone. Rapproche le texte, éclaire-le mieux ou tiens l'iPhone plus droit.")
            }
            return ResultatLocal(texte: lignes.map(\.texte).joined(separator: "\n"), utile: true,
                                 note: "Lu sur cet iPhone, sans envoi. Colonnes côte à côte et écriture à la main peuvent être mal lues.")

        case "affichage":
            let lignes = AnalyseImageLocale.lireTexte(image).sorted { $0.hauteur > $1.hauteur }
            guard let plusGrand = lignes.first else {
                return ResultatLocal(texte: "Je ne vois aucun texte lisible sur cet affichage.", utile: false,
                                     note: "Lecture faite sur cet iPhone. Un affichage lointain ou lumineux peut être illisible.")
            }
            var texte = "En plus gros : « \(plusGrand.texte) »."
            let autres = lignes.dropFirst().prefix(4).map { "« \($0.texte) »" }
            if !autres.isEmpty { texte += " Autre texte : \(autres.joined(separator: ", "))." }
            return ResultatLocal(texte: texte, utile: true,
                                 note: "Lu sur cet iPhone : texte brut, sans interprétation (direction, horaire). Vérifie avant de monter.")

        case "couleur":
            guard let c = AnalyseImageLocale.couleurs(image) else {
                return ResultatLocal(texte: "Je n'arrive pas à estimer la couleur de cette image.", utile: false,
                                     note: "Estimation faite sur cet iPhone.")
            }
            var texte = "Au centre de l'image : surtout \(c.principale) (environ \(NombresFr.pourcent(c.part)))"
            if let seconde = c.seconde {
                texte += ", avec du \(seconde) (environ \(NombresFr.pourcent(c.partSeconde)))"
            }
            texte += "."
            return ResultatLocal(texte: texte, utile: true,
                                 note: "Estimation faite sur cet iPhone, au centre de l'image seulement ; l'éclairage peut fausser la couleur.")

        case "objet":
            let codes = AnalyseImageLocale.codesBarres(image)
            let categories = AnalyseImageLocale.categories(image)
            let lignes = AnalyseImageLocale.lireTexte(image).sorted { $0.hauteur > $1.hauteur }
            var morceaux: [String] = []
            if !categories.traduites.isEmpty {
                morceaux.append("Ça ressemble à : \(categories.traduites.joined(separator: ", ")).")
            }
            if !codes.isEmpty {
                morceaux.append("Code-barres lu : \(codes.prefix(2).joined(separator: ", ")).")
            }
            if !lignes.isEmpty {
                morceaux.append("Texte visible : \(lignes.prefix(3).map { "« \($0.texte) »" }.joined(separator: ", ")).")
            }
            guard !morceaux.isEmpty else {
                return ResultatLocal(texte: "Je ne reconnais pas cet objet sans ton ordinateur.", utile: false,
                                     note: "Sur l'iPhone seul : catégories générales, code-barres et texte visible seulement.")
            }
            return ResultatLocal(texte: morceaux.joined(separator: " "), utile: true,
                                 note: "Estimation sur cet iPhone : sans ton ordinateur, IRIS ne nomme ni la marque ni le produit exact.")

        case "scene":
            let categories = AnalyseImageLocale.categories(image)
            let personnes = AnalyseImageLocale.personnes(image)
            let lignes = AnalyseImageLocale.lireTexte(image)
            var morceaux: [String] = []
            if !categories.traduites.isEmpty {
                morceaux.append("Catégories reconnues : \(categories.traduites.joined(separator: ", ")).")
            }
            if !personnes.isEmpty {
                morceaux.append(phrasePersonnes(personnes))
            }
            if !lignes.isEmpty {
                morceaux.append("Du texte est visible : \(lignes.prefix(2).map { "« \($0.texte) »" }.joined(separator: ", ")).")
            }
            if categories.nonTraduites > 0 && categories.traduites.isEmpty {
                morceaux.append("D'autres catégories ont été reconnues, mais IRIS ne sait pas encore les dire en français.")
            }
            guard !morceaux.isEmpty else {
                return ResultatLocal(texte: "Je ne peux pas décrire cette scène sans ton ordinateur.", utile: false,
                                     note: "Sur l'iPhone seul : catégories générales, personnes et texte visible seulement.")
            }
            return ResultatLocal(texte: morceaux.joined(separator: " "), utile: true,
                                 note: "Repli sur l'iPhone : ce n'est pas une description, seulement des catégories générales ; ni obstacles, ni distances.")

        case "personnes":
            let personnes = AnalyseImageLocale.personnes(image)
            let texte = personnes.isEmpty ? "Je ne détecte personne sur cette photo." : phrasePersonnes(personnes)
            return ResultatLocal(texte: texte, utile: true,
                                 note: "Compte fait sur cet iPhone : IRIS ne reconnaît personne ; sans ton ordinateur, ni expression, ni vêtements, ni gestes.")

        case "billets":
            let coupures = AnalyseImageLocale.coupuresLues(AnalyseImageLocale.lireTexte(image))
            let note = "Estimation d'après les chiffres et les mots imprimés lus sur cet iPhone : les pièces ne sont pas reconnues et un billet plié peut être mal lu. Vérifie un montant important."
            if coupures.count == 1, let seule = coupures.first {
                return ResultatLocal(texte: "Probablement un billet de \(seule.valeur) $ : j'ai lu \(seule.preuves.map { "« \($0) »" }.joined(separator: " et ")).",
                                     utile: true, note: note)
            }
            if coupures.count > 1 {
                let montants = coupures.map { "\($0.valeur) $" }.joined(separator: ", ")
                return ResultatLocal(texte: "J'ai lu les montants de plusieurs billets : \(montants). Je ne peux pas les compter sans ton ordinateur.",
                                     utile: true, note: note)
            }
            return ResultatLocal(texte: "Je ne peux pas reconnaître ce billet sans ton ordinateur. Retourne-le ou éclaire-le mieux.",
                                 utile: false, note: note)

        default:
            return ResultatLocal(texte: "Ce mode n'a pas d'analyse sur l'iPhone.", utile: false, note: "")
        }
    }

    nonisolated static func phrasePersonnes(_ personnes: [PersonneVue]) -> String {
        let n = personnes.count
        if n == 1, let seule = personnes.first {
            return "Je détecte une personne, \(AnalyseImageLocale.position(seule.centreX))."
        }
        if n <= 4 {
            let positions = personnes.map { "une \(AnalyseImageLocale.position($0.centreX))" }.joined(separator: ", ")
            return "Je détecte \(n) personnes : \(positions)."
        }
        return "Je détecte au moins \(n) personnes, réparties dans l'image."
    }
}
