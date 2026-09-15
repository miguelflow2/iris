// EcranQuotidien.swift — reçus, comparaison de prix, pas à pas, entraînement et résumé du jour sur l'iPhone
// (interfaces G et H du chantier du 2026-09-13).
//
// Le travail se fait sur l'ordinateur, par ses vraies routes ; l'iPhone prend la photo, montre le résultat
// et le lit à voix haute. Règles suivies partout :
// - DEHORS, parler=false : la phrase rendue est lue par l'iPhone, jamais par le haut-parleur de
//   l'ordinateur resté à la maison ;
// - lunettes d'abord : ce qui capte ou agit (photo, analyse, comparaison, démarrer, commander, lire) exige
//   les lunettes ; consulter, exporter et effacer ses données restent permis sans elles (Loi 25) ;
// - les champs de vérité du service (limite, note, avertissement, phrase, memoire_suspendue, local)
//   s'affichent tels quels ;
// - rien n'est gardé sur l'iPhone : l'export CSV que l'utilisateur prépare vit dans le dossier temporaire de
//   l'app, le temps de le partager, et il est effacé quand on quitte l'écran.

import PhotosUI
import SwiftUI
import UIKit

// MARK: - Outils communs

/// Lit une phrase une seule fois : la réponse HTTP et l'événement du bus portent souvent la même phrase,
/// dans un ordre qui n'est pas garanti.
@MainActor
final class LecteurSansDoublon {
    private var derniers: [(texte: String, quand: Date)] = []

    func dire(_ texte: String, voix: MoteurVoix) {
        let propre = texte.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !propre.isEmpty else { return }
        let maintenant = Date()
        derniers = derniers.filter { maintenant.timeIntervalSince($0.quand) < 8 }
        guard !derniers.contains(where: { $0.texte == propre }) else { return }
        derniers.append((propre, maintenant))
        Task { await voix.parler(propre) }
    }
}

enum ImageQuotidien {
    /// JPEG réduit à 1600 px sur son plus grand côté, prêt à envoyer ; nil si l'image est illisible.
    /// Sûr hors du fil principal (UIGraphicsImageRenderer l'est).
    static func preparer(_ donnees: Data) -> ImageEnvoyee? {
        guard let image = UIImage(data: donnees), image.size.width > 0, image.size.height > 0 else { return nil }
        let echelle = min(1, 1600 / max(image.size.width, image.size.height))
        let taille = CGSize(width: (image.size.width * echelle).rounded(), height: (image.size.height * echelle).rounded())
        let format = UIGraphicsImageRendererFormat()
        format.scale = 1
        format.opaque = true
        let rendu = UIGraphicsImageRenderer(size: taille, format: format).image { _ in
            image.draw(in: CGRect(origin: .zero, size: taille))
        }
        guard let jpeg = rendu.jpegData(compressionQuality: 0.8) else { return nil }
        return ImageEnvoyee(mediaType: "image/jpeg", data: jpeg.base64EncodedString())
    }
}

enum FormatQuotidien {
    static func montant(_ valeur: Double?, devise: String?) -> String {
        guard let valeur else { return "—" }
        let f = NumberFormatter()
        f.locale = Locale(identifier: "fr_CA")
        f.numberStyle = .currency
        f.currencyCode = (devise ?? "CAD").uppercased()
        return f.string(from: NSNumber(value: valeur)) ?? String(format: "%.2f", valeur)
    }

    static func jourISO(_ date: Date) -> String {
        let f = DateFormatter()
        f.locale = Locale(identifier: "en_US_POSIX")
        f.dateFormat = "yyyy-MM-dd"
        return f.string(from: date)
    }
}

/// La voix de l'iPhone peut-elle lire maintenant ? (lunettes présentes, pas de mode confidentiel)
@MainActor
private func lecturePermise(_ env: EnvironnementIRIS) -> Bool {
    env.lunettesPresentes && env.reglages?.privacyMode != true && !env.pont.verrouPersistant
}

/// Photographier avec l'iPhone (en secours de la caméra des lunettes, et c'est dit) ou choisir une photo.
@MainActor
struct BoutonsPhotoQuotidien: View {
    @Environment(EnvironnementIRIS.self) private var env
    let libelle: String
    let occupe: Bool
    let surImage: (ImageEnvoyee) async -> Void
    let surErreur: (Error) -> Void
    @State private var element: PhotosPickerItem?

    init(libelle: String, occupe: Bool, surImage: @escaping (ImageEnvoyee) async -> Void,
         surErreur: @escaping (Error) -> Void) {
        self.libelle = libelle
        self.occupe = occupe
        self.surImage = surImage
        self.surErreur = surErreur
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            if env.perception != nil {
                Button {
                    Task { await photographier() }
                } label: {
                    Label(libelle, systemImage: "camera.fill")
                }
                .buttonStyle(.holo)
                .disabled(occupe || !env.lunettesPresentes)
            }
            PhotosPicker(selection: $element, matching: .images) {
                Label("Choisir une photo", systemImage: "photo.on.rectangle")
            }
            .buttonStyle(.holo(.sombre, compact: true))
            .disabled(occupe || !env.lunettesPresentes)
            NoteVerite(texte: "La caméra des lunettes arrive ; en attendant, la photo est prise avec ton iPhone. Elle n'est pas gardée sur l'iPhone.")
        }
        .onChange(of: element) { _, choisi in
            guard let choisi else { return }
            element = nil
            Task { await charger(choisi) }
        }
    }

    private func photographier() async {
        guard let perception = env.perception else { return }
        do {
            let capture = try await perception.prendrePhotoTelephone()
            await surImage(capture.pourEnvoi)
        } catch {
            surErreur(error)
        }
    }

    private func charger(_ choisi: PhotosPickerItem) async {
        do {
            guard let donnees = try await choisi.loadTransferable(type: Data.self) else {
                surErreur(ErreurPont.refus(statut: 422, message: "Cette photo n'a pas pu être lue.", detail: nil))
                return
            }
            let image = await Task.detached(priority: .userInitiated) { ImageQuotidien.preparer(donnees) }.value
            guard let image else {
                surErreur(ErreurPont.refus(statut: 422, message: "Image illisible : format non reconnu.", detail: nil))
                return
            }
            await surImage(image)
        } catch {
            surErreur(error)
        }
    }
}

// MARK: - Reçus (G)

@MainActor
struct EcranRecus: View {
    @Environment(EnvironnementIRIS.self) private var env
    @State private var liste: ListeRecus?
    @State private var dernier: Recu?
    @State private var enCours = false
    @State private var erreur: Error?
    @State private var exportURL: URL?

    var body: some View {
        List {
            Section {
                if !env.lunettesPresentes {
                    LunettesRequisesVue(message: "Lire un reçu marche avec les lunettes VELA. Tes reçus déjà gardés restent consultables ci-dessous.")
                }
                BoutonsPhotoQuotidien(libelle: "Photographier un reçu", occupe: enCours,
                                      surImage: { image in await analyser(image) },
                                      surErreur: { erreur = $0 })
                if enCours {
                    HStack(spacing: 10) {
                        ProgressView()
                        Text("Lecture du reçu par ton ordinateur…").foregroundStyle(Couleurs.texte2)
                    }
                }
                if let erreur {
                    BandeauErreur(erreur: erreur)
                }
            } header: {
                Text("Nouveau reçu")
            } footer: {
                Text("L'image part à ton ordinateur, qui lit le reçu et le range avec tes autres reçus.")
            }
            .listRowBackground(Couleurs.carte)

            if let dernier {
                Section("Reçu lu") {
                    DetailRecu(recu: dernier)
                }
                .listRowBackground(Couleurs.carte)
            }

            if let totaux = liste?.totaux, (totaux.nombre ?? 0) > 0 {
                Section("Totaux") {
                    LabeledContent("Reçus", value: "\(totaux.nombre ?? 0)")
                    LabeledContent("Total", value: FormatQuotidien.montant(totaux.total, devise: totaux.devise))
                    if let tps = totaux.tps, tps > 0 { LabeledContent("TPS", value: FormatQuotidien.montant(tps, devise: totaux.devise)) }
                    if let tvq = totaux.tvq, tvq > 0 { LabeledContent("TVQ", value: FormatQuotidien.montant(tvq, devise: totaux.devise)) }
                    if let tvh = totaux.tvh, tvh > 0 { LabeledContent("TVH", value: FormatQuotidien.montant(tvh, devise: totaux.devise)) }
                    if let sans = totaux.sansTotal, sans > 0 {
                        NoteVerite(texte: "\(sans) reçu\(sans > 1 ? "s" : "") sans total lisible : non compté\(sans > 1 ? "s" : "").", genre: .avertissement)
                    }
                    if let autres = totaux.autresDevises, !autres.isEmpty {
                        NoteVerite(texte: "Autres devises, jamais converties : " + autres.sorted { $0.key < $1.key }
                            .map { FormatQuotidien.montant($0.value, devise: $0.key) }.joined(separator: ", ") + ".")
                    }
                }
                .foregroundStyle(Couleurs.texte)
                .listRowBackground(Couleurs.carte)
            }

            Section {
                if let recus = liste?.recus {
                    if recus.isEmpty {
                        Text("Aucun reçu gardé sur ton ordinateur.").foregroundStyle(Couleurs.texte2)
                    }
                    ForEach(recus.indices, id: \.self) { index in
                        LigneRecuListe(recu: recus[index])
                            .swipeActions {
                                if let id = recus[index].id {
                                    Button("Effacer", role: .destructive) { Task { await supprimer(id) } }
                                }
                            }
                    }
                } else if env.pont.etat.estConnecte {
                    ProgressView()
                } else {
                    NoteVerite(texte: "Ton ordinateur ne répond pas : tes reçus vivent sur lui.", genre: .avertissement)
                }
                if let exportURL {
                    ShareLink(item: exportURL) { Label("Partager le fichier CSV", systemImage: "square.and.arrow.up") }
                } else if env.pont.etat.estConnecte, !(liste?.recus.isEmpty ?? true) {
                    Button("Préparer l'export CSV") { Task { await exporter() } }
                }
            } header: {
                Text("Mes reçus")
            } footer: {
                Text("Glisse un reçu vers la gauche pour l'effacer de ton ordinateur. Consulter, exporter et effacer marchent sans lunettes.")
            }
            .listRowBackground(Couleurs.carte)

            if let limite = liste?.limite {
                Section { NoteVerite(texte: limite) }
                    .listRowBackground(Couleurs.carte)
            }
        }
        .fondIRIS()
        .navigationTitle("Reçus")
        .refreshable { await charger() }
        .task { await charger() }
        // Le fichier CSV préparé ne reste pas sur l'iPhone une fois l'écran quitté.
        .onDisappear {
            if let exportURL {
                try? FileManager.default.removeItem(at: exportURL)
                self.exportURL = nil
            }
        }
    }

    private func charger() async {
        guard env.pont.etat.estConnecte else { return }
        do {
            let lue: ListeRecus = try await env.pont.get("/api/recus")
            liste = lue
        } catch {
            erreur = error
        }
    }

    private func analyser(_ image: ImageEnvoyee) async {
        guard !enCours else { return }
        enCours = true
        defer { enCours = false }
        erreur = nil
        do {
            let recu: Recu = try await env.pont.post("/api/recus/analyser",
                                                    corps: DemandeAnalyseRecu(source: "image", image: image), delai: 120)
            dernier = recu
            UINotificationFeedbackGenerator().notificationOccurred(.success)
            if lecturePermise(env) {
                let montant = FormatQuotidien.montant(recu.total, devise: recu.devise)
                let debut = recu.enregistre == false ? "Reçu lu, mais pas enregistré" : "Reçu enregistré"
                Task { await env.voix.parler("\(debut) : \(recu.commercant ?? "commerçant non lu"), total \(montant).") }
            }
            await charger()
        } catch {
            erreur = error
        }
    }

    private func supprimer(_ id: String) async {
        do {
            let _: ReponseIgnoree = try await env.pont.delete("/api/recus/\(id)")
            if dernier?.id == id { dernier = nil }
            exportURL = nil
            await charger()
        } catch {
            erreur = error
        }
    }

    private func exporter() async {
        do {
            let (donnees, _) = try await env.pont.requeteBrute(.get, "/api/recus/export", corps: nil, typeContenu: nil,
                                                               parametres: [URLQueryItem(name: "format", value: "csv")], delai: 30)
            let url = FileManager.default.temporaryDirectory.appendingPathComponent("iris-recus.csv")
            try donnees.write(to: url, options: [.atomic, .completeFileProtection])
            exportURL = url
        } catch {
            erreur = error
        }
    }
}

@MainActor
private struct LigneRecuListe: View {
    let recu: Recu

    var body: some View {
        VStack(alignment: .leading, spacing: 3) {
            HStack {
                Text(recu.commercant ?? "Commerçant non lu").font(.headline).foregroundStyle(Couleurs.texte)
                Spacer()
                Text(FormatQuotidien.montant(recu.total, devise: recu.devise)).monospacedDigit().foregroundStyle(Couleurs.texte)
            }
            Text([recu.date, recu.categorie].compactMap { $0 }.joined(separator: " · "))
                .font(.caption)
                .foregroundStyle(Couleurs.attenue)
        }
        .accessibilityElement(children: .combine)
    }
}

@MainActor
private struct DetailRecu: View {
    let recu: Recu

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(recu.commercant ?? "Commerçant non lu").font(.title3.bold()).foregroundStyle(Couleurs.texte)
            if let date = recu.date { Text(date).foregroundStyle(Couleurs.texte2) }
            Text("Total : \(FormatQuotidien.montant(recu.total, devise: recu.devise))").font(.headline).foregroundStyle(Couleurs.texte)
            let taxes = [("TPS", recu.tps), ("TVQ", recu.tvq), ("TVH", recu.tvh)]
                .compactMap { nom, valeur in valeur.map { "\(nom) \(FormatQuotidien.montant($0, devise: recu.devise))" } }
            if !taxes.isEmpty {
                Text(taxes.joined(separator: " · ")).font(.subheadline).foregroundStyle(Couleurs.texte2)
            }
            if let categorie = recu.categorie {
                Text("Catégorie suggérée : \(categorie)").font(.subheadline).foregroundStyle(Couleurs.texte2)
            }
            if let confiance = recu.confiance {
                Text("Confiance de la lecture : \(Int((confiance * 100).rounded())) %").font(.footnote).foregroundStyle(Couleurs.attenue)
            }
            NoteVerite(texte: recu.local == false
                       ? "Lu par ton ordinateur avec le moteur VELA."
                       : "Lu par ton ordinateur, sans le moteur VELA.")
            if recu.enregistre == false {
                NoteVerite(texte: "Reçu lu, mais PAS enregistré : la mémoire d'IRIS est suspendue (mode invité ou zone sans mémoire).",
                           genre: .avertissement)
            }
            if let note = recu.note, !note.isEmpty {
                NoteVerite(texte: note)
            }
        }
        .padding(.vertical, 4)
    }
}

// MARK: - Comparaison de prix (H)

@MainActor
struct EcranPrix: View {
    @Environment(EnvironnementIRIS.self) private var env
    @State private var requete = ""
    @State private var resultat: ComparaisonPrix?
    @State private var enCours = false
    @State private var erreur: Error?
    @State private var dureeMs: Double?

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 16) {
                if !env.lunettesPresentes {
                    LunettesRequisesVue(message: "Comparer les prix marche avec les lunettes VELA.")
                }
                Carte(titre: "Quel produit ?") {
                    BoutonsPhotoQuotidien(libelle: "Photographier l'étiquette", occupe: enCours,
                                          surImage: { image in await comparer(image: image) },
                                          surErreur: { erreur = $0 })
                    TextField("Ou écris le nom du produit", text: $requete)
                        .textInputAutocapitalization(.never)
                        .submitLabel(.search)
                        .onSubmit { Task { await comparer(image: nil) } }
                        .padding(12)
                        .background(Couleurs.carte2, in: RoundedRectangle(cornerRadius: 12))
                    Button("Comparer par le nom") { Task { await comparer(image: nil) } }
                        .buttonStyle(.holo(.sombre, compact: true))
                        .disabled(enCours || requete.trimmingCharacters(in: .whitespaces).isEmpty || !env.lunettesPresentes)
                    if enCours {
                        HStack(spacing: 10) {
                            ProgressView()
                            Text("Recherche des prix par ton ordinateur…").foregroundStyle(Couleurs.texte2)
                        }
                    }
                    NoteVerite(texte: "Ton ordinateur identifie le produit, puis envoie son nom à un service de recherche web réglé sur l'ordinateur. Sans ce réglage, la comparaison est refusée et le message le dit.")
                }

                if let erreur {
                    BandeauErreur(erreur: erreur)
                }

                if let resultat {
                    Carte(titre: "Produit") {
                        let p = resultat.produit
                        Text(p?.nom ?? "Produit non identifié").font(.title3.bold()).foregroundStyle(Couleurs.texte)
                        let details = [p?.marque, p?.format, p?.codeBarres.map { "code-barres \($0)" }].compactMap { $0 }
                        if !details.isEmpty {
                            Text(details.joined(separator: " · ")).foregroundStyle(Couleurs.texte2)
                        }
                        if let vu = p?.prixVu {
                            Text("Prix lu sur l'étiquette : \(FormatQuotidien.montant(vu, devise: "CAD"))").foregroundStyle(Couleurs.texte2)
                        }
                        if let resume = resultat.resume {
                            Text(resume).font(.headline).foregroundStyle(Couleurs.texte)
                        }
                    }
                    Carte(titre: "Offres trouvées") {
                        let offres = resultat.offres ?? []
                        if offres.isEmpty {
                            Text("Aucune offre trouvée en ligne pour ce produit.").foregroundStyle(Couleurs.texte2)
                        }
                        ForEach(offres, id: \.self) { offre in
                            VStack(alignment: .leading, spacing: 2) {
                                HStack {
                                    Text(offre.marchand ?? "Marchand").font(.headline).foregroundStyle(Couleurs.texte)
                                    Spacer()
                                    Text(FormatQuotidien.montant(offre.prix, devise: offre.devise)).monospacedDigit().foregroundStyle(Couleurs.texte)
                                }
                                if let extrait = offre.extrait, !extrait.isEmpty {
                                    Text(extrait).font(.caption).foregroundStyle(Couleurs.attenue).lineLimit(3)
                                }
                                if let lien = offre.url.flatMap({ URL(string: $0) }) {
                                    Link("Ouvrir la page", destination: lien).font(.subheadline)
                                }
                            }
                            .padding(.vertical, 4)
                        }
                        if let avertissement = resultat.avertissement {
                            NoteVerite(texte: avertissement, genre: .avertissement)
                        }
                        if let dureeMs {
                            Text("Mesuré : \(FormatIRIS.secondes(ms: dureeMs)) depuis cet iPhone.")
                                .font(.footnote).foregroundStyle(Couleurs.attenue)
                        }
                    }
                }
            }
            .padding()
        }
        .fondIRIS()
        .navigationTitle("Comparer les prix")
        .navigationBarTitleDisplayMode(.inline)
    }

    private func comparer(image: ImageEnvoyee?) async {
        let texte = requete.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !enCours, image != nil || !texte.isEmpty else { return }
        enCours = true
        defer { enCours = false }
        erreur = nil
        let debut = Date()
        do {
            let r: ComparaisonPrix = try await env.pont.post(
                "/api/achats/comparer",
                corps: DemandeComparaison(source: "image", image: image, requete: texte.isEmpty ? nil : texte, parler: false),
                delai: 120)
            resultat = r
            dureeMs = Date().timeIntervalSince(debut) * 1000
            if lecturePermise(env), let resume = r.resume {
                Task { await env.voix.parler(resume) }
            }
        } catch {
            erreur = error
        }
    }
}

// MARK: - Pas à pas (H)

@MainActor
struct EcranPasAPas: View {
    @Environment(EnvironnementIRIS.self) private var env
    @State private var session: SessionPasAPas?
    @State private var recueLe = Date()
    @State private var sujet = ""
    @State private var type = "recette"
    @State private var etapesTexte = ""
    @State private var enCours = false
    @State private var erreur: Error?
    @State private var abonnement: AbonnementEvenements?
    @State private var lecteur = LecteurSansDoublon()

    private let types: [(id: String, nom: String)] = [
        ("recette", "Recette"), ("montage", "Montage"), ("reparation", "Réparation"), ("autre", "Autre"),
    ]

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 16) {
                if !env.lunettesPresentes {
                    LunettesRequisesVue(message: "Le pas à pas marche avec les lunettes VELA.")
                }
                if let session, session.actif {
                    enCoursVue(session)
                } else {
                    formulaire
                }
                if let erreur {
                    BandeauErreur(erreur: erreur)
                }
                Carte(titre: "Limites") {
                    if let limite = session?.limite {
                        NoteVerite(texte: limite)
                    }
                    NoteVerite(texte: "Dans les lunettes, app IRIS ouverte à l'écran : « Dis-moi Iris, étape suivante » (ou « répète », « c'est fini ») passe par ton ordinateur, qui pilote le pas à pas. Écran verrouillé ou app fermée, iOS n'écoute pas : utilise ces boutons.")
                    NoteVerite(texte: "Les minuteurs tournent sur ton ordinateur : leur fin est aussi annoncée par son haut-parleur. Sur l'iPhone, tu l'entends seulement si l'app est ouverte et reliée en direct à l'ordinateur.")
                }
            }
            .padding()
        }
        .fondIRIS()
        .navigationTitle("Pas à pas")
        .navigationBarTitleDisplayMode(.inline)
        .task {
            await charger()
            abonnement = env.pont.abonner { evenement in
                guard evenement.type == "pas_a_pas.etat" else { return }
                if let lue = evenement.champs["session"].flatMap({ try? JSONEncoder().encode($0) })
                    .flatMap({ try? JSONIRIS.decodeur.decode(SessionPasAPas.self, from: $0) }) {
                    session = lue
                    recueLe = Date()
                }
                if let annonce = evenement.champs["annonce"]?.texte, lecturePermise(env) {
                    lecteur.dire(annonce, voix: env.voix)
                }
            }
        }
        .onDisappear { abonnement?.annuler() }
    }

    private var formulaire: some View {
        Carte(titre: "Démarrer") {
            TextField("Sujet (par exemple : crêpes)", text: $sujet)
                .padding(12)
                .background(Couleurs.carte2, in: RoundedRectangle(cornerRadius: 12))
            Picker("Type", selection: $type) {
                ForEach(types, id: \.id) { Text($0.nom).tag($0.id) }
            }
            .pickerStyle(.segmented)
            Text("Tes étapes, une par ligne (facultatif)").font(.footnote).foregroundStyle(Couleurs.texte2)
            TextEditor(text: $etapesTexte)
                .frame(minHeight: 110)
                .scrollContentBackground(.hidden)
                .padding(8)
                .background(Couleurs.carte2, in: RoundedRectangle(cornerRadius: 12))
            Button {
                Task { await demarrer() }
            } label: {
                if enCours { ProgressView().tint(Couleurs.fond) } else { Text("Démarrer le pas à pas") }
            }
            .buttonStyle(.holo)
            .disabled(enCours || !env.lunettesPresentes
                      || (sujet.trimmingCharacters(in: .whitespaces).isEmpty && etapesTexte.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty))
            NoteVerite(texte: "Sans étapes fournies, ton ordinateur les fait rédiger par le moteur VELA : vérifie-les avant de les suivre.")
        }
    }

    @ViewBuilder
    private func enCoursVue(_ s: SessionPasAPas) -> some View {
        let etapes = s.etapes ?? []
        let index = min(max(s.index ?? 0, 0), max(etapes.count - 1, 0))
        let courante = etapes.indices.contains(index) ? etapes[index] : nil
        VStack(alignment: .leading, spacing: 10) {
            Text("\(s.sujet ?? "Pas à pas") · étape \(index + 1) sur \(etapes.count)")
                .font(.subheadline.weight(.semibold))
                .foregroundStyle(Couleurs.fond.opacity(0.7))
            Text(courante?.texte ?? "")
                .font(.system(size: 30, weight: .bold))
                .foregroundStyle(Couleurs.fond)
                .fixedSize(horizontal: false, vertical: true)
        }
        .padding(18)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(Couleurs.holo, in: RoundedRectangle(cornerRadius: 20, style: .continuous))
        .accessibilityElement(children: .combine)

        if let avertissement = s.avertissement {
            NoteVerite(texte: avertissement, genre: .avertissement)
        }

        HStack(spacing: 10) {
            boutonCommande("Précédente", icone: "chevron.left", action: "precedent", variante: .sombre)
            boutonCommande("Répéter", icone: "arrow.counterclockwise", action: "repeter", variante: .sombre)
        }
        boutonCommande("Étape suivante", icone: "chevron.right", action: "suivant", variante: .holo)

        if courante?.minuteurS != nil {
            boutonCommande("Lancer le minuteur de l'étape", icone: "timer", action: "minuteur", variante: .bleu)
        }
        if let minuteurs = s.minuteurs, !minuteurs.isEmpty {
            Carte(titre: "Minuteurs sur ton ordinateur") {
                TimelineView(.periodic(from: .now, by: 1)) { contexte in
                    VStack(alignment: .leading, spacing: 6) {
                        ForEach(minuteurs, id: \.self) { m in
                            let ecoule = contexte.date.timeIntervalSince(recueLe)
                            let reste = max(0, Double(m.restantS ?? 0) - ecoule)
                            Text("Étape \(m.etape) : \(FormatIRIS.duree(secondes: reste))")
                                .monospacedDigit()
                                .foregroundStyle(Couleurs.texte)
                        }
                    }
                }
                boutonCommande("Annuler le minuteur", icone: "xmark", action: "annuler_minuteur", variante: .sombre)
            }
        }
        boutonCommande("C'est fini", icone: "checkmark", action: "terminer", variante: .rouge)
    }

    private func boutonCommande(_ titre: String, icone: String, action: String, variante: VarianteHolo) -> some View {
        Button {
            Task { await commande(action) }
        } label: {
            Label(titre, systemImage: icone)
        }
        .buttonStyle(.holo(variante))
        // Arrêter reste permis sans lunettes (le service l'accepte aussi) ; le reste les exige.
        .disabled(enCours || (action != "terminer" && action != "annuler_minuteur" && !env.lunettesPresentes))
    }

    private func charger() async {
        guard env.pont.etat.estConnecte else { return }
        do {
            let lue: SessionPasAPas = try await env.pont.get("/api/pas-a-pas/etat")
            session = lue
            recueLe = Date()
        } catch {
            erreur = error
        }
    }

    private func demarrer() async {
        guard !enCours else { return }
        enCours = true
        defer { enCours = false }
        erreur = nil
        let lignes = etapesTexte.components(separatedBy: .newlines)
            .map { $0.trimmingCharacters(in: .whitespaces) }
            .filter { !$0.isEmpty }
        do {
            let lue: SessionPasAPas = try await env.pont.post(
                "/api/pas-a-pas/demarrer",
                corps: DemandePasAPas(sujet: sujet.trimmingCharacters(in: .whitespaces), type: type,
                                      etapes: lignes.isEmpty ? nil : lignes, parler: false),
                delai: 120)
            session = lue
            recueLe = Date()
            if let phrase = lue.phrase, lecturePermise(env) { lecteur.dire(phrase, voix: env.voix) }
        } catch {
            erreur = error
        }
    }

    private func commande(_ action: String) async {
        guard !enCours else { return }
        enCours = true
        defer { enCours = false }
        erreur = nil
        do {
            let lue: SessionPasAPas = try await env.pont.post(
                "/api/pas-a-pas/commande", corps: CommandePasAPas(action: action, secondes: nil, parler: false), delai: 60)
            session = lue
            recueLe = Date()
            if let phrase = lue.phrase, lecturePermise(env) { lecteur.dire(phrase, voix: env.voix) }
        } catch {
            erreur = error
        }
    }
}

// MARK: - Entraînement (H)

@MainActor
struct EcranEntrainement: View {
    @Environment(EnvironnementIRIS.self) private var env
    @State private var seance: SeanceEntrainement?
    @State private var recueLe = Date()
    @State private var exercice = ""
    @State private var seriesCibles = 0
    @State private var repos = 90
    @State private var historique: ListeSeances?
    @State private var enCours = false
    @State private var erreur: Error?
    @State private var abonnement: AbonnementEvenements?
    @State private var lecteur = LecteurSansDoublon()

    var body: some View {
        List {
            if !env.lunettesPresentes {
                Section { LunettesRequisesVue(message: "L'entraînement marche avec les lunettes VELA. Ton historique reste consultable ci-dessous.") }
                    .listRowBackground(Color.clear)
            }
            if let seance, seance.actif {
                Section("Séance en cours") { enCoursVue(seance) }
                    .listRowBackground(Couleurs.carte)
            } else {
                Section("Démarrer") { formulaire }
                    .listRowBackground(Couleurs.carte)
            }
            if let erreur {
                Section { BandeauErreur(erreur: erreur) }
                    .listRowBackground(Couleurs.carte)
            }
            Section {
                if let seances = historique?.seances {
                    if seances.isEmpty {
                        Text("Aucune séance gardée.").foregroundStyle(Couleurs.texte2)
                    }
                    ForEach(seances) { s in
                        VStack(alignment: .leading, spacing: 2) {
                            Text(s.exercice ?? "Entraînement").font(.headline).foregroundStyle(Couleurs.texte)
                            Text([FormatIRIS.dateCourte(s.debut?.date),
                                  s.series.map { "\($0) série\($0 > 1 ? "s" : "")" },
                                  s.dureeS.map { FormatIRIS.duree(secondes: $0) }]
                                .compactMap { $0 }.filter { !$0.isEmpty }.joined(separator: " · "))
                                .font(.caption).foregroundStyle(Couleurs.attenue)
                        }
                        .swipeActions {
                            Button("Effacer", role: .destructive) { Task { await supprimer(s.id) } }
                        }
                    }
                }
            } header: {
                Text("Historique")
            } footer: {
                Text("Glisse une séance vers la gauche pour l'effacer de ton ordinateur.")
            }
            .listRowBackground(Couleurs.carte)
            Section {
                if let limite = seance?.limite { NoteVerite(texte: limite) }
                NoteVerite(texte: "Dans les lunettes, app IRIS ouverte à l'écran : « Dis-moi Iris, série terminée » (ou « pause », « on reprend ») passe par ton ordinateur, qui compte la série. Écran verrouillé ou app fermée, iOS n'écoute pas : utilise ces boutons. La fin du repos est aussi annoncée par le haut-parleur de ton ordinateur.")
            }
            .listRowBackground(Couleurs.carte)
        }
        .fondIRIS()
        .navigationTitle("Entraînement")
        .refreshable { await charger() }
        .task {
            await charger()
            abonnement = env.pont.abonner { evenement in
                guard evenement.type == "entrainement.etat" else { return }
                if let lue = evenement.champs["seance"].flatMap({ try? JSONEncoder().encode($0) })
                    .flatMap({ try? JSONIRIS.decodeur.decode(SeanceEntrainement.self, from: $0) }) {
                    seance = lue
                    recueLe = Date()
                }
                if let annonce = evenement.champs["annonce"]?.texte, lecturePermise(env) {
                    lecteur.dire(annonce, voix: env.voix)
                }
            }
        }
        .onDisappear { abonnement?.annuler() }
    }

    private var formulaire: some View {
        VStack(alignment: .leading, spacing: 10) {
            TextField("Exercice (facultatif)", text: $exercice)
                .padding(12)
                .background(Couleurs.carte2, in: RoundedRectangle(cornerRadius: 12))
            Stepper(seriesCibles == 0 ? "Séries : sans objectif" : "Séries visées : \(seriesCibles)", value: $seriesCibles, in: 0...50)
                .foregroundStyle(Couleurs.texte)
            Stepper("Repos : \(FormatIRIS.duree(secondes: Double(repos)))", value: $repos, in: 10...900, step: 10)
                .foregroundStyle(Couleurs.texte)
            Button {
                Task { await demarrer() }
            } label: {
                if enCours { ProgressView().tint(Couleurs.fond) } else { Text("Démarrer la séance") }
            }
            .buttonStyle(.holo)
            .disabled(enCours || !env.lunettesPresentes)
        }
    }

    @ViewBuilder
    private func enCoursVue(_ s: SeanceEntrainement) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(s.exercice ?? "Entraînement").font(.title2.bold()).foregroundStyle(Couleurs.texte)
            Text("Séries faites : \(s.series ?? 0)" + (s.seriesCibles.map { " sur \($0)" } ?? ""))
                .font(.title3).foregroundStyle(Couleurs.texte)
            if s.etat == "repos" {
                TimelineView(.periodic(from: .now, by: 1)) { contexte in
                    let reste = max(0, (s.reposRestantS ?? 0) - contexte.date.timeIntervalSince(recueLe))
                    Text("Repos : \(FormatIRIS.duree(secondes: reste))")
                        .font(.system(size: 34, weight: .bold)).monospacedDigit()
                        .foregroundStyle(Couleurs.vert)
                }
            } else if s.enPause == true {
                Text("En pause").font(.title3.bold()).foregroundStyle(Couleurs.avertissement)
            }
            if let suspendue = s.memoireSuspendue, !suspendue.isEmpty {
                NoteVerite(texte: "Mémoire suspendue (\(suspendue)) : cette séance ne sera pas gardée.", genre: .avertissement)
            }
        }
        Button("Série terminée") { Task { await commande("serie") } }
            .buttonStyle(.holo)
            .disabled(enCours || !env.lunettesPresentes)
        if s.enPause == true {
            Button("Reprendre") { Task { await commande("reprendre") } }
                .buttonStyle(.holo(.bleu))
                .disabled(enCours || !env.lunettesPresentes)
        } else {
            Button("Pause") { Task { await commande("pause") } }
                .buttonStyle(.holo(.sombre))
                .disabled(enCours)
        }
        Button("Terminer la séance") { Task { await commande("terminer") } }
            .buttonStyle(.holo(.rouge))
            .disabled(enCours)
    }

    private func charger() async {
        guard env.pont.etat.estConnecte else { return }
        do {
            let lue: SeanceEntrainement = try await env.pont.get("/api/entrainement/etat")
            seance = lue
            recueLe = Date()
            let seances: ListeSeances = try await env.pont.get("/api/entrainement/seances")
            historique = seances
        } catch {
            erreur = error
        }
    }

    private func demarrer() async {
        guard !enCours else { return }
        enCours = true
        defer { enCours = false }
        erreur = nil
        let nom = exercice.trimmingCharacters(in: .whitespaces)
        do {
            let lue: SeanceEntrainement = try await env.pont.post(
                "/api/entrainement/demarrer",
                corps: DemandeEntrainement(exercice: nom.isEmpty ? nil : nom, seriesCibles: seriesCibles == 0 ? nil : seriesCibles,
                                           reposS: repos, parler: false),
                delai: 30)
            seance = lue
            recueLe = Date()
            if let phrase = lue.phrase, lecturePermise(env) { lecteur.dire(phrase, voix: env.voix) }
        } catch {
            erreur = error
        }
    }

    private func commande(_ action: String) async {
        guard !enCours else { return }
        enCours = true
        defer { enCours = false }
        erreur = nil
        do {
            let lue: SeanceEntrainement = try await env.pont.post(
                "/api/entrainement/commande", corps: CommandeEntrainement(action: action, parler: false), delai: 30)
            seance = lue
            recueLe = Date()
            if let phrase = lue.phrase, lecturePermise(env) { lecteur.dire(phrase, voix: env.voix) }
            if action == "terminer" {
                if let seances: ListeSeances = try? await env.pont.get("/api/entrainement/seances") {
                    historique = seances
                }
            }
        } catch {
            erreur = error
        }
    }

    private func supprimer(_ id: String) async {
        do {
            let _: ReponseIgnoree = try await env.pont.delete("/api/entrainement/seances/\(id)")
            let seances: ListeSeances = try await env.pont.get("/api/entrainement/seances")
            historique = seances
        } catch {
            erreur = error
        }
    }
}

// MARK: - Résumé du jour (G)

@MainActor
struct EcranResumeJour: View {
    @Environment(EnvironnementIRIS.self) private var env
    @State private var jour = Date()
    @State private var resume: ResumeJour?
    @State private var enCours = false
    @State private var erreur: Error?

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 16) {
                Carte {
                    DatePicker("Jour", selection: $jour, in: ...Date(), displayedComponents: .date)
                        .foregroundStyle(Couleurs.texte)
                    Button {
                        Task { await charger() }
                    } label: {
                        if enCours { ProgressView().tint(Couleurs.fond) } else { Text("Voir le résumé") }
                    }
                    .buttonStyle(.holo(.sombre, compact: true))
                    .disabled(enCours || !env.pont.etat.estConnecte)
                }
                if let erreur {
                    BandeauErreur(erreur: erreur)
                }
                if let resume {
                    Carte(titre: "Résumé") {
                        Text(resume.texte.isEmpty ? "Rien de noté ce jour-là." : resume.texte)
                            .foregroundStyle(Couleurs.texte)
                            .textSelection(.enabled)
                        Button("Lire sur l'iPhone") {
                            Task { await env.voix.parler(resume.texte) }
                        }
                        .buttonStyle(.holo(.sombre, compact: true))
                        .disabled(resume.texte.isEmpty || !lecturePermise(env))
                        if !env.lunettesPresentes {
                            NoteVerite(texte: "La lecture à voix haute marche avec les lunettes VELA ; le résumé écrit reste consultable.")
                        }
                        NoteVerite(texte: resume.local == false
                                   ? "Rédigé par ton ordinateur avec le moteur VELA, à partir de ce qu'IRIS a noté."
                                   : "Rédigé sur ton ordinateur, sans le moteur VELA.")
                        if let note = resume.note { NoteVerite(texte: note) }
                    }
                    if let sections = resume.sections {
                        section("Fait", sections.fait)
                        section("Reste à faire", sections.reste)
                        section("Rappels à venir", sections.rappels)
                        section("Souvenirs retenus dans la journée", sections.aRetenir)
                    }
                    if let limite = resume.limite {
                        NoteVerite(texte: limite)
                    }
                }
            }
            .padding()
        }
        .fondIRIS()
        .navigationTitle("Résumé du jour")
        .navigationBarTitleDisplayMode(.inline)
        .task { await charger() }
    }

    @ViewBuilder
    private func section(_ titre: String, _ elements: [String]?) -> some View {
        if let elements, !elements.isEmpty {
            Carte(titre: titre) {
                ForEach(elements, id: \.self) { element in
                    HStack(alignment: .firstTextBaseline, spacing: 8) {
                        Text("•").foregroundStyle(Couleurs.attenue).accessibilityHidden(true)
                        Text(element).foregroundStyle(Couleurs.texte2)
                    }
                }
            }
        }
    }

    private func charger() async {
        guard env.pont.etat.estConnecte, !enCours else { return }
        enCours = true
        defer { enCours = false }
        erreur = nil
        do {
            let lu: ResumeJour = try await env.pont.get("/api/resume/jour",
                                                        parametres: [URLQueryItem(name: "date", value: FormatQuotidien.jourISO(jour))],
                                                        delai: 90)
            resume = lu
        } catch {
            erreur = error
        }
    }
}
