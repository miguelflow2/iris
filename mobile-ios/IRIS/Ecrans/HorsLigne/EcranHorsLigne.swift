// EcranHorsLigne.swift — quand l'ordinateur ne répond pas : ce qui marche encore, ce qui ne marche
// pas, et pourquoi. Dit clairement plutôt que de laisser des boutons tourner dans le vide.

import SwiftUI

@MainActor
struct EcranHorsLigne: View {
    @Environment(EnvironnementIRIS.self) private var env
    @State private var verification = false

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 16) {
                Carte(titre: "Liaison avec l'ordinateur") {
                    PastillePC()
                    switch env.pont.etat {
                    case .horsLigne(let raison):
                        Text(raison).foregroundStyle(Couleurs.texte2)
                    case .connecte:
                        Text("Ton ordinateur répond : toutes les fonctions sont disponibles.")
                            .foregroundStyle(Couleurs.texte2)
                    case .nonConfigure, .motDePasseRequis:
                        Text("Cet iPhone n'est pas encore relié à ton ordinateur.")
                            .foregroundStyle(Couleurs.texte2)
                    case .connexion:
                        Text("Vérification en cours…").foregroundStyle(Couleurs.texte2)
                    case .verrouille(let raison):
                        Text(raison).foregroundStyle(Couleurs.texte2)
                    }
                    Button {
                        Task {
                            verification = true
                            await env.pont.verifier()
                            verification = false
                        }
                    } label: {
                        if verification { ProgressView().tint(Couleurs.fond) } else { Text("Réessayer maintenant") }
                    }
                    .buttonStyle(.holo(.sombre, compact: true))
                    .disabled(verification)
                    NoteVerite(texte: "L'iPhone réessaie seul toutes les 20 secondes tant que l'app est ouverte.")
                }

                Carte(titre: "Ce qui marche sans l'ordinateur") {
                    puce("Relire les cours gardés sur cet iPhone (\(env.coursHorsLigne.gardes.count)).", ok: true)
                    if env.perception != nil {
                        puce("Onglet Accessibilité : chaque fonction indique elle-même si elle a besoin de l'ordinateur ou d'Internet.", ok: true)
                    }
                    puce("Les zones sans mémoire restent surveillées par l'iPhone ; le signal part vers l'ordinateur dès que la liaison revient. D'ici là, la mémoire n'est pas suspendue par cette zone.", ok: true)
                    puce("Les lunettes restent reliées à l'iPhone comme un casque Bluetooth mains libres (appels).", ok: true)
                    if !env.coursHorsLigne.gardes.isEmpty {
                        NavigationLink("Ouvrir mes cours gardés") { EcranListeCours() }
                            .buttonStyle(.holo(.sombre, compact: true))
                    }
                }

                Carte(titre: "Ce qui ne marche pas sans l'ordinateur") {
                    puce("Parler à IRIS (voix ou écrit) : c'est l'ordinateur qui comprend et répond.", ok: false)
                    puce("L'interprète : la traduction est faite par l'ordinateur.", ok: false)
                    puce("Reçus, comparaison de prix, pas à pas, entraînement et résumé du jour : tout se passe sur l'ordinateur.", ok: false)
                    puce("Générer des fiches ou des questions de cours.", ok: false)
                    puce("Activer le mode invité, créer ou supprimer une zone.", ok: false)
                    puce("« Dis-moi Iris » : l'écoute ne démarre pas, puisque personne ne pourrait répondre.", ok: false)
                }

                Carte(titre: "Pistes") {
                    puce("Sans Tailscale, l'app iPhone ne joint pas ton ordinateur hors de ton réseau local : elle ne passe pas par le relais VELA.", ok: false)
                    puce("Vérifie que Tailscale est connecté sur cet iPhone et sur l'ordinateur.", ok: nil)
                    puce("L'ordinateur doit être allumé, pas en veille, avec IRIS ouverte.", ok: nil)
                    puce("À l'école ou au travail, certains réseaux Wi-Fi bloquent ce genre de liaison : essaie avec les données cellulaires.", ok: nil)
                }
            }
            .padding()
        }
        .fondIRIS()
        .navigationTitle("Mode hors ligne")
    }

    private func puce(_ texte: String, ok: Bool?) -> some View {
        HStack(alignment: .firstTextBaseline, spacing: 8) {
            Image(systemName: ok == true ? "checkmark.circle.fill" : ok == false ? "xmark.circle" : "lightbulb")
                .foregroundStyle(ok == true ? Couleurs.vert : ok == false ? Couleurs.rouge : Couleurs.avertissement)
                .accessibilityHidden(true)
            Text(texte).foregroundStyle(Couleurs.texte2)
        }
        .accessibilityElement(children: .combine)
    }
}
