// EcranCours.swift — les cours enregistrés sur l'ordinateur : liste, fiches, questions, transcription.
//
// Consulter, exporter et effacer ses cours reste permis sans lunettes (Loi 25). Générer des fiches
// envoie la transcription au moteur : c'est l'ordinateur qui décide (consentement, mode local), et
// sa réponse exacte s'affiche. Démarrer un cours n'est pas proposé ici : cela ouvrirait le micro de
// l'ordinateur, qui n'est pas dans la salle quand tu es dehors.

import SwiftUI

@MainActor
struct EcranListeCours: View {
    @Environment(EnvironnementIRIS.self) private var env
    @State private var cours: [CoursResume] = []
    @State private var chargement = false
    @State private var erreur: Error? = nil

    var body: some View {
        List {
            if env.pont.etat.estConnecte {
                Section("Sur ton ordinateur") {
                    if chargement && cours.isEmpty {
                        ProgressView()
                    } else if cours.isEmpty && erreur == nil {
                        Text("Aucun cours. Un cours s'enregistre depuis l'application IRIS de l'ordinateur (Cours).")
                            .foregroundStyle(Couleurs.attenue)
                    }
                    ForEach(cours) { c in
                        NavigationLink {
                            EcranCoursDetail(coursId: c.id, titre: c.titre)
                        } label: {
                            LigneCours(titre: c.titre, matiere: c.matiere, detail: detail(c))
                        }
                    }
                    if let erreur {
                        BandeauErreur(erreur: erreur)
                    }
                }
                .listRowBackground(Couleurs.carte)
            } else {
                Section {
                    NoteVerite(texte: "Ton ordinateur ne répond pas : seuls les cours gardés sur cet iPhone sont lisibles.", genre: .avertissement)
                }
                .listRowBackground(Couleurs.carte)
            }

            // IRIS verrouillée : les copies gardées ne se relisent pas (l'écran de verrouillage passe déjà
            // devant ; ceci ferme la porte si une vue restait ouverte derrière).
            if !env.coursHorsLigne.gardes.isEmpty && !env.pont.verrouPersistant {
                Section("Gardés sur cet iPhone") {
                    ForEach(env.coursHorsLigne.gardes) { g in
                        NavigationLink {
                            EcranCoursDetail(coursId: g.id, titre: g.titre)
                        } label: {
                            LigneCours(titre: g.titre, matiere: g.matiere,
                                       detail: "Copie du \(FormatIRIS.dateCourte(g.gardeLe))")
                        }
                    }
                }
                .listRowBackground(Couleurs.carte)
            }
        }
        .fondIRIS()
        .navigationTitle("Mes cours")
        .refreshable { await charger() }
        .task { await charger() }
    }

    private func detail(_ c: CoursResume) -> String {
        var morceaux: [String] = []
        if let date = c.debut?.date { morceaux.append(FormatIRIS.dateCourte(date)) }
        if let duree = c.dureeS, duree > 0 { morceaux.append(FormatIRIS.duree(secondes: duree)) }
        if c.actif == true { morceaux.append("en cours") }
        if c.etat == "transcription" {
            let pourcent = Int(((c.progression ?? 0) * 100).rounded())
            morceaux.append("transcription \(pourcent) %")
        }
        if c.fiches == true { morceaux.append("fiches") }
        if c.questions == true { morceaux.append("questions") }
        return morceaux.joined(separator: " · ")
    }

    private func charger() async {
        guard env.pont.etat.estConnecte else { return }
        chargement = true
        defer { chargement = false }
        do {
            let liste: ListeCours = try await env.pont.get("/api/cours")
            cours = liste.cours
            erreur = nil
        } catch {
            erreur = error
        }
    }
}

@MainActor
private struct LigneCours: View {
    let titre: String
    let matiere: String?
    let detail: String

    var body: some View {
        VStack(alignment: .leading, spacing: 3) {
            Text(titre.isEmpty ? "Cours sans titre" : titre)
                .font(.headline).foregroundStyle(Couleurs.texte)
            if let matiere, !matiere.isEmpty {
                Text(matiere).font(.subheadline).foregroundStyle(Couleurs.texte2)
            }
            if !detail.isEmpty {
                Text(detail).font(.caption).foregroundStyle(Couleurs.attenue)
            }
        }
        .padding(.vertical, 2)
    }
}

@MainActor
struct EcranCoursDetail: View {
    @Environment(EnvironnementIRIS.self) private var env
    @Environment(\.dismiss) private var fermer
    let coursId: String
    let titre: String

    private enum Partie: String, CaseIterable, Identifiable {
        case fiches = "Fiches", questions = "Questions", transcription = "Transcription"
        var id: String { rawValue }
    }

    @State private var cours: CoursDetail? = nil
    @State private var depuisCopie = false
    @State private var partie: Partie = .fiches
    @State private var erreur: Error? = nil
    @State private var generation: String? = nil
    /// Réponse 202 de /generer (long cours) : la rédaction continue sur l'ordinateur ; rien n'est encore rédigé.
    @State private var phraseArrierePlan: String? = nil
    @State private var reponsesVues: Set<Int> = []
    @State private var exportURL: URL? = nil
    @State private var confirmationSuppression = false

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 14) {
                if let cours {
                    entete(cours)
                    Picker("Partie", selection: $partie) {
                        ForEach(Partie.allCases) { Text($0.rawValue).tag($0) }
                    }
                    .pickerStyle(.segmented)
                    switch partie {
                    case .fiches: fiches(cours)
                    case .questions: questions(cours)
                    case .transcription: transcription(cours)
                    }
                } else if erreur == nil {
                    ProgressView().frame(maxWidth: .infinity)
                }
                if let erreur {
                    BandeauErreur(erreur: erreur)
                }
            }
            .padding()
        }
        .fondIRIS()
        .navigationTitle(titre.isEmpty ? "Cours" : titre)
        .navigationBarTitleDisplayMode(.inline)
        .toolbar {
            ToolbarItem(placement: .topBarTrailing) { menu }
        }
        .task { await charger() }
        .confirmationDialog("Effacer ce cours de ton ordinateur ?", isPresented: $confirmationSuppression, titleVisibility: .visible) {
            Button("Effacer le cours", role: .destructive) { Task { await supprimer() } }
        } message: {
            Text("La transcription, les fiches et les questions sont effacées de l'ordinateur. La copie gardée sur cet iPhone, s'il y en a une, est effacée aussi.")
        }
    }

    private var menu: some View {
        Menu {
            if let cours {
                if env.coursHorsLigne.estGarde(cours.id) {
                    Button("Retirer la copie de cet iPhone", role: .destructive) { env.coursHorsLigne.retirer(cours.id) }
                } else {
                    Button("Garder sur cet iPhone") { env.coursHorsLigne.garder(cours) }
                }
            }
            if let exportURL {
                ShareLink(item: exportURL) { Label("Partager le fichier Markdown", systemImage: "square.and.arrow.up") }
            } else if env.pont.etat.estConnecte && !depuisCopie {
                Button("Préparer l'export Markdown") { Task { await exporter() } }
            }
            if env.pont.etat.estConnecte && !depuisCopie {
                Button("Effacer ce cours", role: .destructive) { confirmationSuppression = true }
            }
        } label: {
            Image(systemName: "ellipsis.circle").accessibilityLabel("Options du cours")
        }
    }

    private func entete(_ cours: CoursDetail) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            if let matiere = cours.matiere, !matiere.isEmpty {
                Text(matiere).font(.subheadline).foregroundStyle(Couleurs.texte2)
            }
            HStack(spacing: 8) {
                if let date = cours.debut?.date { Text(FormatIRIS.dateCourte(date)) }
                if let duree = cours.dureeS, duree > 0 { Text("· \(FormatIRIS.duree(secondes: duree))") }
            }
            .font(.caption)
            .foregroundStyle(Couleurs.attenue)
            if depuisCopie {
                NoteVerite(texte: "Copie gardée sur cet iPhone : elle peut dater d'avant les dernières modifications faites sur l'ordinateur.", genre: .avertissement)
            }
            if let erreurCours = cours.erreur, !erreurCours.isEmpty {
                NoteVerite(texte: erreurCours, genre: .erreur)
            }
            if cours.etat == "generation" || phraseArrierePlan != nil {
                NoteVerite(texte: phraseArrierePlan ?? "Rédaction en cours sur ton ordinateur : rouvre le cours pour voir les fiches et les questions.")
            }
            if let erreurGeneration = cours.erreurGeneration, !erreurGeneration.isEmpty, cours.etat != "generation" {
                NoteVerite(texte: "La dernière rédaction n'a pas abouti : \(erreurGeneration)", genre: .erreur)
            }
            if let erreurCopie = env.coursHorsLigne.erreur {
                NoteVerite(texte: erreurCopie, genre: .erreur)
            }
        }
    }

    @ViewBuilder
    private func fiches(_ cours: CoursDetail) -> some View {
        if let fiches = cours.fiches, !fiches.isEmpty {
            Carte {
                TexteMarkdown(texte: fiches)
            }
        } else {
            Carte {
                Text("Pas encore de fiches pour ce cours.").foregroundStyle(Couleurs.texte2)
                boutonGenerer("fiches", libelle: "Générer les fiches")
            }
        }
    }

    @ViewBuilder
    private func questions(_ cours: CoursDetail) -> some View {
        if let questions = cours.questions, !questions.isEmpty {
            ForEach(Array(questions.enumerated()), id: \.offset) { index, q in
                Carte {
                    HStack {
                        Text(libelleType(q.type)).font(.caption.weight(.semibold)).foregroundStyle(Couleurs.attenue)
                        Spacer()
                        if let d = q.difficulte {
                            Text(String(repeating: "●", count: max(1, min(3, d))) + String(repeating: "○", count: max(0, 3 - d)))
                                .font(.caption).foregroundStyle(Couleurs.attenue)
                                .accessibilityLabel("Difficulté \(d) sur 3")
                        }
                    }
                    Text(q.question ?? "(question illisible)").font(.headline).foregroundStyle(Couleurs.texte)
                    if reponsesVues.contains(index) {
                        Text(q.reponse ?? "(pas de réponse)").foregroundStyle(Couleurs.texte2)
                    } else {
                        Button("Voir la réponse") { reponsesVues.insert(index) }
                            .font(.subheadline)
                    }
                }
            }
        } else {
            Carte {
                Text("Pas encore de questions pour ce cours.").foregroundStyle(Couleurs.texte2)
                boutonGenerer("questions", libelle: "Générer les questions")
            }
        }
    }

    @ViewBuilder
    private func transcription(_ cours: CoursDetail) -> some View {
        let lignes = cours.transcription ?? []
        if lignes.isEmpty {
            Carte { Text("Transcription vide.").foregroundStyle(Couleurs.texte2) }
        } else {
            Carte {
                ForEach(Array(lignes.enumerated()), id: \.offset) { _, ligne in
                    HStack(alignment: .firstTextBaseline, spacing: 8) {
                        if let ts = ligne.ts {
                            Text(FormatIRIS.duree(secondes: ts))
                                .font(.caption.monospacedDigit())
                                .foregroundStyle(Couleurs.attenue)
                                .frame(minWidth: 52, alignment: .leading)
                        }
                        Text(ligne.texte).foregroundStyle(Couleurs.texte2).textSelection(.enabled)
                    }
                }
                NoteVerite(texte: "Transcription faite sur l'ordinateur par la reconnaissance locale : elle peut contenir des erreurs.")
            }
        }
    }

    @ViewBuilder
    private func boutonGenerer(_ quoi: String, libelle: String) -> some View {
        if env.pont.etat.estConnecte && !depuisCopie {
            if generation == quoi {
                HStack {
                    ProgressView()
                    Text("Génération sur ton ordinateur…").foregroundStyle(Couleurs.texte2)
                }
            } else {
                Button(libelle) { Task { await generer(quoi) } }
                    .buttonStyle(.holo(.sombre, compact: true))
                    .disabled(generation != nil)
                NoteVerite(texte: "La transcription est envoyée au moteur VELA par ton ordinateur ; le temps dépend de la longueur du cours.")
            }
        }
    }

    private func libelleType(_ type: String?) -> String {
        switch type {
        case "definition": return "Définition"
        case "application": return "Application"
        case "comprehension": return "Compréhension"
        case "calcul": return "Calcul"
        case "vrai_faux": return "Vrai ou faux"
        default: return "Question"
        }
    }

    // MARK: - Actions

    private func charger() async {
        if env.pont.etat.estConnecte {
            do {
                let lu: CoursDetail = try await env.pont.get("/api/cours/\(coursId)", delai: 30)
                cours = lu
                depuisCopie = false
                erreur = nil
                if let cours, env.coursHorsLigne.estGarde(cours.id) {
                    // La copie suit la version de l'ordinateur quand on la consulte en ligne.
                    env.coursHorsLigne.garder(cours)
                }
                return
            } catch {
                erreur = error
            }
        }
        if !env.pont.verrouPersistant, let copie = env.coursHorsLigne.lire(coursId) {
            cours = copie
            depuisCopie = true
            erreur = nil
        }
    }

    private func generer(_ quoi: String) async {
        generation = quoi
        defer { generation = nil }
        do {
            // La génération peut être longue (découpage des longues transcriptions) : délai large.
            let reponse: ReponseGeneration = try await env.pont.post("/api/cours/\(coursId)/generer", corps: DemandeGeneration(quoi: quoi), delai: 600)
            // 202 {en_arriere_plan, phrase} : long cours rédigé en arrière-plan. Ce n'est PAS une fin de rédaction.
            phraseArrierePlan = reponse.enArrierePlan == true
                ? (reponse.phrase ?? "La rédaction continue en arrière-plan sur ton ordinateur.")
                : nil
            await charger()
        } catch {
            erreur = error
        }
    }

    private func exporter() async {
        do {
            let (donnees, _) = try await env.pont.requeteBrute(.get, "/api/cours/\(coursId)/exporter", corps: nil,
                                                               typeContenu: nil, parametres: [], delai: 30)
            let nom = (titre.isEmpty ? "cours" : titre)
                .components(separatedBy: CharacterSet.alphanumerics.union(.whitespaces).inverted).joined()
            let url = FileManager.default.temporaryDirectory.appendingPathComponent("\(nom.isEmpty ? "cours" : nom).md")
            try donnees.write(to: url, options: [.atomic, .completeFileProtection])
            exportURL = url
        } catch {
            erreur = error
        }
    }

    private func supprimer() async {
        do {
            let _: ReponseIgnoree = try await env.pont.delete("/api/cours/\(coursId)")
            env.coursHorsLigne.retirer(coursId)
            fermer()
        } catch {
            erreur = error
        }
    }
}

/// Réponse de POST /api/cours/{id}/generer : le cours rédigé (200), ou 202 {en_arriere_plan: true, parties, phrase}.
private struct ReponseGeneration: Decodable, Sendable {
    let enArrierePlan: Bool?
    let phrase: String?
}

/// POST /api/cours/{id}/generer {"quoi": "fiches"|"questions"|"tout"}
private struct DemandeGeneration: Encodable {
    let quoi: String
}

/// Markdown des fiches : titres, listes et gras rendus ligne par ligne (AttributedString ne gère que
/// le Markdown « en ligne »).
@MainActor
struct TexteMarkdown: View {
    let texte: String

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            ForEach(Array(texte.components(separatedBy: "\n").enumerated()), id: \.offset) { _, ligne in
                ligneVue(ligne)
            }
        }
    }

    @ViewBuilder
    private func ligneVue(_ ligne: String) -> some View {
        let propre = ligne.trimmingCharacters(in: .whitespaces)
        if propre.isEmpty {
            Spacer().frame(height: 4)
        } else if propre.hasPrefix("### ") {
            Text(enLigne(String(propre.dropFirst(4)))).font(.headline).foregroundStyle(Couleurs.texte)
        } else if propre.hasPrefix("## ") {
            Text(enLigne(String(propre.dropFirst(3)))).font(.title3.bold()).foregroundStyle(Couleurs.texte)
        } else if propre.hasPrefix("# ") {
            Text(enLigne(String(propre.dropFirst(2)))).font(.title2.bold()).foregroundStyle(Couleurs.texte)
        } else if propre.hasPrefix("- ") || propre.hasPrefix("* ") {
            HStack(alignment: .firstTextBaseline, spacing: 6) {
                Text("•").foregroundStyle(Couleurs.attenue)
                Text(enLigne(String(propre.dropFirst(2)))).foregroundStyle(Couleurs.texte2)
            }
        } else {
            Text(enLigne(propre)).foregroundStyle(Couleurs.texte2)
        }
    }

    private func enLigne(_ s: String) -> AttributedString {
        (try? AttributedString(markdown: s, options: .init(interpretedSyntax: .inlineOnlyPreservingWhitespace)))
            ?? AttributedString(s)
    }
}
