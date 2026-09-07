# Squelette Swift — un point de départ concret, pas un produit fini

Écrit le 2026-09-06. Complément de `PONT-TELEPHONE-PC.md`. Ce fichier donne le **squelette de code**
de la partie « app iPhone » : de quoi démarrer une fois un Mac disponible. Deux avertissements
honnêtes, à lire avant tout :

1. **Ce code n'a pas été compilé.** Il ne peut pas l'être ici (Windows, pas de Xcode). C'est un
   point de départ annoté, à reprendre et corriger sur Mac. Les API utilisées sont **réelles**
   (`URLSession`, `Codable`, `AppIntents`, `MessageUI`) — rien d'inventé — mais la syntaxe exacte,
   les imports et le cycle de vie sont à valider dans Xcode.
2. **Il ne contient que le possible.** Aucune ligne ne prétend piloter une autre app, voir l'écran
   ou décrocher un appel cellulaire : ces murs (cf. REALITE-IOS.md) n'ont pas de code parce qu'ils
   n'ont pas d'API.

---

## 1. Le client du pont — parler au backend IRIS

Portage direct du JavaScript de `backend/iris/mobile.py`. Mêmes routes, même serrure.

```swift
import Foundation

// L'adresse Tailscale stable du PC maison, p. ex. "https://bureau.tail1234.ts.net".
// Voir docs/ACCES-DISTANT.md. Jamais une adresse 192.168.* : elle ne vaut qu'à la maison.
struct PontIRIS {
    let base: URL
    var session: String?   // le jeton de session, rangé dans le Keychain (pas UserDefaults)

    // En-tête commun : Authorization: Bearer <jeton>. Jamais le jeton dans l'URL.
    private func requete(_ chemin: String, methode: String = "GET", corps: Data? = nil) -> URLRequest {
        var r = URLRequest(url: base.appendingPathComponent(chemin))
        r.httpMethod = methode
        r.setValue("application/json", forHTTPHeaderField: "Content-Type")
        if let s = session { r.setValue("Bearer \(s)", forHTTPHeaderField: "Authorization") }
        r.httpBody = corps
        return r
    }

    // 1) Un mot de passe est-il posé ? GET /api/compte -> { configure }
    struct EtatCompte: Codable { let configure: Bool }
    func compteConfigure() async throws -> Bool {
        let (data, _) = try await URLSession.shared.data(for: requete("api/compte"))
        return try JSONDecoder().decode(EtatCompte.self, from: data).configure
    }

    // 2) Se connecter. POST /api/compte/connexion { mot_de_passe } -> { session }
    struct Connexion: Codable { let session: String }
    mutating func connexion(motDePasse: String) async throws {
        let corps = try JSONEncoder().encode(["mot_de_passe": motDePasse])
        let (data, reponse) = try await URLSession.shared.data(
            for: requete("api/compte/connexion", methode: "POST", corps: corps))
        guard (reponse as? HTTPURLResponse)?.statusCode == 200 else {
            throw ErreurPont.motDePasseRefuse
        }
        self.session = try JSONDecoder().decode(Connexion.self, from: data).session
        // TODO: ranger self.session dans le Keychain, le relire au lancement.
    }

    // 3) Envoyer un message et attendre la réponse (sondage, comme la page web).
    struct Conversation: Codable { let id: String }
    struct Message: Codable { let role: String; let text: String? }
    struct FilConversation: Codable { let messages: [Message] }

    func ouvrirConversation(titre: String) async throws -> String {
        let corps = try JSONEncoder().encode(["title": titre, "agent": "auto"])
        let (data, _) = try await URLSession.shared.data(
            for: requete("api/conversations", methode: "POST", corps: corps))
        return try JSONDecoder().decode(Conversation.self, from: data).id
    }

    func envoyer(texte: String, dans conversation: String) async throws {
        // images: [] — l'app iPhone n'envoie pas d'image au PC dans la v1.
        let corps = try JSONSerialization.data(withJSONObject:
            ["text": texte, "agent": "auto", "images": []])
        _ = try await URLSession.shared.data(
            for: requete("api/conversations/\(conversation)/messages", methode: "POST", corps: corps))
    }

    // Sonde jusqu'à ~120 s, comme mobile.py. Une app native pourra remplacer ça par un push APNs.
    func attendreReponse(dans conversation: String) async throws -> String? {
        let debut = Date()
        while Date().timeIntervalSince(debut) < 120 {
            try await Task.sleep(nanoseconds: 1_200_000_000)   // 1,2 s
            let (data, _) = try await URLSession.shared.data(for: requete("api/conversations/\(conversation)"))
            let fil = try JSONDecoder().decode(FilConversation.self, from: data)
            if let dernier = fil.messages.last(where: { $0.role == "assistant" }),
               let texte = dernier.text, !texte.isEmpty {
                return texte
            }
        }
        return nil
    }
}

enum ErreurPont: Error { case motDePasseRefuse, injoignable }
```

---

## 2. Les brouillons SMS — l'écran natif, geste humain obligatoire

`GET /api/telephonie/en_attente` renvoie les brouillons ; on ouvre le SMS avec l'écran d'Apple.
**Rien ne part sans le toucher de l'utilisateur** — c'est iOS qui l'impose, pas ce code.

```swift
import SwiftUI
import MessageUI

// Forme d'un brouillon, d'après Brouillon.en_dict (telephonie.py). Sur iPhone on prend lien_ios.
struct Brouillon: Codable, Identifiable {
    let id: String
    let genre: String            // "sms" | "appel"
    let numero: String
    let numero_lisible: String
    let texte: String
    let lien_ios: String
}

// MFMessageComposeViewController est l'écran de rédaction SMS d'Apple, pré-rempli.
// On l'enveloppe pour SwiftUI. L'utilisateur voit le texte, et c'est LUI qui touche Envoyer.
struct RedacteurSMS: UIViewControllerRepresentable {
    let numero: String
    let texte: String
    var fini: (_ envoye: Bool) -> Void

    func makeUIViewController(context: Context) -> MFMessageComposeViewController {
        let vc = MFMessageComposeViewController()
        vc.recipients = [numero]
        vc.body = texte
        vc.messageComposeDelegate = context.coordinator
        return vc
    }
    func updateUIViewController(_ vc: MFMessageComposeViewController, context: Context) {}
    func makeCoordinator() -> Coord { Coord(fini: fini) }

    final class Coord: NSObject, MFMessageComposeViewControllerDelegate {
        let fini: (Bool) -> Void
        init(fini: @escaping (Bool) -> Void) { self.fini = fini }
        func messageComposeViewController(_ c: MFMessageComposeViewController,
                                          didFinishWith result: MessageComposeResult) {
            fini(result == .sent)   // .sent seulement si l'utilisateur a réellement envoyé
            c.dismiss(animated: true)
        }
    }
}
```

Après retour (`fini`), l'app appelle `POST /api/telephonie/{id}/envoye` ou `/annule` (voir le
client du §1 à compléter). Pour un **appel**, pas d'écran spécial : on ouvre `brouillon.lien_ios`
(un `tel:…`) avec `UIApplication.shared.open(...)` ; iOS demande « Appeler ? » et l'utilisateur
confirme.

---

## 3. L'activation vocale — « Dis Siri, parle à IRIS »

Le mot maison « Dis-moi Iris » écran éteint est **impossible** (REALITE-IOS.md, point 8). Le
substitut réel est un **App Shortcut** : IRIS déclare une phrase à Siri.

```swift
import AppIntents

// Une action que l'app publie : « ouvre IRIS, prête à écouter ».
struct ParlerAIris: AppIntent {
    static var title: LocalizedStringResource = "Parler à IRIS"
    static var openAppWhenRun = true   // Siri ouvre l'app ; on ne peut pas piloter en fond

    func perform() async throws -> some IntentResult {
        // TODO: signaler à l'app de démarrer l'écoute vocale dès l'ouverture.
        return .result()
    }
}

// La phrase que l'utilisateur dit à Siri : « Dis Siri, parle à IRIS ».
struct RaccourcisIRIS: AppShortcutsProvider {
    static var appShortcuts: [AppShortcut] {
        AppShortcut(intent: ParlerAIris(),
                    phrases: ["Parle à \(.applicationName)", "Parler à IRIS"],
                    shortTitle: "Parler à IRIS",
                    systemImageName: "mic.fill")
    }
}
```

C'est tout ce que l'activation mains-libres autorise : **ouvrir** l'app à la voix, pas l'écouter en
permanence en tâche de fond. À valider dans Xcode : l'enchaînement Siri → écoute continue selon la
version d'iOS.

---

## Ce que ce squelette ne contient pas — et pourquoi

- **Pas de code pour voir l'écran, ni pour cliquer dans une autre app** : aucune API ne le permet
  (sandbox). Ce travail vit sur le PC (`capture.py`, `tools.py`), joint par le client du §1.
- **Pas de décrochage d'appel cellulaire** : CallKit ne touche pas la ligne SIM. Le code CallKit
  n'aura de sens que le jour d'un vrai numéro VoIP IRIS (phase 3 du plan).
- **Pas d'envoi de SMS silencieux, ni de lecture du numéro de la ligne** : impossibles, y compris en
  app signée par Miguel.

Le squelette ne fait donc **que** le faisable, et le rend concret. Le reste n'est pas « à écrire
plus tard » : c'est « à faire ailleurs » (sur le PC) ou « à ne pas promettre ».
