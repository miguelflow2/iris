// EcranAccessibilite.swift — l'onglet Accessibilité de l'iPhone : voir, lire, entendre, se déplacer,
// partager sa vue. Chaque ligne dit où se fait le travail (sur l'iPhone ou sur l'ordinateur) ; ce qui
// n'est pas livré est écrit en bas, tel quel.
//
// Lunettes d'abord : sans lunettes VELA présentes, l'invitation à les connecter est en tête et les
// fonctions de capture refusent de démarrer (chaque écran le redit). Une fonction déjà en cours (alertes,
// guidage, partage) n'est pas coupée net par la disparition des lunettes : on peut toujours l'arrêter
// d'ici. Les alertes sonores, elles, s'arrêtent seules après 10 minutes sans lunettes, et le disent.

import SwiftUI
import UIKit

@MainActor
struct EcranAccessibilite: View {
    @Environment(EnvironnementIRIS.self) private var env
    let perception: PerceptionIRIS
    @State private var appairage = false

    private let modesVoir = ["scene", "lecture", "billets", "objet", "couleur", "personnes", "affichage"]

    // Initialiseur explicite : les propriétés privées (@State, @Environment) rendraient l'initialiseur
    // implicite privé, donc inaccessible depuis les autres fichiers.
    init(perception: PerceptionIRIS) {
        self.perception = perception
    }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 16) {
                carteLunettes
                enCours

                if !env.lunettesPresentes {
                    LunettesRequisesVue(message: "Voir, lire, les sous-titres, les alertes, le guidage et le partage de ta vue marchent avec les lunettes VELA.")
                }

                Carte(titre: "Voir et lire") {
                    ForEach(modesVoir, id: \.self) { id in
                        if let mode = ModeVisionTelephone.pour(id) {
                            NavigationLink {
                                EcranVision(perception: perception, mode: mode)
                            } label: {
                                LigneAccessibilite(icone: mode.icone, titre: mode.titre,
                                                   detail: mode.localDabord
                                                       ? "Sur l'iPhone d'abord, sans envoi."
                                                       : "Avec ton ordinateur ; repli limité sur l'iPhone.")
                            }
                            .buttonStyle(.plain)
                        }
                    }
                }

                Carte(titre: "Entendre") {
                    NavigationLink {
                        EcranSousTitres(perception: perception)
                    } label: {
                        LigneAccessibilite(icone: "captions.bubble", titre: "Sous-titres en direct",
                                           detail: "Ce qui est dit, écrit en très grand. Sur l'iPhone, sans envoi.")
                    }
                    .buttonStyle(.plain)
                    NavigationLink {
                        EcranAlertes(perception: perception)
                    } label: {
                        LigneAccessibilite(icone: "ear.trianglebadge.exclamationmark", titre: "Alertes sonores",
                                           detail: "Alarme, sirène, klaxon, sonnette : vibration, notification et voix.")
                    }
                    .buttonStyle(.plain)
                }

                Carte(titre: "Se déplacer") {
                    NavigationLink {
                        EcranGuidage(perception: perception)
                    } label: {
                        LigneAccessibilite(icone: "figure.walk", titre: "Guide-moi",
                                           detail: "Itinéraire à pied, consignes dites étape par étape.")
                    }
                    .buttonStyle(.plain)
                    NavigationLink {
                        EcranOuSuisJe(perception: perception)
                    } label: {
                        LigneAccessibilite(icone: "location", titre: "Où suis-je ?",
                                           detail: "L'adresse la plus proche, avec la précision du GPS.")
                    }
                    .buttonStyle(.plain)
                }

                Carte(titre: "Avec un proche") {
                    NavigationLink {
                        EcranPartageVue(perception: perception)
                    } label: {
                        LigneAccessibilite(icone: "person.2.wave.2", titre: "Partager ma vue",
                                           detail: "Un proche voit ce que filme l'iPhone et peut t'écrire.")
                    }
                    .buttonStyle(.plain)
                }

                Carte(titre: "Mémoire et ordinateur") {
                    NavigationLink {
                        EcranOuEst(perception: perception)
                    } label: {
                        LigneAccessibilite(icone: "magnifyingglass", titre: "Où ai-je posé… ?",
                                           detail: "Cherche dans ce qu'IRIS a vu ou entendu, sur ton ordinateur.")
                    }
                    .buttonStyle(.plain)
                    if let ecran = ModeVisionTelephone.pour("ecran") {
                        NavigationLink {
                            EcranVision(perception: perception, mode: ecran)
                        } label: {
                            LigneAccessibilite(icone: ecran.icone, titre: ecran.titre,
                                               detail: "Ton ordinateur capture et décrit son propre écran.")
                        }
                        .buttonStyle(.plain)
                    }
                }

                Carte(titre: "Ce qui n'est pas livré") {
                    ForEach(TexteAccessibilite.nonLivre, id: \.self) { texte in
                        TexteAccessibilite.puce(texte)
                    }
                }
            }
            .padding()
        }
        .fondIRIS()
        .navigationTitle("Accessibilité")
        .sheet(isPresented: $appairage) {
            NavigationStack {
                EcranLunettes(lunettes: perception.lunettesBLE)
                    .toolbar {
                        ToolbarItem(placement: .cancellationAction) {
                            Button("Fermer") { appairage = false }
                        }
                    }
            }
            .preferredColorScheme(.dark)
        }
        // Le plein écran des alertes est affiché par la racine de l'app (RacineVue), pour tous les onglets.
    }

    // MARK: - Lunettes

    private var carteLunettes: some View {
        let etat = perception.lunettesBLE.etat
        return Button {
            appairage = true
        } label: {
            HStack(spacing: 12) {
                Image(systemName: "eyeglasses")
                    .font(.title2)
                    .foregroundStyle(etat.connectees && etat.verifiees ? Couleurs.vert : Couleurs.attenue)
                    .accessibilityHidden(true)
                VStack(alignment: .leading, spacing: 2) {
                    Text(titreLunettes(etat))
                        .font(.headline)
                        .foregroundStyle(Couleurs.texte)
                    Text(detailLunettes(etat))
                        .font(.subheadline)
                        .foregroundStyle(Couleurs.attenue)
                        .multilineTextAlignment(.leading)
                }
                Spacer(minLength: 0)
                Image(systemName: "chevron.right")
                    .foregroundStyle(Couleurs.attenue)
                    .accessibilityHidden(true)
            }
            .padding(14)
            .background(Couleurs.carte, in: RoundedRectangle(cornerRadius: 16, style: .continuous))
        }
        .buttonStyle(.plain)
        .accessibilityElement(children: .combine)
        .accessibilityHint("Ouvre la connexion des lunettes.")
    }

    private func titreLunettes(_ etat: EtatLunettes) -> String {
        if etat.connectees && !etat.verifiees { return "Appareil relié non reconnu" }
        if etat.connectees { return etat.nom ?? "Lunettes connectées" }
        if env.lunettesPresentes { return "Lunettes vues par ton ordinateur" }
        return "Lunettes non connectées à cet iPhone"
    }

    private func detailLunettes(_ etat: EtatLunettes) -> String {
        if etat.connectees && !etat.verifiees {
            return etat.message ?? "Vérification de l'appareil en cours : IRIS attend ses services Bluetooth."
        }
        if etat.connectees && !env.lunettesPresentes, let refus = env.attestation.erreur {
            return "Ton ordinateur refuse ces lunettes : \(refus)"
        }
        if etat.connectees {
            let batterie = etat.batterie.map { "Batterie \($0) %" } ?? "Batterie inconnue"
            let camera = etat.cameraConfirmee
                ? "Caméra des lunettes utilisable."
                : "Caméra : photos prises avec l'iPhone en attendant."
            return "\(batterie). \(camera)"
        }
        return etat.message ?? "Touche pour les connecter."
    }

    // MARK: - Fonctions en cours

    @ViewBuilder
    private var enCours: some View {
        if perception.alertesSonores.actives {
            BandeauEnCours(icone: "ear.fill", texte: "Alertes sonores actives", action: "Arrêter") {
                perception.alertesSonores.desactiver()
            }
        }
        if perception.guidageAPied.guidageActif {
            BandeauEnCours(icone: "figure.walk", texte: "Guidage vers \(perception.guidageAPied.destinationNom ?? "ta destination")",
                           action: "Arrêter") {
                perception.guidageAPied.arreterGuidage()
            }
        }
        if perception.partageVue.phase == .actif {
            BandeauEnCours(icone: "person.2.wave.2.fill", texte: "Partage de ta vue en cours", action: "Arrêter") {
                Task { await perception.partageVue.arreter() }
            }
        }
    }
}

// MARK: - Où ai-je posé… ?

@MainActor
struct EcranOuEst: View {
    @Environment(EnvironnementIRIS.self) private var env
    let perception: PerceptionIRIS
    @State private var question = ""
    @State private var reponse: ReponseOuEst?
    @State private var erreur: Error?
    @State private var enCours = false
    @State private var ecoute = false
    @AccessibilityFocusState private var focusReponse: Bool

    // Initialiseur explicite : les propriétés privées (@State, @Environment) rendraient l'initialiseur
    // implicite privé, donc inaccessible depuis les autres fichiers.
    init(perception: PerceptionIRIS) {
        self.perception = perception
    }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 16) {
                Carte {
                    Text("IRIS cherche dans ce qu'elle a réellement décrit ou entendu, et dans ce que tu lui as dit. Elle ne devine jamais un lieu.")
                        .foregroundStyle(Couleurs.texte2)
                    TextField("Par exemple : mes clés", text: $question)
                        .textInputAutocapitalization(.never)
                        .submitLabel(.search)
                        .onSubmit { Task { await chercher() } }
                        .padding(12)
                        .background(Couleurs.carte2, in: RoundedRectangle(cornerRadius: 12))
                        .accessibilityLabel("Objet à retrouver")
                    HStack(spacing: 10) {
                        Button {
                            Task { await chercher() }
                        } label: {
                            if enCours { ProgressView().tint(Couleurs.fond) } else { Label("Chercher", systemImage: "magnifyingglass") }
                        }
                        .buttonStyle(.holo)
                        .disabled(enCours || question.trimmingCharacters(in: .whitespaces).isEmpty)

                        Button {
                            Task { await dicter() }
                        } label: {
                            Label(ecoute ? "J'écoute…" : "Dicter", systemImage: "mic.fill")
                        }
                        .buttonStyle(.holo(.sombre, compact: true))
                        .disabled(enCours || !env.lunettesPresentes)
                        .accessibilityHint(env.lunettesPresentes ? "Dis le nom de l'objet." : "La dictée marche avec les lunettes VELA.")
                    }
                }

                if let erreur {
                    BandeauErreur(erreur: erreur)
                }

                if let reponse {
                    Carte(titre: "Réponse") {
                        Text(reponse.reponse)
                            .font(.title3.weight(.semibold))
                            .foregroundStyle(Couleurs.texte)
                            .textSelection(.enabled)
                            .accessibilityFocused($focusReponse)
                        if let souvenirs = reponse.souvenirs, !souvenirs.isEmpty {
                            Text("Souvenirs utilisés")
                                .font(.footnote.weight(.semibold))
                                .foregroundStyle(Couleurs.attenue)
                                .accessibilityAddTraits(.isHeader)
                            ForEach(souvenirs) { souvenir in
                                VStack(alignment: .leading, spacing: 2) {
                                    if let date = souvenir.date {
                                        Text(date).font(.caption).foregroundStyle(Couleurs.attenue)
                                    }
                                    Text(souvenir.texte).foregroundStyle(Couleurs.texte2)
                                }
                                .accessibilityElement(children: .combine)
                            }
                        }
                        if let note = reponse.note {
                            NoteVerite(texte: note)
                        }
                        NoteVerite(texte: reponse.local == false
                                   ? "Formulé par le moteur VELA à partir de tes souvenirs datés."
                                   : "Souvenir rendu tel quel, sans le moteur VELA.")
                    }
                }

                // Pas « marche sans lunettes » : l'ordinateur exige aujourd'hui les lunettes sur cette route
                // (routes_accessibilite.py, exiger_lunettes « ou_est »). Phrase à rétablir quand il ne le fera plus.
                NoteVerite(texte: "Il faut que ton ordinateur réponde : la mémoire vit sur lui. L'objet a pu être déplacé depuis le souvenir.")
            }
            .padding()
        }
        .fondIRIS()
        .navigationTitle("Où ai-je posé… ?")
        .navigationBarTitleDisplayMode(.inline)
    }

    private func chercher() async {
        let texte = question.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !texte.isEmpty, !enCours else { return }
        enCours = true
        defer { enCours = false }
        erreur = nil
        do {
            let r = try await perception.visionAccessibilite.ouEst(texte)
            reponse = r
            if UIAccessibility.isVoiceOverRunning {
                focusReponse = true
            } else {
                Task { await env.voix.parler(r.reponse) }
            }
        } catch {
            erreur = error
            Annonce.voiceOver(error.localizedDescription)
        }
    }

    private func dicter() async {
        guard !ecoute else {
            env.voix.annulerEcoute()
            return
        }
        ecoute = true
        defer { ecoute = false }
        do {
            let phrase = try await env.voix.ecouterUnePhrase(langue: env.voix.langueIRIS, delaiMax: 8)
            question = phrase
            await chercher()
        } catch {
            if case ErreurVoix.interrompu? = error as? ErreurVoix { return }
            erreur = error
        }
    }
}
