# OpenCode — ce que c'est, ce que ça change sur l'ordinateur, ce qu'IRIS lui interdit

Ce document est écrit pour quelqu'un qui n'est pas administrateur système. Il répond à cinq
questions, dans cet ordre : **qu'est-ce que c'est**, **qu'est-ce que ça met sur ma machine**,
**qu'est-ce que ça peut faire**, **qu'est-ce qu'IRIS l'empêche de faire**, **combien ça coûte** —
et il finit par **comment tout enlever**.

Tout ce qui est présenté ici comme un fait a été mesuré sur cet ordinateur le **5 septembre 2026**.
Ce qui n'a pas pu être vérifié est écrit **« non trouvé »**, jamais deviné. La liste complète de ce
qui reste inconnu est en fin de document, et elle est courte mais importante.

Le script d'installation qui accompagne ce document : `scripts/installer-opencode.ps1`.

---

## 1. Ce qu'OpenCode est

OpenCode est un **agent de programmation** : on lui donne un dossier de projet et une consigne en
français ou en anglais (« corrige le bogue de connexion »), il lit le code, décide quoi changer,
**écrit dans les fichiers** et **lance des commandes** — tests, build, git — jusqu'à considérer que
c'est fait.

Ce n'est pas un chatbot qui propose du code à recopier. Il agit tout seul sur le disque.

**Ce qu'OpenCode n'est pas, et ce point est tranché :** ce n'est pas un moteur d'IA de plus à côté
d'OpenRouter. Ce ne sont pas les mêmes couches. OpenRouter *fournit* un modèle ; OpenCode
*consomme* un modèle pour modifier des fichiers. Les deux ne figurent jamais dans la même liste
dans IRIS, et ne se remplacent pas l'un l'autre.

**Le rôle d'IRIS là-dedans.** Miguel dit « Iris, corrige le bogue dans mon site ». IRIS ne se met
pas à écrire du code dans le fil de la conversation : elle envoie un ouvrier — OpenCode —
travailler dans **un** dossier précis, puis elle rend compte, fichier par fichier, de ce qu'il a
fait. C'est une **délégation**, et c'est pour cela que l'accord humain porte sur un *dossier*.

---

## 2. Ce qui est déjà sur cette machine (et pourquoi ça ne suffit pas)

OpenCode existe sous **deux formes différentes**, et c'est la source de toute la confusion :
l'**application de bureau** (une fenêtre, comme un logiciel normal) et l'**outil en ligne de
commande** (un programme sans fenêtre, qu'un autre programme peut appeler). IRIS a besoin du
second. C'est le premier qui est installé.

| Ce qui est là | Où | Taille | Ce que c'est |
|---|---|---|---|
| Application de bureau **OpenCode 1.18.25** | `%LOCALAPPDATA%\Programs\@opencode-aidesktop` | 231 Mo (`OpenCode.exe`) | Installée le 28 août. Une fenêtre Electron. **N'apporte aucune ligne de commande.** |
| Réglages de l'application de bureau | `%APPDATA%\ai.opencode.desktop` | quelques Ko | Fenêtres, espaces de travail, mises à jour |
| Kit de greffons `@opencode-ai/plugin` et `@opencode-ai/sdk` **1.18.23** | `~/.config/opencode/node_modules` | 52 Mo | Posé le 27 août. Des **bibliothèques**, pas un programme |
| Votre configuration OpenCode | `~/.config/opencode/opencode.jsonc` | 50 octets | Vide : uniquement la ligne `$schema` |
| Historique des sessions | `~/.local/share/opencode` | **313 Mo** (`opencode.db` : 311 Mo) | Toutes les conversations OpenCode passées, du 27 août au 3 septembre |
| Cache des modèles | `~/.cache/opencode/models.json` | 4,2 Mo | Liste des modèles disponibles |

**Et l'outil en ligne de commande ? Absent.** Vérifié : rien dans le PATH, rien dans `%APPDATA%\npm`,
pas de `~/.opencode/bin`, pas de `~/.bun`, `~/.cache/opencode/bin` est vide. Aucun fichier
`opencode.cmd`, `opencode.exe` ou `opencode` nulle part.

C'est pour cela qu'aujourd'hui IRIS répond, quand on lui demande de corriger un bogue :

> « OpenCode n'est pas installé sur cet ordinateur, alors je ne peux pas encore lui confier de
> travail de programmation. […] Il faut l'installer toi-même, dans un terminal. »

Ce n'est pas une panne. C'est l'état normal tant que le programme n'existe pas, et IRIS le dit
proprement au lieu de planter. **IRIS n'installe jamais OpenCode elle-même** : poser un programme
qui a le droit de modifier vos fichiers, c'est une décision qui se prend sciemment, par la personne
qui en assume les conséquences.

---

## 3. Ce que l'installation ajoute, exactement

Le script installe l'outil en ligne de commande **par npm**, le gestionnaire de paquets de Node.js.
Ce n'est pas une préférence de style, c'est ce que la machine permet :

- **Node 24.19.0** et **npm 11.17.0** sont déjà installés (`C:\Program Files\nodejs`).
- **bun, scoop et chocolatey sont absents** : les voies d'installation qui passent par eux ne
  s'appliquent pas ici.
- Le dossier où npm pose ses programmes globaux, `%APPDATA%\npm`, est **déjà dans votre PATH** :
  rien à modifier dans l'environnement Windows.
- Et surtout : `%APPDATA%\npm` est précisément l'un des endroits où IRIS cherche le binaire
  (`_candidats_binaire` dans `backend/iris/opencode.py`). Une installation npm globale tombe donc
  pile où IRIS regarde, même si le PATH était cassé.
- Une installation npm globale **se défait par une commande**, sans désinstalleur ni registre.

| | |
|---|---|
| **Droits administrateur** | **Non requis.** Si quelque chose vous les demande, ce n'est pas ce script. |
| **Registre Windows** | Pas touché |
| **PATH** | Pas modifié (il contient déjà ce qu'il faut) |
| **Ce qui est écrit** | `%APPDATA%\npm` et `%APPDATA%\npm\node_modules` |
| **Ce qui n'est PAS touché** | `~/.config/opencode` (vos réglages), `~/.local/share/opencode` (vos sessions), l'application de bureau |
| **Réversible** | Oui — voir la section 8 |

**Le nom du paquet n'est pas une certitude, et le script ne fait pas semblant.** Les seuls paquets
prouvés sur ce disque sont `@opencode-ai/plugin` et `@opencode-ai/sdk`, qui sont des bibliothèques.
Le nom du paquet npm qui fournit la commande `opencode` **n'a pas pu être vérifié** pour ce projet.
Le script part donc d'une hypothèse (`-Paquet`, par défaut `opencode-ai`), **la confirme auprès du
registre npm avant d'installer quoi que ce soit** — `npm view` lit des informations, il n'installe
rien — et **s'arrête net** si le paquet n'existe pas ou ne fournit pas de commande nommée
`opencode`. Il vous dit alors d'aller chercher le nom exact et de relancer avec `-Paquet <nom>`.

Pour tout voir sans rien installer :

```powershell
.\scripts\installer-opencode.ps1 -Simulation
```

Après installation, le script vérifie que le programme **répond** (`opencode --version`), qu'**IRIS
le trouvera**, et il enregistre l'aide de la commande dans un fichier texte (`%TEMP%`). Ce dernier
point n'est pas cosmétique : IRIS appelle aujourd'hui `opencode run "<consigne>"` sans que
personne n'ait jamais pu confronter cette ligne à un vrai binaire. Le premier ordinateur où
OpenCode existe est le premier endroit où on peut enfin le vérifier.

---

## 4. Ce qu'OpenCode peut faire sur cette machine

Ce n'est pas une liste théorique. C'est ce que le journal des sessions passées
(`~/.local/share/opencode/log/opencode.log`, 27 août – 3 septembre) montre qu'il a **déjà fait**,
avant qu'IRIS n'ait quoi que ce soit à voir avec lui.

**Décisions de permission enregistrées sur cette période : 2 017.
Dont 1 999 « autorisé » et 18 « demander ».** Dans 1 780 cas, la règle qui a autorisé était `*` :
« tout ».

| Ce qu'il a demandé | Combien de fois |
|---|---|
| Lancer une commande système (`bash`) | 1 435 |
| Modifier un fichier (`edit`) | 282 |
| Lire un fichier (`read`) | 126 |
| **Sortir du dossier de travail** (`external_directory`) | **111** |
| Aller chercher une page web (`webfetch`) | 11 |
| Chercher sur le web (`websearch`) | 10 |

Trois faits méritent d'être lus lentement :

1. **Il a été lancé sur la racine du disque.** Le journal contient 8 démarrages avec pour dossier de
   travail `C:\` — l'ordinateur entier — et 11 avec `C:\Users\migue`, le dossier personnel complet.
2. **Il lance du code arbitraire.** Parmi les commandes autorisées : des `python -c "…"` qui ouvrent
   des connexions réseau, et un `uvicorn.run(app, host='0.0.0.0', port=8001)` — c'est-à-dire un
   serveur qui écoute sur **toutes** les interfaces réseau, pas seulement sur la machine.
3. **Il est déjà venu dans le backend d'IRIS, tout seul.** Le journal montre ses appels à
   `http://127.0.0.1:8765/` et `http://127.0.0.1:8765/api/transcribe` : l'API d'IRIS elle-même.

Ce n'est pas un reproche à OpenCode : il a fait ce qu'on lui demandait, avec les permissions qu'on
lui avait données. C'est une description de **ce dont il est capable**, et c'est la raison d'être de
tout ce qui suit.

Ajoutons ce qui ne se voit pas dans le journal mais qui découle de la nature de l'outil :
**OpenCode envoie votre code source à un fournisseur d'IA** pour pouvoir le comprendre. Le contenu
des fichiers qu'il lit sort de l'ordinateur.

---

## 5. Comment IRIS l'encadre

Le service vit dans `backend/iris/opencode.py`. Il reprend, volontairement à l'identique, la serrure
déjà utilisée pour le courriel et le SMS (`courriel.py`, `telephonie.py`).

**La serrure.** La fonction qui lance OpenCode n'accepte pas un travail : elle n'accepte qu'une
**autorisation**, et une autorisation ne peut être fabriquée que par la fonction qui affiche la
demande à l'écran et attend la réponse. Il n'existe aucun chemin dans le code pour lancer OpenCode
sans qu'un humain ait dit oui. Ce n'est pas une consigne qu'on peut oublier de suivre, c'est une
impossibilité de construction.

Cette autorisation :

- vaut **cinq minutes**, puis expire ;
- **ne sert qu'une fois** ;
- est liée à l'**empreinte** du travail — le dossier résolu, la consigne, la durée. Si l'un des
  trois change entre l'accord et le lancement, elle est refusée ;
- porte sur le **chemin réel** du dossier, pas sur la phrase dite. Un accord donné pour
  `Documents/IRIS/site-flowcare` ne vaut jamais pour un autre dossier.

**Le périmètre.** IRIS ne devine jamais dans quel dossier travailler. Tant que vous ne lui avez
nommé aucun dossier autorisé, elle répond « tu ne m'as autorisé aucun dossier de travail » et ne
lance rien — même OpenCode installé. Et une **liste noire prime sur la liste blanche** : autoriser
`~/Documents` n'ouvre pas `~/Documents/.ssh` par ricochet.

**Ce qu'IRIS impose à OpenCode le temps d'un lancement**, sans jamais écrire dans votre fichier
`~/.config/opencode/opencode.jsonc` — vos réglages vous appartiennent :

| Réglage imposé | Valeur | Pourquoi |
|---|---|---|
| Partage de session | **désactivé** | Par défaut OpenCode permet de publier une session sur le web. Le code d'un client n'a pas à devenir une page publique. |
| Aller chercher sur le web | **refusé** | Un agent qui peut aller chercher sur le web peut aussi y envoyer. |
| Sortir du dossier | **refusé** | Voir la limite honnête, plus bas. |
| Modifier des fichiers / lancer des commandes | autorisé | L'accord humain a déjà été donné, et il portait sur le dossier. |

**Avant, pendant, après.** Avant : IRIS photographie le dossier (chaque fichier, sa taille, sa date)
et relève l'état git. Pendant : elle limite la durée — dix minutes par défaut. Après : elle
recompare, et vous dit « 3 fichiers modifiés, 1 ajouté », ou « il n'a rien modifié » avec la même
netteté. Un dépassement de délai n'est **pas** présenté comme un échec ni comme une annulation :
ce qui a été écrit reste écrit, et la phrase le dit.

**Les traces.** Chaque intervention laisse un dossier daté dans les données d'IRIS, écrit **avant**
le lancement — si IRIS est fermée pendant qu'OpenCode travaille, il reste sur le disque de quoi
répondre à « qu'est-ce qu'elle a lancé, où, et pourquoi ». Les **refus sont tracés autant que les
accords** : un journal qui ne montre que les succès ne prouve rien.

---

## 6. Ce qu'IRIS ne laissera PAS OpenCode faire

**Section obligatoire.** Elle contient aussi ce qu'IRIS ne peut *pas* garantir, parce qu'une
promesse fausse est pire que pas de promesse.

### Ce qui est réellement empêché

| Interdit | Comment |
|---|---|
| **Travailler dans un dossier que vous n'avez pas nommé** | Liste blanche vide par défaut. Aucune déduction depuis la conversation : « corrige mon site » ne désigne pas un dossier, ça désigne une idée. |
| **Toucher au dépôt d'IRIS lui-même** | Liste noire, et ce n'est pas une précaution théorique : le journal prouve qu'OpenCode y est déjà allé tout seul. |
| **Lire les clés et les réglages d'IRIS** | Le dossier de données d'IRIS (`.env`, `settings.json`, `iris.db`) est en liste noire. Un agent envoyé « corriger mon site » qui lit `.env` lit aussi les clés ElevenLabs et de licence. |
| **Toucher à `~/.ssh`, `~/.aws`, `~/.gnupg`, `~/.config`, `%APPDATA%`, Windows, Program Files** | Liste noire, même si ces dossiers sont imbriqués dans un dossier autorisé. |
| **Travailler à la racine d'un disque, ou dans tout votre dossier personnel** | Refus explicite. Le journal montre qu'OpenCode a déjà été démarré 8 fois sur `C:\`. Par IRIS, jamais. |
| **Travailler sur un partage réseau** | Refusé : ce qui s'y passe ne se surveille pas et ne se répare pas. |
| **Travailler dans un dossier qui n'existe pas** | IRIS ne le crée pas. Sur un nom mal orthographié, OpenCode inventerait un projet entier dans un dossier vide. |
| **Partir sans consigne précise** | Un agent envoyé sans consigne fait ce qu'il croit utile, et c'est comme ça qu'un site marche moins bien après. |
| **Publier une session sur le web** | Partage désactivé à chaque lancement. |
| **Aller chercher sur le web** | Refusé à chaque lancement. |
| **Tourner indéfiniment** | Dix minutes par défaut, une heure au maximum absolu. |
| **Être lancé sur un simple « oui » dicté** | Aucune confirmation ne passe par la voix aujourd'hui. Demandé à la voix, IRIS répond « valide-le à l'écran » — plutôt que d'ouvrir une fenêtre que personne ne regarde et de conclure sur un refus silencieux. |
| **Être relancé avec un vieil accord** | Cinq minutes, usage unique, empreinte revérifiée au moment d'agir. |
| **Tourner en mode local** | Le mode local interdit d'envoyer vos données dehors ; OpenCode envoie le code source à un fournisseur d'IA. IRIS ne le lance pas. |
| **Être installé par IRIS** | Elle ne pose pas elle-même un programme qui a le droit d'écrire dans vos fichiers. |

### La limite, dite franchement

**IRIS ne peut pas empêcher OpenCode d'écrire ailleurs sur l'ordinateur.** Une fois lancé, le
processus tourne sous votre session Windows, avec vos droits. Il n'existe pas ici de bac à sable, et
le réglage « interdiction de sortir du dossier » revient à demander à l'agent qu'on surveille de se
surveiller lui-même — le journal montre d'ailleurs qu'il a évalué cette permission 111 fois.

**Et il y a une seconde limite, qui n'est écrite nulle part ailleurs.** La liste noire empêche
OpenCode de *lire le fichier* `.env` d'IRIS — mais le processus OpenCode est lancé en **héritant de
tout l'environnement d'IRIS**, et IRIS charge les clés de son `.env` dans cet environnement au
démarrage (`load_env_files` dans `backend/iris/config.py`, puis `dict(os.environ)` dans
`backend/iris/opencode.py`). Sur cette machine, cela veut dire concrètement qu'un OpenCode lancé par
IRIS reçoit `ELEVENLABS_API_KEY` dans ses variables d'environnement, sans avoir eu besoin d'ouvrir
le moindre fichier interdit. Le dossier est protégé ; la variable ne l'est pas. **Ce n'est pas
corrigé à ce jour** — c'est signalé ici pour que personne ne croie le contraire.

Le périmètre est une **déclaration** et un **détecteur**, pas une prison. IRIS le dit dans la phrase
même qu'elle affiche avant de demander votre accord, au lieu de le masquer :

> « Je ne peux pas l'empêcher d'écrire ailleurs sur ton ordinateur : il tourne avec tes droits.
> Je le surveille et je te dis tout ce qui a changé, mais je ne l'enferme pas. »

Et de la même façon, sur ce qu'on pourra défaire : si le dossier n'est pas sous git, IRIS annonce
avant de partir qu'elle notera tout ce qu'il touche mais **ne pourra pas tout remettre comme
avant**. C'est cette phrase-là qui doit décider d'un oui ou d'un non.

---

## 7. Ce que ça coûte

**Aucun prix n'est indiqué ici, parce qu'aucun prix n'a été trouvé.** Ce qui suit est ce qui a été
constaté sur cette machine, et rien de plus.

Les sessions OpenCode déjà passées sur cet ordinateur ont utilisé un fournisseur nommé `opencode`
et quatre modèles, tous portant `-free` dans leur nom :

| Modèle utilisé | Nombre de requêtes relevées |
|---|---|
| `muse-spark-1.2-contributor-free` | 527 |
| `mimo-v2.5-free` | 419 |
| `ling-3.0-flash-fin-free` | 81 |
| `hy3-free` | 12 |

Ce que cela **ne prouve pas** : que ces modèles resteront gratuits, qu'ils seront ceux utilisés
demain, ou qu'aucune facture n'existe. Le suffixe d'un nom de modèle n'est pas un contrat.

| Question | Réponse |
|---|---|
| Quels modèles ? | Ceux du tableau ci-dessus ont servi ici. La liste complète est téléchargée depuis `https://models.opencode.ai/api.json` (observé dans le journal). |
| Combien coûte chacun ? | **Non trouvé.** |
| Quelle clé d'API, et où est-elle stockée ? | **Non trouvé.** Aucun fichier d'authentification n'a été trouvé dans `~/.config/opencode` ni dans `~/.local/share/opencode`. Le compte est vraisemblablement lié à l'application de bureau, mais ce n'est pas vérifié. |
| Facturé à qui ? | **Non trouvé.** |
| Faut-il un abonnement ? | **Non trouvé.** |

**Ce qui est certain, en revanche :** OpenCode consomme un fournisseur d'IA **distinct** de celui
d'IRIS, avec son propre compte. IRIS ne configure pas OpenCode avec sa clé et ne lui dit pas quel
modèle prendre : ce sont deux factures séparées. Avant de laisser OpenCode travailler régulièrement,
allez lire dans son application de bureau quel compte et quel modèle sont sélectionnés.

**Mais attention à une nuance qui n'est pas une question d'argent :** « IRIS ne lui donne pas sa
clé » ne veut pas dire « OpenCode n'y a pas accès ». Le processus hérite de tout l'environnement
d'IRIS, clés comprises — voir la seconde limite en fin de section 6. C'est une question de fuite de
secret, pas de facturation, mais elle se lit dans la même phrase et il ne faut pas les confondre.

---

## 8. Comment tout enlever

### Enlever l'outil en ligne de commande (ce que le script a posé)

```powershell
.\scripts\installer-opencode.ps1 -Desinstaller
```

Retire le paquet npm global et vérifie ensuite qu'aucun binaire `opencode` ne répond plus. Ne touche
ni à vos réglages, ni à vos sessions, ni à l'application de bureau. IRIS redevient alors simplement
muette sur la délégation : l'outil disparaît de ce qu'elle sait faire, et rien d'autre ne change
dans son comportement.

### Enlever aussi les 313 Mo de sessions passées

```powershell
.\scripts\installer-opencode.ps1 -Desinstaller -EffacerDonnees
```

Supprime `~/.local/share/opencode`. **C'est irréversible et il n'y a pas de corbeille** : c'est
l'historique complet de vos conversations avec OpenCode. Le script affiche le chemin, le nombre de
fichiers et la taille exacte, puis exige que vous tapiez `EFFACER` en majuscules. Cette suppression
est délibérément séparée du retrait du programme : retirer un programme est réversible en une
commande, effacer des données ne l'est pas, et les deux ne doivent pas partir du même geste.

### Enlever l'application de bureau

Elle n'a rien à voir avec ce script et a son propre désinstalleur :

```
%LOCALAPPDATA%\Programs\@opencode-aidesktop\Uninstall OpenCode.exe
```

Ou : *Paramètres Windows → Applications → OpenCode*.

### Enlever le reste, à la main si vous le souhaitez

| Dossier | Contenu |
|---|---|
| `~/.config/opencode` | Vos réglages OpenCode et le kit de greffons (52 Mo) |
| `~/.cache/opencode` | Cache de la liste des modèles (4,2 Mo) |
| `%APPDATA%\ai.opencode.desktop` | Réglages de l'application de bureau |

Le script ne touche à aucun des trois : ce sont vos affaires, pas ce qu'il a posé.

---

## 9. Ce qui n'a pas été trouvé

À lire avant de faire confiance à ce document sur ces points précis.

| Question | État |
|---|---|
| La commande d'installation officielle recommandée par opencode.ai | **Non trouvé.** Le script utilise npm, justifié par ce que cette machine permet (section 3), pas par une documentation vérifiée. |
| Le nom exact du paquet npm qui fournit `opencode` | **Non vérifié.** Le script part d'une hypothèse, la confirme auprès du registre npm, et s'arrête si elle est fausse. |
| La ligne de commande réelle : sous-commandes, options | **Non trouvé.** IRIS appelle `opencode run "<consigne>"`, le dossier étant épinglé par le répertoire courant du processus — un choix fait sans jamais avoir vu le binaire. Le script capture `--help` à l'installation, précisément pour que ce soit enfin vérifiable. **C'est le premier point à contrôler après l'installation.** |
| L'API HTTP locale d'OpenCode (`serve`), ses routes, son port | **Non trouvé.** Le jour où IRIS saura la piloter, chaque écriture de fichier pourra être confirmée une par une, au lieu d'être autorisée en bloc pour toute la durée du travail. |
| Les prix, la clé d'API, qui est facturé | **Non trouvé** (section 7). |
| Les clés d'IRIS passées à OpenCode par l'environnement | **Trouvé, et non corrigé.** Le processus OpenCode hérite de tout l'environnement d'IRIS, `ELEVENLABS_API_KEY` comprise. La liste noire protège le fichier `.env`, pas la variable. Voir la fin de la section 6. |

**Un dernier point, qui n'est pas dans OpenCode mais dans IRIS :** la liste des dossiers autorisés se
lit dans les réglages, section `opencode`, clé `racines`. Cette section **n'existe pas encore** dans
`backend/iris/config.py`. Conséquence concrète : même avec OpenCode parfaitement installé, IRIS
répondra « tu ne m'as autorisé aucun dossier de travail » tant que cette section n'aura pas été
ajoutée et remplie. Le script d'installation le signale à la fin, plutôt que de vous laisser croire
à une panne.
