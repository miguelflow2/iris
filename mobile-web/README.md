# IRIS — application web téléphone (VELA)

> Parlez à Iris depuis votre téléphone. Une page web installable, pas une application des
> magasins : aucune revue, aucun compte développeur, aucune paperasse Apple ou Google.

C'est une **PWA** (progressive web app) : un site qu'on ouvre dans le navigateur du téléphone et
qu'on peut poser sur l'écran d'accueil, où elle s'ouvre alors plein écran comme une vraie app. Son
cœur est la **voix d'Iris**, rendue par l'agent conversationnel de VELA.

---

## Ce qui marche vraiment (et ce qui n'est pas là)

**Ce que fait cette app, sur n'importe quel téléphone, n'importe où :**

- **Parler à Iris de vive voix**, en français. On touche l'orbe, on autorise le micro, on parle ;
  Iris écoute, réfléchit et répond à voix haute. La reconnaissance, le raisonnement et la voix
  vivent côté services de VELA (agent + relais) — le téléphone n'est que le micro et l'oreille.
- **Converser et s'informer** : questions, explications, recherche web quand le service le permet.
- **S'installer sur l'écran d'accueil** et s'ouvrir plein écran, avec l'icône VELA.

**Ce que cette app ne fait PAS — et ne prétend jamais faire :**

- **Elle ne pilote pas votre ordinateur.** Ouvrir une application, écrire du code, cliquer, taper,
  envoyer un courriel/texto/appel : tout cela n'existe que dans l'**application de bureau IRIS**
  (Electron + backend Python) installée sur le PC, seule à avoir des « bras ».
- **Raison technique, sans détour :** un téléphone sur données cellulaires ne peut pas rejoindre le
  backend IRIS local. Ce backend écoute sur `127.0.0.1` derrière un jeton de session et refuse les
  requêtes venues d'un tunnel (voir `docs/ACCES-DISTANT.md` et `docs/AGENT-VOCAL-ELEVENLABS.md`,
  section « canal inverse »). Le relais public de VELA sert le **cerveau** (le modèle), pas un
  lien descendant vers un PC précis : **ce canal inverse n'existe pas encore**. Tant qu'il n'est
  pas construit, aucune action PC n'est pilotable depuis le web téléphone. La page le dit
  explicitement à l'utilisateur au lieu de faire semblant.

C'est la même division du travail que celle décrite pour l'iPhone dans `mobile-ios/` : le téléphone
est la bouche et l'oreille ; les bras restent sur le PC.

---

## Comment c'est fait

Volontairement **statique** : du HTML, du CSS et du JavaScript ordinaire, **aucun build**, aucune
dépendance à installer. C'est le plus simple à héberger et le plus robuste.

```
mobile-web/
├── index.html            La page (coquille PWA + widget vocal + notes honnêtes)
├── manifest.webmanifest  Nom, icônes, couleurs, display standalone (chemins relatifs)
├── sw.js                 Agent de service : coquille hors ligne ; ne met JAMAIS le réseau en cache
├── icone-192.png         Icône VELA (reprise de backend/iris/assets)
├── icone-512.png         Icône VELA
├── _headers              En-têtes Netlify (sécurité, cache, micro autorisé)
├── netlify.toml          Déploiement Netlify (publie le dossier tel quel, sans build)
├── assets/
│   ├── app.css           Style : palette VELA (encre, crème, terracotta)
│   └── app.js            État de la voix, aide à l'installation, agent de service
└── README.md             Ce fichier
```

### La voix : l'agent conversationnel ElevenLabs

On intègre l'**agent vocal déjà créé** (il EST Iris, français, cerveau branché sur le relais VELA)
via son **widget embarquable**, dans `index.html` :

```html
<elevenlabs-convai agent-id="agent_2501m1xxsyq3e6d9xn8z5039cfzs" language="fr" ...></elevenlabs-convai>
<script src="https://elevenlabs.io/convai-widget/index.js" async></script>
```

On ne fournit **que l'identifiant public** de l'agent — il n'est pas secret et peut vivre dans le
code. **Aucune clé ElevenLabs, aucune clé de modèle n'est jamais côté client.** Le widget demande
lui-même le micro au premier geste de l'utilisateur, gère les états écoute/parle et affiche la
transcription. C'est l'option retenue parmi les deux possibles parce qu'elle est la plus simple et
la plus robuste (voir « Alternative » plus bas).

`app.js` se contente de trois choses : dire honnêtement si le widget a bien chargé (« Voix d'Iris
prête » / « Voix indisponible » — jamais de faux « prête »), aider à poser l'app sur l'écran
d'accueil, et enregistrer l'agent de service.

---

## Lancer en développement

L'app étant statique, n'importe quel petit serveur HTTP suffit. Le service worker et le micro
exigent un **contexte sûr** : `localhost`/`127.0.0.1` compte comme sûr, ou bien du HTTPS.

```bash
# depuis la racine du dépôt
python -m http.server 8899 --directory mobile-web
# puis ouvrir http://127.0.0.1:8899/ dans un navigateur
```

Une entrée `mobile-web` a aussi été ajoutée à `.claude/launch.json` (serveur statique sur le port
8899) pour l'outil de prévisualisation.

Pour tester la voix pour de vrai, ouvrez la page sur un **téléphone** (ou un navigateur de bureau
avec micro), touchez l'orbe, autorisez le micro, et parlez. Sur `localhost`, le micro fonctionne ;
depuis un autre appareil du réseau, il faut du HTTPS (voir le déploiement).

---

## Déployer (statique, comme le site vitrine)

Même logique que `site/` : on publie des fichiers, il n'y a rien à compiler. **HTTPS obligatoire**
en production (le micro et l'installation PWA l'exigent hors de localhost).

**Option 1 — glisser-déposer (le plus rapide).** Déposer le dossier `mobile-web/` sur
<https://app.netlify.com/drop>. Netlify sert en HTTPS et applique `_headers` automatiquement.

**Option 2 — dépôt relié.** Pointer le site Netlify sur ce dépôt, « base directory » = `mobile-web`,
« publish directory » = `mobile-web` (ou `.`), aucune commande de build. `netlify.toml` est déjà
prêt en ce sens.

**Adresse suggérée :** un sous-domaine dédié, par exemple `app.vela.app` ou `iris.vela.app`, distinct
du site vitrine. Les chemins de l'app sont relatifs, donc un sous-dossier (`vela.app/app/`)
fonctionne aussi.

Après déploiement, vérifier sur un vrai téléphone : (1) la page charge, (2) « Voix d'Iris prête »
s'affiche, (3) l'orbe demande le micro et Iris répond, (4) « Sur l'écran d'accueil » (iOS Safari)
ou « Installer » (Android Chrome) pose bien l'app plein écran.

---

## Notes honnêtes et points de vigilance

- **Service worker en prévisualisation locale.** Dans certains navigateurs instrumentés (l'aperçu
  intégré des outils), l'enregistrement du service worker échoue avec « An unknown error occurred
  when fetching the script », alors que le fichier est servi correctement (200, type
  `text/javascript`) et que sa syntaxe est valide. C'est une limite de l'environnement d'aperçu,
  pas un défaut du code : sur un hébergement HTTPS réel (Netlify) et sur un vrai téléphone, il
  s'enregistre. Rien dans l'app ne dépend du service worker pour fonctionner — sans lui, la page
  marche quand même ; il n'apporte que la coquille hors ligne et l'invite d'installation Android.

- **Content-Security-Policy volontairement ouverte.** Contrairement au site vitrine (CSP stricte),
  cette app n'impose pas de CSP serrée, car le widget vocal ouvre des connexions temps réel
  (WebRTC/WebSocket) vers des serveurs média dont la liste n'est ni fixe ni publiée. Une CSP trop
  serrée casserait la voix **sans message visible** — le « déploiement menteur » que le projet
  s'interdit. Pour la durcir plus tard : parler à Iris une fois, relever dans l'onglet Réseau les
  origines réellement contactées, composer `script-src`/`connect-src`/`media-src` en conséquence, et
  **tester que la voix marche encore** avant de livrer. Détails dans `_headers`.

- **Attribution « Powered by ElevenLabs ».** Le widget affiche sa propre mention de plateforme en
  bas. Ce n'est **pas** une fuite du « cerveau » (le modèle reste masqué par le relais) : c'est
  l'attribution du fournisseur de voix. Elle n'a pas été retirée par un procédé trompeur ; sa
  suppression dépend des réglages/forfait ElevenLabs du widget. À décider côté marque.

- **Le jeton d'appareil (cerveau) est côté ElevenLabs, pas ici.** Le lien entre l'agent et le
  relais VELA (le « Custom LLM » et son jeton, rotation ~jour 80) se configure dans le tableau de
  bord ElevenLabs, comme décrit dans `docs/AGENT-VOCAL-ELEVENLABS.md`. Cette app web n'y touche pas
  et ne contient aucun secret.

- **iOS.** L'installation ne se fait que par Safari ▸ Partager ▸ « Sur l'écran d'accueil » (aucun
  bouton « Installer » n'existe sur iPhone) ; le micro et la voix ne marchent qu'au premier plan,
  sur un vrai geste — ce que le widget respecte. Voir `mobile-ios/REALITE-IOS.md`.

---

## Prochaines étapes possibles

1. **Canal inverse relais → PC (pour les actions à distance).** Pour qu'Iris agisse sur
   l'ordinateur *depuis le téléphone*, il faudrait que le backend IRIS ouvre une connexion
   **sortante** persistante vers le relais (WebSocket/long-poll, authentifiée par le jeton
   d'appareil), et que le relais route les actions vers le bon PC. Ce canal n'existe pas
   aujourd'hui (`serveur/relais.py` est un proxy sans état). Tant qu'il n'est pas construit, cette
   app reste « voix + conversation ». Voir `docs/AGENT-VOCAL-ELEVENLABS.md`, section « canal
   inverse (2c) ».
2. **Notifications push web.** Utiles pour qu'Iris signale la fin d'une tâche longue. Faisables en
   PWA (Push API + VAPID) sur Android tout de suite, et sur iOS 16.4+ **à condition** que l'app soit
   installée sur l'écran d'accueil. Demande un petit service d'envoi côté VELA.
3. **Marque à 100 %.** Décider du sort de l'attribution « Powered by ElevenLabs », affiner les
   textes du widget, et éventuellement fixer un sous-domaine stable.
4. **Passer au SDK React (seulement si besoin).** Voir ci-dessous.

### Alternative écartée pour l'instant : le SDK React

L'autre voie était un vrai projet React avec `@elevenlabs/react`
(`useConversation`, `startSession({ agentId, connectionType: "webrtc" })`). Elle donne un contrôle
total sur l'interface (bouton « Parler » maison, fil de transcription sur mesure, états gérés à la
main) mais impose un **build** (Vite), un bundle à héberger, et plus de code à maintenir. Pour le
besoin actuel — voix + conversation, honnête et robuste, hébergeable en statique — le widget suffit
et présente moins de pièces mobiles. On pourra basculer sur le SDK le jour où l'on voudra une
interface conversationnelle entièrement maison.
