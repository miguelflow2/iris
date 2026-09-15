// EcranIA.swift — l'onglet IA : écrire ou dire une demande à IRIS, qui la traite sur l'ordinateur.
//
// Règle « lunettes d'abord » : sans lunettes, la voix est refusée et l'écrit consomme un aperçu de
// 10 messages (compté par l'ordinateur). Le compteur restant est affiché ici, tel que l'ordinateur
// le donne.

import SwiftUI

@MainActor
struct EcranIA: View {
    @Environment(EnvironnementIRIS.self) private var env
    @State private var saisie = ""
    @State private var lectureAuto = UserDefaults.standard.object(forKey: "iris_lecture_auto") as? Bool ?? true
    @State private var erreurVoix: String? = nil
    @State private var enEcoute = false
    @FocusState private var champActif: Bool

    var body: some View {
        let conversation = env.conversation
        VStack(spacing: 0) {
            ScrollViewReader { defilement in
                ScrollView {
                    LazyVStack(alignment: .leading, spacing: 10) {
                        bandeauxHaut
                        if conversation.bulles.isEmpty {
                            Text("Demande à IRIS de faire quelque chose sur ton ordinateur, de chercher dans ta mémoire ou de t'aider à écrire. Elle répond ici et à voix haute.")
                                .foregroundStyle(Couleurs.attenue)
                                .padding(.top, 24)
                        }
                        ForEach(conversation.bulles) { bulle in
                            VueBulle(bulle: bulle)
                                .id(bulle.id)
                        }
                    }
                    .padding()
                }
                .onChange(of: conversation.bulles.last?.texte) { _, _ in
                    if let dernier = conversation.bulles.last {
                        withAnimation { defilement.scrollTo(dernier.id, anchor: .bottom) }
                    }
                }
            }
            barreSaisie
        }
        .fondIRIS()
        .navigationTitle("IA")
        .toolbar {
            ToolbarItem(placement: .topBarTrailing) {
                Menu {
                    Toggle("Lire les réponses à voix haute", isOn: Binding(
                        get: { lectureAuto },
                        set: { lectureAuto = $0; UserDefaults.standard.set($0, forKey: "iris_lecture_auto") }))
                    Button("Relire la dernière réponse") {
                        Task { await env.voix.parler(env.voix.derniereParole) }
                    }
                    .disabled(env.voix.derniereParole.isEmpty)
                    Button("Effacer l'affichage", role: .destructive) { conversation.effacerFil() }
                } label: {
                    Image(systemName: "ellipsis.circle")
                        .accessibilityLabel("Options")
                }
            }
        }
        .alert(item: Binding(get: { conversation.accordDemande }, set: { conversation.accordDemande = $0 })) { demande in
            Alert(
                title: Text(demande.titre),
                message: Text(demande.detail),
                primaryButton: .default(Text("Autoriser")) {
                    Task { await conversation.repondreAccord(demande, accepte: true) }
                },
                secondaryButton: .cancel(Text("Refuser")) {
                    Task { await conversation.repondreAccord(demande, accepte: false) }
                })
        }
        .task(id: env.ecouteDemandeeAuLancement) {
            guard env.ecouteDemandeeAuLancement else { return }
            env.ecouteDemandeeAuLancement = false
            await ecouter()
        }
        .task { await env.attestation.rafraichirPresence() }
    }

    @ViewBuilder
    private var bandeauxHaut: some View {
        if !env.lunettesPresentes, env.pont.etat.estConnecte {
            let presence = env.attestation.presence
            VStack(alignment: .leading, spacing: 8) {
                if let restant = presence?.apercuRestant, let total = presence?.apercuTotal {
                    NoteVerite(texte: "Sans lunettes : aperçu d'IRIS par écrit, \(restant) message\(restant > 1 ? "s" : "") restant\(restant > 1 ? "s" : "") sur \(total). La voix demande les lunettes.",
                               genre: restant == 0 ? .avertissement : .limite)
                }
                LunettesRequisesVue(message: "Parler à IRIS marche avec les lunettes VELA.",
                                    acheterURL: presence?.acheterUrl.flatMap { URL(string: $0) })
            }
        }
        switch env.pont.etat {
        case .nonConfigure, .motDePasseRequis:
            Carte {
                Text("Relie d'abord ton ordinateur : c'est lui qui fait le travail d'IRIS.")
                    .foregroundStyle(Couleurs.texte2)
                NavigationLink("Relier mon ordinateur") { EcranConnexionPC() }
                    .buttonStyle(.holo(.sombre, compact: true))
            }
        case .horsLigne(let raison):
            NoteVerite(texte: "Ton ordinateur ne répond pas : \(raison)", genre: .avertissement)
        default:
            EmptyView()
        }
        if let erreurVoix {
            NoteVerite(texte: erreurVoix, genre: .erreur)
        }
    }

    private var barreSaisie: some View {
        VStack(spacing: 6) {
            if enEcoute || env.voix.etat == .commande {
                Text(env.voix.partiel.isEmpty ? "Je t'écoute…" : "« \(env.voix.partiel) »")
                    .font(.callout)
                    .foregroundStyle(Couleurs.texte2)
                    .frame(maxWidth: .infinity, alignment: .leading)
            }
            HStack(spacing: 10) {
                TextField("Écris à IRIS…", text: $saisie, axis: .vertical)
                    .lineLimit(1...5)
                    .focused($champActif)
                    .padding(.horizontal, 14)
                    .padding(.vertical, 10)
                    .background(Couleurs.carte, in: RoundedRectangle(cornerRadius: 20))
                    .foregroundStyle(Couleurs.texte)
                    .submitLabel(.send)
                    .onSubmit { Task { await envoyerSaisie() } }

                if saisie.trimmingCharacters(in: .whitespaces).isEmpty {
                    Button {
                        Task { await ecouter() }
                    } label: {
                        Image(systemName: enEcoute ? "stop.fill" : "mic.fill")
                            .font(.title3.weight(.semibold))
                            .frame(width: 46, height: 46)
                            .foregroundStyle(Couleurs.fond)
                            .background(Couleurs.holo, in: Circle())
                    }
                    .accessibilityLabel(enEcoute ? "Arrêter l'écoute" : "Dire une demande à IRIS")
                    .disabled(!enEcoute && (env.conversation.occupe || env.raisonVoixImpossible() != nil))
                } else {
                    Button {
                        Task { await envoyerSaisie() }
                    } label: {
                        Image(systemName: "arrow.up")
                            .font(.title3.weight(.bold))
                            .frame(width: 46, height: 46)
                            .foregroundStyle(Couleurs.fond)
                            .background(Couleurs.holo, in: Circle())
                    }
                    .accessibilityLabel("Envoyer")
                    .disabled(env.conversation.occupe || !env.pont.etat.estConnecte)
                }
            }
        }
        .padding(.horizontal)
        .padding(.vertical, 10)
        .background(Couleurs.fond2)
    }

    private func envoyerSaisie() async {
        let texte = saisie
        guard !texte.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else { return }
        saisie = ""
        let reponse = await env.demander(texte)
        await env.attestation.rafraichirPresence()
        if lectureAuto, let reponse {
            await env.voix.parler(reponse)
        }
    }

    private func ecouter() async {
        if enEcoute {
            env.voix.annulerEcoute()
            return
        }
        if let raison = env.raisonVoixImpossible() {
            erreurVoix = raison
            return
        }
        erreurVoix = nil
        champActif = false
        enEcoute = true
        do {
            let phrase = try await env.voix.ecouterUnePhrase(langue: env.voix.langueIRIS, delaiMax: 8)
            enEcoute = false
            if let reponse = await env.demanderAVoix(phrase) {
                await env.voix.parler(reponse)
            }
        } catch {
            enEcoute = false
            if case ErreurVoix.interrompu? = error as? ErreurVoix { return }
            erreurVoix = error.localizedDescription
        }
    }
}

@MainActor
struct VueBulle: View {
    let bulle: ConversationIRIS.Bulle

    var body: some View {
        HStack {
            if bulle.role == .moi { Spacer(minLength: 40) }
            VStack(alignment: .leading, spacing: 4) {
                Text(bulle.texte)
                    .foregroundStyle(bulle.role == .moi ? Couleurs.fond : Couleurs.texte)
                    .textSelection(.enabled)
                if let meta = bulle.meta {
                    Text(meta)
                        .font(.caption)
                        .foregroundStyle(Couleurs.attenue)
                }
            }
            .padding(.horizontal, 14)
            .padding(.vertical, 10)
            .background {
                switch bulle.role {
                case .moi: Couleurs.holo
                case .iris: Couleurs.carte
                case .info: Couleurs.carte2
                }
            }
            .clipShape(RoundedRectangle(cornerRadius: 18, style: .continuous))
            .opacity(bulle.enAttente ? 0.7 : 1)
            .accessibilityElement(children: .combine)
            .accessibilityLabel((bulle.role == .moi ? "Toi : " : bulle.role == .iris ? "IRIS : " : "") + bulle.texte)
            if bulle.role != .moi { Spacer(minLength: 40) }
        }
    }
}
