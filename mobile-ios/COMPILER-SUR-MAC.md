# Compiler l'app iPhone IRIS sur un Mac

Écrit le 2026-09-13 par l'équipe ios-cœur. **À lire avant tout : le code Swift de `mobile-ios/IRIS/`
a été écrit sur Windows, sans Xcode ni compilateur Swift.** Il n'a jamais été compilé, jamais lancé
dans un simulateur, jamais installé sur un iPhone. Chaque fichier a été relu deux fois en cherchant
les erreurs de compilation et n'emploie que des API publiques d'iOS 17, mais **il faut s'attendre à
une première série d'erreurs à corriger dans Xcode** (le plus probable : inférence de types dans
les vues SwiftUI, isolation `@MainActor`, avertissements de concurrence). Rien de ce qui suit n'a
été exécuté.

---

## 1. Ce qu'il faut

| Quoi | Détail | Coût |
|---|---|---|
| Un Mac | macOS 14 (Sonoma) ou plus récent | Mac mini d'occasion, ou Mac loué à l'heure |
| Xcode 15 ou plus récent | App Store du Mac (gratuit, ~10 Go) | 0 $ |
| Homebrew | <https://brew.sh> | 0 $ |
| XcodeGen | génère `IRIS.xcodeproj` à partir de `project.yml` | 0 $ |
| Compte Apple Developer | installer au-delà de 7 jours, TestFlight, App Store | **99 $ US/an** |
| Un iPhone sous iOS 17 ou plus | la reconnaissance vocale « sur l'appareil » et les zones (CLMonitor) exigent un vrai appareil | — |
| Lunettes VELA | pour l'attestation et la voix par Bluetooth | — |
| Tailscale | sur l'ordinateur ET sur l'iPhone (app Tailscale de l'App Store) | 0 $ (usage personnel) |

Sans compte payant, un identifiant Apple gratuit permet d'installer l'app sur **son propre**
iPhone pour 7 jours (profil de développement « Personal Team »). Suffisant pour un premier essai,
pas pour un pilote.

## 2. Générer le projet

```sh
brew install xcodegen
cd chemin/vers/iris/mobile-ios
xcodegen generate
open IRIS.xcodeproj
```

`xcodegen generate` crée `IRIS.xcodeproj` et `IRIS/Info.plist` (permissions en français, modes
d'arrière-plan). Ne modifie pas `Info.plist` à la main : modifie `project.yml` puis regénère.

## 3. Signature

1. Xcode › Settings › Accounts : ajouter l'identifiant Apple (celui du compte développeur).
2. Cible **IRIS** › Signing & Capabilities : cocher « Automatically manage signing », choisir
   l'équipe (Team). On peut aussi mettre l'identifiant d'équipe dans `project.yml`
   (`DEVELOPMENT_TEAM`) puis regénérer.
3. Si l'identifiant `ca.velaglass.iris` est déjà pris, le changer dans `project.yml`
   (`PRODUCT_BUNDLE_IDENTIFIER`).
4. Aucune « capability » à ajouter : les modes d'arrière-plan (audio, bluetooth-central,
   location) viennent de l'Info.plist. Aucun entitlement spécial n'est demandé.

## 4. Première compilation

1. Choisir la cible **IRIS** et un iPhone branché en USB (ou le simulateur pour l'interface).
2. Produit › Build (⌘B). Corriger les erreurs **une par une en partant de la première** : une erreur
   dans `Partage/Contrats.swift` en provoque des dizaines ailleurs.
3. Le module de l'équipe perception (`IRIS/Perception/`, `IRIS/Ecrans/Accessibilite/`) est trouvé à
   l'exécution par le nom Objective-C `IRISFabriquePerception`. S'il manque ou ne compile pas, on peut
   retirer ses dossiers : l'app compile et démarre sans lui, et l'onglet Accessibilité le dit.
4. Sur l'iPhone : Réglages › Confidentialité et sécurité › Mode développeur › activer (iOS 16+),
   puis Réglages › Général › VPN et gestion de l'appareil › faire confiance au développeur.

## 4 bis. Tests unitaires (IRISTests) — jamais lancés à ce jour

Ajoutés le 2026-09-14. Ils couvrent les fonctions pures dont une erreur ne se verrait qu'en vrai :
trames des lunettes (octets identiques au service Python), mot d'activation et phrases « mode invité »,
adresses permises en `http://`, classement des refus 401/403/428 (verrouillée ≠ session refusée),
horodatages et décodage des réponses (reçus, prix, pas à pas, séances), couleurs et billets lus sur
l'iPhone, zone sans mémoire signalée, arrêt des alertes sans lunettes, contrastes WCAG.

1. `xcodegen generate` crée aussi la cible `IRISTests` et l'ajoute au schéma `IRIS`.
2. Choisir un simulateur iOS 17, puis Produit › Test (⌘U), ou en ligne de commande :
   `xcodebuild test -scheme IRIS -destination 'platform=iOS Simulator,name=iPhone 15'`.
3. Un test qui échoue dit ce qu'il attendait : corriger le code, pas l'attente, sauf si le service a
   changé (voir le script ci-dessous).

Depuis Windows, sans Mac, une partie se vérifie quand même (sans exécuter le Swift) :

```sh
backend/.venv/Scripts/python.exe mobile-ios/outils/verifier_ios.py
```

Le script recalcule côté Python les octets des trames, les motifs « mode invité », les noms de couleur et
les contrastes attendus par les tests Swift ; il vérifie que chaque route `/api/…` appelée par l'app
existe dans le service, que chaque champ envoyé existe dans le modèle de la route, et que les phrases de
refus reconnues par l'app sont toujours celles du service. Il ne remplace ni la compilation ni ⌘U.

## 5. Brancher l'ordinateur

1. Sur l'ordinateur : IRIS ouverte, un mot de passe créé et l'accès depuis le téléphone activé (Mon profil › Compte et sécurité).
2. Tailscale sur l'ordinateur et `tailscale serve` pour obtenir l'adresse
   `https://<nom>.<tailnet>.ts.net` (voir `docs/ACCES-DISTANT.md`).
3. Tailscale connecté sur l'iPhone.
4. Dans l'app : Profil › Relier ou changer d'ordinateur › adresse + mot de passe.

L'app refuse une adresse `http://` hors du réseau local (le mot de passe voyagerait en clair). En
`http://` sur le réseau local ou une adresse Tailscale `100.x`, elle se connecte mais l'affiche.

## 6. Liste de vérification sur un vrai iPhone (rien n'a été vérifié)

Permissions — chaque texte doit apparaître en français, au bon moment :

- [ ] Micro : au premier « Parler à IRIS » ou « Dis-moi Iris ».
- [ ] Reconnaissance vocale : juste après le micro.
- [ ] Bluetooth : à la première recherche de lunettes (module perception).
- [ ] Position « Pendant l'utilisation » : à « Ajouter une zone ici » ou à l'activation des zones.
- [ ] Position « Toujours » : bouton « Permettre « Toujours » » dans Zones sans mémoire.
- [ ] Réseau local : à la première connexion vers une adresse du réseau local.
- [ ] Caméra : seulement si le module perception prend une photo avec l'iPhone.

Fonctions :

- [ ] Connexion : mauvaise adresse, mauvais mot de passe (« Mot de passe incorrect. »), puis bon.
- [ ] Session gardée après avoir tué et relancé l'app (Trousseau).
- [ ] Événements en direct (pastille « Ordinateur relié », pas « sans direct ») ; couper le Wi-Fi puis
      le remettre : reconnexion sans rafale.
- [ ] Verrouiller IRIS depuis l'ordinateur : l'écran de verrouillage apparaît ; déverrouiller.
- [ ] Onglet IA sans lunettes : le compteur « aperçu » s'affiche et baisse à chaque message écrit.
- [ ] Lunettes connectées à l'iPhone : dans l'app de bureau, la présence passe à « téléphone » dans
      les 10 s ; lunettes éteintes : elle disparaît (DELETE) ; app en arrière-plan : elle expire
      en ~150 s.
- [ ] « Dis-moi Iris » app ouverte : vibration au mot d'activation, commande envoyée, réponse lue
      **dans les lunettes** (vérifier la sortie affichée : « … (Bluetooth) »).
- [ ] Écoute continue plus de 5 minutes : pas d'arrêt, pas de fuite mémoire (Instruments).
- [ ] Brancher / débrancher les lunettes pendant l'écoute : pas de plantage (changement de format du micro).
- [ ] Appel entrant pendant l'écoute : l'écoute s'arrête puis reprend.
- [ ] Débit : 1×, 2×, 3× ; vérifier qu'au-delà d'environ 2× la voix de l'iPhone n'accélère plus
      (limite affichée dans Profil).
- [ ] Interprète : « Je parle » (français), « L'autre parle » (anglais, espagnol…) ; vérifier que la
      reconnaissance hors ligne existe pour la langue (sinon message clair) ; latences affichées.
- [ ] Cours : liste, fiches, questions, transcription ; « Garder sur cet iPhone », mode avion,
      relecture ; export Markdown par la feuille de partage.
- [ ] Mode invité : activer 15 min depuis l'iPhone, vérifier sur l'ordinateur, terminer.
- [ ] « Dis-moi Iris, mode invité » app ouverte : l'ordinateur passe en mode invité (mémoire suspendue) ;
      « Dis-moi Iris, fin du mode invité » : refus dit à voix haute, le mode reste actif.
- [ ] Mode confidentiel activé sur l'ordinateur : « Dis-moi Iris » s'arrête sur l'iPhone (état
      « indisponible » avec la raison), « Parler », dictée, sous-titres, alertes et aperçu caméra refusent ;
      le désactiver : l'écoute du mot d'activation reprend seule.
- [ ] Alertes sonores actives, puis « Parler à IRIS » : refus clair (micro déjà pris), pas de plantage.
- [ ] Un autre appareil Bluetooth (bracelet, écouteurs) relié à l'iPhone : « Appareil relié non
      reconnu », aucune fonction des lunettes ne s'ouvre, rien n'est attesté à l'ordinateur.
- [ ] Verrouiller IRIS à distance, tuer l'app, la relancer en mode avion : l'écran de verrouillage
      reste, les cours gardés ne s'ouvrent pas ; réseau revenu et IRIS déverrouillée : il disparaît.
- [ ] Photo : appel entrant pendant la prise de vue → message « iOS a coupé la caméra » en moins de
      8 s, les boutons de vision redeviennent utilisables.
- [ ] Reçus, prix, pas à pas, entraînement, résumé du jour depuis l'iPhone : rien n'est dit par le
      haut-parleur de l'ordinateur (parler=false), la réponse est lue sur l'iPhone.
- [ ] Alerte sonore détectée sur un autre onglet que Accessibilité : le plein écran s'affiche.
- [ ] Zones : créer une zone ici, activer la surveillance « Toujours », quitter l'app, sortir de la
      zone à pied (plus de 200 m), revenir : l'ordinateur doit recevoir l'identifiant (journal
      d'IRIS), jamais la position. Mesurer le retard réel.
- [ ] « Dis Siri, parle à IRIS » : l'app s'ouvre sur l'onglet IA et écoute.
- [ ] Mode hors ligne : couper l'ordinateur ; l'app le dit en moins de 20 s et reste utilisable.
- [ ] VoiceOver : tous les boutons ont un libellé ; taille de texte maximale lisible ; réglage
      « Grand texte » appliqué.
- [ ] (réparation du 2026-09-14) Pas à pas démarré, app ouverte : « Dis-moi Iris, étape suivante » dans
      les lunettes change d'étape (POST /api/voix/commande), sans passer par le modèle. Consentement
      « transcript » retiré sur l'ordinateur, Wi-Fi coupé puis rétabli pendant une demande écrite : l'app dit
      le consentement manquant en moins de 10 s, pas « connexion perdue » après 3 minutes.
- [ ] Effacement à distance pendant que l'app est en arrière-plan : à la réouverture, écran de
      verrouillage « effacées à distance » et Accueil › Mes cours vide.
- [ ] Alertes sonores actives, app en arrière-plan : activer le mode confidentiel sur l'ordinateur ; les
      alertes s'arrêtent en environ une minute (indicateur de micro d'iOS éteint).
- [ ] Interprète ou « Parler » en cours, puis activer les sous-titres : aucune erreur audio, la voix
      s'arrête avant que le micro des sous-titres démarre.

## 7. TestFlight (pilote)

1. Compte Apple Developer actif (99 $ US/an) ; créer l'app dans App Store Connect avec le même
   identifiant de paquet.
2. Xcode › Product › Archive › Distribute App › App Store Connect › Upload.
3. App Store Connect › TestFlight : ajouter les testeurs (courriel). Un testeur externe demande une
   courte revue d'Apple (souvent 24-48 h). L'exemption de chiffrement est déjà déclarée
   (`ITSAppUsesNonExemptEncryption = false` : seulement le HTTPS du système).
4. Pour une publication sur l'App Store : le mode d'arrière-plan `audio` doit être justifié (lecture
   des réponses écran verrouillé) ; la description ne doit promettre ni écoute en arrière-plan ni
   temps de réponse garanti.

## 8. Ce qui a été écrit sans compilateur — à surveiller en premier

- `Partage/Contrats.swift` : décodage `convertFromSnakeCase` ; si une réponse du service change de
  forme, le message « Réponse de l'ordinateur illisible : … » nomme le champ fautif.
- `Voix/MoteurVoix.swift` : le plus risqué. AVAudioEngine + SFSpeechRecognizer + AVSpeechSynthesizer
  sur la même session audio ; relance toutes les 55 s ; bascules d'état. À éprouver longtemps sur
  un vrai iPhone avec les lunettes.
- `Pont/FluxEvenements.swift` : `URLSessionWebSocketTask` avec en-tête `Authorization` ; code de
  fermeture 4401 lu par `closeCode.rawValue`.
- `Confiance/SurveillanceZones.swift` : `CLMonitor` (iOS 17) recréé au lancement en arrière-plan ;
  comportement réel au réveil à vérifier.
- `App/EnvironnementIRIS.swift` : `NSClassFromString("IRISFabriquePerception")` pour trouver le module
  perception ; si la classe n'est pas marquée `@objc(IRISFabriquePerception)`, l'onglet
  Accessibilité dira que le module manque alors qu'il est là.
- Les vues SwiftUI (`Ecrans/`) : vérifier sur petit écran (iPhone SE) et en « Grand texte ».
- `Ecrans/Quotidien/EcranQuotidien.swift` (reçus, prix, pas à pas, entraînement, résumé) : écrit le
  2026-09-14, jamais affiché. Vérifier en particulier les `TimelineView` des minuteurs et du repos.
- `Perception/CameraTelephone.swift` : délais maximaux de 8 s au démarrage et à la photo ; vérifier
  qu'une caméra lente ne reste pas allumée après l'erreur (indicateur vert d'iOS).
