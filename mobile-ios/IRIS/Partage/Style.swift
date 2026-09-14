// Style.swift — la charte visuelle des maquettes IRIS, portée en SwiftUI.
//
// Mêmes valeurs que renderer/src/styles.css (fond #1b1b1d, cartes #2c2c2e, bouton holographique
// en dégradé pastel). Les écrans de l'équipe perception peuvent s'en servir aussi.

import SwiftUI

enum Couleurs {
    static let fond = Color(rgb: 0x1B1B1D)
    static let fond2 = Color(rgb: 0x232325)
    static let carte = Color(rgb: 0x2C2C2E)
    static let carte2 = Color(rgb: 0x3A3A3C)
    static let carte3 = Color(rgb: 0x48484A)
    static let ligne = Color.white.opacity(0.08)
    static let ligne2 = Color.white.opacity(0.16)
    static let texte = Color.white
    static let texte2 = Color(rgb: 0xD1D1D6)
    static let attenue = Color(rgb: 0x8E8E93)
    static let bleu = Color(rgb: 0x0A84FF)
    static let rouge = Color(rgb: 0xFF3B30)
    static let vert = Color(rgb: 0x30D158)
    static let orange = Color(rgb: 0xFF9F0A)
    static let avertissement = Color(rgb: 0xFFD166)

    /// Le dégradé holographique des maquettes (rose → lavande → blanc → cyan → menthe), à 100°.
    static let holo = LinearGradient(
        stops: [
            .init(color: Color(rgb: 0xF8D2F6), location: 0.0),
            .init(color: Color(rgb: 0xEBE3FF), location: 0.22),
            .init(color: Color(rgb: 0xFFFFFF), location: 0.48),
            .init(color: Color(rgb: 0xD4F4FF), location: 0.74),
            .init(color: Color(rgb: 0xD7FFE8), location: 1.0),
        ],
        startPoint: UnitPoint(x: 0.0, y: 0.41),
        endPoint: UnitPoint(x: 1.0, y: 0.59)
    )

    static let holoIcone = LinearGradient(
        colors: [Color(rgb: 0xF7C0FF), Color(rgb: 0xC9C6FF), Color(rgb: 0x9AF0FF)],
        startPoint: .topLeading, endPoint: .bottomTrailing
    )
}

extension Color {
    init(rgb: UInt32, opacite: Double = 1) {
        self.init(
            .sRGB,
            red: Double((rgb >> 16) & 0xFF) / 255,
            green: Double((rgb >> 8) & 0xFF) / 255,
            blue: Double(rgb & 0xFF) / 255,
            opacity: opacite
        )
    }
}

// MARK: - Bouton holographique

enum VarianteHolo {
    case holo, blanc, sombre, bleu, rouge, contour
}

/// Le grand bouton des maquettes. `ButtonStyle` plutôt qu'une vue : il garde l'accessibilité d'un
/// vrai bouton (VoiceOver, taille dynamique, état désactivé).
struct StyleHolo: ButtonStyle {
    var variante: VarianteHolo = .holo
    var compact = false
    @Environment(\.isEnabled) private var actif

    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(compact ? Font.body.weight(.semibold) : Font.title3.weight(.bold))
            .lineLimit(3)
            .multilineTextAlignment(.center)
            .foregroundStyle(couleurTexte)
            .frame(maxWidth: compact ? nil : .infinity, minHeight: compact ? 44 : 54)
            .padding(.horizontal, 22)
            .background { fond }
            .overlay(
                Capsule().strokeBorder(variante == .contour ? Couleurs.ligne2 : Color.clear, lineWidth: 1.5)
            )
            .clipShape(Capsule())
            .shadow(color: variante == .holo ? Color.white.opacity(0.18) : Color.clear, radius: 14, y: 8)
            .scaleEffect(configuration.isPressed ? 0.985 : 1)
            .opacity(actif ? 1 : 0.45)
            .contentShape(Capsule())
    }

    private var couleurTexte: Color {
        switch variante {
        case .holo, .blanc: return Couleurs.fond
        default: return Couleurs.texte
        }
    }

    @ViewBuilder private var fond: some View {
        switch variante {
        case .holo: Couleurs.holo
        case .blanc: Color.white
        case .sombre: Couleurs.carte2
        case .bleu: Couleurs.bleu
        case .rouge: Couleurs.rouge
        case .contour: Color.clear
        }
    }
}

extension ButtonStyle where Self == StyleHolo {
    static var holo: StyleHolo { StyleHolo() }
    static func holo(_ variante: VarianteHolo, compact: Bool = false) -> StyleHolo {
        StyleHolo(variante: variante, compact: compact)
    }
}

// MARK: - Cartes et textes

struct Carte<Contenu: View>: View {
    var titre: String?
    @ViewBuilder var contenu: () -> Contenu

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            if let titre {
                Text(titre)
                    .font(.footnote.weight(.semibold))
                    .foregroundStyle(Couleurs.attenue)
                    .textCase(.uppercase)
                    .accessibilityAddTraits(.isHeader)
            }
            contenu()
        }
        .padding(16)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(Couleurs.carte, in: RoundedRectangle(cornerRadius: 16, style: .continuous))
    }
}

/// Phrase de vérité (limite, note, avertissement) : toujours visible, jamais cachée dans un « i ».
struct NoteVerite: View {
    let texte: String
    var genre: Genre = .limite

    enum Genre { case limite, avertissement, erreur, succes }

    var body: some View {
        HStack(alignment: .firstTextBaseline, spacing: 8) {
            Image(systemName: icone)
                .foregroundStyle(couleur)
                .accessibilityHidden(true)
            Text(texte)
                .font(.footnote)
                .foregroundStyle(genre == .limite ? Couleurs.texte2 : couleur)
                .fixedSize(horizontal: false, vertical: true)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .accessibilityElement(children: .combine)
    }

    private var icone: String {
        switch genre {
        case .limite: return "info.circle"
        case .avertissement: return "exclamationmark.triangle"
        case .erreur: return "xmark.octagon"
        case .succes: return "checkmark.circle"
        }
    }

    private var couleur: Color {
        switch genre {
        case .limite: return Couleurs.attenue
        case .avertissement: return Couleurs.avertissement
        case .erreur: return Color(rgb: 0xFF8A80)
        case .succes: return Couleurs.vert
        }
    }
}

extension View {
    /// Fond sombre des maquettes sur tout l'écran.
    func fondIRIS() -> some View {
        self
            .scrollContentBackground(.hidden)
            .background(Couleurs.fond.ignoresSafeArea())
    }
}

enum FormatIRIS {
    /// « 2,0× » pour tts_rate 370 (185 = 1×).
    static func multiplicateur(ttsRate: Int) -> String {
        let f = NumberFormatter()
        f.locale = Locale(identifier: "fr_CA")
        f.minimumFractionDigits = 1
        f.maximumFractionDigits = 1
        let valeur = Double(ttsRate) / 185.0
        return (f.string(from: NSNumber(value: valeur)) ?? String(format: "%.1f", valeur)) + "×"
    }

    /// « 1,4 s » à partir de millisecondes.
    static func secondes(ms: Double) -> String {
        let f = NumberFormatter()
        f.locale = Locale(identifier: "fr_CA")
        f.minimumFractionDigits = 1
        f.maximumFractionDigits = 1
        return (f.string(from: NSNumber(value: ms / 1000)) ?? String(format: "%.1f", ms / 1000)) + " s"
    }

    static func duree(secondes s: Double) -> String {
        let total = Int(s.rounded())
        let h = total / 3600, m = (total % 3600) / 60, sec = total % 60
        if h > 0 { return "\(h) h \(String(format: "%02ld", m))" }
        if m > 0 { return "\(m) min \(String(format: "%02ld", sec))" }
        return "\(sec) s"
    }

    static func dateCourte(_ date: Date?) -> String {
        guard let date else { return "" }
        return date.formatted(.dateTime.day().month(.abbreviated).hour().minute().locale(Locale(identifier: "fr_CA")))
    }
}
