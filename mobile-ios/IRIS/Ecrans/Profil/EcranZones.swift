// EcranZones.swift — les zones sans mémoire : les lieux où IRIS ne retient rien.
//
// Accessible sans lunettes (confiance). La liste vit sur l'ordinateur ; la surveillance, sur
// l'iPhone (Confiance/SurveillanceZones.swift), qui n'envoie que l'identifiant de la zone.

import CoreLocation
import SwiftUI

struct EcranZones: View {
    @Environment(EnvironnementIRIS.self) private var env
    @State private var nom = ""
    @State private var rayon: Double = 150
    @State private var ajoutEnCours = false
    @State private var erreurAjout: String? = nil
    @State private var aSupprimer: ZoneSansMemoire? = nil

    private let rayons: [Double] = [50, 100, 150, 250, 500, 1000]

    var body: some View {
        let zones = env.zones
        Form {
            Section {
                Toggle("Surveiller mes zones avec cet iPhone", isOn: Binding(
                    get: { zones.surveillanceActive },
                    set: { actif in
                        Task { if actif { await zones.activerSurveillance() } else { await zones.desactiverSurveillance() } }
                    }))
                if zones.surveillanceActive {
                    etatAutorisation(zones.autorisation)
                }
                if let active = zones.zoneActiveServeur, let nomZone = active.nom {
                    Label("Mémoire suspendue : zone « \(nomZone) »", systemImage: "brain.head.profile")
                        .foregroundStyle(Couleurs.orange)
                }
                if let signal = zones.dernierSignal {
                    NoteVerite(texte: signal, genre: .succes)
                }
                if let erreur = zones.erreur {
                    NoteVerite(texte: erreur, genre: .erreur)
                }
            } footer: {
                Text("Dans une zone sans mémoire, IRIS ne retient rien : ni souvenirs, ni journal, ni cours, ni photos décrites, ni reçus. Cet iPhone compare sa position à tes zones et n'envoie à ton ordinateur que le nom de code de la zone où il se trouve, jamais ta position.")
            }
            .listRowBackground(Couleurs.carte)

            Section("Mes zones") {
                if zones.zones.isEmpty {
                    Text("Aucune zone.").foregroundStyle(Couleurs.attenue)
                }
                ForEach(zones.zones) { zone in
                    HStack {
                        VStack(alignment: .leading) {
                            Text(zone.nom).foregroundStyle(Couleurs.texte)
                            Text("Rayon \(Int(zone.rayonM)) m").font(.footnote).foregroundStyle(Couleurs.attenue)
                        }
                        Spacer()
                        if zones.zonesDedans.contains(zone.id) {
                            Text("Tu es dedans").font(.footnote.weight(.semibold)).foregroundStyle(Couleurs.orange)
                        }
                    }
                    .swipeActions {
                        Button("Supprimer", role: .destructive) { aSupprimer = zone }
                    }
                }
                if zones.zonesNonSurveillees > 0 {
                    NoteVerite(texte: "\(zones.zonesNonSurveillees) zone(s) ne sont pas surveillées par cet iPhone : iOS en accepte au plus \(SurveillanceZones.limiteRegionsIOS) par app. Les plus petites passent en premier.", genre: .avertissement)
                }
            }
            .listRowBackground(Couleurs.carte)

            Section {
                TextField("Nom (ex. Clinique)", text: $nom)
                Picker("Rayon", selection: $rayon) {
                    ForEach(rayons, id: \.self) { valeur in
                        Text(valeur < 1000 ? "\(Int(valeur)) m" : "1 km").tag(valeur)
                    }
                }
                Button {
                    Task { await ajouter() }
                } label: {
                    if ajoutEnCours { ProgressView().tint(Couleurs.fond) } else { Text("Ajouter une zone ici") }
                }
                .buttonStyle(.holo(.sombre))
                .listRowBackground(Color.clear)
                .disabled(nom.trimmingCharacters(in: .whitespaces).isEmpty || ajoutEnCours || !env.pont.etat.estConnecte)
                if let erreurAjout {
                    NoteVerite(texte: erreurAjout, genre: .erreur)
                }
            } header: {
                Text("Nouvelle zone")
            } footer: {
                Text("La zone est centrée sur ta position actuelle : c'est le seul moment où ta position est envoyée à ton ordinateur.")
            }
            .listRowBackground(Couleurs.carte)

            Section("Limites") {
                NoteVerite(texte: SurveillanceZones.limiteIPhone)
                if let limite = zones.limiteServeur {
                    NoteVerite(texte: limite)
                }
            }
            .listRowBackground(Couleurs.carte)
        }
        .fondIRIS()
        .navigationTitle("Zones sans mémoire")
        .task { await zones.charger() }
        .confirmationDialog("Supprimer cette zone ?", isPresented: Binding(
            get: { aSupprimer != nil }, set: { if !$0 { aSupprimer = nil } }), titleVisibility: .visible) {
            Button("Supprimer « \(aSupprimer?.nom ?? "") »", role: .destructive) {
                if let zone = aSupprimer { Task { await zones.supprimer(zone) } }
                aSupprimer = nil
            }
        }
    }

    @ViewBuilder
    private func etatAutorisation(_ statut: CLAuthorizationStatus) -> some View {
        switch statut {
        case .authorizedAlways:
            NoteVerite(texte: "Position permise « Toujours » : les zones marchent même app fermée.", genre: .succes)
        case .authorizedWhenInUse:
            NoteVerite(texte: "Position permise seulement pendant l'utilisation : app fermée, l'entrée dans une zone ne sera pas détectée.", genre: .avertissement)
            Button("Permettre « Toujours »") { env.zones.demanderToujours() }
        case .denied, .restricted:
            NoteVerite(texte: "Position refusée pour IRIS : la surveillance ne peut pas marcher. Réglages › IRIS › Position.", genre: .erreur)
        default:
            NoteVerite(texte: "En attente de l'autorisation de position.")
        }
    }

    private func ajouter() async {
        ajoutEnCours = true
        defer { ajoutEnCours = false }
        erreurAjout = nil
        let statut = CLLocationManager().authorizationStatus
        if statut == .notDetermined {
            // La première demande ouvre la question d'iOS ; l'utilisateur retouche « Ajouter » ensuite.
            env.zones.demanderPosition()
            erreurAjout = "Autorise la position pour IRIS, puis touche de nouveau « Ajouter une zone ici »."
            return
        }
        do {
            try await env.zones.ajouterIci(nom: nom.trimmingCharacters(in: .whitespaces), rayonM: rayon)
            nom = ""
        } catch {
            erreurAjout = error.localizedDescription
        }
    }
}
