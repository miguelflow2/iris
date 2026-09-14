// OutilsPerception.swift — petits outils partagés par les services de perception : garde « lunettes
// d'abord » et mode confidentiel, annonces VoiceOver, écran gardé allumé, retour haptique, images JPEG.

import Foundation
import UIKit

// MARK: - Garde de capture

/// Toute fonction qui CAPTE (voir, écouter) passe par ici avant d'ouvrir la caméra ou le micro.
///
/// Deux règles, dans cet ordre : le mode confidentiel réglé sur l'ordinateur arrête tout ; les lunettes
/// VELA doivent être présentes (connectées à cet iPhone, ou vues par l'ordinateur). L'environnement de
/// l'app est lu À L'USAGE, jamais à la création : la fabrique de perception est appelée pendant que
/// l'environnement lui-même se construit.
@MainActor
final class GardeCapture {
    private let lunettes: LunettesBLE

    static let messageConfidentiel = "Le mode confidentiel est actif sur ton ordinateur : IRIS ne capte rien tant qu'il l'est."
    static let messageLunettes = "Cette fonction marche avec les lunettes VELA. Connecte tes lunettes pour l'utiliser."

    init(lunettes: LunettesBLE) {
        self.lunettes = lunettes
    }

    /// nil si la capture est permise ; sinon l'erreur à afficher telle quelle.
    func refus(fonction: String) -> ErreurPont? {
        let env = EnvironnementIRIS.partage
        if env.reglages?.privacyMode == true {
            return .refus(statut: 409, message: Self.messageConfidentiel, detail: nil)
        }
        if !(lunettes.etat.connectees || env.lunettesPresentes) {
            return .lunettesRequises(RefusLunettes(code: "lunettes_requises", fonction: fonction,
                                                   message: Self.messageLunettes,
                                                   acheterUrl: env.attestation.presence?.acheterUrl))
        }
        return nil
    }

    /// Mode 100 % local réglé sur l'ordinateur : aucune image ne doit partir vers le moteur.
    var localSeulement: Bool {
        EnvironnementIRIS.partage.reglages?.localOnly == true
    }

    var ordinateurJoignable: Bool {
        EnvironnementIRIS.partage.pont.etat.estConnecte
    }
}

// MARK: - Annonces

@MainActor
enum Annonce {
    /// Annonce VoiceOver mise en file (n'interrompt pas la phrase en cours). Rien si VoiceOver est éteint.
    static func voiceOver(_ texte: String) {
        guard UIAccessibility.isVoiceOverRunning, !texte.isEmpty else { return }
        let phrase = NSAttributedString(string: texte, attributes: [.accessibilitySpeechQueueAnnouncement: true])
        UIAccessibility.post(notification: .announcement, argument: phrase)
    }

    /// Un résultat à dire : par VoiceOver quand il tourne (l'utilisateur garde son débit et peut
    /// l'interrompre, et on évite deux voix en même temps), sinon par la voix d'IRIS dans les lunettes.
    static func resultat(_ texte: String, voix: any ServiceVoix) {
        if UIAccessibility.isVoiceOverRunning {
            voiceOver(texte)
        } else {
            Task { await voix.parler(texte) }
        }
    }

    /// Une alerte ou une consigne de trajet : TOUJOURS par la voix d'IRIS (l'écran peut être éteint ou
    /// l'iPhone dans une poche, où VoiceOver ne dit rien).
    static func urgent(_ texte: String, voix: any ServiceVoix) {
        Task { await voix.parler(texte) }
    }
}

// MARK: - Écran allumé

/// Plusieurs fonctions peuvent vouloir garder l'écran allumé (guidage, sous-titres, partage) : il ne
/// s'éteint à nouveau que quand la dernière a fini.
@MainActor
enum EveilEcran {
    private static var raisons: Set<String> = []

    static func activer(_ raison: String) {
        raisons.insert(raison)
        UIApplication.shared.isIdleTimerDisabled = true
    }

    static func desactiver(_ raison: String) {
        raisons.remove(raison)
        if raisons.isEmpty {
            UIApplication.shared.isIdleTimerDisabled = false
        }
    }
}

// MARK: - Retour haptique

@MainActor
enum Haptique {
    static func alerte() {
        let generateur = UINotificationFeedbackGenerator()
        generateur.prepare()
        generateur.notificationOccurred(.warning)
    }

    static func succes() {
        UINotificationFeedbackGenerator().notificationOccurred(.success)
    }

    static func tic() {
        UIImpactFeedbackGenerator(style: .light).impactOccurred()
    }
}

// MARK: - Images

enum ImagesJPEG {
    /// Redessine l'image à l'endroit (orientation EXIF appliquée), réduite à `coteMax` pixels sur son plus
    /// grand côté. Rend l'image prête pour Vision et un JPEG prêt à envoyer. Sûr hors du fil principal
    /// (UIGraphicsImageRenderer l'est).
    static func normaliser(_ donnees: Data, coteMax: CGFloat = 1600, qualite: CGFloat = 0.8) -> (CGImage, Data)? {
        guard let image = UIImage(data: donnees), image.size.width > 0, image.size.height > 0 else { return nil }
        let echelle = min(1, coteMax / max(image.size.width, image.size.height))
        let taille = CGSize(width: (image.size.width * echelle).rounded(), height: (image.size.height * echelle).rounded())
        let format = UIGraphicsImageRendererFormat()
        format.scale = 1
        format.opaque = true
        let rendu = UIGraphicsImageRenderer(size: taille, format: format).image { _ in
            image.draw(in: CGRect(origin: .zero, size: taille))
        }
        guard let cg = rendu.cgImage, let jpeg = rendu.jpegData(compressionQuality: qualite) else { return nil }
        return (cg, jpeg)
    }
}

// MARK: - Nombres dits en français

enum NombresFr {
    static func entier(_ n: Double) -> String {
        let f = NumberFormatter()
        f.locale = Locale(identifier: "fr_CA")
        f.maximumFractionDigits = 0
        return f.string(from: NSNumber(value: n.rounded())) ?? String(Int(n.rounded()))
    }

    static func decimal(_ n: Double, chiffres: Int = 1) -> String {
        let f = NumberFormatter()
        f.locale = Locale(identifier: "fr_CA")
        f.minimumFractionDigits = 0
        f.maximumFractionDigits = chiffres
        return f.string(from: NSNumber(value: n)) ?? String(format: "%.\(chiffres)f", n)
    }

    /// « 40 mètres », « 1,2 kilomètre », « 3,5 kilomètres ». Arrondi à 5 m sous 100 m, à 10 m au-delà :
    /// annoncer « 37 mètres » ferait croire à une précision que le GPS n'a pas.
    static func distance(_ metres: Double) -> String {
        let m = max(0, metres)
        if m < 1000 {
            let arrondi = m < 100 ? (m / 5).rounded() * 5 : (m / 10).rounded() * 10
            let valeur = max(5, arrondi)
            return "\(entier(valeur)) mètre\(valeur >= 2 ? "s" : "")"
        }
        let km = (m / 100).rounded() / 10
        return "\(decimal(km)) kilomètre\(km >= 2 ? "s" : "")"
    }

    /// « 11 minutes », « 1 h 05 ».
    static func duree(_ secondes: Double) -> String {
        let minutes = max(1, Int((secondes / 60).rounded()))
        if minutes < 60 { return "\(minutes) minute\(minutes >= 2 ? "s" : "")" }
        return "\(minutes / 60) h \(String(format: "%02d", minutes % 60))"
    }

    static func pourcent(_ fraction: Double) -> String {
        "\(entier(fraction * 100)) %"
    }
}
