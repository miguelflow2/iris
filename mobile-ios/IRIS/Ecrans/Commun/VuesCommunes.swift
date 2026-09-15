// VuesCommunes.swift — morceaux d'interface partagés : lunettes requises, verrouillage, état du PC.

import SwiftUI

/// « Cette fonction marche avec les lunettes VELA » : jamais une erreur technique, toujours deux
/// actions. Aucune mention d'un mode de démonstration (accès propriétaire caché).
@MainActor
struct LunettesRequisesVue: View {
    @Environment(EnvironnementIRIS.self) private var env
    @Environment(\.openURL) private var ouvrirURL
    let message: String
    let acheterURL: URL?
    @State private var appairage = false

    // Initialiseur explicite : les propriétés privées (@Environment, @State) ne doivent pas rendre
    // l'initialiseur implicite inaccessible depuis les autres écrans.
    init(message: String = "Cette fonction marche avec les lunettes VELA.", acheterURL: URL? = nil) {
        self.message = message
        self.acheterURL = acheterURL
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            Label {
                Text(message)
                    .font(.headline)
                    .foregroundStyle(Couleurs.texte)
            } icon: {
                Image(systemName: "eyeglasses")
                    .foregroundStyle(Couleurs.holoIcone)
            }
            Button("Connecter mes lunettes") { appairage = true }
                .buttonStyle(.holo)
            Button("Acheter les lunettes") {
                ouvrirURL(acheterURL ?? EnvironnementIRIS.urlAchat)
            }
            .buttonStyle(.holo(.contour))
        }
        .padding(16)
        .background(Couleurs.carte, in: RoundedRectangle(cornerRadius: 16, style: .continuous))
        .sheet(isPresented: $appairage) {
            NavigationStack {
                Group {
                    if let perception = env.perception {
                        perception.ecranLunettes()
                    } else {
                        ScrollView {
                            Carte(titre: "Lunettes") {
                                Text("L'appairage des lunettes n'est pas inclus dans cette version de l'app iPhone. Tu peux connecter les lunettes à ton ordinateur : IRIS les verra de là.")
                                    .foregroundStyle(Couleurs.texte2)
                            }
                            .padding()
                        }
                        .fondIRIS()
                    }
                }
                .toolbar {
                    ToolbarItem(placement: .cancellationAction) {
                        Button("Fermer") { appairage = false }
                    }
                }
            }
            .preferredColorScheme(.dark)
        }
    }
}

/// Écran de verrouillage : IRIS a été verrouillée (sur l'ordinateur ou à distance). Seul le mot de
/// passe du propriétaire la déverrouille. L'état est gardé sur l'iPhone : il reste affiché hors ligne,
/// et ne se lève que quand l'ordinateur répond qu'IRIS n'est plus verrouillée.
@MainActor
struct VerrouVue: View {
    @Environment(EnvironnementIRIS.self) private var env
    let raison: String
    @State private var motDePasse = ""
    @State private var enCours = false
    @State private var erreur: String? = nil
    @State private var reconnexion = false

    init(raison: String) {
        self.raison = raison
    }

    var body: some View {
        VStack(spacing: 20) {
            Spacer()
            Image(systemName: "lock.fill")
                .font(.system(size: 56))
                .foregroundStyle(Couleurs.holoIcone)
                .accessibilityHidden(true)
            Text("IRIS est verrouillée")
                .font(.title.bold())
                .foregroundStyle(Couleurs.texte)
            Text(raison)
                .multilineTextAlignment(.center)
                .foregroundStyle(Couleurs.texte2)
            if env.pont.aUneSession {
                SecureField("Mot de passe du propriétaire", text: $motDePasse)
                    .textContentType(.password)
                    .padding(14)
                    .background(Couleurs.carte, in: RoundedRectangle(cornerRadius: 14))
                    .submitLabel(.go)
                    .onSubmit { Task { await deverrouiller() } }
                if let erreur {
                    NoteVerite(texte: erreur, genre: .erreur)
                }
                Button {
                    Task { await deverrouiller() }
                } label: {
                    if enCours { ProgressView().tint(Couleurs.fond) } else { Text("Déverrouiller") }
                }
                .buttonStyle(.holo)
                .disabled(motDePasse.isEmpty || enCours)
            } else {
                // Session révoquée (effacement à distance, mot de passe changé) : il faut d'abord se
                // reconnecter à l'ordinateur, qui dira ensuite s'il est encore verrouillé.
                Text("La session de cet iPhone n'est plus valide : reconnecte-toi à ton ordinateur, puis déverrouille.")
                    .multilineTextAlignment(.center)
                    .foregroundStyle(Couleurs.texte2)
                Button("Me reconnecter à l'ordinateur") { reconnexion = true }
                    .buttonStyle(.holo)
            }
            // Verrouillée, l'état ne passe jamais à « hors ligne » : le pont retient à part que l'ordinateur
            // n'a pas répondu à la dernière vérification.
            if let injoignable = env.pont.injoignablePendantVerrou {
                NoteVerite(texte: "Ton ordinateur ne répond pas (\(injoignable)) : IRIS reste verrouillée sur cet iPhone jusqu'à ce qu'il réponde.", genre: .avertissement)
            }
            NoteVerite(texte: "Verrou logiciel : il s'applique à l'application IRIS, pas au matériel.")
            Spacer()
        }
        .padding(24)
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(Couleurs.fond.ignoresSafeArea())
        .accessibilityAddTraits(.isModal)
        .sheet(isPresented: $reconnexion) {
            NavigationStack {
                EcranConnexionPC()
                    .toolbar {
                        ToolbarItem(placement: .cancellationAction) {
                            Button("Fermer") { reconnexion = false }
                        }
                    }
            }
            .preferredColorScheme(.dark)
        }
    }

    private func deverrouiller() async {
        guard !motDePasse.isEmpty, !enCours else { return }
        enCours = true
        defer { enCours = false }
        do {
            try await env.pont.deverrouiller(motDePasse: motDePasse)
            motDePasse = ""
            erreur = nil
        } catch {
            erreur = error.localizedDescription
        }
    }
}

/// Pastille d'état de la liaison avec l'ordinateur.
@MainActor
struct PastillePC: View {
    @Environment(EnvironnementIRIS.self) private var env

    var body: some View {
        let info = description
        HStack(spacing: 6) {
            Circle().fill(info.couleur).frame(width: 8, height: 8)
            Text(info.texte)
                .font(.footnote.weight(.medium))
                .foregroundStyle(Couleurs.texte2)
                .lineLimit(1)
        }
        .padding(.horizontal, 10)
        .padding(.vertical, 6)
        .background(Couleurs.carte, in: Capsule())
        .accessibilityElement(children: .combine)
        .accessibilityLabel("Ordinateur : \(info.texte)")
    }

    private var description: (texte: String, couleur: Color) {
        switch env.pont.etat {
        case .nonConfigure: return ("Ordinateur non relié", Couleurs.attenue)
        case .motDePasseRequis: return ("Mot de passe requis", Couleurs.orange)
        case .connexion: return ("Connexion…", Couleurs.orange)
        case .connecte(let evenements):
            return (evenements ? "Ordinateur relié" : "Ordinateur relié (sans direct)", Couleurs.vert)
        case .horsLigne: return ("Hors ligne", Couleurs.rouge)
        case .verrouille: return ("IRIS verrouillée", Couleurs.rouge)
        }
    }
}

/// Pastille d'état des lunettes.
@MainActor
struct PastilleLunettes: View {
    @Environment(EnvironnementIRIS.self) private var env

    var body: some View {
        let presentes = env.lunettesPresentes
        HStack(spacing: 6) {
            Image(systemName: "eyeglasses")
                .foregroundStyle(presentes ? Couleurs.vert : Couleurs.attenue)
            Text(texte)
                .font(.footnote.weight(.medium))
                .foregroundStyle(Couleurs.texte2)
                .lineLimit(1)
        }
        .padding(.horizontal, 10)
        .padding(.vertical, 6)
        .background(Couleurs.carte, in: Capsule())
        .accessibilityElement(children: .combine)
    }

    private var texte: String {
        let presentes = env.lunettesPresentes
        if let etat = env.perception?.lunettes.etat, etat.connectees {
            if !etat.verifiees { return "Appareil relié non reconnu" }
            if !presentes {
                return env.attestation.erreur != nil ? "Lunettes refusées par l'ordinateur" : "Lunettes : vérification par l'ordinateur…"
            }
            if let batterie = etat.batterie { return "\(etat.nom ?? "Lunettes") · \(batterie) %" }
            return etat.nom ?? "Lunettes connectées"
        }
        if presentes {
            return env.attestation.presence?.source == "pc" ? "Lunettes vues par l'ordinateur" : "Lunettes présentes"
        }
        return "Lunettes absentes"
    }
}

/// Bandeau d'erreur ou de note, affiché tel quel.
@MainActor
struct BandeauErreur: View {
    let erreur: Error

    var body: some View {
        let pont = erreur as? ErreurPont
        if let pont, case .lunettesRequises(let refus) = pont {
            LunettesRequisesVue(message: refus.message, acheterURL: refus.acheterUrl.flatMap { URL(string: $0) })
        } else if let pont, case .consentement(let refus) = pont {
            NoteVerite(texte: (refus.message ?? "Consentement requis.") + " Cette autorisation se donne sur l'ordinateur, dans IRIS › Confidentialité.",
                       genre: .avertissement)
        } else {
            NoteVerite(texte: erreur.localizedDescription, genre: .erreur)
        }
    }
}
