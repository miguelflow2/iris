// RaccourcisSiri.swift — « Dis Siri, parle à IRIS » : la seule activation mains libres qu'iOS permet
// à une app tierce quand elle n'est pas à l'écran (voir mobile-ios/REALITE-IOS.md, point 8).
//
// Siri ouvre l'app ; l'onglet IA commence alors à écouter une phrase, si les lunettes sont là et
// l'ordinateur joignable. Rien ne s'exécute en arrière-plan.

import AppIntents

struct ParlerAIris: AppIntent {
    static var title: LocalizedStringResource = "Parler à IRIS"
    static var description = IntentDescription("Ouvre IRIS, prête à écouter ta demande.")
    static var openAppWhenRun: Bool = true

    @MainActor
    func perform() async throws -> some IntentResult {
        EnvironnementIRIS.partage.ecouteDemandeeAuLancement = true
        EnvironnementIRIS.partage.ongletChoisi = .ia
        return .result()
    }
}

struct RaccourcisIRIS: AppShortcutsProvider {
    static var appShortcuts: [AppShortcut] {
        AppShortcut(
            intent: ParlerAIris(),
            phrases: [
                "Parle à \(.applicationName)",
                "Parler à \(.applicationName)",
            ],
            shortTitle: "Parler à IRIS",
            systemImageName: "mic.fill"
        )
    }
}
