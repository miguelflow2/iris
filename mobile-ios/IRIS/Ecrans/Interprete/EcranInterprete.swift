// EcranInterprete.swift — l'interprète bidirectionnel dehors : « Je parle » / « L'autre parle ».
//
// Chemin réel : la phrase est reconnue SUR L'IPHONE dans la langue de celui qui parle, le texte part
// à l'ordinateur (POST /api/interprete/texte, « langue » = langue de L'AUTRE personne quel que soit
// « qui »), et la traduction est lue par l'iPhone dans la langue cible, et affichée en grand pour être
// montrée. On n'appelle JAMAIS /api/interprete/demarrer d'ici : cela ouvrirait le micro de
// l'ordinateur resté à la maison.

import SwiftUI

struct EcranInterprete: View {
    @Environment(EnvironnementIRIS.self) private var env

    private struct Tour: Identifiable {
        let id = UUID()
        let qui: String
        let original: String
        let traduction: String
        let source: String
        let cible: String
        let latenceMs: Int?
        let totalMs: Double
    }

    @State private var langues: [LangueInterprete] = []
    @State private var langueMoi = "fr"
    @State private var langueAutre = UserDefaults.standard.string(forKey: "iris_interprete_langue") ?? "en"
    @State private var empechement: String? = nil
    @State private var chargement = true
    @State private var occupe = false
    @State private var statut: String? = nil
    @State private var erreur: Error? = nil
    @State private var grandTexte = ""
    @State private var grandSurTitre = ""
    @State private var grandLangue = "fr"
    @State private var tours: [Tour] = []
    @State private var saisie = ""
    @State private var saisieQui = "moi"
    @State private var voixAutreDisponible = true

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 16) {
                if !env.lunettesPresentes {
                    LunettesRequisesVue(message: "L'interprète marche avec les lunettes VELA.")
                } else if !env.pont.etat.estConnecte {
                    Carte {
                        Text("L'interprète a besoin de ton ordinateur : c'est lui qui traduit.")
                            .foregroundStyle(Couleurs.texte2)
                        if case .horsLigne(let raison) = env.pont.etat {
                            NoteVerite(texte: raison, genre: .avertissement)
                        }
                    }
                } else {
                    contenu
                }
            }
            .padding()
        }
        .fondIRIS()
        .navigationTitle("Interprète")
        .task { await chargerEtat() }
        .onDisappear {
            env.voix.annulerEcoute()
            env.voix.arreterParole()
        }
    }

    @ViewBuilder
    private var contenu: some View {
        Carte(titre: "Langue de l'autre personne") {
            if chargement {
                ProgressView()
            } else if langues.isEmpty {
                Text("Aucune langue disponible sur ton ordinateur.").foregroundStyle(Couleurs.texte2)
            } else {
                Picker("Langue", selection: $langueAutre) {
                    ForEach(langues) { langue in
                        Text(langue.nom.capitalized).tag(langue.code)
                    }
                }
                .pickerStyle(.menu)
                .onChange(of: langueAutre) { _, nouvelle in
                    UserDefaults.standard.set(nouvelle, forKey: "iris_interprete_langue")
                    voixAutreDisponible = MoteurVoix.voixDisponible(pour: nouvelle)
                }
                if !voixAutreDisponible {
                    NoteVerite(texte: "Cet iPhone n'a pas de voix en \(MoteurVoix.nomLangue(langueAutre)) : les traductions pour l'autre personne seront affichées en grand, pas lues. Montre-lui l'écran.", genre: .avertissement)
                }
            }
            if let empechement {
                NoteVerite(texte: "Sur ton ordinateur : \(empechement)", genre: .avertissement)
            }
        }

        HStack(spacing: 12) {
            Button {
                Task { await tour(qui: "moi") }
            } label: {
                VStack(spacing: 4) {
                    Image(systemName: "person.wave.2.fill").font(.title2)
                    Text("Je parle")
                    Text(MoteurVoix.nomLangue(langueMoi)).font(.caption)
                }
                .frame(maxWidth: .infinity, minHeight: 96)
            }
            .buttonStyle(BoutonInterprete(variante: .holo))

            Button {
                Task { await tour(qui: "autre") }
            } label: {
                VStack(spacing: 4) {
                    Image(systemName: "person.2.wave.2.fill").font(.title2)
                    Text("L'autre parle")
                    Text(MoteurVoix.nomLangue(langueAutre)).font(.caption)
                }
                .frame(maxWidth: .infinity, minHeight: 96)
            }
            .buttonStyle(BoutonInterprete(variante: .sombre))
        }
        .disabled(occupe || langues.isEmpty)

        if occupe && !env.voix.partiel.isEmpty {
            Text("« \(env.voix.partiel) »")
                .font(.title3)
                .foregroundStyle(Couleurs.texte2)
        }
        if occupe {
            Button("Arrêter") { env.voix.annulerEcoute() }
                .buttonStyle(.holo(.contour, compact: true))
        }
        if let statut {
            Text(statut).font(.footnote).foregroundStyle(Couleurs.texte2)
        }
        if let erreur {
            BandeauErreur(erreur: erreur)
        }

        if !grandTexte.isEmpty {
            VStack(alignment: .leading, spacing: 8) {
                Text(grandSurTitre).font(.subheadline).foregroundStyle(Couleurs.fond.opacity(0.7))
                Text(grandTexte)
                    .font(.system(size: 34, weight: .bold))
                    .foregroundStyle(Couleurs.fond)
                    .textSelection(.enabled)
                    .environment(\.locale, Locale(identifier: grandLangue))
                Button("Relire") {
                    Task { await lire(grandTexte, langue: grandLangue, pourAutre: grandLangue != langueMoi) }
                }
                .buttonStyle(.holo(.blanc, compact: true))
            }
            .padding(18)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(Couleurs.holo, in: RoundedRectangle(cornerRadius: 20, style: .continuous))
            .accessibilityElement(children: .combine)
        }

        Carte(titre: "Écrire une phrase") {
            Picker("Qui", selection: $saisieQui) {
                Text("Moi").tag("moi")
                Text("L'autre personne").tag("autre")
            }
            .pickerStyle(.segmented)
            TextField("Phrase à traduire", text: $saisie, axis: .vertical)
                .lineLimit(1...4)
                .padding(10)
                .background(Couleurs.carte2, in: RoundedRectangle(cornerRadius: 12))
            Button("Traduire") {
                Task { await traduireSaisie() }
            }
            .buttonStyle(.holo(.sombre, compact: true))
            .disabled(saisie.trimmingCharacters(in: .whitespaces).isEmpty || occupe || langues.isEmpty)
        }

        if !tours.isEmpty {
            Carte(titre: "Échanges") {
                ForEach(tours.reversed()) { t in
                    VStack(alignment: .leading, spacing: 2) {
                        Text("\(t.qui == "moi" ? "Moi" : "L'autre personne") · \(MoteurVoix.nomLangue(t.source)) → \(MoteurVoix.nomLangue(t.cible))")
                            .font(.caption).foregroundStyle(Couleurs.attenue)
                        Text(t.original).foregroundStyle(Couleurs.texte2)
                        Text(t.traduction).font(.headline).foregroundStyle(Couleurs.texte)
                    }
                    .padding(.vertical, 4)
                }
                NoteVerite(texte: "Cette liste n'est pas gardée sur l'iPhone quand tu quittes l'écran. Ton ordinateur garde les derniers échanges en mémoire vive environ 10 minutes après le dernier, puis les oublie ; ils ne vont ni dans ta mémoire ni dans ton journal.")
            }
        }

        NoteVerite(texte: "La parole est reconnue sur cet iPhone ; le texte reconnu part à ton ordinateur, qui le traduit avec le moteur VELA. L'autre personne n'a rien accepté : préviens-la avant de traduire ce qu'elle dit. La durée de chaque traduction est mesurée et affichée ; elle dépend du réseau.")
    }

    // MARK: - Actions

    private func chargerEtat() async {
        chargement = true
        defer { chargement = false }
        guard env.pont.etat.estConnecte else { return }
        do {
            let etat: EtatInterprete = try await env.pont.get("/api/interprete/etat")
            langueMoi = etat.langueMoi ?? "fr"
            langues = (etat.langues ?? []).filter { $0.code != langueMoi }
            if !langues.contains(where: { $0.code == langueAutre }) {
                langueAutre = langues.first(where: { $0.code == etat.langueAutre })?.code ?? langues.first?.code ?? "en"
            }
            // L'état décrit l'interprète du MICRO de l'ordinateur : seul un empêchement bloquant qui
            // touche aussi le texte concerne cet écran (le refus exact reviendra de toute façon).
            voixAutreDisponible = MoteurVoix.voixDisponible(pour: langueAutre)
            if etat.empechementBloquant == true, let message = etat.empechement,
               !message.localizedCaseInsensitiveContains("audio brut") {
                empechement = message
            } else {
                empechement = nil
            }
        } catch {
            erreur = error
        }
    }

    private func tour(qui: String) async {
        guard !occupe else { return }
        if let raison = env.raisonVoixImpossible() {
            statut = raison
            return
        }
        occupe = true
        defer { occupe = false }
        erreur = nil
        env.voix.arreterParole()
        let langueEcoute = qui == "moi" ? langueMoi : langueAutre
        statut = qui == "moi"
            ? "Parle en \(MoteurVoix.nomLangue(langueMoi))…"
            : "L'autre personne peut parler en \(MoteurVoix.nomLangue(langueAutre))…"
        let texte: String
        do {
            texte = try await env.voix.ecouterUnePhrase(langue: MoteurVoix.localePreferee(langueEcoute), delaiMax: 15)
        } catch {
            if case ErreurVoix.interrompu? = error as? ErreurVoix {
                statut = "Écoute arrêtée."
            } else {
                statut = nil
                erreur = error
            }
            return
        }
        await traduire(qui: qui, texte: texte)
    }

    private func traduireSaisie() async {
        let texte = saisie.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !texte.isEmpty, !occupe else { return }
        occupe = true
        defer { occupe = false }
        erreur = nil
        await traduire(qui: saisieQui, texte: texte)
        if erreur == nil { saisie = "" }
    }

    private func traduire(qui: String, texte: String) async {
        statut = "Traduction…"
        let debut = Date()
        do {
            let r: ReponseTraduction = try await env.pont.post(
                "/api/interprete/texte", corps: DemandeTraduction(qui: qui, texte: texte, langue: langueAutre), delai: 30)
            let total = Date().timeIntervalSince(debut) * 1000
            let source = r.langueSource ?? (qui == "moi" ? langueMoi : langueAutre)
            let cible = r.langueCible ?? (qui == "moi" ? langueAutre : langueMoi)
            grandSurTitre = qui == "moi"
                ? "Pour l'autre personne (\(MoteurVoix.nomLangue(cible))) :"
                : "Pour toi (\(MoteurVoix.nomLangue(cible))) :"
            grandTexte = r.traduction
            grandLangue = cible
            tours.append(Tour(qui: qui, original: texte, traduction: r.traduction, source: source, cible: cible,
                              latenceMs: r.latenceMs, totalMs: total))
            if tours.count > 50 { tours.removeFirst(tours.count - 50) }
            var mesure = ""
            if let latence = r.latenceMs {
                mesure = "Traduit en \(FormatIRIS.secondes(ms: Double(latence))) (mesuré par l'ordinateur) ; "
            }
            statut = mesure + "\(FormatIRIS.secondes(ms: total)) aller-retour depuis cet iPhone."
            await lire(r.traduction, langue: cible, pourAutre: qui == "moi")
        } catch {
            statut = nil
            erreur = error
            grandSurTitre = "Entendu, mais pas traduit :"
            grandTexte = texte
            grandLangue = qui == "moi" ? langueMoi : langueAutre
        }
    }

    private func lire(_ texte: String, langue: String, pourAutre: Bool) async {
        let locale = MoteurVoix.localePreferee(langue)
        if pourAutre && !MoteurVoix.voixDisponible(pour: locale) { return }
        // Pour l'autre personne, débit naturel : le débit accéléré du propriétaire la perdrait.
        await env.voix.parler(texte, langue: locale, debit: pourAutre ? 1.0 : nil)
    }
}

/// Grand bouton carré de l'interprète, variante du bouton holographique.
struct BoutonInterprete: ButtonStyle {
    var variante: VarianteHolo
    @Environment(\.isEnabled) private var actif

    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(.headline)
            .foregroundStyle(variante == .holo ? Couleurs.fond : Couleurs.texte)
            .padding(12)
            .background {
                if variante == .holo { Couleurs.holo } else { Couleurs.carte2 }
            }
            .clipShape(RoundedRectangle(cornerRadius: 22, style: .continuous))
            .scaleEffect(configuration.isPressed ? 0.98 : 1)
            .opacity(actif ? 1 : 0.45)
    }
}
