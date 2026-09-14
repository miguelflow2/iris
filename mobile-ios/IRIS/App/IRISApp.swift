// IRISApp.swift — point d'entrée de l'app iPhone IRIS (VELA).

import SwiftUI
import UIKit

@main
struct IRISApp: App {
    @UIApplicationDelegateAdaptor(DelegueApplication.self) private var delegueApplication
    @Environment(\.scenePhase) private var phase

    var body: some Scene {
        WindowGroup {
            RacineVue()
                .environment(EnvironnementIRIS.partage)
                .preferredColorScheme(.dark)
                .tint(Couleurs.bleu)
        }
        .onChange(of: phase) { _, nouvelle in
            let env = EnvironnementIRIS.partage
            switch nouvelle {
            case .active:
                Task { await env.auPremierPlan() }
            case .background:
                env.enArrierePlan()
            default:
                break
            }
        }
    }
}

final class DelegueApplication: NSObject, UIApplicationDelegate {
    func application(_ application: UIApplication,
                     didFinishLaunchingWithOptions launchOptions: [UIApplication.LaunchOptionsKey: Any]? = nil) -> Bool {
        // Créé dès le lancement, même en arrière-plan (réveil par une zone sans mémoire) : la
        // surveillance des zones doit recevoir l'événement qui a réveillé l'app.
        MainActor.assumeIsolated {
            _ = EnvironnementIRIS.partage
        }
        return true
    }
}
