// EcranProfil.swift — l'onglet Profil : ordinateur, lunettes, voix, confiance, à propos.
//
// Tout ce qui est ici reste accessible SANS lunettes (réglages, confidentialité, mode invité, zones
// sans mémoire, appairage, achat) : obligation de la Loi 25 et de la sécurité.

import SwiftUI

@MainActor
struct EcranProfil: View {
    @Environment(EnvironnementIRIS.self) private var env
    @Environment(\.openURL) private var ouvrirURL
    @State private var debit: Double = 185
    @State private var debitCharge = false
    @State private var erreurReglage: String? = nil
    @State private var appairage = false
    @State private var confirmationOubli = false

    private let verbosites: [(id: String, nom: String)] = [
        ("concis", "Concis"), ("normal", "Normal"), ("descriptif", "Descriptif"),
    ]

    var body: some View {
        Form {
            sectionOrdinateur
            sectionLunettes
            sectionVoix
            sectionConfiance
            sectionAPropos
        }
        .fondIRIS()
        .navigationTitle("Profil")
        .task {
            await env.chargerReglages()
            if let rate = env.reglages?.ttsRate { debit = Double(rate) }
            debitCharge = true
        }
        .sheet(isPresented: $appairage) {
            NavigationStack {
                Group {
                    if let perception = env.perception {
                        perception.ecranLunettes()
                    } else {
                        Text("L'appairage des lunettes n'est pas inclus dans cette version de l'app iPhone.")
                            .padding()
                    }
                }
                .toolbar {
                    ToolbarItem(placement: .cancellationAction) { Button("Fermer") { appairage = false } }
                }
            }
            .preferredColorScheme(.dark)
        }
        .confirmationDialog("Oublier la session sur cet iPhone ?", isPresented: $confirmationOubli, titleVisibility: .visible) {
            Button("Oublier la session", role: .destructive) { env.pont.oublierSession() }
        } message: {
            Text("Les autres appareils restent connectés. Il faudra retaper le mot de passe.")
        }
    }

    // MARK: - Ordinateur

    private var sectionOrdinateur: some View {
        Section("Ordinateur") {
            HStack {
                Text("État").foregroundStyle(Couleurs.texte)
                Spacer()
                PastillePC()
            }
            if let adresse = env.pont.adresse {
                LabeledContent("Adresse", value: adresse.host ?? adresse.absoluteString)
                    .foregroundStyle(Couleurs.texte)
            }
            if env.pont.liaisonNonChiffree {
                NoteVerite(texte: "Adresse en http : la liaison n'est chiffrée que si elle passe par Tailscale. Préfère l'adresse https://….ts.net.", genre: .avertissement)
            }
            NavigationLink("Relier ou changer d'ordinateur") { EcranConnexionPC() }
            if env.pont.aUneSession {
                Button("Oublier la session sur cet iPhone", role: .destructive) { confirmationOubli = true }
            }
            NavigationLink("Mode hors ligne") { EcranHorsLigne() }
        }
        .listRowBackground(Couleurs.carte)
    }

    // MARK: - Lunettes

    private var sectionLunettes: some View {
        Section("Lunettes VELA") {
            HStack {
                Text("État").foregroundStyle(Couleurs.texte)
                Spacer()
                PastilleLunettes()
            }
            if let erreur = env.attestation.erreur {
                NoteVerite(texte: erreur, genre: .erreur)
            }
            Button("Connecter mes lunettes") { appairage = true }
            Button("Acheter les lunettes") {
                let url = env.attestation.presence?.acheterUrl.flatMap { URL(string: $0) } ?? EnvironnementIRIS.urlAchat
                ouvrirURL(url)
            }
            NoteVerite(texte: "Quand les lunettes sont connectées à cet iPhone, l'app le signale à ton ordinateur toutes les 60 secondes. App IRIS fermée ou en arrière-plan depuis plus de 2 minutes et demie, ton ordinateur ne voit plus les lunettes.")
            if let limite = env.attestation.presence?.limite {
                NoteVerite(texte: limite)
            }
        }
        .listRowBackground(Couleurs.carte)
    }

    // MARK: - Voix

    private var sectionVoix: some View {
        Section("Voix d'IRIS") {
            VStack(alignment: .leading, spacing: 6) {
                HStack {
                    Text("Débit").foregroundStyle(Couleurs.texte)
                    Spacer()
                    Text(FormatIRIS.multiplicateur(ttsRate: Int(debit)))
                        .monospacedDigit()
                        .foregroundStyle(Couleurs.texte2)
                }
                Slider(value: $debit, in: 90...555, step: 5, onEditingChanged: { modifie in
                    if !modifie { Task { await enregistrerDebit() } }
                })
                .accessibilityValue(FormatIRIS.multiplicateur(ttsRate: Int(debit)))
                .disabled(!debitCharge || !env.pont.etat.estConnecte)
                Button("Essayer ce débit") {
                    Task { await env.voix.parler("Voici la voix d'IRIS à ce débit.", langue: nil, debit: debit / 185) }
                }
                .font(.subheadline)
                NoteVerite(texte: "Réglage partagé avec ton ordinateur. Sur l'ordinateur, la voix Windows avance par crans ; au-delà de 2×, la voix reste intelligible mais moins naturelle. Sur cet iPhone, la voix plafonne vers 2× : elle ne va pas plus vite au-delà.")
            }

            Picker("Longueur des réponses", selection: Binding(
                get: { env.reglages?.verbosite ?? "normal" },
                set: { nouvelle in Task { await enregistrer(PatchReglages(verbosite: nouvelle)) } })) {
                ForEach(verbosites, id: \.id) { Text($0.nom).tag($0.id) }
            }
            .pickerStyle(.segmented)
            .disabled(!env.pont.etat.estConnecte)

            Toggle("Grand texte", isOn: Binding(
                get: { env.reglages?.interfaceGrandTexte ?? false },
                set: { actif in Task { await enregistrer(PatchReglages(interfaceGrandTexte: actif)) } }))
            .disabled(!env.pont.etat.estConnecte)

            if let erreurReglage {
                NoteVerite(texte: erreurReglage, genre: .erreur)
            }
        }
        .listRowBackground(Couleurs.carte)
    }

    // MARK: - Confiance

    private var sectionConfiance: some View {
        Section("Confiance") {
            NavigationLink { EcranModeInvite() } label: {
                Label("Mode invité", systemImage: "person.2.slash")
            }
            NavigationLink { EcranZones() } label: {
                Label("Zones sans mémoire", systemImage: "mappin.slash")
            }
        }
        .listRowBackground(Couleurs.carte)
    }

    // MARK: - À propos

    private var sectionAPropos: some View {
        Section("À propos") {
            LabeledContent("Version", value: Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String ?? "?")
            NavigationLink("Ce que l'app iPhone fait, et ne fait pas") { EcranLimites() }
            Text("VELA, entreprise canadienne.")
                .font(.footnote)
                .foregroundStyle(Couleurs.attenue)
        }
        .listRowBackground(Couleurs.carte)
    }

    // MARK: - Enregistrement des réglages

    private func enregistrerDebit() async {
        await enregistrer(PatchReglages(ttsRate: Int(debit)))
    }

    private func enregistrer(_ patch: PatchReglages) async {
        do {
            try await env.modifierReglages(patch)
            erreurReglage = nil
        } catch {
            erreurReglage = error.localizedDescription
        }
    }
}

/// Les limites réelles de l'app iPhone, dites telles quelles.
@MainActor
struct EcranLimites: View {
    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 16) {
                Carte(titre: "Ce que l'app fait") {
                    puce("Elle est la voix et l'oreille d'IRIS dehors : la parole est reconnue sur l'iPhone, le texte part à ton ordinateur, qui fait le travail, et la réponse est lue dans tes lunettes.")
                    puce("Interprète : tu parles, puis l'autre personne ; la traduction est faite par ton ordinateur, la voix dans l'autre langue par l'iPhone.")
                    puce("Cours : relire tes fiches, questions et transcriptions ; en garder une copie sur l'iPhone.")
                    puce("Reçus, comparaison de prix, pas à pas, entraînement et résumé du jour : l'iPhone prend la photo et lit la réponse, ton ordinateur fait le travail.")
                    puce("Mode invité et zones sans mémoire : pour qu'IRIS ne retienne rien quand tu le choisis.")
                }
                Carte(titre: "Ce qu'elle ne fait pas") {
                    puce("Écouter « Dis-moi Iris » écran verrouillé ou app fermée : iOS le réserve à Siri.")
                    puce("Joindre ton ordinateur sans Tailscale hors de ton réseau local : l'app ne passe pas par le relais VELA.")
                    puce("Piloter le pas à pas ou l'entraînement à la voix écran verrouillé : la voix ne marche qu'app ouverte à l'écran ; sinon, ces commandes se donnent avec les boutons.")
                    puce("Sortir du mode invité à la voix : IRIS ne sait pas qui parle dans les lunettes ; on en sort depuis l'app.")
                    puce("Répondre sans ton ordinateur : IRIS travaille sur l'ordinateur ; s'il ne répond pas, seules les fonctions locales restent (voir Mode hors ligne).")
                    puce("Garantir un temps de réponse : il dépend du réseau, de l'ordinateur et de la demande. Il est mesuré et affiché sous chaque réponse.")
                    puce("Alerte d'obstacle en temps réel depuis les lunettes : elles n'envoient pas de vidéo en direct par Bluetooth.")
                    puce("Reconnaître les personnes par leur nom : données biométriques, non livré.")
                    puce("Enregistrer une vidéo, mettre à jour le micrologiciel ou effacer la mémoire interne des lunettes : protocole non documenté par le fabricant.")
                    puce("Langue des signes : non prévue.")
                }
            }
            .padding()
        }
        .fondIRIS()
        .navigationTitle("Limites")
    }

    private func puce(_ texte: String) -> some View {
        HStack(alignment: .firstTextBaseline, spacing: 8) {
            Text("•").foregroundStyle(Couleurs.attenue)
            Text(texte).foregroundStyle(Couleurs.texte2)
        }
    }
}
