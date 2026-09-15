// CommandesLocales.swift — les phrases que l'app iPhone traite elle-même au lieu de les envoyer au chat.
//
// Pourquoi : sur l'ordinateur, « Dis-moi Iris, mode invité » est une INTERCEPTION de l'écoute
// (voice/listener.py, priorité 10), consultée avant le modèle. Une commande dite dans les lunettes et
// reconnue par l'iPhone part, elle, au chat (POST /api/conversations/{id}/messages), qui ne consulte
// aucune interception : le modèle pouvait répondre « d'accord » sans que la mémoire soit suspendue.
// Depuis le 2026-09-14, une commande PARLÉE passe par POST /api/voix/commande (EnvironnementIRIS.demanderAVoix),
// qui consulte les interceptions de l'ordinateur. Ces motifs restent pour l'ÉCRIT (onglet IA) et en repli
// sur un ordinateur qui ne connaît pas encore cette route : mêmes motifs que mode_invite.py, vraie route.
//
// Sortir du mode invité à la voix est REFUSÉ, comme sur l'ordinateur sans verrou vocal : l'invité porte
// les lunettes, et IRIS ne sait pas qui parle. Si la phrase suffisait, l'invité en sortirait et IRIS lui
// répondrait avec les souvenirs du propriétaire. Le mode se termine depuis l'app ou à la fin de la minuterie.

import Foundation

enum CommandeLocale: Equatable {
    case activerModeInvite
    case quitterModeInvite
}

enum CommandesLocales {
    // Mêmes motifs que backend/iris/mode_invite.py (_ACTIVER, _DESACTIVER), appliqués au texte normalisé
    // comme sur l'ordinateur (sans accents ni ponctuation, minuscules).
    private static let politesse = "(?: s il (?:te|vous) plait)?"
    private static let motifActiver = try? NSRegularExpression(pattern:
        "^(?:iris )?(?:(?:active|activer|activez|passe|passer|passez|mets|mettre|lance|lancer|demarre|demarrer)"
        + "(?: le| en| au)? )?mode invite" + politesse + "$")
    private static let motifQuitter = try? NSRegularExpression(pattern:
        "^(?:iris )?(?:fin|termine|terminer|arrete|arreter|desactive|desactiver|desactivez|quitte|quitter|sors|"
        + "sortir|sortez|stop)(?: du| le| de| la)? mode invite" + politesse + "$")

    /// La commande reconnue, ou nil (très vite) quand la phrase ne concerne pas l'app.
    static func reconnaitre(_ texte: String) -> CommandeLocale? {
        let propre = MotActivation.normaliser(texte)
        guard propre.contains("invite") else { return nil }
        let plage = NSRange(propre.startIndex..<propre.endIndex, in: propre)
        if motifQuitter?.firstMatch(in: propre, options: [], range: plage) != nil { return .quitterModeInvite }
        if motifActiver?.firstMatch(in: propre, options: [], range: plage) != nil { return .activerModeInvite }
        return nil
    }

    /// « 16 h 05 », heure locale de l'iPhone (même forme que heure_locale côté ordinateur).
    static func heure(_ date: Date, calendrier: Calendar = .current) -> String {
        let c = calendrier.dateComponents([.hour, .minute], from: date)
        return "\(c.hour ?? 0) h \(String(format: "%02d", c.minute ?? 0))"
    }

    static func phraseInviteActive(jusqua: Date?, concis: Bool) -> String {
        let fin = jusqua.map { " jusqu'à \(heure($0))" } ?? ""
        if concis { return "Mode invité activé\(fin)." }
        return "Mode invité activé\(fin) : je ne garde pas de souvenirs de cette session, et ses conversations seront effacées à la fin. Quiconque porte les lunettes me parle ; pour en sortir avant, utilise l'application IRIS : je ne peux pas savoir qui me parle."
    }

    static func phraseSortieRefusee(actif: Bool?, jusqua: Date?) -> String {
        if actif == false { return "Le mode invité n'est pas actif." }
        var phrase = "Je ne peux pas savoir qui me parle : termine le mode invité dans l'app IRIS, Profil, Mode invité."
        if let jusqua { phrase += " Il se terminera aussi tout seul à \(heure(jusqua))." }
        return phrase
    }
}
