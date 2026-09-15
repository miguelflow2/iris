// EcranPartageVue.swift — « Partager ma vue » : démarrer, envoyer le lien, voir ce qui est mesuré,
// lire les messages du proche, prolonger, arrêter.
//
// Le partage continue quand on quitte l'écran (bandeau « en cours » dans l'onglet Accessibilité) : un
// proche est peut-être en train d'aider. Arrêter reste toujours possible, lunettes présentes ou non.

import SwiftUI
import UIKit

@MainActor
struct EcranPartageVue: View {
    @Environment(EnvironnementIRIS.self) private var env
    let perception: PerceptionIRIS
    @AccessibilityFocusState private var focusCode: Bool

    // Initialiseur explicite : les propriétés privées (@State, @Environment) rendraient l'initialiseur
    // implicite privé, donc inaccessible depuis les autres fichiers.
    init(perception: PerceptionIRIS) {
        self.perception = perception
    }

    private var partage: PartageVueTelephone { perception.partageVue }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 16) {
                if !env.lunettesPresentes && partage.phase == .repos {
                    LunettesRequisesVue(message: "Le partage de ta vue marche avec les lunettes VELA.")
                }

                Carte {
                    switch partage.phase {
                    case .repos:
                        Text("Ton proche verra, dans son navigateur, ce que filme la caméra arrière de l'iPhone, quelques images par seconde. Il pourra t'écrire : ses messages seront lus à voix haute.")
                            .foregroundStyle(Couleurs.texte2)
                        Button {
                            Task { await partage.demarrer() }
                        } label: {
                            Label("Démarrer le partage", systemImage: "video.fill")
                        }
                        .buttonStyle(.holo)
                        .disabled(!env.lunettesPresentes)
                        .accessibilityHint("Ouvre la caméra, puis ton ordinateur crée un lien à envoyer à ton proche.")

                    case .demarrage(let etape):
                        HStack(spacing: 10) {
                            ProgressView()
                            Text(etape).foregroundStyle(Couleurs.texte2)
                        }
                        .accessibilityElement(children: .combine)

                    case .actif:
                        enCours
                    }

                    if let statut = partage.statut {
                        NoteVerite(texte: statut)
                    }
                    if let erreur = partage.erreur {
                        BandeauErreur(erreur: erreur)
                    }
                }

                NoteVerite(texte: PartageVueTelephone.noteSecours)

                if !partage.messages.isEmpty {
                    Carte(titre: "Messages de ton proche") {
                        ForEach(partage.messages.reversed()) { message in
                            VStack(alignment: .leading, spacing: 2) {
                                Text(message.date.formatted(date: .omitted, time: .shortened))
                                    .font(.caption)
                                    .foregroundStyle(Couleurs.attenue)
                                Text(message.texte)
                                    .font(.title3)
                                    .foregroundStyle(Couleurs.texte)
                            }
                            .accessibilityElement(children: .combine)
                        }
                        NoteVerite(texte: "Messages gardés en mémoire vive le temps du partage seulement.")
                    }
                }

                Carte(titre: "Limites") {
                    NoteVerite(texte: PartageVueTelephone.limiteLocale)
                    if let note = partage.noteServeur {
                        NoteVerite(texte: note)
                    }
                    ForEach(partage.limitesServeur, id: \.self) { limite in
                        NoteVerite(texte: limite)
                    }
                    if partage.limitesServeur.isEmpty {
                        NoteVerite(texte: "Trois personnes au plus peuvent regarder. Le lien expire 30 minutes après sa création, sauf si tu le prolonges. Toute personne qui a le lien peut regarder tant qu'il est valide : ne le donne qu'à quelqu'un de confiance.")
                    }
                }
            }
            .padding()
        }
        .fondIRIS()
        .navigationTitle("Partager ma vue")
        .navigationBarTitleDisplayMode(.inline)
    }

    @ViewBuilder
    private var enCours: some View {
        ApercuCamera(camera: perception.camera)
            .frame(height: 260)
            .clipShape(RoundedRectangle(cornerRadius: 14, style: .continuous))
            .accessibilityLabel("Aperçu de ce que voit ton proche")

        if let code = partage.code {
            VStack(alignment: .leading, spacing: 2) {
                Text("Code du partage")
                    .font(.footnote.weight(.semibold))
                    .foregroundStyle(Couleurs.attenue)
                Text(PartageVueTelephone.codeEpele(code))
                    .font(.system(size: 30, weight: .bold, design: .monospaced))
                    .foregroundStyle(Couleurs.texte)
                    .textSelection(.enabled)
            }
            .accessibilityElement(children: .combine)
            .accessibilityLabel("Code du partage : \(PartageVueTelephone.codeEpele(code))")
            .accessibilityFocused($focusCode)
            .onAppear { focusCode = UIAccessibility.isVoiceOverRunning }
        }

        if let url = partage.urlSpectateur {
            ShareLink(item: url,
                      subject: Text("Vision partagée"),
                      message: Text("Voici le lien pour voir ce que je vois, avec IRIS. Il expire dans 30 minutes.")) {
                Label("Envoyer le lien à mon proche", systemImage: "square.and.arrow.up")
            }
            .buttonStyle(.holo)
        }

        VStack(alignment: .leading, spacing: 6) {
            ligne("Personnes qui regardent", "\(partage.spectateurs)")
            ligne("Images envoyées", "\(partage.imagesEnvoyees)")
            ligne("Cadence reçue par le relais (mesurée)",
                  "\(NombresFr.decimal(partage.cadenceRelais)) image\(partage.cadenceRelais >= 2 ? "s" : "")/s")
            ligne("Cadence visée par l'iPhone", "\(NombresFr.entier(partage.cadenceVisee)) images/s au plus")
            ligne("Données envoyées", TexteAccessibilite.octets(partage.octetsEnvoyes))
            if let fin = partage.expireFin {
                TimelineView(.periodic(from: .now, by: 1)) { _ in
                    ligne("Expire dans", FormatIRIS.duree(secondes: max(0, fin.timeIntervalSinceNow)))
                }
            }
        }

        HStack(spacing: 10) {
            Button("Prolonger") {
                Task { await partage.prolonger() }
            }
            .buttonStyle(.holo(.sombre, compact: true))
            .accessibilityHint("Garde le lien 30 minutes de plus.")
            Button("Arrêter") {
                Task { await partage.arreter() }
            }
            .buttonStyle(.holo(.rouge, compact: true))
            .accessibilityHint("Ferme le lien : ton proche ne voit plus rien.")
        }

        Toggle("Lire les messages à voix haute", isOn: Binding(get: { partage.lireMessages },
                                                               set: { partage.choisirLectureMessages($0) }))
            .tint(Couleurs.bleu)
            .foregroundStyle(Couleurs.texte)
    }

    private func ligne(_ titre: String, _ valeur: String) -> some View {
        HStack {
            Text(titre).foregroundStyle(Couleurs.texte2)
            Spacer()
            Text(valeur).monospacedDigit().foregroundStyle(Couleurs.texte)
        }
        .font(.subheadline)
        .accessibilityElement(children: .combine)
    }
}
