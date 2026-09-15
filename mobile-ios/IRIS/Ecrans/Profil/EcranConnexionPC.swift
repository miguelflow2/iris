// EcranConnexionPC.swift — relier l'iPhone à l'ordinateur : adresse Tailscale et mot de passe.

import SwiftUI

@MainActor
struct EcranConnexionPC: View {
    @Environment(EnvironnementIRIS.self) private var env
    @Environment(\.dismiss) private var fermer
    @State private var adresse = ""
    @State private var motDePasse = ""
    @State private var enCours = false
    @State private var erreur: String? = nil
    @State private var reussi = false

    var body: some View {
        Form {
            Section {
                TextField("https://bureau.tail1234.ts.net", text: $adresse)
                    .textInputAutocapitalization(.never)
                    .autocorrectionDisabled()
                    .keyboardType(.URL)
                    .textContentType(.URL)
                SecureField("Mot de passe du propriétaire", text: $motDePasse)
                    .textContentType(.password)
            } header: {
                Text("Ton ordinateur")
            } footer: {
                Text("L'adresse est celle que Tailscale donne à ton ordinateur (dans IRIS sur l'ordinateur : Mon profil › Compte et sécurité › Accès depuis le téléphone). Le mot de passe est celui créé dans IRIS sur l'ordinateur ; la session ouverte (30 jours) est gardée dans le Trousseau de cet iPhone.")
            }
            .listRowBackground(Couleurs.carte)

            Section {
                Button {
                    Task { await connecter() }
                } label: {
                    if enCours { ProgressView().tint(Couleurs.fond) } else { Text("Se connecter") }
                }
                .buttonStyle(.holo)
                .listRowBackground(Color.clear)
                .disabled(adresse.trimmingCharacters(in: .whitespaces).isEmpty || motDePasse.isEmpty || enCours)
            }

            if let erreur {
                Section {
                    NoteVerite(texte: erreur, genre: .erreur)
                }
                .listRowBackground(Couleurs.carte)
            }
            if reussi {
                Section {
                    NoteVerite(texte: "Relié. \(env.pont.liaisonNonChiffree ? "Adresse en http : la liaison n'est chiffrée que si elle passe par Tailscale (adresse 100.x). Préfère l'adresse https." : "Liaison chiffrée (https).")", genre: .succes)
                }
                .listRowBackground(Couleurs.carte)
            }

            Section {
                NoteVerite(texte: "Dehors, le téléphone joint l'ordinateur par Tailscale, un réseau privé chiffré : aucun port n'est ouvert sur ta box. L'ordinateur doit rester allumé, IRIS ouverte, et Tailscale connecté des deux côtés.")
                NoteVerite(texte: "Sans Tailscale, l'app iPhone ne joint pas ton ordinateur hors de ton réseau local : elle ne passe pas par le relais VELA (il ne sert, sur l'iPhone, qu'au partage de ta vue).",
                           genre: .avertissement)
            }
            .listRowBackground(Couleurs.carte)
        }
        .fondIRIS()
        .navigationTitle("Relier l'ordinateur")
        .onAppear {
            if adresse.isEmpty, let actuelle = env.pont.adresse { adresse = actuelle.absoluteString }
        }
    }

    private func connecter() async {
        enCours = true
        erreur = nil
        reussi = false
        defer { enCours = false }
        do {
            try await env.pont.connecter(adresse: adresse, motDePasse: motDePasse)
            motDePasse = ""
            reussi = true
            await env.chargerReglages()
            await env.zones.reessayer()
        } catch {
            erreur = error.localizedDescription
        }
    }
}
