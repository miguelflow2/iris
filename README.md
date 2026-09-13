# IRIS — l'assistante de VELA

> *Parlez. Elle agit. Vous vérifiez.*

IRIS est une assistante vocale de bureau (Windows) pour la marque **VELA** (lunettes audio
connectées). On lui parle, elle **agit sur l'ordinateur** — ouvre des applications, navigue, écrit
et lance du code, envoie courriels et messages après votre accord, traduit une conversation,
retient ce qui compte pour vous. Son cerveau est un grand modèle de langage ; ses données restent
chez vous.

Ce qui la distingue d'un simple haut-parleur intelligent :

- **Elle agit, elle ne répond pas seulement.** Clavier, souris, navigateur, fichiers, code.
- **Vos données restent sur votre machine.** Traitement local par défaut ; ce qui sort est tracé.
- **Vous pouvez vérifier.** Registre de transparence chaîné en SHA-256 (falsification détectable),
  consentement par type de donnée, chiffrement AES-256 au repos, indicateur de capture impossible à
  masquer, mode 100 % local.
- **Elle demande avant d'agir sur l'irréversible.** Aucun courriel, SMS ou appel ne part sans que
  vous en voyiez le contenu et l'approuviez ; rien de destructeur sans votre accord.

---

## Où en est le projet (au 6 septembre 2026)

Sois lucide en lisant ce dépôt : **IRIS fonctionne pleinement sur la machine de développement**, et
**pas encore comme un produit qu'un inconnu installe et utilise sans rien configurer**. L'état
vérifié, dimension par dimension, est dans **[docs/ETAT-IRIS-2026-09-06.md](docs/ETAT-IRIS-2026-09-06.md)** —
à lire avant tout le reste.

En deux mots : le code des fonctionnalités est là et testé (plus de 870 tests) ; ce qui manque pour
un vrai produit est du **déploiement**, pas du code — le relais d'IA à mettre en ligne, l'installateur
à signer, le paiement à brancher. Voir la section « Installer et utiliser » plus bas, qui ne cache
rien.

---

## Le dépôt, dossier par dossier

| Dossier | Ce que c'est |
|---|---|
| `backend/` | Le cœur d'IRIS : service FastAPI (Python), voix, mémoire, outils qui pilotent l'ordinateur, connecteurs IA. `backend/iris/` = le code, `backend/tests/` = les tests. |
| `renderer/` | L'interface (React/TypeScript) affichée dans l'application. |
| `electron/` | L'enveloppe de bureau (Electron) qui lance l'interface et embarque le backend. |
| `serveur/` | **Le relais d'IA de VELA** : le serveur qui sert un cerveau aux clients selon leur abonnement, sans qu'ils collent de clé. Le cœur du modèle d'affaires. |
| `server/` | Le serveur de **licences** : reçoit les paiements PayPal, émet les clés d'abonnement. |
| `site/` | Le site vitrine de VELA (pages statiques, prêt pour Netlify). |
| `mobile-ios/` | L'étude de l'app iPhone : ce qu'Apple permet, bride, interdit, et par quoi commencer. |
| `scripts/` | Les scripts PowerShell : construire, déployer, installer le relais, le tunnel. |
| `docs/` | Les décisions, l'architecture, les diagnostics, l'état vérifié. |

---

## Lancer en développement

Prérequis : **Node ≥ 20**, **Python 3.11+** (3.13 testé), **Windows 10/11**.

```bash
cd backend && python -m venv .venv && .venv/Scripts/python -m pip install -r requirements-dev.txt && cd ..
npm install
npm run dev
```

Dites **« Dis-moi Iris, … »**, ou tapez dans la conversation.
Raccourcis : `Ctrl+Maj+Espace` (parler), `Ctrl+Maj+I` (afficher IRIS).

**Tests** (ce sur quoi on peut compter) :

```bash
cd backend && .venv/Scripts/python -m pytest -q          # le cœur d'IRIS
cd server  && .venv/Scripts/python -m pytest -q          # le serveur de licences (SON venv)
cd serveur && ../backend/.venv/Scripts/python -m pytest -q   # le relais
npm run typecheck                                        # l'interface
```

**Construire l'installateur** : `npm run dist:full` → `release/IRIS-Setup-<version>.exe`.
Aucun Python ni Node n'est requis sur la machine cible : le backend est embarqué.

---

## Installer et utiliser — l'état réel, sans détour

**Sur la machine de Miguel (développement) :** IRIS marche de bout en bout. Le cerveau est Claude,
la clé vit dans le trousseau Windows.

**Sur la machine d'un inconnu, aujourd'hui : pas encore.** Trois pièces manquent, et ce sont des
déploiements, pas du code :

1. **Le cerveau doit voyager.** Sans le relais VELA déployé en ligne, une IRIS installée n'a pas
   d'IA (à moins que la personne colle sa propre clé). → **[docs/DEPLOIEMENT-SERVEUR.md](docs/DEPLOIEMENT-SERVEUR.md)**
   explique comment le mettre en ligne (tunnel Cloudflare, économie Claude-aux-payants).
2. **L'installateur doit être signé.** Sinon Windows affiche « Windows a protégé votre ordinateur ».
   C'est un certificat à acheter. → `docs/SIGNATURE.md` *(à venir)*.
3. **Le paiement doit activer un compte.** Le code existe (serveur de licences + webhooks PayPal),
   il attend un compte PayPal Business branché.

Le chemin complet de « ça marche chez moi » à « n'importe qui l'installe » est décrit dans
`docs/ETAT-IRIS-2026-09-06.md`, section par section.

---

## La configuration sensible (rien de tout ça n'est dans le dépôt)

Les clés et secrets ne sont **jamais** versionnés : ils vivent dans le trousseau Windows chiffré, ou
dans des fichiers `.env` ignorés par git.

- **Voix (ElevenLabs)** : `backend/.env` avec `ELEVENLABS_API_KEY=…`, ou Paramètres › Voix.
- **Cerveau (clé du modèle)** : saisi dans Paramètres › Moteurs IA (rangé dans le trousseau).
- **Relais** : `serveur/.env` (voir `installer-relais.ps1`).
- **Ligne téléphonique IRIS (Twilio)** : `backend/.env`. IRIS envoie/reçoit SMS et appels depuis un
  vrai numéro loué, mais toujours **après confirmation** — rien ne part seul. Mettre
  `telephonie.fournisseur` à `twilio_ligne` dans les réglages, puis renseigner :
  - `TWILIO_API_KEY_SID` — **fourni** (le SID `SK…` de la clé d'API). Déjà dans `backend/.env`.
  - `TWILIO_API_KEY_SECRET` — **à fournir** : le secret de cette clé, montré **une seule fois** à sa
    création dans la console Twilio (irrécupérable ensuite ; sinon, créer une nouvelle clé).
  - `TWILIO_ACCOUNT_SID` — **à fournir** : l'Account SID `AC…`, en haut du tableau de bord Twilio.
  - `TWILIO_NUMBER` — **à fournir** : le numéro loué, au format `+1…` (E.164).

  **Pour RECEVOIR** (SMS et appels entrants), il faut en plus exposer le backend sur une **URL
  publique** — le tunnel Cloudflare existant (`scripts/deployer-serveur.ps1`,
  `scripts/installer-tunnel.ps1`) — et la déclarer à Twilio (console du numéro → *A message comes
  in* / *A call comes in*, pointant vers `/twilio/entrant/sms` et `/twilio/entrant/appel`), puis :
  - `TWILIO_AUTH_TOKEN` — l'Auth Token du compte. **Twilio signe** chaque webhook avec lui (jamais
    avec le secret de la clé d'API) : sans lui, l'entrant est **refusé** (échec fermé, jamais ouvert).
  - `TWILIO_PUBLIC_BASE` — l'URL publique du tunnel, ex. `https://iris.exemple.app`, pour recalculer
    la signature à l'identique derrière le proxy.

  Créer une clé d'API et louer un numéro exigent une carte de crédit et une pièce d'identité : ces
  gestes ne peuvent être faits que par le titulaire du compte. Tant que les valeurs manquent, l'outil
  se signale « non configuré » en français et propose de préparer le message sur le téléphone.

> **Dépôt privé.** Ce code contient le secret qui signe les clés d'abonnement
> (`LICENSE_SECRET`). Tant que le dépôt reste privé, c'est sans danger. **Avant de le rendre public
> ou d'inviter un collaborateur en qui vous n'avez pas une confiance totale**, ce secret doit être
> changé — sinon on peut forger des abonnements gratuits.
