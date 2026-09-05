# Relais IA de VELA

Le service qui donne à IRIS son accès à l'intelligence artificielle, **sans que le client
fournisse quoi que ce soit**.

Avant, IRIS réclamait une clé OpenRouter à chaque utilisateur, dès le premier écran. C'était faux
sur le fond — ce qu'on vend, c'est une assistante qui marche, pas un formulaire à remplir — et
faux commercialement : si le client apporte sa clé, l'abonnement ne sert plus à grand-chose.

Ici, la clé est celle de VELA. IRIS se présente avec un jeton d'appareil, le relais reconnaît
l'abonnement rattaché au courriel, et décide quel modèle répond.

**Tant que ce service n'est pas déployé, aucun client ne peut avoir d'IA sans coller sa propre
clé.** C'est la seule pièce manquante entre le code et un produit qui marche à l'installation.

---

## 1. Ce qu'il fait

| Point d'entrée | À quoi il sert |
|---|---|
| `POST /api/appareil` | Premier contact d'une installation d'IRIS. Rend un jeton d'appareil et le plan. |
| `POST /v1/chat/completions` | L'IA. Compatible OpenAI, donc IRIS s'y branche sans code particulier. |
| `GET /v1/models` | Les modèles auxquels cet abonnement donne droit. |
| `POST /v1/voix/{voice_id}` | La voix ElevenLabs des forfaits payants. |
| `GET /api/licence` | Repli, si le serveur de licences n'est pas déployé. |
| `GET /sante` | État du service. |

### Qui obtient quoi

| Forfait | Modèles | Requêtes/mois | Voix |
|---|---|---|---|
| Gratuit | modèles gratuits | 300 | Windows |
| Pro | + Gemini 2.5 Flash, GPT-5 mini | 600 | ElevenLabs |
| Premium | + Claude Sonnet 5 | 1000 | ElevenLabs |
| Entreprise | + Claude Opus 5 | 1500 | ElevenLabs |

Le client propose un modèle, **le relais dispose**. Un plan Gratuit n'obtient jamais Claude,
quelle que soit la requête envoyée. C'est vérifié par un test.

---

## 2. Ce qu'il ne fait pas

**Il ne conserve aucune conversation.** Il transmet, il ne garde pas. Ce qui reste après le
passage, ce sont des compteurs — combien de requêtes ce mois-ci — et les journaux techniques
d'un serveur.

C'est écrit noir sur blanc dans la politique de confidentialité du site, qui dit aussi que
**VELA est intermédiaire** de ces échanges. Elle affirmait le contraire jusqu'au 4 septembre
2026 : « votre ordinateur parle directement au fournisseur ». Cette phrase est devenue fausse le
jour où le relais est apparu, et elle a été corrigée. Si vous modifiez ce service, relisez cette
page : une promesse de confidentialité qui ne correspond plus au code est un problème sérieux,
pas un détail de rédaction.

---

## 3. Démarrer en local

```bash
cd serveur
python -m venv .venv
.venv/Scripts/python -m pip install fastapi uvicorn httpx pydantic
VELA_OPENROUTER_KEY=sk-or-v1-... .venv/Scripts/python -m uvicorn relais:app --port 8100
```

Vérifier : `curl http://127.0.0.1:8100/sante` doit répondre `{"ok": true, "amont": true}`.
Si `amont` vaut `false`, la clé n'a pas été lue.

Pour qu'IRIS s'y adresse, dans `settings.json` de l'application :
`"relay_server": "http://127.0.0.1:8100"`.

---

## 4. Les variables d'environnement

| Variable | Indispensable | Rôle |
|---|---|---|
| `VELA_OPENROUTER_KEY` | **oui** | La clé OpenRouter de VELA. Sans elle, le service refuse toute demande. |
| `VELA_SECRET` | oui en production | Signe les jetons d'appareil. Sans elle, une valeur par défaut connue est utilisée : n'importe qui pourrait fabriquer un jeton. |
| `VELA_LICENCES_URL` | recommandée | L'adresse du serveur de licences. C'est lui qui sait qui est abonné. |
| `VELA_ELEVENLABS_KEY` | si voix incluse | Sans elle, un abonné Pro paie une voix qu'il n'entendra pas. |
| `VELA_LICENCE_SECRET` | si repli utilisé | Doit être **identique** à `LICENSE_SECRET` dans `backend/iris/plans.py`, sinon IRIS rejette les clés émises. |
| `VELA_DONNEES` | non | Où écrire compteurs et repli. Défaut : `serveur/donnees`. |

Générer un secret : `python -c "import secrets; print(secrets.token_urlsafe(32))"`

---

## 5. Une seule source de vérité sur les abonnés

Le serveur de licences (dossier `server/`) reçoit les webhooks PayPal, crée les abonnements et
émet les clés. **C'est lui qui sait qui est abonné.** Le relais le lui demande, et met la réponse
en cache cinq minutes.

Tenir ici une seconde liste d'abonnés reviendrait à avoir deux vérités qui finiraient par
diverger — et c'est toujours le client qui paierait la différence. Le fichier `abonnes.json` du
dossier `donnees/` existe uniquement comme repli quand le serveur de licences ne répond pas, ou
pour un essai. Ce n'est pas la référence.

Format du repli, si vous devez l'utiliser :

```json
{ "client@exemple.com": { "plan": "premium", "expires": "2027-01-31" } }
```

---

## 6. Héberger

N'importe quel hébergeur Python convient. Deux exigences réelles :

1. **Le disque doit survivre aux redémarrages**, sinon les compteurs de quota repartent de zéro
   à chaque redéploiement — et le quota mensuel ne veut plus rien dire. Sur un hébergeur à
   disque éphémère, prévoyez un volume, ou acceptez que les quotas soient indicatifs.
2. **HTTPS**, évidemment : le jeton d'appareil circule dans l'en-tête `Authorization`.

Commande de démarrage : `uvicorn relais:app --host 0.0.0.0 --port $PORT`

Puis pointez `relay_server` d'IRIS (`backend/iris/config.py`, valeur par défaut
`https://relais.vela.app`) vers l'adresse obtenue.

---

## 7. Ce que ça coûte, et ce qui protège

Ce service dépense de l'argent réel à chaque requête. Trois garde-fous existent :

- **Un quota mensuel par abonné**, appliqué avant l'appel en amont.
- **Un modèle imposé selon le plan** : impossible d'atteindre Claude avec un compte gratuit.
- **Un jeton signé** dont le courriel fait partie du corps signé : le modifier casse la
  signature.

Ce qui n'existe pas encore et qu'il faudra surveiller : rien ne limite le nombre d'appareils
qu'un même courriel peut enregistrer. Un abonné pourrait installer IRIS sur dix machines et
consommer dix quotas. À traiter le jour où il y aura assez de clients pour que ça se voie.

---

## 8. Les tests

```bash
cd serveur
../backend/.venv/Scripts/python -m pytest -q
```

19 tests. Ils portent sur ce qui coûterait cher si ça cédait : un plan Gratuit qui atteindrait un
modèle payant, un jeton forgé, une clé d'abonnement qu'IRIS refuserait, la clé d'API qui fuirait
dans une réponse.

---

## 9. Faire tourner le relais sur un poste Windows

La section 3 lance le relais dans une fenêtre PowerShell. C'est parfait pour essayer, et
insuffisant pour servir : on ferme la session, il s'arrête ; le courant saute, il ne revient
pas ; il plante à trois heures du matin, personne ne le relance. Pour qu'il tourne vraiment en
permanence, il faut en faire un **service Windows**.

```powershell
# la première fois (récupère le superviseur)
.\scripts\installer-relais.ps1 -Telecharger

# ensuite
.\scripts\installer-relais.ps1
```

**En administrateur.** Enregistrer un service demande une élévation : il n'existe aucun chemin
sans elle. Le script s'arrête avec un message clair si vous l'oubliez.

### Ce que le script fait, dans l'ordre

0. **Vérifie ce qui doit être vrai.** Espace disque, dossier `Downloads`, et surtout : que rien
   n'écoute déjà sur le port 8100. Il refuse d'installer si c'est le cas — voir plus bas.
1. **Crée `serveur/.venv`** et y installe `serveur/requirements.txt`. Le relais cesse ainsi de
   dépendre de `backend/.venv`, qui est l'environnement de développement d'IRIS et se fait
   reconstruire sans prévenir. Puis il vérifie que `relais.py` s'importe : une faute de frappe
   vaut mieux découverte ici que sous la forme d'un service qui refuse de démarrer.
2. **Demande les clés et écrit `serveur/.env`.** Il ne redemande que ce qui manque, donc on peut
   le relancer sans tout ressaisir. `VELA_SECRET` est **générée automatiquement**
   (`secrets.token_urlsafe(32)`) si elle est absente, et n'est jamais affichée. Les droits du
   fichier sont refermés sur SYSTEM, les administrateurs et vous : l'héritage est coupé, donc
   aucun autre compte du poste ne lit la clé OpenRouter. Le script complète aussi `.gitignore`.
3. **Enregistre le service** `VelaRelais`, démarrage automatique, avec relance après une chute.
4. **Vérifie `/sante`** et le dit franchement si ça ne répond pas.

### Les commandes

| Commande | Effet |
|---|---|
| `.\scripts\installer-relais.ps1` | Installe ou réinstalle, puis démarre. |
| `.\scripts\installer-relais.ps1 -Journal` | Les dernières lignes du journal. |
| `.\scripts\installer-relais.ps1 -Journal -Suivre` | Le journal en direct. |
| `.\scripts\installer-relais.ps1 -Relancer` | Relance — après un changement de clé, par exemple. |
| `.\scripts\installer-relais.ps1 -Arreter` | Arrête. Le service repart au prochain démarrage. |
| `.\scripts\installer-relais.ps1 -Desinstaller` | Retire le service. Garde `.env`, `donnees/` et les journaux. |

### Où sont les choses

| Quoi | Où |
|---|---|
| Journaux | `serveur/journaux/` — 5 Mo par fichier, 4 conservés |
| Secrets | `serveur/.env` — jamais versionné, lisible par vous seul |
| Compteurs de quota | `serveur/donnees/` |
| Configuration du service | `serveur/relais-service.xml` — régénérée à chaque installation |

`VelaRelais.err.log` est le **journal normal**, pas une liste de pannes : uvicorn écrit toutes ses
lignes sur la sortie d'erreur, y compris « application startup complete ». C'est `.out.log` qui
reste vide.

### Les secrets ne sont dans aucune définition de service

Les arguments d'une tâche planifiée se lisent en clair dans `C:\Windows\System32\Tasks\`, les
variables de NSSM en clair dans le registre, et le bloc `<env>` de WinSW en clair dans son XML.
Aucun de ces trois endroits ne convient. Les clés vivent donc dans `serveur/.env`, et c'est le
script lui-même — relancé par le service avec `-Executer` — qui les charge dans le seul processus
enfant. Le XML du service, lui, ne contient rien de secret et peut être lu par n'importe qui.

### Le service tourne sous LocalSystem, pas sous votre compte

C'est un choix, et il mérite d'être expliqué. Faire tourner un service « même si l'utilisateur
n'est pas connecté » sous votre compte oblige à **stocker le mot de passe** du compte — ici un
compte Microsoft — dans la définition du service. Ce service casse alors en silence au prochain
changement de ce mot de passe. Comme `relais.py` ne lit que des variables d'environnement, jamais
le Gestionnaire d'identification ni `%APPDATA%`, LocalSystem lui suffit, et il n'y a plus aucun
mot de passe stocké nulle part.

### Un seul relais à la fois

`_verrou` (`relais.py`) est un `threading.Lock` : il ne sérialise que les fils d'**un** processus.
Deux relais qui partagent `donnees/quotas.json` font du lire-modifier-écrire concurrent et perdent
leurs incréments mutuels — à commencer par `tous|jetons`, le compteur qui porte le plafond global
de 30 M jetons, c'est-à-dire le seul garde-fou entre un bogue et un compte OpenRouter vidé. C'est
pourquoi le service démarre avec `--workers 1` et pourquoi l'installation refuse de continuer si
le port 8100 est déjà pris.

### Quand `/sante` ment

**`/sante` répond toujours `{"ok": true}`.** Il ne teste ni la clé ni le disque, et `_lire` avale
toutes les exceptions : un disque plein ou illisible se lit donc « compteurs à zéro, tout va
bien », pendant que chaque appel de `/v1/chat/completions` répond 500. Le seul champ qui dise
quelque chose est **`amont`** : à `false`, la clé n'a pas été lue et IRIS reçoit un 503 à chaque
demande. Le script d'installation vérifie `amont`, pas `ok`.

Deux corrections restent à faire dans `relais.py` : protéger `_ecrire`, et faire échouer `/sante`
quand le disque n'est pas accessible en écriture. Un service permanent surveillé par un point de
santé qui ne teste pas le disque est un service qu'on croit vivant.

### Ce que ce script ne fait pas

- **Il n'expose rien à l'extérieur.** Le relais n'écoute que sur `127.0.0.1` : aucun client ne
  peut l'atteindre tant qu'un tunnel sortant n'est pas en place. On n'ouvre **jamais** un port du
  routeur vers ce poste.
- **Il ne change pas `backend/iris/config.py`**, dont la valeur par défaut reste
  `https://relais.vela.app`. Tant que le tunnel n'a pas de nom stable, les IRIS installées
  continueront de s'adresser à une adresse qui ne répond pas.
- **Il ne fait pas rallumer la machine après une coupure de courant.** Windows ne peut pas se
  rallumer tout seul : cela se règle dans le BIOS/UEFI (« Restore on AC Power Loss » = Power On),
  et nulle part ailleurs.
- **Il ne libère pas de place sur le disque.** Le relais réécrit intégralement `quotas.json` deux
  fois par requête, et le service écrit des journaux. Le script refuse d'installer en dessous de
  2 Go libres, et il a raison de le faire.
