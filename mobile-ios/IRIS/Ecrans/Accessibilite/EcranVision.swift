// EcranVision.swift — un écran par mode de vision : Devant moi, Lire, Billets, Objet, Couleur,
// Personnes, Affichage, Écran de l'ordinateur.
//
// Déroulé pensé pour une personne non voyante : un seul grand bouton ; « photo en cours » annoncé ; le
// résultat prend le focus VoiceOver (ou est lu par la voix d'IRIS si VoiceOver est éteint) ; sous le
// résultat, tout ce qui compte pour lui faire confiance : d'où vient la photo, où s'est fait le travail,
// la durée MESURÉE, et les notes du service telles quelles.

import PhotosUI
import SwiftUI
import UIKit

struct EcranVision: View {
    @Environment(EnvironnementIRIS.self) private var env
    let perception: PerceptionIRIS
    let mode: ModeVisionTelephone

    @State private var question = ""
    @State private var apercu = false
    @State private var analyse: AnalyseVision?
    @State private var erreur: Error?
    @State private var photoChoisie: PhotosPickerItem?
    @AccessibilityFocusState private var focusResultat: Bool

    // Initialiseur explicite : les propriétés privées (@State, @Environment) rendraient l'initialiseur
    // implicite privé, donc inaccessible depuis les autres fichiers.
    init(perception: PerceptionIRIS, mode: ModeVisionTelephone) {
        self.perception = perception
        self.mode = mode
    }

    private var vision: VisionAccessibilite { perception.visionAccessibilite }
    private var estEcran: Bool { mode.id == "ecran" }
    private var questionPermise: Bool { ["scene", "objet", "ecran", "personnes"].contains(mode.id) }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 16) {
                if !env.lunettesPresentes {
                    LunettesRequisesVue(message: "« \(mode.titre) » marche avec les lunettes VELA.")
                }

                Carte {
                    Text(mode.titre)
                        .font(.title2.bold())
                        .foregroundStyle(Couleurs.texte)
                        .accessibilityAddTraits(.isHeader)
                    Text(mode.consigne)
                        .foregroundStyle(Couleurs.texte2)
                    if !estEcran && !perception.lunettesBLE.etat.cameraConfirmee {
                        NoteVerite(texte: VisionAccessibilite.noteSecoursCamera)
                    }
                    if estEcran && !env.pont.etat.estConnecte {
                        NoteVerite(texte: "Ton ordinateur ne répond pas : l'écran à décrire est le sien.", genre: .avertissement)
                    }
                    if apercu && !estEcran {
                        ApercuCamera(camera: perception.camera)
                            .frame(height: 260)
                            .clipShape(RoundedRectangle(cornerRadius: 14, style: .continuous))
                    }
                    if questionPermise {
                        TextField("Question précise (facultatif)", text: $question, axis: .vertical)
                            .lineLimit(1...3)
                            .padding(12)
                            .background(Couleurs.carte2, in: RoundedRectangle(cornerRadius: 12))
                            .accessibilityHint("Par exemple : est-ce qu'il y a une porte ?")
                    }

                    Button {
                        Task { await lancer(source: estEcran ? .ecranPC : .lunettes, strategie: .auto) }
                    } label: {
                        if vision.enCours {
                            HStack(spacing: 10) {
                                ProgressView().tint(Couleurs.fond)
                                Text(vision.etape ?? "Analyse…")
                            }
                        } else {
                            Label(mode.bouton, systemImage: estEcran ? "desktopcomputer" : "camera.fill")
                        }
                    }
                    .buttonStyle(.holo)
                    .disabled(vision.enCours || !env.lunettesPresentes)
                    .accessibilityHint(estEcran
                                       ? "Ton ordinateur décrit son écran ; le résultat sera lu."
                                       : "Prend une photo avec l'iPhone ; le résultat sera lu.")

                    if !estEcran {
                        HStack(spacing: 10) {
                            PhotosPicker(selection: $photoChoisie, matching: .images) {
                                Label("Choisir une photo", systemImage: "photo.on.rectangle")
                            }
                            .buttonStyle(.holo(.sombre, compact: true))
                            .disabled(vision.enCours || !env.lunettesPresentes)
                            .accessibilityHint("Décrit une photo déjà prise, choisie dans tes photos.")
                            Spacer(minLength: 0)
                            Toggle("Aperçu", isOn: $apercu)
                                .fixedSize(horizontal: true, vertical: false)
                                .tint(Couleurs.bleu)
                                .accessibilityHint("Affiche ce que voit la caméra, pour cadrer.")
                        }
                    }
                }

                if let erreur {
                    BandeauErreur(erreur: erreur)
                }

                if let analyse {
                    resultat(analyse)
                }

                Carte(titre: "Limites") {
                    NoteVerite(texte: mode.limite)
                    if !estEcran {
                        NoteVerite(texte: "Rien n'est enregistré sur l'iPhone : la photo reste en mémoire le temps de cet écran. Envoyée à ton ordinateur, elle suit ses réglages de mémoire et de confidentialité.")
                    }
                }
            }
            .padding()
        }
        .fondIRIS()
        .navigationTitle(mode.court)
        .navigationBarTitleDisplayMode(.inline)
        .onChange(of: photoChoisie) { _, element in
            guard let element else { return }
            photoChoisie = nil
            Task { await chargerPhoto(element) }
        }
        .onChange(of: apercu) { _, actif in
            if actif {
                Task {
                    do {
                        try await perception.camera.demarrer(pour: "apercu")
                    } catch {
                        erreur = error
                        apercu = false
                    }
                }
            } else {
                perception.camera.arreter(pour: "apercu")
            }
        }
        .onDisappear {
            if apercu { perception.camera.arreter(pour: "apercu") }
        }
    }

    // MARK: - Résultat

    @ViewBuilder
    private func resultat(_ analyse: AnalyseVision) -> some View {
        let r = analyse.resultat
        VStack(alignment: .leading, spacing: 10) {
            Text(analyse.parOrdinateur ? "Réponse d'IRIS" : "Analyse sur cet iPhone")
                .font(.footnote.weight(.semibold))
                .foregroundStyle(Couleurs.fond.opacity(0.7))
                .accessibilityHidden(true)
            Text(r.texte)
                .font(.title3.weight(.semibold))
                .foregroundStyle(Couleurs.fond)
                .textSelection(.enabled)
                .fixedSize(horizontal: false, vertical: true)
                .accessibilityLabel(r.texte)
                .accessibilityFocused($focusResultat)
            HStack(spacing: 10) {
                Button("Relire") {
                    Task { await env.voix.parler(r.texte) }
                }
                .buttonStyle(.holo(.blanc, compact: true))
                .accessibilityHint("Lit le résultat avec la voix d'IRIS.")
                Button("Arrêter la lecture") {
                    env.voix.arreterParole()
                }
                .buttonStyle(.holo(.sombre, compact: true))
            }
        }
        .padding(18)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(Couleurs.holo, in: RoundedRectangle(cornerRadius: 20, style: .continuous))

        Carte(titre: "D'où vient cette réponse") {
            Text(provenance(analyse))
                .foregroundStyle(Couleurs.texte2)
            Text(mesure(analyse))
                .font(.footnote)
                .foregroundStyle(Couleurs.attenue)
            if let secours = analyse.noteSecours {
                NoteVerite(texte: secours)
            }
            if let note = r.note, !note.isEmpty {
                NoteVerite(texte: note, genre: analyse.parOrdinateur ? .limite : .avertissement)
            }
            if let suspendue = r.memoireSuspendue, !suspendue.isEmpty {
                NoteVerite(texte: "Mémoire suspendue (\(suspendue)) : cette description n'a pas été retenue.")
            }
            if !analyse.parOrdinateur, let image = analyse.image, env.pont.etat.estConnecte, env.reglages?.localOnly != true {
                Button {
                    Task { await lancer(source: .image(image), strategie: .ordinateur) }
                } label: {
                    Label("Demander à IRIS sur l'ordinateur", systemImage: "sparkles")
                }
                .buttonStyle(.holo(.sombre, compact: true))
                .disabled(vision.enCours)
                .accessibilityHint("Envoie la même photo à ton ordinateur pour une lecture plus fine.")
            }
        }
    }

    private func provenance(_ analyse: AnalyseVision) -> String {
        let photo: String
        switch analyse.provenance {
        case .lunettes?: photo = "Photo prise par la caméra des lunettes."
        case .telephone?: photo = "Photo prise avec la caméra de l'iPhone."
        case .bibliotheque?: photo = "Photo choisie dans tes photos."
        case nil: photo = "Capture de l'écran de ton ordinateur."
        }
        let travail: String
        if !analyse.parOrdinateur {
            travail = "Analysée sur cet iPhone, sans envoi."
        } else if analyse.resultat.local == true {
            travail = "Analysée par ton ordinateur, sans le moteur VELA."
        } else {
            travail = "Analysée par ton ordinateur avec le moteur VELA."
        }
        return "\(photo) \(travail)"
    }

    private func mesure(_ analyse: AnalyseVision) -> String {
        var texte = "Mesuré : \(FormatIRIS.secondes(ms: Double(analyse.dureeTotaleMs))) au total sur l'iPhone"
        if analyse.provenance != nil { texte += ", photo comprise" }
        if analyse.parOrdinateur, let travail = analyse.resultat.dureeMs {
            texte += " ; \(FormatIRIS.secondes(ms: Double(travail))) de travail sur l'ordinateur"
        }
        return texte + "."
    }

    // MARK: - Actions

    private func lancer(source: SourceVision, strategie: StrategieVision) async {
        guard !vision.enCours else { return }
        erreur = nil
        env.voix.arreterParole()
        Annonce.voiceOver(estEcran ? "Description de l'écran en cours." : "Photo en cours, ne bouge pas.")
        do {
            let nouvelle = try await vision.analyser(mode: mode.id, source: source,
                                                     question: questionPermise ? question : nil, strategie: strategie)
            analyse = nouvelle
            Haptique.succes()
            if UIAccessibility.isVoiceOverRunning {
                // Le focus fait lire le résultat par VoiceOver, au débit choisi par l'utilisateur.
                focusResultat = true
            } else {
                Task { await env.voix.parler(nouvelle.resultat.texte) }
            }
        } catch {
            erreur = error
            Annonce.voiceOver(error.localizedDescription)
        }
    }

    private func chargerPhoto(_ element: PhotosPickerItem) async {
        do {
            guard let donnees = try await element.loadTransferable(type: Data.self) else {
                erreur = ErreurPont.refus(statut: 422, message: "Cette photo n'a pas pu être lue.", detail: nil)
                return
            }
            let image = ImageCapturee(donnees: donnees, typeMedia: "image/jpeg", provenance: .bibliotheque)
            await lancer(source: .image(image), strategie: .auto)
        } catch {
            erreur = error
        }
    }
}
