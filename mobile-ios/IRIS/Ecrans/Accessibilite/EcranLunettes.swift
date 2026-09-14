// EcranLunettes.swift — « Connecter mes lunettes » : recherche, connexion, batterie, état de la caméra.
//
// Accessible SANS lunettes (c'est son but). Dit clairement ce que cette connexion fait et ne fait pas :
// le son des lunettes passe par Réglages › Bluetooth d'iOS ; ici, IRIS se relie à leur canal de commande.

import CoreBluetooth
import SwiftUI
import UIKit

struct EcranLunettes: View {
    let lunettes: LunettesBLE
    @State private var erreur: Error?
    @State private var connexionVers: String?
    @State private var confirmationOubli = false

    // Initialiseur explicite : les propriétés privées (@State, @Environment) rendraient l'initialiseur
    // implicite privé, donc inaccessible depuis les autres fichiers.
    init(lunettes: LunettesBLE) {
        self.lunettes = lunettes
    }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 16) {
                carteEtat
                carteRecherche
                Carte(titre: "Ce qu'il faut savoir") {
                    NoteVerite(texte: "Le son (micro et haut-parleur des lunettes) se relie dans Réglages › Bluetooth de l'iPhone, comme un casque : iOS ne laisse aucune app faire cet appairage à sa place. Ici, IRIS se relie au canal de commande des lunettes : présence, batterie, caméra.")
                    NoteVerite(texte: "Caméra : la commande photo des lunettes n'est pas encore confirmée sur le vrai matériel. En attendant, les photos sont prises avec l'iPhone, et chaque écran le dit.")
                    NoteVerite(texte: "Tant que les lunettes sont connectées ici et que l'app IRIS est ouverte, ton ordinateur en est informé toutes les 60 secondes. App fermée ou en arrière-plan depuis plus de 2 minutes et demie, il ne les voit plus.")
                    NoteVerite(texte: "Protocole non prouvé sur tous les modèles : si la batterie reste « inconnue », ces lunettes ne l'annoncent pas par un canal connu d'IRIS.")
                    if !lunettes.servicesVus.isEmpty {
                        Text("Services Bluetooth vus : \(lunettes.servicesVus.joined(separator: ", "))")
                            .font(.caption.monospaced())
                            .foregroundStyle(Couleurs.attenue)
                            .textSelection(.enabled)
                            .accessibilityLabel("Diagnostic : \(lunettes.servicesVus.count) services Bluetooth vus.")
                    }
                }
            }
            .padding()
        }
        .fondIRIS()
        .navigationTitle("Mes lunettes")
        .navigationBarTitleDisplayMode(.inline)
        .onDisappear { lunettes.arreterRecherche() }
        .confirmationDialog("Oublier ces lunettes sur cet iPhone ?", isPresented: $confirmationOubli, titleVisibility: .visible) {
            Button("Oublier", role: .destructive) { lunettes.oublier() }
        } message: {
            Text("L'iPhone ne les reliera plus automatiquement. Tu pourras les rechercher de nouveau.")
        }
    }

    // MARK: - État

    private var carteEtat: some View {
        let etat = lunettes.etat
        return Carte(titre: "État") {
            HStack(spacing: 12) {
                Image(systemName: "eyeglasses")
                    .font(.largeTitle)
                    .foregroundStyle(etat.connectees ? Couleurs.vert : Couleurs.attenue)
                    .accessibilityHidden(true)
                VStack(alignment: .leading, spacing: 2) {
                    Text(etat.connectees ? (etat.nom ?? "Lunettes connectées") : "Lunettes non connectées")
                        .font(.headline)
                        .foregroundStyle(Couleurs.texte)
                    if etat.connectees {
                        Text(etat.batterie.map { "Batterie : \($0) %" } ?? "Batterie inconnue")
                            .foregroundStyle(Couleurs.texte2)
                        Text(etat.cameraConfirmee ? "Caméra des lunettes utilisable." : (lunettes.cameraExposee
                            ? "Caméra repérée, commande photo non confirmée."
                            : "Aucune caméra repérée sur ce modèle."))
                            .font(.subheadline)
                            .foregroundStyle(Couleurs.attenue)
                    } else if let memorisee = lunettes.paireMemorisee {
                        Text("Paire retenue : \(memorisee)")
                            .font(.subheadline)
                            .foregroundStyle(Couleurs.attenue)
                    }
                }
            }
            .accessibilityElement(children: .combine)

            if let message = etat.message {
                NoteVerite(texte: message, genre: etat.connectees ? .limite : .avertissement)
            }
            if etat.connectees {
                Button("Déconnecter") { lunettes.deconnecter() }
                    .buttonStyle(.holo(.sombre, compact: true))
                    .accessibilityHint("L'iPhone ne les reliera plus automatiquement jusqu'à la prochaine connexion.")
            }
            if lunettes.paireMemorisee != nil {
                Button("Oublier ces lunettes", role: .destructive) { confirmationOubli = true }
                    .font(.subheadline)
            }
        }
    }

    // MARK: - Recherche

    private var carteRecherche: some View {
        Carte(titre: "Rechercher") {
            Button {
                if lunettes.rechercheEnCours {
                    lunettes.arreterRecherche()
                } else {
                    erreur = nil
                    lunettes.rechercher()
                    Annonce.voiceOver("Recherche des lunettes pendant 15 secondes.")
                }
            } label: {
                if lunettes.rechercheEnCours {
                    HStack(spacing: 10) {
                        ProgressView().tint(Couleurs.fond)
                        Text("Recherche… (touche pour arrêter)")
                    }
                } else {
                    Label("Rechercher mes lunettes", systemImage: "antenna.radiowaves.left.and.right")
                }
            }
            .buttonStyle(.holo)
            .disabled(connexionVers != nil)

            Text("Allume les lunettes ou sors-les de l'étui, et garde-les à moins de 2 mètres.")
                .font(.footnote)
                .foregroundStyle(Couleurs.attenue)

            ForEach(lunettes.appareilsTrouves) { appareil in
                Button {
                    Task { await connecter(appareil) }
                } label: {
                    HStack {
                        VStack(alignment: .leading, spacing: 2) {
                            Text(appareil.nom).font(.headline).foregroundStyle(Couleurs.texte)
                            Text(signal(appareil.rssi)).font(.caption).foregroundStyle(Couleurs.attenue)
                        }
                        Spacer()
                        if connexionVers == appareil.id {
                            ProgressView()
                        } else if lunettes.etat.connectees && lunettes.etat.identifiant == appareil.id {
                            Image(systemName: "checkmark.circle.fill").foregroundStyle(Couleurs.vert)
                                .accessibilityHidden(true)
                        }
                    }
                    .padding(12)
                    .background(Couleurs.carte2, in: RoundedRectangle(cornerRadius: 12))
                }
                .buttonStyle(.plain)
                .disabled(connexionVers != nil)
                .accessibilityElement(children: .combine)
                .accessibilityLabel("\(appareil.nom), \(signal(appareil.rssi))")
                .accessibilityHint("Relie ces lunettes à l'iPhone.")
            }

            if let message = lunettes.derniereErreur {
                NoteVerite(texte: message, genre: .avertissement)
            }
            if let erreur {
                NoteVerite(texte: erreur.localizedDescription, genre: .erreur)
            }
        }
    }

    private func signal(_ rssi: Int?) -> String {
        guard let rssi else { return "déjà reliées à l'iPhone" }
        if rssi > -60 { return "signal fort, tout près" }
        if rssi > -78 { return "signal moyen" }
        return "signal faible, loin"
    }

    private func connecter(_ appareil: AppareilLunettes) async {
        connexionVers = appareil.id
        defer { connexionVers = nil }
        erreur = nil
        do {
            try await lunettes.connecter(appareil)
            Haptique.succes()
            Annonce.voiceOver("Lunettes connectées : \(appareil.nom).")
        } catch {
            erreur = error
            Annonce.voiceOver(error.localizedDescription)
        }
    }
}
