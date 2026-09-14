// EcranSousTitres.swift — sous-titres en direct, en texte géant et de taille réglable.
//
// L'écoute s'arrête quand on quitte l'écran : rien ne tourne caché. L'écran reste allumé pendant les
// sous-titres. La dernière phrase, encore en cours de reconnaissance, est en blanc vif ; les phrases closes
// sont en gris clair.

import SwiftUI
import UIKit

struct EcranSousTitres: View {
    @Environment(EnvironnementIRIS.self) private var env
    let perception: PerceptionIRIS
    @State private var erreur: Error?
    @State private var bascule = false

    // Initialiseur explicite : les propriétés privées (@State, @Environment) rendraient l'initialiseur
    // implicite privé, donc inaccessible depuis les autres fichiers.
    init(perception: PerceptionIRIS) {
        self.perception = perception
    }

    private var sousTitres: SousTitresTelephone { perception.sousTitres }

    var body: some View {
        VStack(spacing: 0) {
            controles
                .padding()
                .background(Couleurs.fond2)

            ScrollViewReader { lecteur in
                ScrollView {
                    LazyVStack(alignment: .leading, spacing: 14) {
                        if sousTitres.lignes.isEmpty && sousTitres.partiel.isEmpty {
                            Text(sousTitres.actif ? "J'écoute…" : "Touche « Démarrer » : ce qui est dit s'écrira ici.")
                                .font(.system(size: min(sousTitres.taille, 34), weight: .semibold))
                                .foregroundStyle(Couleurs.attenue)
                        }
                        ForEach(sousTitres.lignes) { ligne in
                            Text(ligne.texte)
                                .font(.system(size: sousTitres.taille, weight: .semibold))
                                .foregroundStyle(Couleurs.texte2)
                                .fixedSize(horizontal: false, vertical: true)
                                .id(ligne.id)
                        }
                        if !sousTitres.partiel.isEmpty {
                            Text(sousTitres.partiel)
                                .font(.system(size: sousTitres.taille, weight: .bold))
                                .foregroundStyle(Couleurs.texte)
                                .fixedSize(horizontal: false, vertical: true)
                                .accessibilityAddTraits(.updatesFrequently)
                                .accessibilityLabel("En cours : \(sousTitres.partiel)")
                        }
                        Color.clear
                            .frame(height: 1)
                            .id("bas")
                            .accessibilityHidden(true)
                    }
                    .padding()
                }
                .onChange(of: sousTitres.lignes.count) {
                    withAnimation(.easeOut(duration: 0.2)) { lecteur.scrollTo("bas", anchor: .bottom) }
                }
                .onChange(of: sousTitres.partiel) {
                    lecteur.scrollTo("bas", anchor: .bottom)
                }
            }

            NoteVerite(texte: SousTitresTelephone.limite)
                .padding(.horizontal)
                .padding(.vertical, 8)
                .background(Couleurs.fond2)
        }
        .background(Couleurs.fond.ignoresSafeArea())
        .navigationTitle("Sous-titres")
        .navigationBarTitleDisplayMode(.inline)
        .onDisappear { sousTitres.arreter() }
    }

    private var controles: some View {
        VStack(alignment: .leading, spacing: 10) {
            if !env.lunettesPresentes && !sousTitres.actif {
                LunettesRequisesVue(message: "Les sous-titres marchent avec les lunettes VELA.")
            }
            HStack(spacing: 10) {
                Button {
                    Task { await basculer() }
                } label: {
                    Label(sousTitres.actif ? "Arrêter" : "Démarrer",
                          systemImage: sousTitres.actif ? "stop.fill" : "captions.bubble.fill")
                }
                .buttonStyle(.holo(sousTitres.actif ? .rouge : .holo, compact: true))
                .disabled(bascule || (!sousTitres.actif && !env.lunettesPresentes))
                .accessibilityHint(sousTitres.actif ? "Arrête l'écoute." : "Écoute et écrit ce qui est dit.")

                Menu {
                    Picker("Langue", selection: Binding(get: { sousTitres.langue },
                                                        set: { sousTitres.choisirLangue($0) })) {
                        ForEach(SousTitresTelephone.langues, id: \.code) { langue in
                            Text(langue.nom).tag(langue.code)
                        }
                    }
                } label: {
                    Label(SousTitresTelephone.langues.first { $0.code == sousTitres.langue }?.nom ?? "Langue",
                          systemImage: "globe")
                        .font(.subheadline.weight(.semibold))
                }
                .disabled(sousTitres.actif)
                .accessibilityLabel("Langue parlée : \(SousTitresTelephone.langues.first { $0.code == sousTitres.langue }?.nom ?? sousTitres.langue)")
                .accessibilityHint(sousTitres.actif ? "Arrête d'abord les sous-titres pour changer de langue." : "")

                Spacer(minLength: 0)

                ShareLink(item: sousTitres.texteComplet) {
                    Image(systemName: "square.and.arrow.up")
                }
                .disabled(sousTitres.lignes.isEmpty)
                .accessibilityLabel("Partager le texte")

                Button {
                    sousTitres.effacer()
                    Annonce.voiceOver("Texte effacé.")
                } label: {
                    Image(systemName: "trash")
                }
                .disabled(sousTitres.lignes.isEmpty && sousTitres.partiel.isEmpty)
                .accessibilityLabel("Effacer le texte")
            }

            HStack(spacing: 10) {
                Image(systemName: "textformat.size.smaller").accessibilityHidden(true)
                Slider(value: Binding(get: { sousTitres.taille }, set: { sousTitres.choisirTaille($0) }),
                       in: 20...120, step: 2)
                    .accessibilityLabel("Taille du texte")
                    .accessibilityValue("\(Int(sousTitres.taille)) points")
                Image(systemName: "textformat.size.larger").accessibilityHidden(true)
            }
            .foregroundStyle(Couleurs.texte2)

            if sousTitres.actif && sousTitres.attenteMicro {
                NoteVerite(texte: "En attente du micro : aucun son n'arrive.", genre: .avertissement)
            }
            if let interruption = perception.micro.interruption {
                NoteVerite(texte: interruption, genre: .avertissement)
            }
            if let message = sousTitres.erreur {
                NoteVerite(texte: message, genre: .erreur)
            }
            if let erreur {
                BandeauErreur(erreur: erreur)
            }
        }
    }

    private func basculer() async {
        guard !bascule else { return }
        bascule = true
        defer { bascule = false }
        erreur = nil
        if sousTitres.actif {
            sousTitres.arreter()
            Annonce.voiceOver("Sous-titres arrêtés.")
            return
        }
        do {
            try await sousTitres.demarrer()
            Annonce.voiceOver("Sous-titres démarrés.")
        } catch {
            erreur = error
            Annonce.voiceOver(error.localizedDescription)
        }
    }
}
