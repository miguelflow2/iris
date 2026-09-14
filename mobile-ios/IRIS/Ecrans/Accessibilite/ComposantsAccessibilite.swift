// ComposantsAccessibilite.swift — morceaux d'interface communs aux écrans de l'onglet Accessibilité.
//
// Règles VoiceOver suivies partout : chaque bouton a un libellé parlé (les icônes seules sont décrites),
// les images décoratives sont cachées, une ligne de liste se lit d'un seul geste (éléments combinés), et
// les résultats importants prennent le focus quand ils arrivent.

import AVFoundation
import SwiftUI
import UIKit

/// Ligne d'accès à une fonction : icône, titre, précision (où se fait le travail).
struct LigneAccessibilite: View {
    let icone: String
    let titre: String
    let detail: String

    var body: some View {
        HStack(spacing: 14) {
            Image(systemName: icone)
                .font(.title3)
                .frame(width: 40, height: 40)
                .foregroundStyle(Couleurs.fond)
                .background(Couleurs.holoIcone, in: RoundedRectangle(cornerRadius: 11))
                .accessibilityHidden(true)
            VStack(alignment: .leading, spacing: 2) {
                Text(titre)
                    .font(.headline)
                    .foregroundStyle(Couleurs.texte)
                    .multilineTextAlignment(.leading)
                Text(detail)
                    .font(.subheadline)
                    .foregroundStyle(Couleurs.attenue)
                    .multilineTextAlignment(.leading)
            }
            Spacer(minLength: 0)
            Image(systemName: "chevron.right")
                .foregroundStyle(Couleurs.attenue)
                .accessibilityHidden(true)
        }
        .padding(.vertical, 6)
        .contentShape(Rectangle())
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(titre)
        .accessibilityHint(detail)
    }
}

/// Aperçu de la caméra arrière (pour les personnes qui voient, ou un proche qui aide à cadrer).
struct ApercuCamera: UIViewRepresentable {
    let camera: CameraTelephone

    func makeUIView(context: Context) -> VueApercu {
        let vue = VueApercu()
        vue.couche.session = camera.session
        vue.couche.videoGravity = .resizeAspectFill
        vue.backgroundColor = .black
        vue.isAccessibilityElement = true
        vue.accessibilityLabel = "Aperçu de la caméra de l'iPhone"
        vue.accessibilityTraits = .image
        return vue
    }

    func updateUIView(_ uiView: VueApercu, context: Context) {}

    final class VueApercu: UIView {
        override class var layerClass: AnyClass { AVCaptureVideoPreviewLayer.self }

        var couche: AVCaptureVideoPreviewLayer {
            // swiftlint:disable:next force_cast
            layer as! AVCaptureVideoPreviewLayer
        }

        override func layoutSubviews() {
            super.layoutSubviews()
            // L'app est en portrait : l'aperçu est tourné comme les images envoyées.
            if let connexion = couche.connection, connexion.isVideoRotationAngleSupported(90) {
                connexion.videoRotationAngle = 90
            }
        }
    }
}

/// Pastille « en cours » (alertes, guidage, partage) avec son action d'arrêt.
struct BandeauEnCours: View {
    let icone: String
    let texte: String
    let action: String
    let agir: () -> Void

    var body: some View {
        HStack(spacing: 10) {
            Image(systemName: icone)
                .foregroundStyle(Couleurs.vert)
                .accessibilityHidden(true)
            Text(texte)
                .font(.subheadline.weight(.semibold))
                .foregroundStyle(Couleurs.texte)
            Spacer(minLength: 8)
            Button(action, action: agir)
                .buttonStyle(.holo(.sombre, compact: true))
                .accessibilityLabel("\(action) : \(texte)")
        }
        .padding(12)
        .background(Couleurs.carte, in: RoundedRectangle(cornerRadius: 14, style: .continuous))
    }
}

/// Plein écran d'une alerte sonore : grand texte, fond rouge, un seul bouton.
struct AlertePleinEcran: View {
    let alerte: AlerteSonore
    let fermer: () -> Void
    @AccessibilityFocusState private var focus: Bool

    // Initialiseur explicite : les propriétés privées (@State, @Environment) rendraient l'initialiseur
    // implicite privé, donc inaccessible depuis les autres fichiers.
    init(alerte: AlerteSonore, fermer: @escaping () -> Void) {
        self.alerte = alerte
        self.fermer = fermer
    }

    var body: some View {
        VStack(spacing: 28) {
            Spacer()
            Image(systemName: "exclamationmark.triangle.fill")
                .font(.system(size: 88))
                .foregroundStyle(.white)
                .accessibilityHidden(true)
            Text(alerte.libelle)
                .font(.system(size: 44, weight: .heavy))
                .multilineTextAlignment(.center)
                .foregroundStyle(.white)
                .minimumScaleFactor(0.5)
                .accessibilityFocused($focus)
                .accessibilityLabel("Alerte sonore : \(alerte.libelle)")
            if let confiance = alerte.confiance {
                Text("Détecté par l'iPhone, confiance \(NombresFr.pourcent(confiance)). Vérifie autour de toi.")
                    .font(.title3)
                    .multilineTextAlignment(.center)
                    .foregroundStyle(.white.opacity(0.9))
            }
            Spacer()
            Button("J'ai compris", action: fermer)
                .buttonStyle(.holo(.blanc))
                .accessibilityHint("Ferme l'alerte.")
        }
        .padding(28)
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(Couleurs.rouge.ignoresSafeArea())
        .accessibilityAddTraits(.isModal)
        .onAppear {
            focus = true
        }
    }
}

enum TexteAccessibilite {
    /// Ce qui reste volontairement non livré : dit tel quel, ici comme dans la FAQ.
    static let nonLivre: [String] = [
        "Alerte d'obstacle en temps réel depuis les lunettes : elles n'envoient pas de vidéo en direct par Bluetooth ; il faudrait un traitement dans les lunettes elles-mêmes.",
        "Reconnaissance des personnes par leur nom : ce sont des données biométriques (consentement exprès et déclaration préalable à la Commission d'accès à l'information du Québec). Non livrée.",
        "Langue des signes : non prévue.",
        "Enregistrement vidéo, mise à jour du micrologiciel et effacement de la mémoire interne des lunettes : protocole non documenté par le fabricant.",
        "Caméra des lunettes : la commande photo n'est pas encore confirmée sur le vrai matériel. En attendant, les photos sont prises avec l'iPhone.",
        "« Ton prénom » dans les alertes sonores : détecté par l'ordinateur seulement, pas par l'iPhone.",
    ]

    static func distance(_ metres: Double?) -> String {
        guard let metres else { return "" }
        return NombresFr.distance(metres)
    }

    static func heure(_ secondes: Double?) -> String {
        guard let secondes else { return "" }
        let format = DateFormatter()
        format.locale = Locale(identifier: "fr_CA")
        format.dateFormat = "HH:mm:ss"
        return format.string(from: Date(timeIntervalSince1970: secondes))
    }

    static func octets(_ n: Int) -> String {
        let f = ByteCountFormatter()
        f.countStyle = .file
        return f.string(fromByteCount: Int64(n))
    }

    static func puce(_ texte: String) -> some View {
        HStack(alignment: .firstTextBaseline, spacing: 8) {
            Text("•").foregroundStyle(Couleurs.attenue).accessibilityHidden(true)
            Text(texte).foregroundStyle(Couleurs.texte2)
        }
        .accessibilityElement(children: .combine)
    }
}
