// AnalyseImageLocale.swift — ce que l'iPhone sait lire et estimer SEUL dans une photo, sans rien envoyer.
//
// Cadre Vision d'Apple, sur l'appareil :
// - lecture de texte (VNRecognizeTextRequest, niveau précis, français et anglais du Canada si l'iPhone
//   les propose, sinon les variantes les plus proches) ;
// - codes-barres (VNDetectBarcodesRequest) ;
// - grandes catégories d'image (VNClassifyImageRequest), traduites en français pour les plus courantes ;
// - personnes présentes (VNDetectHumanRectanglesRequest et visages) : un NOMBRE et une POSITION, jamais
//   une identité, un âge, une origine ou un état de santé ;
// - couleur dominante au centre de l'image (histogramme par nom de couleur, pas une moyenne qui mélangerait
//   deux couleurs en une troisième).
//
// C'est un repli honnête, pas l'équivalent du moteur VELA : les phrases produites ici le disent.
// Tout est synchrone et lourd : à appeler hors du fil principal.

import CoreGraphics
import Foundation
import Vision

struct LigneLue: Hashable {
    let texte: String
    let hauteur: CGFloat
    let confiance: Float
    let centreX: CGFloat
    let centreY: CGFloat
}

struct PersonneVue: Hashable {
    let centreX: CGFloat
    let hauteur: CGFloat
}

enum AnalyseImageLocale {
    // MARK: - Texte

    /// Lignes lues, dans l'ordre de lecture (haut en bas, puis gauche à droite).
    static func lireTexte(_ image: CGImage) -> [LigneLue] {
        let requete = VNRecognizeTextRequest()
        requete.recognitionLevel = .accurate
        requete.usesLanguageCorrection = true
        requete.automaticallyDetectsLanguage = true
        requete.recognitionLanguages = languesTexte(requete)
        let gestionnaire = VNImageRequestHandler(cgImage: image, orientation: .up, options: [:])
        do {
            try gestionnaire.perform([requete])
        } catch {
            return []
        }
        let lignes = (requete.results ?? []).compactMap { observation -> LigneLue? in
            guard let meilleur = observation.topCandidates(1).first else { return nil }
            let texte = meilleur.string.trimmingCharacters(in: .whitespacesAndNewlines)
            guard !texte.isEmpty else { return nil }
            let boite = observation.boundingBox
            return LigneLue(texte: texte, hauteur: boite.height, confiance: meilleur.confidence,
                            centreX: boite.midX, centreY: boite.midY)
        }
        // Vision place l'origine en bas à gauche : on trie du haut vers le bas, par bandes.
        return lignes.sorted { a, b in
            if abs(a.centreY - b.centreY) > min(a.hauteur, b.hauteur) * 0.5 { return a.centreY > b.centreY }
            return a.centreX < b.centreX
        }
    }

    private static func languesTexte(_ requete: VNRecognizeTextRequest) -> [String] {
        let voulues = ["fr-CA", "en-CA", "fr-FR", "en-US"]
        guard let permises = try? requete.supportedRecognitionLanguages(), !permises.isEmpty else { return ["fr-FR", "en-US"] }
        var choix: [String] = []
        for langue in voulues where permises.contains(langue) && !choix.contains(langue) {
            choix.append(langue)
        }
        for prefixe in ["fr", "en"] where !choix.contains(where: { $0.hasPrefix(prefixe) }) {
            if let proche = permises.first(where: { $0.hasPrefix(prefixe) }) { choix.append(proche) }
        }
        return choix.isEmpty ? Array(permises.prefix(2)) : choix
    }

    // MARK: - Codes-barres

    static func codesBarres(_ image: CGImage) -> [String] {
        let requete = VNDetectBarcodesRequest()
        let gestionnaire = VNImageRequestHandler(cgImage: image, orientation: .up, options: [:])
        do {
            try gestionnaire.perform([requete])
        } catch {
            return []
        }
        var vus: [String] = []
        for observation in requete.results ?? [] {
            guard let valeur = observation.payloadStringValue, !valeur.isEmpty, !vus.contains(valeur) else { continue }
            vus.append(valeur)
        }
        return vus
    }

    // MARK: - Catégories

    /// Catégories traduites (confiance ≥ 0,35, cinq au plus) et nombre de catégories fortes non traduites.
    static func categories(_ image: CGImage) -> (traduites: [String], nonTraduites: Int) {
        let requete = VNClassifyImageRequest()
        let gestionnaire = VNImageRequestHandler(cgImage: image, orientation: .up, options: [:])
        do {
            try gestionnaire.perform([requete])
        } catch {
            return ([], 0)
        }
        var traduites: [String] = []
        var nonTraduites = 0
        for observation in (requete.results ?? []).filter({ $0.confidence >= 0.35 }).prefix(12) {
            if let francais = TraductionEtiquettes.francais[observation.identifier] {
                if !traduites.contains(francais) { traduites.append(francais) }
            } else {
                nonTraduites += 1
            }
            if traduites.count >= 5 { break }
        }
        return (traduites, nonTraduites)
    }

    // MARK: - Personnes

    static func personnes(_ image: CGImage) -> [PersonneVue] {
        let corps = VNDetectHumanRectanglesRequest()
        corps.upperBodyOnly = false
        let visages = VNDetectFaceRectanglesRequest()
        let gestionnaire = VNImageRequestHandler(cgImage: image, orientation: .up, options: [:])
        do {
            try gestionnaire.perform([corps, visages])
        } catch {
            return []
        }
        let parCorps = (corps.results ?? []).filter { $0.confidence >= 0.5 }
            .map { PersonneVue(centreX: $0.boundingBox.midX, hauteur: $0.boundingBox.height) }
        let parVisage = (visages.results ?? []).filter { $0.confidence >= 0.5 }
            .map { PersonneVue(centreX: $0.boundingBox.midX, hauteur: $0.boundingBox.height) }
        // Un gros plan montre un visage sans corps, une foule lointaine des corps sans visage : on garde
        // la détection la plus nombreuse plutôt que d'additionner (une personne compterait deux fois).
        return (parCorps.count >= parVisage.count ? parCorps : parVisage).sorted { $0.centreX < $1.centreX }
    }

    static func position(_ centreX: CGFloat) -> String {
        if centreX < 0.34 { return "à gauche" }
        if centreX > 0.66 { return "à droite" }
        return "au centre"
    }

    // MARK: - Couleur

    /// (nom de la couleur principale, part du centre, seconde couleur et sa part si elle compte).
    static func couleurs(_ image: CGImage) -> (principale: String, part: Double, seconde: String?, partSeconde: Double)? {
        let cote = 48
        let largeur = CGFloat(image.width), hauteur = CGFloat(image.height)
        guard largeur > 0, hauteur > 0 else { return nil }
        // Le centre (la moitié de la largeur et de la hauteur) : ce qu'on tend devant l'objectif.
        let zone = CGRect(x: largeur * 0.25, y: hauteur * 0.25, width: largeur * 0.5, height: hauteur * 0.5).integral
        guard let centre = image.cropping(to: zone) else { return nil }
        var pixels = [UInt8](repeating: 0, count: cote * cote * 4)
        let rempli: Bool = pixels.withUnsafeMutableBytes { tampon -> Bool in
            guard let contexte = CGContext(data: tampon.baseAddress, width: cote, height: cote, bitsPerComponent: 8,
                                           bytesPerRow: cote * 4, space: CGColorSpaceCreateDeviceRGB(),
                                           bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue) else { return false }
            contexte.interpolationQuality = .medium
            contexte.draw(centre, in: CGRect(x: 0, y: 0, width: cote, height: cote))
            return true
        }
        guard rempli else { return nil }
        var comptes: [String: Int] = [:]
        for i in stride(from: 0, to: pixels.count, by: 4) {
            let nom = nomCouleur(r: Double(pixels[i]) / 255, v: Double(pixels[i + 1]) / 255, b: Double(pixels[i + 2]) / 255)
            comptes[nom, default: 0] += 1
        }
        let total = Double(cote * cote)
        let tries = comptes.sorted { $0.value > $1.value }
        guard let premiere = tries.first else { return nil }
        let seconde = tries.dropFirst().first
        let partSeconde = Double(seconde?.value ?? 0) / total
        return (premiere.key, Double(premiere.value) / total, partSeconde >= 0.15 ? seconde?.key : nil, partSeconde)
    }

    /// Nom français d'une couleur (composantes 0…1), d'après teinte, saturation et luminosité.
    static func nomCouleur(r: Double, v: Double, b: Double) -> String {
        let maxi = max(r, v, b), mini = min(r, v, b)
        let luminosite = (maxi + mini) / 2
        let delta = maxi - mini
        let saturation = delta == 0 ? 0 : delta / (1 - abs(2 * luminosite - 1))
        if luminosite < 0.12 { return "noir" }
        if saturation < 0.15 {
            if luminosite > 0.88 { return "blanc" }
            if luminosite > 0.65 { return "gris clair" }
            if luminosite < 0.3 { return "gris foncé" }
            return "gris"
        }
        var teinte: Double
        if delta == 0 {
            teinte = 0
        } else if maxi == r {
            teinte = 60 * ((v - b) / delta).truncatingRemainder(dividingBy: 6)
        } else if maxi == v {
            teinte = 60 * ((b - r) / delta + 2)
        } else {
            teinte = 60 * ((r - v) / delta + 4)
        }
        if teinte < 0 { teinte += 360 }

        let base: String
        switch teinte {
        case 15..<45 where luminosite < 0.4:
            return "brun"
        case 20..<50 where saturation < 0.5 && luminosite > 0.7:
            return "beige"
        case 0..<15, 345..<360:
            // Un rouge très clair se dit « rose » en français courant.
            base = luminosite > 0.7 ? "rose" : "rouge"
        case 15..<40:
            base = "orange"
        case 40..<68:
            base = "jaune"
        case 68..<165:
            base = "vert"
        case 165..<195:
            base = "turquoise"
        case 195..<255:
            base = "bleu"
        case 255..<310:
            base = "violet"
        default:
            base = luminosite > 0.6 ? "rose" : "magenta"
        }
        if base == "rose" { return base }
        if luminosite < 0.3 { return "\(base) foncé" }
        if luminosite > 0.72 { return "\(base) clair" }
        return base
    }

    // MARK: - Billets canadiens (estimation d'après le texte imprimé)

    /// Coupures dont le CHIFFRE et le MOT (français ou anglais) sont tous deux lus sur l'image.
    static func coupuresLues(_ lignes: [LigneLue]) -> [(valeur: Int, preuves: [String])] {
        let texte = lignes.map(\.texte).joined(separator: " ")
        let plie = texte.folding(options: [.diacriticInsensitive, .caseInsensitive], locale: Locale(identifier: "fr_CA")).uppercased()
        let jetons = Set(plie.components(separatedBy: CharacterSet.alphanumerics.inverted).filter { !$0.isEmpty })
        let coupures: [(Int, [String])] = [
            (5, ["CINQ", "FIVE"]), (10, ["DIX", "TEN"]), (20, ["VINGT", "TWENTY"]),
            (50, ["CINQUANTE", "FIFTY"]), (100, ["CENT", "HUNDRED"]),
        ]
        var trouvees: [(valeur: Int, preuves: [String])] = []
        for (valeur, mots) in coupures {
            guard jetons.contains(String(valeur)) else { continue }
            let motsLus = mots.filter { jetons.contains($0) }
            guard !motsLus.isEmpty else { continue }
            trouvees.append((valeur, [String(valeur)] + motsLus))
        }
        return trouvees
    }
}
