// RacineVue.swift — les quatre onglets des maquettes (Accueil, IA, Accessibilité, Profil) et les
// écrans qui passent devant tout : plein écran d'une alerte sonore, verrouillage d'IRIS.

import SwiftUI

@MainActor
struct RacineVue: View {
    @Environment(EnvironnementIRIS.self) private var env
    @State private var alertePleinEcran: AlerteSonore?

    var body: some View {
        @Bindable var env = env
        ZStack {
            TabView(selection: $env.ongletChoisi) {
                NavigationStack { EcranAccueil() }
                    .tabItem { Label("Accueil", systemImage: "house.fill") }
                    .tag(Onglet.accueil)

                NavigationStack { EcranIA() }
                    .tabItem { Label("IA", systemImage: "sparkles") }
                    .tag(Onglet.ia)

                NavigationStack { OngletAccessibilite() }
                    .tabItem { Label("Accessibilité", systemImage: "accessibility") }
                    .tag(Onglet.accessibilite)

                NavigationStack { EcranProfil() }
                    .tabItem { Label("Profil", systemImage: "person.crop.circle") }
                    .tag(Onglet.profil)
            }
            .toolbarBackground(Couleurs.fond2, for: .tabBar)
            .toolbarBackground(.visible, for: .tabBar)

            // Plein écran d'alerte : UNE seule fois, ici, pour tous les onglets et tous les écrans. Une
            // superposition plutôt qu'un fullScreenCover : une présentation échoue en silence quand une
            // feuille est déjà ouverte. Limite : une feuille ouverte (appairage…) reste au-dessus ; la
            // vibration, la notification et la voix préviennent quand même.
            if let alerte = alertePleinEcran, let perception = env.perception {
                perception.vueAlertePleinEcran(alerte) { alertePleinEcran = nil }
                    // Une nouvelle alerte par-dessus la précédente : vue neuve, donc focus VoiceOver reposé.
                    .id(alerte.id)
                    .transition(.opacity)
                    .zIndex(1)
            }

            // Verrouillée (vue par l'ordinateur, ou gardée sur l'iPhone depuis la dernière fois) : l'écran
            // de verrouillage passe devant tout, même hors ligne, cours gardés compris.
            if env.pont.verrouPersistant || estVerrouillee {
                VerrouVue(raison: raisonVerrou)
                    .transition(.opacity)
                    .zIndex(2)
            }
        }
        .background(Couleurs.fond.ignoresSafeArea())
        .dynamicTypeSize(env.grandTexte ? DynamicTypeSize.xxLarge...DynamicTypeSize.accessibility5
                                        : DynamicTypeSize.xSmall...DynamicTypeSize.accessibility5)
        .onChange(of: env.perception?.alertes.derniereSignalee?.id) { _, _ in
            if let alerte = env.perception?.alertes.derniereSignalee {
                alertePleinEcran = alerte
            }
        }
        .task { await env.auPremierPlan() }
    }

    private var estVerrouillee: Bool {
        if case .verrouille = env.pont.etat { return true }
        return false
    }

    private var raisonVerrou: String {
        if case .verrouille(let raison) = env.pont.etat { return raison }
        return env.pont.raisonVerrou
    }
}

/// L'onglet Accessibilité appartient à l'équipe perception (Ecrans/Accessibilite/). S'il n'est pas
/// inclus dans cette version, on le dit au lieu d'afficher des boutons qui ne feraient rien.
@MainActor
struct OngletAccessibilite: View {
    @Environment(EnvironnementIRIS.self) private var env

    var body: some View {
        if let perception = env.perception {
            perception.ecranAccessibilite()
        } else {
            ScrollView {
                VStack(alignment: .leading, spacing: 16) {
                    Carte(titre: "Accessibilité") {
                        Text("Le module de perception (lunettes, description de ce qui est devant toi, lecture, alertes sonores, guidage) n'est pas inclus dans cette version de l'app.")
                            .foregroundStyle(Couleurs.texte2)
                        NoteVerite(texte: "Rien n'est simulé : tant que ce module manque, ces fonctions ne sont pas proposées sur l'iPhone. Sur l'ordinateur, IRIS › Accessibilité reste disponible.")
                    }
                }
                .padding()
            }
            .fondIRIS()
            .navigationTitle("Accessibilité")
        }
    }
}
