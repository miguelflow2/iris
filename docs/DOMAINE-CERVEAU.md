# Donner un domaine STABLE au cerveau d'IRIS

**Écrit le 7 septembre 2026.** Ce document mène, pas à pas, de « je n'ai pas de domaine » à « une IRIS
installée chez un inconnu répond ». Pour quelqu'un qui **n'est pas administrateur système**. Il ne
survend rien : chaque étape dit ce qu'elle coûte et ce qu'elle ne fait pas.

---

## Pourquoi cette étape existe

Le **relais** est le serveur qui donne un cerveau aux IRIS installées, sans que le client colle sa
propre clé (voir `docs/DEPLOIEMENT-SERVEUR.md`). Aujourd'hui il n'est joignable que par un tunnel
Cloudflare **éphémère** : une adresse `https://quelquechose.trycloudflare.com` qui **change à chaque
redémarrage**. Parfait pour un essai ; impossible à figer dans une application livrée — le jour où le
tunnel redémarre, toutes les IRIS installées perdent le contact, en silence.

Il faut donc une **adresse stable**, du genre `https://relais.mondomaine.com`, qui survit aux
redémarrages. C'est ce que fait un **tunnel Cloudflare nommé**. Cette adresse devient :

- la valeur par défaut de `relay_server` que porteront toutes les copies installées (`pointer-cerveau.ps1`) ;
- l'URL du « Custom LLM » de l'agent vocal ElevenLabs (`https://relais.mondomaine.com/v1`).

**Rien de tout ceci n'ouvre un port du routeur.** Le tunnel est une connexion *sortante* : la machine
se connecte à Cloudflare, jamais l'inverse.

---

## Ce que ça coûte

| Poste | Coût | Note |
|---|---|---|
| Nom de domaine | ~12–15 $/an | chez n'importe quel registraire (Cloudflare Registrar, Namecheap, OVH…) |
| Compte Cloudflare | **0 $** | le plan gratuit suffit pour un tunnel nommé et le DNS |
| Tunnel `cloudflared` | **0 $** | logiciel libre, déjà récupéré par `deployer-serveur.ps1 -Telecharger` |

Le seul déboursé réel est le domaine. Tout le reste est gratuit.

---

## Vue d'ensemble (les étapes)

1. Acheter un domaine.
2. L'ajouter à un compte Cloudflare (changer les *nameservers*).
3. Créer un tunnel **nommé** et récupérer son **jeton**.
4. Router un **Public Hostname** `relais.<domaine>` vers `http://localhost:8100`.
5. Sur l'ordi B : `deployer-serveur.ps1 -Domaine relais.<domaine> -Jeton <jeton>`.
6. Repointer le code : `pointer-cerveau.ps1 -Adresse https://relais.<domaine>`.
7. **Re-bâtir l'installateur** et remplacer l'.exe du site.
8. Repointer l'agent vocal ElevenLabs (à part, avec la clé de gestion ElevenLabs).

Les étapes 1 à 4 se font une seule fois, dans le navigateur. Les étapes 5 à 8 se font depuis le dépôt.

---

## Étape 1 — Acheter un domaine

Chez le registraire de ton choix. Le plus simple est **Cloudflare Registrar** (le domaine est alors
déjà dans Cloudflare, l'étape 2 disparaît), mais n'importe lequel fait l'affaire. Prends un nom court.
Le sous-domaine `relais.` sera ajouté ensuite, gratuitement — tu n'as pas à l'acheter séparément.

> Honnêtement : un `.com` coûte ~12–15 $/an. Les extensions « à 1 $ la première année » se renouvellent
> souvent beaucoup plus cher ; regarde le prix de **renouvellement**, pas celui d'accroche.

## Étape 2 — Ajouter le domaine à Cloudflare (nameservers)

À sauter si tu as pris le domaine chez Cloudflare Registrar.

1. Crée un compte gratuit sur **dash.cloudflare.com**.
2. « Add a site » → tape ton domaine → choisis le plan **Free**.
3. Cloudflare te donne **deux nameservers** (du genre `x.ns.cloudflare.com`).
4. Va chez ton registraire, remplace les nameservers du domaine par ceux de Cloudflare.
5. Attends que la zone passe à **« Active »** dans Cloudflare (souvent minutes, parfois quelques heures).

Tant que la zone n'est pas « Active », rien de la suite ne marchera : c'est le prérequis.

## Étape 3 — Créer un tunnel NOMMÉ et récupérer le jeton

1. Dans le tableau de bord Cloudflare : **Zero Trust** (menu de gauche).
   - Au premier accès, Zero Trust demande de choisir un plan : prends le **Free**. (Aucune carte n'est
     débitée sur ce plan ; il peut en demander une pour vérification, mais tu restes à 0 $.)
2. **Networks → Tunnels → Create a tunnel**.
3. Type de connecteur : **Cloudflared**. Donne un nom au tunnel (p.ex. `relais-vela`). **Save**.
4. Cloudflare affiche une commande d'installation qui contient un **jeton** — une longue chaîne
   commençant par `eyJ...`. **C'est ce jeton qu'il faut copier.** Tu n'as pas besoin d'exécuter la
   commande affichée : `deployer-serveur.ps1` s'en charge avec ce jeton.

> Le jeton est un secret : il fait tourner *ton* tunnel. Ne le colle nulle part en public, ne le
> committe pas. `deployer-serveur.ps1` le reçoit en argument et ne l'écrit pas sur le disque.

## Étape 4 — Router `relais.<domaine>` vers le relais local

Toujours dans l'écran du tunnel, onglet **Public Hostname** → **Add a public hostname** :

- **Subdomain** : `relais`
- **Domain** : ton domaine (menu déroulant)
- **Path** : (laisser vide)
- **Type** : `HTTP`
- **URL** : `localhost:8100`

**Save**. Cloudflare crée tout seul l'enregistrement DNS `relais.<domaine>`. L'adresse publique du
cerveau sera donc `https://relais.<domaine>`, et le port `8100` est celui du relais local (constante
`PORT_RELAIS` de `deployer-serveur.ps1`).

> Le `Type: HTTP` + `URL: localhost:8100` est le point qui casse le plus souvent. Si plus tard le relais
> ne répond « qu'en local », c'est presque toujours ce champ (mauvais port, ou `https` au lieu de `http`).

---

## Étape 5 — Lancer le relais + le tunnel nommé (sur l'ordi B)

Depuis le dossier du projet, dans PowerShell **ouvert en administrateur** (pour que le tunnel
redémarre tout seul après une coupure) :

```
.\scripts\deployer-serveur.ps1 -Telecharger                                   # une seule fois
.\scripts\deployer-serveur.ps1 -Domaine relais.mondomaine.com -Jeton eyJ...   # adresse stable
```

Passe en `-Domaine` le **nom d'hôte complet** que tu as routé à l'étape 4 (`relais.mondomaine.com`),
pas seulement `mondomaine.com`. Le script accepte aussi la forme `https://relais.mondomaine.com` et la
nettoie tout seul.

Le script : met le relais en service permanent, lance le tunnel nommé, écrit l'adresse dans
`serveur/donnees/adresse-publique.txt`, puis **vérifie `/sante` à travers le domaine public**. En cas
d'échec, il dit *pourquoi* : tunnel non démarré (jeton/droits), ou **hostname pas encore routé** côté
Cloudflare (avec le rappel exact : Public Hostname `relais.<domaine>` → `http://localhost:8100`), ou
propagation DNS en cours.

Vérifier plus tard : `.\scripts\deployer-serveur.ps1 -Etat`.

> **Sans droits admin**, le script lance quand même le tunnel, mais **pour la session en cours
> seulement** : il s'arrêtera à l'extinction. Pour un vrai service permanent, relance en administrateur.

## Étape 6 — Pointer le code IRIS vers l'adresse stable

Depuis le dépôt :

```
.\scripts\pointer-cerveau.ps1 -Adresse https://relais.mondomaine.com
```

Ce script :

- réécrit proprement la valeur par défaut de `relay_server` dans `backend/iris/config.py` (idempotent,
  sans abîmer le reste du fichier) — c'est cette valeur que porteront les copies **installées ensuite** ;
- pose aussi la valeur dans les réglages **LIVE** de cette machine (le dossier de données), via le venv ;
- accepte `-DryRun` pour montrer ce qui changerait **sans rien écrire** ;
- affiche à la fin la checklist de ce qui reste (étapes 5, 7, 8).

Essaie d'abord à blanc : `.\scripts\pointer-cerveau.ps1 -Adresse https://relais.mondomaine.com -DryRun`.

> Ce script ne touche **ni** à l'agent ElevenLabs **ni** à aucune clé secrète. Le repointage vocal se
> fait à l'étape 8, séparément.

## Étape 7 — RE-BÂTIR l'installateur (sinon les clients gardent l'ancienne adresse)

`pointer-cerveau.ps1` change la valeur par défaut **dans les sources**. Les installateurs déjà construits,
eux, portent encore l'ancienne. Il faut donc reconstruire :

```
npm run dist:full
```

Puis remplacer le fichier téléchargé par le site :

```
site\telechargement\IRIS-Setup-<version>.exe   <-  le nouvel .exe produit dans release\
```

**Sans cette étape, un inconnu qui télécharge l'application installe une IRIS qui cherche son cerveau à
l'ancienne adresse.** C'est l'oubli le plus coûteux de toute la liste.

## Étape 8 — Repointer l'agent vocal ElevenLabs (séparément)

**Fait à part, avec la clé de gestion ElevenLabs** — qui n'est nulle part sur le disque, et qu'aucun
script du dépôt ne manipule. Dans le tableau de bord de l'agent (voir `docs/AGENT-VOCAL-ELEVENLABS.md`
pour le détail) :

- **Custom LLM → Server URL** : `https://relais.mondomaine.com/v1`
  (vérifier une fois en direct que la requête sort bien vers `.../v1/chat/completions` et non
  `.../v1/v1/chat/completions`).
- **Secret `OPENAI_API_KEY`** : le **jeton d'appareil** obtenu via
  `POST https://relais.mondomaine.com/api/appareil` (corps `{"email":"...","machine":"eleven-agent"}`).
  Ce jeton vaut 90 jours — programmer un rappel vers le jour 80 pour le régénérer.

L'agent ne voit jamais de clé Anthropic/OpenRouter : il ne connaît que le relais et son jeton d'appareil.

---

## Vérifier de bout en bout

1. `deployer-serveur.ps1 -Etat` → le relais répond en local **et** l'adresse publique est connue.
2. Dans un navigateur : `https://relais.mondomaine.com/sante` → doit répondre `{"ok": true}`.
3. Sur une machine cliente **fraîchement installée** (après l'étape 7), IRIS répond sans qu'aucune clé
   n'ait été collée : le cerveau vient de VELA, réglé selon l'abonnement.
4. Un appel à l'agent vocal ElevenLabs obtient une réponse (le « cerveau » vocal passe par le relais).

---

## Ce qui reste, honnêtement

- **Le domaine est le seul vrai coût**, et il se renouvelle chaque année. Rien d'autre n'est payant ici.
- **La propagation DNS n'est pas instantanée.** Après les étapes 2 et 4, il peut s'écouler quelques
  minutes (parfois plus) avant que `relais.<domaine>` réponde. Un `/sante` qui échoue juste après la
  création n'est pas forcément une erreur — `deployer-serveur.ps1 -Etat` finit par passer au vert.
- **Le repointage ElevenLabs (étape 8) est manuel et hors script**, par choix : la clé de gestion
  ElevenLabs ne doit vivre nulle part dans le dépôt.
- **Le serveur de licences** (activation automatique après paiement) est un autre service, non couvert
  ici (voir `docs/DEPLOIEMENT-SERVEUR.md`).
- **La machine doit rester allumée.** Une machine résidentielle tient pour commencer ; au-delà de
  quelques dizaines de clients actifs, un hébergeur (IP fixe, redémarrages, montée en charge) devient
  nécessaire — mais l'adresse stable, elle, ne changera pas : seul le tunnel déménagera.
