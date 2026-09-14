// RacineVue.swift — les quatre onglets des maquettes (Accueil, IA, Accessibilité, Profil) et les
// écrans qui passent devant tout : verrouillage d'IRIS.

import SwiftUI

struct RacineVue: View {
    @Environment(EnvironnementIRIS.self) private var env

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

            if case .verrouille(let raison) = env.pont.etat {
                VerrouVue(raison: raison)
                    .transition(.opacity)
                    .zIndex(1)
            }
        }
        .background(Couleurs.fond.ignoresSafeArea())
        .dynamicTypeSize(env.grandTexte ? DynamicTypeSize.xxLarge...DynamicTypeSize.accessibility5
                                        : DynamicTypeSize.xSmall...DynamicTypeSize.accessibility5)
        .task { await env.auPremierPlan() }
    }
}

/// L'onglet Accessibilité appartient à l'équipe perception (Ecrans/Accessibilite/). S'il n'est pas
/// inclus dans cette version, on le dit au lieu d'afficher des boutons qui ne feraient rien.
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
