// MotActivation.swift — reconnaître « Dis-moi Iris » dans le texte reconnu, et isoler la commande.
//
// Même normalisation que le service (voice/listener.py : normalize) : sans accents, minuscules,
// tout ce qui n'est ni lettre ni chiffre devient une espace. La reconnaissance de l'iPhone écrit
// « Dis-moi Iris », « dis moi iris », « Dismoi Iris » ou « dit moi Irisse » selon la diction : on
// accepte ces variantes, et le mot d'activation réglé sur l'ordinateur s'il a été changé.

import Foundation

enum MotActivation {
    static func normaliser(_ texte: String) -> String {
        let sansAccents = texte.folding(options: [.diacriticInsensitive, .caseInsensitive], locale: Locale(identifier: "fr_CA"))
        var sortie = ""
        sortie.reserveCapacity(sansAccents.count)
        for caractere in sansAccents.lowercased() {
            if caractere.isASCII && (caractere.isLetter || caractere.isNumber) {
                sortie.append(caractere)
            } else {
                sortie.append(" ")
            }
        }
        return sortie.split(separator: " ").joined(separator: " ")
    }

    /// Les suites de mots acceptées comme mot d'activation.
    static func variantes(_ motActivation: String) -> [[String]] {
        var suites: [[String]] = []
        let regle = normaliser(motActivation).split(separator: " ").map(String.init)
        if !regle.isEmpty { suites.append(regle) }
        let debuts = [["dis", "moi"], ["dit", "moi"], ["di", "moi"], ["dismoi"], ["dites", "moi"], ["dis", "moa"]]
        let noms = ["iris", "iriss", "irisse", "irys", "hiris", "yris"]
        for debut in debuts {
            for nom in noms {
                suites.append(debut + [nom])
            }
        }
        // Les plus longues d'abord : « dites moi iris » avant « moi iris ».
        return suites.sorted { $0.count > $1.count }
    }

    /// Cherche le mot d'activation dans les segments reconnus (SFTranscriptionSegment.substring).
    /// Rend nil s'il est absent ; sinon la commande qui suit (chaîne vide si rien n'a encore été dit).
    static func commande(apres segments: [String], motActivation: String) -> String? {
        var jetons: [(mot: String, segment: Int)] = []
        for (index, segment) in segments.enumerated() {
            for mot in normaliser(segment).split(separator: " ") {
                jetons.append((String(mot), index))
            }
        }
        guard !jetons.isEmpty else { return nil }
        let mots = jetons.map(\.mot)
        for suite in variantes(motActivation) where !suite.isEmpty && mots.count >= suite.count {
            for debut in 0...(mots.count - suite.count) where Array(mots[debut..<(debut + suite.count)]) == suite {
                let dernierSegment = jetons[debut + suite.count - 1].segment
                let reste = segments.dropFirst(dernierSegment + 1).joined(separator: " ")
                return reste.trimmingCharacters(in: .whitespacesAndNewlines.union(.punctuationCharacters))
            }
        }
        return nil
    }
}
