// EcranGuidage.swift — « Guide-moi » (itinéraire à pied, consignes dites) et « Où suis-je ? ».
//
// Sécurité avant la règle commerciale : un trajet déjà commencé n'est jamais coupé si les lunettes
// disparaissent en route ; seul un NOUVEAU trajet exige de les reconnecter. Le guidage continue quand on
// quitte l'écran (bandeau « en cours » dans l'onglet Accessibilité, avec « Arrêter »).

import MapKit
import SwiftUI
import UIKit

@MainActor
struct EcranGuidage: View {
    @Environment(EnvironnementIRIS.self) private var env
    let perception: PerceptionIRIS

    @State private var destination = ""
    @State private var lieux: [LieuTrouve] = []
    @State private var recherche = false
    @State private var demarrage = false
    @State private var dictee = false
    @State private var erreur: Error?
    @AccessibilityFocusState private var focusConsigne: Bool

    // Initialiseur explicite : les propriétés privées (@State, @Environment) rendraient l'initialiseur
    // implicite privé, donc inaccessible depuis les autres fichiers.
    init(perception: PerceptionIRIS) {
        self.perception = perception
    }

    private var guidage: GuidageAPied { perception.guidageAPied }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 16) {
                if guidage.guidageActif {
                    carteEnCours
                } else {
                    if !env.lunettesPresentes {
                        LunettesRequisesVue(message: "Le guidage marche avec les lunettes VELA.")
                    }
                    if !guidage.accordCartes {
                        CarteAccordCartes(guidage: guidage)
                    }
                    carteDestination
                }

                if let etat = guidage.etatTexte {
                    NoteVerite(texte: etat, genre: .avertissement)
                }
                if let erreur {
                    BandeauErreur(erreur: erreur)
                }

                if !guidage.etapes.isEmpty {
                    Carte(titre: "Étapes") {
                        ForEach(Array(guidage.etapes.enumerated()), id: \.offset) { index, etape in
                            HStack(alignment: .firstTextBaseline, spacing: 8) {
                                Text("\(index + 1).")
                                    .monospacedDigit()
                                    .foregroundStyle(Couleurs.attenue)
                                Text(etape.texte)
                                    .foregroundStyle(guidage.guidageActif && index == guidage.indexEtape ? Couleurs.texte : Couleurs.texte2)
                                    .fontWeight(guidage.guidageActif && index == guidage.indexEtape ? .bold : .regular)
                                Spacer(minLength: 4)
                                Text(TexteAccessibilite.distance(etape.distanceM))
                                    .font(.caption)
                                    .foregroundStyle(Couleurs.attenue)
                            }
                            .accessibilityElement(children: .combine)
                            .accessibilityLabel("Étape \(index + 1)\(guidage.guidageActif && index == guidage.indexEtape ? ", en cours" : "") : \(etape.texte), \(TexteAccessibilite.distance(etape.distanceM))")
                        }
                    }
                }

                Carte(titre: "Limites") {
                    NoteVerite(texte: guidage.limite)
                    NoteVerite(texte: "Écran verrouillé, la position continue (indicateur de position d'iOS) mais iOS peut couper les annonces vocales : garde l'app IRIS ouverte pendant le trajet.")
                    NoteVerite(texte: GuidageAPied.mentionCartes)
                    if guidage.accordCartes && !guidage.guidageActif {
                        Button("Retirer mon accord d'envoi au service de cartes") {
                            guidage.donnerAccordCartes(false)
                            lieux = []
                        }
                        .font(.subheadline)
                    }
                }
            }
            .padding()
        }
        .fondIRIS()
        .navigationTitle("Guide-moi")
        .navigationBarTitleDisplayMode(.inline)
    }

    // MARK: - Choisir la destination

    private var carteDestination: some View {
        Carte(titre: "Destination") {
            TextField("Adresse ou lieu", text: $destination)
                .textContentType(.fullStreetAddress)
                .submitLabel(.search)
                .onSubmit { Task { await chercher() } }
                .padding(12)
                .background(Couleurs.carte2, in: RoundedRectangle(cornerRadius: 12))
                .accessibilityLabel("Adresse ou lieu de destination")
            HStack(spacing: 10) {
                Button {
                    Task { await chercher() }
                } label: {
                    if recherche { ProgressView().tint(Couleurs.fond) } else { Label("Chercher", systemImage: "magnifyingglass") }
                }
                .buttonStyle(.holo)
                .disabled(recherche || demarrage || !guidage.accordCartes || destination.trimmingCharacters(in: .whitespaces).isEmpty)

                Button {
                    Task { await dicter() }
                } label: {
                    Label(dictee ? "J'écoute…" : "Dicter", systemImage: "mic.fill")
                }
                .buttonStyle(.holo(.sombre, compact: true))
                .disabled(recherche || demarrage || !guidage.accordCartes || !env.lunettesPresentes)
                .accessibilityHint("Dis l'adresse ou le nom du lieu.")
            }

            ForEach(lieux) { lieu in
                Button {
                    Task { await demarrer(lieu) }
                } label: {
                    VStack(alignment: .leading, spacing: 2) {
                        Text(lieu.nom).font(.headline).foregroundStyle(Couleurs.texte)
                        if !lieu.adresse.isEmpty {
                            Text(lieu.adresse).font(.subheadline).foregroundStyle(Couleurs.texte2)
                        }
                        if let distance = lieu.distanceM {
                            Text("À vol d'oiseau : \(NombresFr.distance(distance))")
                                .font(.caption)
                                .foregroundStyle(Couleurs.attenue)
                        }
                    }
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(12)
                    .background(Couleurs.carte2, in: RoundedRectangle(cornerRadius: 12))
                }
                .buttonStyle(.plain)
                .disabled(demarrage || !env.lunettesPresentes)
                .accessibilityElement(children: .combine)
                .accessibilityHint("Démarre le guidage à pied vers ce lieu.")
            }
            if demarrage {
                HStack(spacing: 8) {
                    ProgressView()
                    Text("Calcul de l'itinéraire…").foregroundStyle(Couleurs.texte2)
                }
            }
        }
    }

    // MARK: - Pendant le trajet

    private var carteEnCours: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("Vers \(guidage.destinationNom ?? "ta destination")")
                .font(.footnote.weight(.semibold))
                .foregroundStyle(Couleurs.fond.opacity(0.7))
            Text(consigneAffichee)
                .font(.system(size: 30, weight: .bold))
                .foregroundStyle(Couleurs.fond)
                .fixedSize(horizontal: false, vertical: true)
                .accessibilityFocused($focusConsigne)
                .accessibilityAddTraits(.updatesFrequently)
            if let prochaine = guidage.distanceProchaineM {
                Text("Prochaine étape dans \(NombresFr.distance(prochaine))")
                    .font(.title3.weight(.semibold))
                    .foregroundStyle(Couleurs.fond)
            }
            if let reste = guidage.distanceRestanteM {
                Text("Reste environ \(NombresFr.distance(reste)) (estimation)")
                    .foregroundStyle(Couleurs.fond.opacity(0.8))
            }
            if let precision = guidage.precisionM {
                Text("Précision du GPS : environ \(NombresFr.distance(precision))")
                    .font(.footnote)
                    .foregroundStyle(Couleurs.fond.opacity(0.7))
            }
            HStack(spacing: 10) {
                Button("Répéter") { guidage.repeter() }
                    .buttonStyle(.holo(.blanc, compact: true))
                    .accessibilityHint("Redit la consigne en cours.")
                Button("Où suis-je ?") {
                    Task { await ouSuisJe() }
                }
                .buttonStyle(.holo(.blanc, compact: true))
            }
            Button("Arrêter le guidage") {
                guidage.arreterGuidage()
            }
            .buttonStyle(.holo(.rouge))
            if !env.lunettesPresentes {
                Text("Lunettes non détectées : le trajet en cours continue jusqu'à l'arrivée ou l'arrêt.")
                    .font(.footnote)
                    .foregroundStyle(Couleurs.fond.opacity(0.8))
            }
        }
        .padding(18)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(Couleurs.holo, in: RoundedRectangle(cornerRadius: 20, style: .continuous))
    }

    private var consigneAffichee: String {
        if guidage.indexEtape < guidage.etapes.count {
            return guidage.etapes[guidage.indexEtape].texte
        }
        return guidage.derniereConsigne ?? "Continue tout droit."
    }

    // MARK: - Actions

    private func chercher() async {
        let texte = destination.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !texte.isEmpty, !recherche else { return }
        recherche = true
        defer { recherche = false }
        erreur = nil
        do {
            lieux = try await guidage.rechercher(texte)
            Annonce.voiceOver("\(lieux.count) lieu\(lieux.count > 1 ? "x" : "") trouvé\(lieux.count > 1 ? "s" : ""). Choisis ta destination.")
        } catch {
            lieux = []
            erreur = error
            Annonce.voiceOver(error.localizedDescription)
        }
    }

    private func demarrer(_ lieu: LieuTrouve) async {
        guard !demarrage else { return }
        demarrage = true
        defer { demarrage = false }
        erreur = nil
        do {
            try await guidage.guider(vers: lieu)
            lieux = []
            if UIAccessibility.isVoiceOverRunning { focusConsigne = true }
        } catch {
            erreur = error
            Annonce.voiceOver(error.localizedDescription)
        }
    }

    private func dicter() async {
        guard !dictee else {
            env.voix.annulerEcoute()
            return
        }
        dictee = true
        defer { dictee = false }
        do {
            destination = try await env.voix.ecouterUnePhrase(langue: env.voix.langueIRIS, delaiMax: 8)
            await chercher()
        } catch {
            if case ErreurVoix.interrompu? = error as? ErreurVoix { return }
            erreur = error
        }
    }

    private func ouSuisJe() async {
        do {
            let phrase = try await guidage.ouSuisJe()
            Annonce.urgent(phrase, voix: env.voix)
        } catch {
            Annonce.urgent(error.localizedDescription, voix: env.voix)
        }
    }
}

// MARK: - Où suis-je ?

@MainActor
struct EcranOuSuisJe: View {
    @Environment(EnvironnementIRIS.self) private var env
    let perception: PerceptionIRIS
    @State private var phrase: String?
    @State private var erreur: Error?
    @State private var enCours = false
    @AccessibilityFocusState private var focusPhrase: Bool

    // Initialiseur explicite : les propriétés privées (@State, @Environment) rendraient l'initialiseur
    // implicite privé, donc inaccessible depuis les autres fichiers.
    init(perception: PerceptionIRIS) {
        self.perception = perception
    }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 16) {
                if !env.lunettesPresentes {
                    LunettesRequisesVue(message: "« Où suis-je ? » marche avec les lunettes VELA.")
                }
                if !perception.guidageAPied.accordCartes {
                    CarteAccordCartes(guidage: perception.guidageAPied)
                }
                Carte {
                    Button {
                        Task { await chercher() }
                    } label: {
                        if enCours {
                            HStack(spacing: 10) {
                                ProgressView().tint(Couleurs.fond)
                                Text("Recherche de la position…")
                            }
                        } else {
                            Label("Où suis-je ?", systemImage: "location.fill")
                        }
                    }
                    .buttonStyle(.holo)
                    .disabled(enCours || !env.lunettesPresentes || !perception.guidageAPied.accordCartes)
                    .accessibilityHint("Dit l'adresse la plus proche et la précision du GPS.")

                    if let phrase {
                        Text(phrase)
                            .font(.title3.weight(.semibold))
                            .foregroundStyle(Couleurs.texte)
                            .textSelection(.enabled)
                            .fixedSize(horizontal: false, vertical: true)
                            .accessibilityFocused($focusPhrase)
                        Button("Relire") {
                            Task { await env.voix.parler(phrase) }
                        }
                        .buttonStyle(.holo(.sombre, compact: true))
                    }
                    if let erreur {
                        BandeauErreur(erreur: erreur)
                    }
                }
                Carte(titre: "Limites") {
                    NoteVerite(texte: "La position vient du GPS de l'iPhone : de 5 à 50 mètres près, parfois plus entre les grands immeubles ou à l'intérieur. L'adresse est demandée au service de cartes d'iOS (réseau requis). La position n'est envoyée ni à IRIS ni à ton ordinateur, et rien n'est conservé.")
                    NoteVerite(texte: GuidageAPied.mentionCartes)
                }
            }
            .padding()
        }
        .fondIRIS()
        .navigationTitle("Où suis-je ?")
        .navigationBarTitleDisplayMode(.inline)
    }

    private func chercher() async {
        guard !enCours else { return }
        enCours = true
        defer { enCours = false }
        erreur = nil
        do {
            let lue = try await perception.guidageAPied.ouSuisJe()
            phrase = lue
            if UIAccessibility.isVoiceOverRunning {
                focusPhrase = true
            } else {
                Task { await env.voix.parler(lue) }
            }
        } catch {
            erreur = error
            Annonce.voiceOver(error.localizedDescription)
        }
    }
}

/// Accord explicite, une fois sur cet iPhone, avant d'envoyer la position au service de cartes d'iOS.
@MainActor
struct CarteAccordCartes: View {
    let guidage: GuidageAPied

    var body: some View {
        Carte(titre: "Avant de commencer") {
            Text(GuidageAPied.texteAccord)
                .foregroundStyle(Couleurs.texte2)
            Button("J'accepte") {
                guidage.donnerAccordCartes(true)
                Annonce.voiceOver("Accord enregistré sur cet iPhone. Tu peux le retirer en bas de l'écran Guide-moi.")
            }
            .buttonStyle(.holo)
            .accessibilityHint("Permet d'envoyer la position au service de cartes d'iOS pour l'adresse et le trajet.")
        }
    }
}
