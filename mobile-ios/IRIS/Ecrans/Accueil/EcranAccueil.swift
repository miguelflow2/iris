// EcranAccueil.swift — l'onglet Accueil : état réel de l'ordinateur et des lunettes, parler à IRIS,
// et les accès aux fonctions de l'iPhone.

import SwiftUI

@MainActor
struct EcranAccueil: View {
    @Environment(EnvironnementIRIS.self) private var env

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 16) {
                entete

                if case .horsLigne(let raison) = env.pont.etat {
                    NavigationLink {
                        EcranHorsLigne()
                    } label: {
                        Carte {
                            Label("Mode hors ligne", systemImage: "wifi.slash")
                                .font(.headline)
                                .foregroundStyle(Couleurs.texte)
                            Text(raison)
                                .font(.subheadline)
                                .foregroundStyle(Couleurs.texte2)
                            Text("Voir ce qui marche sans l'ordinateur ›")
                                .font(.subheadline.weight(.semibold))
                                .foregroundStyle(Couleurs.bleu)
                        }
                    }
                    .buttonStyle(.plain)
                }

                if env.pont.etat == .nonConfigure || env.pont.etat == .motDePasseRequis {
                    Carte(titre: "Pour commencer") {
                        Text("IRIS travaille sur ton ordinateur. Cet iPhone est sa voix et son oreille dehors : relie-le à ton ordinateur avec son adresse et ton mot de passe.")
                            .foregroundStyle(Couleurs.texte2)
                        NavigationLink("Relier mon ordinateur") { EcranConnexionPC() }
                            .buttonStyle(.holo)
                    }
                }

                CarteVoix()

                if !env.lunettesPresentes {
                    LunettesRequisesVue(message: "La voix, l'interprète et les fonctions de capture marchent avec les lunettes VELA.")
                }

                Carte(titre: "Fonctions") {
                    NavigationLink { EcranInterprete() } label: {
                        LigneFonction(icone: "character.bubble", titre: "Interprète",
                                      detail: "Deux boutons : toi, puis l'autre personne. Traduit par ton ordinateur.")
                    }
                    Divider().overlay(Couleurs.ligne)
                    NavigationLink { EcranListeCours() } label: {
                        LigneFonction(icone: "graduationcap", titre: "Mes cours",
                                      detail: "Fiches, questions et transcriptions enregistrées sur ton ordinateur.")
                    }
                    Divider().overlay(Couleurs.ligne)
                    NavigationLink { EcranHorsLigne() } label: {
                        LigneFonction(icone: "wifi.slash", titre: "Mode hors ligne",
                                      detail: "Ce qui marche quand l'ordinateur ne répond pas.")
                    }
                }

                Carte(titre: "Au quotidien") {
                    NavigationLink { EcranRecus() } label: {
                        LigneFonction(icone: "doc.text.viewfinder", titre: "Reçus",
                                      detail: "Photographie un reçu : ton ordinateur le lit et le range. Montants à vérifier.")
                    }
                    Divider().overlay(Couleurs.ligne)
                    NavigationLink { EcranPrix() } label: {
                        LigneFonction(icone: "tag", titre: "Comparer les prix",
                                      detail: "Prix trouvés en ligne par ton ordinateur, à vérifier en magasin.")
                    }
                    Divider().overlay(Couleurs.ligne)
                    NavigationLink { EcranPasAPas() } label: {
                        LigneFonction(icone: "list.number", titre: "Pas à pas",
                                      detail: "Une étape à la fois, lue à voix haute : recette, montage, réparation.")
                    }
                    Divider().overlay(Couleurs.ligne)
                    NavigationLink { EcranEntrainement() } label: {
                        LigneFonction(icone: "figure.strengthtraining.traditional", titre: "Entraînement",
                                      detail: "Séries et repos chronométrés. IRIS ne compte pas les répétitions.")
                    }
                    Divider().overlay(Couleurs.ligne)
                    NavigationLink { EcranResumeJour() } label: {
                        LigneFonction(icone: "calendar", titre: "Résumé du jour",
                                      detail: "Ce qu'IRIS a noté sur ton ordinateur : fait, reste à faire, rappels.")
                    }
                }
            }
            .padding()
        }
        .fondIRIS()
        .navigationTitle("IRIS")
        .refreshable { await env.pont.verifier() }
    }

    private var entete: some View {
        VStack(alignment: .leading, spacing: 8) {
            if !env.pont.nomProprietaire.isEmpty {
                Text("Bonjour \(env.pont.nomProprietaire)")
                    .font(.title2.bold())
                    .foregroundStyle(Couleurs.texte)
            }
            ScrollView(.horizontal, showsIndicators: false) {
                HStack(spacing: 8) {
                    PastillePC()
                    PastilleLunettes()
                }
            }
        }
    }
}

@MainActor
struct LigneFonction: View {
    let icone: String
    let titre: String
    let detail: String

    var body: some View {
        HStack(spacing: 14) {
            Image(systemName: icone)
                .font(.title3)
                .frame(width: 36, height: 36)
                .foregroundStyle(Couleurs.fond)
                .background(Couleurs.holoIcone, in: RoundedRectangle(cornerRadius: 10))
                .accessibilityHidden(true)
            VStack(alignment: .leading, spacing: 2) {
                Text(titre).font(.headline).foregroundStyle(Couleurs.texte)
                Text(detail).font(.subheadline).foregroundStyle(Couleurs.attenue)
                    .multilineTextAlignment(.leading)
            }
            Spacer(minLength: 0)
            Image(systemName: "chevron.right")
                .foregroundStyle(Couleurs.attenue)
                .accessibilityHidden(true)
        }
        .contentShape(Rectangle())
        .padding(.vertical, 4)
    }
}

/// La carte de la voix : bouton « Parler à IRIS » (une phrase) et interrupteur « Dis-moi Iris ».
@MainActor
struct CarteVoix: View {
    @Environment(EnvironnementIRIS.self) private var env
    @State private var erreur: String? = nil
    @State private var enEcoute = false

    var body: some View {
        let voix = env.voix
        Carte(titre: "Voix") {
            etatVoix(voix.etat)

            if !voix.partiel.isEmpty {
                Text("« \(voix.partiel) »")
                    .font(.title3)
                    .foregroundStyle(Couleurs.texte)
                    .accessibilityLabel("Entendu : \(voix.partiel)")
            }

            Button {
                Task { await parlerUneFois() }
            } label: {
                Label(enEcoute ? "J'écoute… (touche pour arrêter)" : "Parler à IRIS", systemImage: "mic.fill")
            }
            .buttonStyle(.holo)
            .disabled(!enEcoute && env.raisonVoixImpossible() != nil)

            Toggle(isOn: Binding(
                get: { voix.motActivationVoulu },
                set: { actif in
                    if actif { voix.demarrerMotActivation() } else { voix.arreterMotActivation() }
                })) {
                VStack(alignment: .leading, spacing: 2) {
                    Text("Écouter « \(voix.motActivation) »").foregroundStyle(Couleurs.texte)
                    Text("Seulement quand l'app IRIS est ouverte à l'écran.")
                        .font(.footnote).foregroundStyle(Couleurs.attenue)
                }
            }
            .tint(Couleurs.bleu)

            if let raison = env.raisonVoixImpossible() {
                NoteVerite(texte: raison, genre: .avertissement)
            }
            if let erreur {
                NoteVerite(texte: erreur, genre: .erreur)
            }
            NoteVerite(texte: "iOS ne laisse aucune app écouter un mot d'activation écran verrouillé ou app fermée : c'est réservé à Siri. Autre voie mains libres : « Dis Siri, parle à IRIS ». La parole est reconnue sur cet iPhone ; seul le texte part à ton ordinateur. Sortie audio actuelle : \(SessionAudio.sortieActuelle).")
        }
    }

    @ViewBuilder
    private func etatVoix(_ etat: EtatVoix) -> some View {
        switch etat {
        case .inactive:
            EmptyView()
        case .veille:
            Label("J'écoute « \(env.voix.motActivation) »", systemImage: "ear")
                .foregroundStyle(Couleurs.vert)
        case .commande:
            Label("Je t'écoute…", systemImage: "waveform")
                .foregroundStyle(Couleurs.vert)
        case .reflexion:
            Label("IRIS réfléchit sur ton ordinateur…", systemImage: "hourglass")
                .foregroundStyle(Couleurs.texte2)
        case .parle:
            Label("IRIS parle", systemImage: "speaker.wave.2.fill")
                .foregroundStyle(Couleurs.texte2)
        case .indisponible(let raison):
            NoteVerite(texte: raison, genre: .avertissement)
        }
    }

    private func parlerUneFois() async {
        if enEcoute {
            env.voix.annulerEcoute()
            return
        }
        if let raison = env.raisonVoixImpossible() {
            erreur = raison
            return
        }
        erreur = nil
        enEcoute = true
        do {
            let phrase = try await env.voix.ecouterUnePhrase(langue: env.voix.langueIRIS, delaiMax: 8)
            enEcoute = false
            if let reponse = await env.demanderAVoix(phrase) {
                await env.voix.parler(reponse)
            }
        } catch {
            enEcoute = false
            if case ErreurVoix.interrompu? = error as? ErreurVoix { return }
            erreur = error.localizedDescription
        }
    }
}
