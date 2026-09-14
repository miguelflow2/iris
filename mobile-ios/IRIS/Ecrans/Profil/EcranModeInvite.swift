// EcranModeInvite.swift — le mode invité : IRIS ne retient rien le temps choisi.
//
// Accessible sans lunettes (confiance). Le texte de limite vient de l'ordinateur (mode_invite.py)
// et s'affiche tel quel.

import SwiftUI

struct EcranModeInvite: View {
    @Environment(EnvironnementIRIS.self) private var env
    @State private var etat: EtatInvite? = nil
    @State private var minutes: Int = 120
    @State private var enCours = false
    @State private var erreur: String? = nil
    @State private var abonnement: AbonnementEvenements? = nil

    private let durees = [15, 30, 60, 120, 240, 480, 720]

    var body: some View {
        Form {
            Section {
                if let etat {
                    HStack {
                        Image(systemName: etat.actif ? "person.2.slash.fill" : "person.2")
                            .foregroundStyle(etat.actif ? Couleurs.orange : Couleurs.attenue)
                        Text(etat.actif ? "Mode invité actif" : "Mode invité inactif")
                            .font(.headline)
                            .foregroundStyle(Couleurs.texte)
                    }
                    if etat.actif {
                        if let fin = etat.jusqua?.date {
                            Text("Retour à la normale à \(fin.formatted(date: .omitted, time: .shortened))"
                                 + (etat.minutesRestantes.map { " (dans \($0) min)" } ?? ""))
                                .foregroundStyle(Couleurs.texte2)
                        }
                        Button("Terminer le mode invité") { Task { await desactiver() } }
                            .buttonStyle(.holo(.rouge))
                            .listRowBackground(Color.clear)
                    } else {
                        Picker("Durée", selection: $minutes) {
                            ForEach(durees, id: \.self) { valeur in
                                Text(valeur < 60 ? "\(valeur) min" : "\(valeur / 60) h").tag(valeur)
                            }
                        }
                        Button("Activer le mode invité") { Task { await activer() } }
                            .buttonStyle(.holo)
                            .listRowBackground(Color.clear)
                    }
                } else if erreur == nil {
                    ProgressView()
                }
            } footer: {
                Text("Pratique quand quelqu'un d'autre utilise IRIS ou qu'une conversation ne doit pas être retenue. Tu peux aussi dire « Dis-moi Iris, mode invité ».")
            }
            .listRowBackground(Couleurs.carte)
            .disabled(enCours)

            if let limite = etat?.limite {
                Section { NoteVerite(texte: limite) }
                    .listRowBackground(Couleurs.carte)
            }
            if let erreur {
                Section { NoteVerite(texte: erreur, genre: .erreur) }
                    .listRowBackground(Couleurs.carte)
            }
        }
        .fondIRIS()
        .navigationTitle("Mode invité")
        .task {
            if let reglage = env.reglages?.modeInviteMinutes, durees.contains(reglage) { minutes = reglage }
            await charger()
            abonnement = env.pont.abonner { evenement in
                guard evenement.type == "invite.etat" else { return }
                Task { await charger() }
            }
        }
        .onDisappear { abonnement?.annuler() }
    }

    private func charger() async {
        do {
            let lu: EtatInvite = try await env.pont.get("/api/confiance/invite")
            etat = lu
            erreur = nil
        } catch {
            erreur = error.localizedDescription
        }
    }

    private func activer() async {
        enCours = true
        defer { enCours = false }
        do {
            let lu: EtatInvite = try await env.pont.post("/api/confiance/invite/activer", corps: DemandeInvite(minutes: minutes))
            etat = lu
            erreur = nil
        } catch {
            erreur = error.localizedDescription
        }
    }

    private func desactiver() async {
        enCours = true
        defer { enCours = false }
        do {
            let lu: EtatInvite = try await env.pont.post("/api/confiance/invite/desactiver", delai: 60)
            etat = lu
            erreur = nil
        } catch {
            erreur = error.localizedDescription
        }
    }
}
