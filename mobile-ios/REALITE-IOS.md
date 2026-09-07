# La vérité d'Apple, capacité par capacité — IRIS sur iPhone

Écrit le 2026-09-06. Se lit sans jamais avoir touché à iOS : chaque cadre technique (CallKit,
App Intents, entitlement…) est expliqué en une phrase à sa première apparition.

Ce document répond à une seule question, pour chacune des huit choses que Miguel demande :
**est-ce qu'une application iPhone peut le faire, oui ou non, et sous quelle forme exacte ?**
Il ne cherche pas à faire plaisir. Une bonne partie de la demande est possible sous une forme un
peu différente ; une autre partie est un mur que ni le temps ni l'argent ne franchissent, parce
que c'est le système d'exploitation lui-même qui l'interdit. Le dire aujourd'hui vaut mieux que de
le découvrir après trois mois de code.

---

## La distinction qui gouverne tout le document : deux sortes d'« interdit »

Sur iPhone, il y a deux barrières très différentes, et les confondre mène à de mauvaises décisions.

1. **L'interdit de la revue (App Store Review).** Apple relit chaque application avant de la publier
   sur l'App Store et refuse celles qui enfreignent ses règles. **Cet interdit-là saute** si Miguel
   n'utilise pas l'App Store : il peut installer sur SON iPhone une application qu'il a signée
   lui-même (compte développeur, TestFlight, distribution ad hoc). C'est un usage personnel, non
   revu par Apple.

2. **L'interdit du système (le « bac à sable », *sandbox*).** Le *sandbox* est la cloison que
   iOS met autour de chaque application : elle ne voit pas la mémoire des autres, ne lit pas leur
   écran, ne touche pas au téléphone cellulaire. **Cet interdit-là ne saute jamais.** Il est
   appliqué par le système à l'exécution, pas par un relecteur. Signer soi-même l'application n'y
   change rien : il n'existe **aucune** API privée fiable pour le contourner, contrairement à
   Android où le développeur peut activer un « service d'accessibilité » qui pilote les autres
   applications.

> **La phrase à retenir.** Tout ce que Miguel demande qui ressemble à « IRIS pilote le téléphone
> comme elle pilote le PC » (voir l'écran des autres apps, cliquer dedans, décrocher le téléphone
> cellulaire, envoyer un SMS en silence) tombe dans la catégorie 2 : le *sandbox*. Ce n'est donc
> **pas** débloqué par un compte développeur ni par l'absence de revue. C'est un mur pour tout le
> monde, y compris pour Apple elle-même dans les apps tierces.

C'est exactement le contraire du PC : sur Windows, IRIS voit l'écran et pilote les applications
parce que Windows le permet à un programme de bureau. iOS a été conçu, dès l'origine, pour que
cela soit impossible. **La valeur centrale d'IRIS sur le PC — voir et agir sur tout — est
précisément la catégorie qu'iOS ferme.**

---

## Le tableau des huit capacités

| # | Ce que Miguel demande | Verdict | Cadre officiel | La forme réellement livrable |
|---|---|---|---|---|
| 1 | IRIS accède au **numéro de téléphone** de l'utilisateur | **IMPOSSIBLE** en lecture automatique | (aucune API ; CTCarrier retiré) | L'utilisateur le tape une fois, IRIS le retient |
| 2 | IRIS **décroche / renvoie / refuse** un appel entrant à la voix | **IMPOSSIBLE** pour un appel cellulaire | CallKit (VoIP seulement) | Possible seulement si l'appel est un appel **VoIP qui passe par IRIS** |
| 3 | Pendant un appel IRIS se tait ; **« Iris raccroche »** coupe l'appel | **IMPOSSIBLE** pour un appel cellulaire | CallKit (VoIP seulement) | Idem : possible uniquement sur un appel VoIP d'IRIS |
| 4 | IRIS **envoie des SMS** depuis le numéro de l'utilisateur | **POSSIBLE MAIS BRIDÉ** | MessageUI (`MFMessageComposeViewController`) | Message **pré-rempli**, l'utilisateur touche Envoyer. Envoi en silence impossible |
| 5 | IRIS **passe des appels** au nom de l'utilisateur | **POSSIBLE MAIS BRIDÉ** | lien `tel:` / CallKit | Composeur **pré-rempli**, l'utilisateur confirme. IRIS ne parle pas pendant l'appel cellulaire |
| 6 | IRIS **ouvre une autre app et l'utilise** (clique, cherche, se déplace) | **IMPOSSIBLE** pour des apps quelconques | App Intents / Shortcuts / liens | Seulement les apps qui **exposent** des actions ; jamais « cliquer dans » une app tierce |
| 7 | IRIS **voit l'écran en permanence** | **IMPOSSIBLE** en permanence et en silence | ReplayKit (partage lancé par l'utilisateur) | Partage d'écran **ponctuel, déclenché par l'utilisateur**, avec indicateur visible |
| 8 | IRIS **écoute l'audio et la vidéo** du téléphone | **BRIDÉ** (micro/caméra) / **IMPOSSIBLE** (le reste) | AVFoundation / ReplayKit | Micro et caméra **au premier plan, avec permission** ; pas d'écoute permanente en fond, pas de captation silencieuse de l'audio des autres apps |

**Décompte.** Sur les huit demandes prises **au pied de la lettre** : **0 pleinement possible**,
**3 possibles mais bridées** (4, 5, 8), **5 impossibles** telles quelles (1, 2, 3, 6, 7) — mais
**chacune des cinq a une approximation honnête et utile**, détaillée plus bas. Le mot « impossible »
ne veut pas dire « rien à faire » : il veut dire « pas sous la forme demandée, voici la forme qui
marche ».

La vraie ligne de partage n'est pas capacité par capacité, elle est plus simple : **tout ce qui
concerne le téléphone comme téléphone** (SMS, appels, son) est possible mais bridé par un geste
humain qu'Apple impose ; **tout ce qui concerne le pilotage des autres applications et de l'écran**
est un mur. Or c'est le second groupe qui fait le cœur d'IRIS sur PC. La conclusion se dessine
d'elle-même : sur iPhone, IRIS est d'abord **une télécommande vocale vers le PC** (ce qui marche
déjà, aujourd'hui, en page web), pas un agent qui pilote le téléphone.

---

## Le détail, capacité par capacité

Chaque fiche donne : ce qui est demandé, le verdict et **pourquoi**, la source, et — quand c'est
un mur — la **meilleure approximation honnête**.

### 1. Accéder au numéro de téléphone de l'utilisateur — IMPOSSIBLE (en lecture auto)

**Ce qui est demandé.** Qu'IRIS connaisse d'elle-même le numéro de l'iPhone.

**Verdict : impossible automatiquement.** iOS n'expose **aucune API publique** pour lire le numéro
de la ligne. La classe qui, autrefois, donnait des informations sur l'opérateur (`CTCarrier`, du
cadre *Core Telephony*) — et qui, même à l'époque, **ne donnait jamais le numéro** — a été
**retirée (« deprecated ») avec iOS 16, sans remplacement** ; depuis iOS 16.4 elle ne renvoie plus
que des valeurs bidon (`--`, `65535`) pour toute app compilée récemment. Apple l'a fait
explicitement pour des raisons de vie privée.

**Cet interdit est de catégorie « système ».** Il ne saute pas avec un compte développeur : il n'y
a pas d'API privée fiable qui rende le numéro, même sur une app signée par Miguel pour son propre
iPhone. C'est un mur pour tout le monde.

**L'approximation honnête, et elle est excellente.** L'utilisateur **tape son numéro une seule fois**
dans un réglage d'IRIS, et IRIS le retient (sur l'appareil, dans le trousseau *Keychain* d'iOS).
C'est trivial, fiable, et cela suffit à tous les usages réels : afficher « votre numéro », le
donner en contexte au PC, l'utiliser pour signer un message. Personne ne remarquera la différence.

**Sources.**
- Fil développeur Apple, retrait de CTCarrier : <https://developer.apple.com/forums/thread/714876>
- Note officielle « Deprecated with no replacement » (iOS 16 / 16.4) confirmée dans le même fil et
  la doc *Core Telephony*.

---

### 2 et 3. Décrocher / refuser / raccrocher un appel entrant à la voix — IMPOSSIBLE (appel cellulaire)

**Ce qui est demandé.** « Untel vous appelle, que voulez-vous faire ? » → « décroche » / « raccroche ».
Et pendant l'appel, « Iris raccroche » qui coupe.

**Verdict : impossible pour un appel cellulaire (le vrai appel qui arrive sur la ligne SIM).** Le
seul cadre qu'Apple offre pour les appels s'appelle **CallKit** — une phrase pour le situer :
*CallKit est le cadre qui donne à une application de téléphonie par Internet (VoIP) le droit
d'afficher l'écran d'appel du système et de coordonner ses appels avec le reste du téléphone.* Le
mot important est **VoIP** : « voix par Internet », c'est-à-dire un appel qui passe par une
application (WhatsApp, Zoom, Google Voice…), **pas** l'appel classique de la ligne téléphonique.

CallKit **ne donne aucun accès aux appels cellulaires.** Une application tierce ne peut pas :
- afficher son propre écran quand un appel SIM arrive,
- décrocher, refuser ou raccrocher l'appel SIM,
- entendre ou couper l'audio d'un appel SIM.

C'est un choix délibéré d'Apple, pour la sécurité et l'intégrité du système. Les développeurs qui
le demandent sur les forums Apple reçoivent invariablement la même réponse : non, CallKit est pour
la VoIP, pas pour les appels de la carte SIM.

**Précision sur la voix pendant l'appel.** Même si l'on pouvait décrocher, IRIS **n'entend pas**
l'audio d'un appel cellulaire (le *sandbox* l'interdit) et ne peut pas écouter « Iris raccroche »
en tâche de fond micro pendant l'appel. Deux murs, pas un.

**Ce que le voisin « app d'appel par défaut » (iOS 18.2) ne change pas.** Depuis iOS 18.2, un
utilisateur peut désigner une app tierce comme « app d'appel par défaut » et « app de messagerie
par défaut » (une exigence du règlement européen DMA, ouverte en partie mondialement). Cela permet
à une app **VoIP** de recevoir les `tel:` et d'être le composeur préféré — **cela ne donne toujours
pas** le droit de décrocher un appel de la ligne SIM ni de piloter l'app Téléphone d'Apple. *À
vérifier dans le détail au moment de construire*, mais aucune source ne suggère que ce réglage
ouvre l'appel cellulaire au contrôle d'un tiers.

**L'approximation honnête — et c'est peut-être le plus bel atout de Miguel.** La demande devient
possible **si l'appel lui-même passe par IRIS en VoIP.** Autrement dit : IRIS n'intercepte pas la
ligne d'Apple ; elle **est** une ligne. Comme Google Voice ou un standard téléphonique
d'entreprise, un numéro (loué chez un opérateur Internet, p. ex. Twilio) sonne « dans IRIS » ; iOS
reçoit une notification VoIP, CallKit affiche l'écran d'appel, et là — parce que c'est **son**
appel — IRIS peut le présenter à la voix, le décrocher (`CXAnswerCallAction`), le raccrocher
(`CXEndCallAction`), se taire pendant, etc. C'est un vrai produit, réaliste, mais **c'est un autre
produit** que « décrocher l'appel de ta ligne habituelle » : le correspondant appelle un numéro
IRIS, pas le numéro personnel de l'utilisateur. À présenter comme tel, jamais comme « IRIS décroche
ton téléphone ».

**Sources.**
- Documentation Apple, CallKit (rôle VoIP) : <https://developer.apple.com/documentation/callkit>
- Fil développeur : impossible de gérer l'UI d'un appel SIM cellulaire via CallKit :
  <https://developer.apple.com/forums/thread/772066>
- App d'appel/messagerie par défaut, iOS 18.2 : <https://developer.apple.com/support/dma-and-apps-in-the-eu/>

---

### 4. Envoyer des SMS depuis le numéro de l'utilisateur — POSSIBLE MAIS BRIDÉ

**Ce qui est demandé.** Qu'IRIS envoie un texto depuis le numéro de l'utilisateur.

**Verdict : possible d'ouvrir un SMS déjà écrit, impossible de l'envoyer en silence.** Le cadre
d'Apple s'appelle **MessageUI**, et sa pièce maîtresse est `MFMessageComposeViewController` — une
phrase : *c'est l'écran de rédaction de SMS d'Apple qu'une app peut faire apparaître, déjà rempli
avec un destinataire et un texte.* Mais la règle est nette dans la documentation : pendant que cet
écran est affiché, **c'est l'utilisateur — et personne d'autre — qui touche Envoyer.** Il n'existe
**aucune API** pour envoyer un SMS sans ce geste. C'est délibéré, pour la vie privée.

**C'est exactement ce qu'IRIS fait déjà, et c'est le bon design.** Le code existant
(`backend/iris/telephonie.py`, voie « iphone ») a déjà tranché ainsi, et sa docstring le dit mieux
que n'importe quelle promesse marketing : la garantie « IRIS n'envoie rien en votre nom sans votre
accord » cesse d'être une propriété fragile du code d'IRIS pour devenir **une propriété d'iOS**.
Même un bogue d'IRIS ne peut pas faire partir un texto tout seul. Bonus : le SMS part de la **vraie
ligne** de l'utilisateur, donc avec **son** numéro — ce qu'un numéro loué chez un tiers ne sait
justement pas faire.

**Ce que l'app iPhone ajoute par rapport à la page web actuelle.** Aujourd'hui la page `/m` ouvre
un lien `sms:` (Messages s'ouvre pré-rempli). Une app native pourrait afficher le même brouillon
avec `MFMessageComposeViewController` (plus propre, reste dans l'app, renvoie « envoyé » ou
« annulé »). La différence est cosmétique. **Le geste humain reste obligatoire dans les deux cas.**

**Ce qui reste un mur.** Envoyer un SMS en tâche de fond, en série, sans que l'utilisateur touche
l'écran : impossible, pour toujours, y compris en app signée par Miguel. C'est du *sandbox*.

**Sources.**
- Documentation Apple, `MFMessageComposeViewController` :
  <https://developer.apple.com/documentation/messageui/mfmessagecomposeviewcontroller>
- Confirmation (l'utilisateur envoie, pas de programme) : <https://developer.apple.com/forums/thread/42310>

---

### 5. Passer des appels au nom de l'utilisateur — POSSIBLE MAIS BRIDÉ

**Ce qui est demandé.** IRIS appelle un restaurant, un service client, au nom de l'utilisateur.

**Verdict : possible de lancer l'appel d'un geste, impossible de le mener seule.** Deux niveaux à
distinguer nettement.

- **Composer un numéro depuis la vraie ligne : possible, avec confirmation.** Un lien `tel:+1…`
  ouvre le composeur du téléphone ; l'iPhone demande « Appeler ce numéro ? » et l'utilisateur
  confirme. L'appel part alors de **sa** ligne, avec **son** numéro. C'est le brouillon d'appel
  qu'IRIS prépare déjà. Utile pour « appelle maman », « rappelle ce numéro ».

- **IRIS parle à la réception à ta place (réservation, service client) : ce n'est pas une capacité
  du téléphone.** Pour qu'IRIS *mène* la conversation, il faut que la voix de synthèse d'IRIS soit
  injectée dans l'appel et qu'elle entende l'autre bout — or, sur un appel cellulaire, le *sandbox*
  interdit à une app de toucher l'audio de l'appel. La seule façon réelle de faire ça, c'est un
  **appel monté côté serveur** (un opérateur Internet type Twilio compose le numéro et relie l'IA à
  la ligne), donc **depuis un numéro loué, pas depuis le numéro personnel**, et facturé à la minute.
  C'est un produit à part entière (le futur « relais » de VELA), pas une fonction de l'app iPhone.

**L'approximation honnête à livrer d'abord.** Le composeur pré-rempli (niveau 1). Et présenter le
« IRIS appelle à ta place » comme une **feuille de route serveur** séparée, jamais comme quelque
chose que l'app iPhone fait toute seule.

**Sources.**
- Schéma d'URL `tel:` (Apple, *URL Scheme Reference*) — comportement composeur + confirmation.
- Même limite CallKit / *sandbox* audio que les points 2-3 (l'app ne touche pas l'audio d'un appel
  cellulaire).

---

### 6. Ouvrir une autre app, demander quoi faire, puis l'utiliser — IMPOSSIBLE (apps quelconques)

**Ce qui est demandé.** IRIS ouvre une application, puis **clique dedans, cherche, se déplace** —
comme elle le fait sur le PC.

**Verdict : mur.** C'est le cœur du *sandbox*, et le point où l'écart PC / iPhone est le plus
brutal. Une app iOS ne peut pas :
- lire l'interface d'une autre app,
- toucher un bouton, remplir un champ ou faire défiler dans une autre app,
- savoir ce qui s'y passe.

Il **n'existe pas**, sur iOS, l'équivalent du « service d'accessibilité » d'Android qui permet à
une app de piloter les autres. Apple réserve ces capacités à ses propres fonctions
d'accessibilité ; **elles sont fermées aux tiers**, et cela ne s'ouvre pas avec un compte
développeur (c'est du système, pas de la revue).

**Ce qui est réellement possible, et c'est étroit.** iOS offre trois canaux, tous **coopératifs** —
ils marchent uniquement si l'app d'en face a prévu d'être pilotée :
- **Ouvrir** une autre app à un endroit précis, via un lien (`x-app://…`, *Universal Link*). C'est
  « ouvrir la page profil dans Instagram », pas « cliquer dans Instagram ».
- **App Intents / SiriKit** — une phrase : *App Intents est le système par lequel une app
  **publie** des actions (« ajoute une tâche », « démarre une minuterie ») qu'IRIS, Siri ou
  l'app Raccourcis peuvent ensuite déclencher.* Mais seules les actions que l'autre app a **choisi
  d'exposer** existent ; on ne « clique » pas dans son écran, on appelle une action qu'elle offre.
- **Raccourcis (Shortcuts)** — enchaîner ces actions publiées. Même limite.

**L'approximation honnête.** Sur le **téléphone**, IRIS peut *ouvrir* des apps et déclencher les
actions qu'elles exposent — utile, mais loin de « piloter n'importe quelle app ». Le vrai « IRIS
clique, cherche, se déplace » **existe déjà, mais sur le PC** : c'est là que l'app iPhone doit
renvoyer la demande. « Iris, sur mon ordinateur, ouvre ce site et remplis le formulaire » → le PC
le fait ; le téléphone n'est que le micro et l'oreille. C'est la bonne division du travail, et elle
est déjà à moitié construite (page `/m` → backend).

**Sources.**
- iOS vs Android : les API d'accessibilité sont fermées aux tiers sur iOS :
  <https://pauljadam.com/iosvsandroida11y/>
- Documentation Apple, App Intents : <https://developer.apple.com/documentation/appintents>

---

### 7. Voir l'écran en permanence — IMPOSSIBLE en permanence ; BRIDÉ en ponctuel

**Ce qui est demandé.** Qu'IRIS voie l'écran tout le temps pour savoir « où on est ».

**Verdict : pas en permanence, pas en silence.** Aucune app tierce ne peut lire en continu ce qui
s'affiche, ni sur son écran ni surtout sur celui des autres apps. Le seul mécanisme qui capture
l'écran entier s'appelle **ReplayKit** — une phrase : *ReplayKit est le cadre de partage/
enregistrement d'écran d'iOS, le même qui alimente le « partage d'écran » de Zoom ou Teams.* Et il
vient avec trois verrous inamovibles :
1. **C'est l'utilisateur qui le lance**, via un bouton système (`RPSystemBroadcastPickerView`) ;
   une app ne peut pas démarrer la capture toute seule.
2. **Un indicateur reste visible** pendant toute la capture (barre/point rouge) : impossible de
   filmer l'écran en cachette.
3. **C'est une session, pas un état permanent** : ça s'arrête, et il faut un nouveau geste pour
   reprendre.

**L'approximation honnête.** Pour un usage réel — « regarde cet écran et dis-moi quoi faire » —
l'utilisateur **lance un partage ReplayKit** le temps d'une question ; IRIS reçoit les images de
cette session, les analyse, répond. C'est ponctuel, visible, consenti. Utile, mais à l'opposé de
« voir en permanence ». Autre voie, plus modeste : l'utilisateur prend une **capture d'écran** et
la donne à IRIS (un geste, une image) — sans aucun cadre spécial.

Là encore, la vraie « vision continue de l'écran » **existe sur le PC** : `backend/iris/capture.py`
capture le bureau, et c'est là que ça a sa place. Sur iPhone, non.

**Sources.**
- Documentation Apple, ReplayKit et `RPSystemBroadcastPickerView` :
  <https://developer.apple.com/documentation/replaykit>
- Capture système déclenchée par l'utilisateur, indicateur visible :
  <https://developer.apple.com/forums/thread/723509>

---

### 8. Écouter l'audio et la vidéo du téléphone — BRIDÉ (micro/caméra) / IMPOSSIBLE (le reste)

**Ce qui est demandé.** Qu'IRIS écoute l'audio et la vidéo du téléphone.

**Verdict, en deux morceaux.**

- **Micro et caméra de l'app, avec permission : possible mais encadré (BRIDÉ).** Via *AVFoundation*
  (le cadre audio/vidéo d'iOS), une app peut, **après une autorisation explicite** de
  l'utilisateur, prendre le micro et la caméra. Mais : au **premier plan**, avec un **indicateur**
  visible (le point orange/vert de la barre d'état), et **pas** en écoute permanente écran éteint.
  L'« écoute du mot d'activation en tâche de fond » (« Dis-moi Iris » qui réveille l'app comme le
  fait « Dis Siri ») **n'est pas possible** pour un tiers : iOS ne laisse pas une app tierce écouter
  le micro en continu en arrière-plan (batterie + vie privée). Le mot d'activation personnalisé est
  réservé à Siri.

- **Capter l'audio des autres apps, ou l'audio du téléphone « en général », en silence :
  impossible.** Le *sandbox* interdit de lire le son que produisent les autres apps. Le seul canal
  qui approche cela est, encore, **ReplayKit** (une session de partage lancée par l'utilisateur
  capture l'audio de l'app + le micro), avec les trois verrous du point 7.

**L'approximation honnête.** Pendant que l'app IRIS est ouverte et au premier plan, elle écoute le
micro pour la voix (c'est déjà le principe de la page `/m` via la reconnaissance du navigateur).
Pour le mot d'activation « Dis-moi Iris » sans ouvrir l'app : **impossible en tâche de fond** ; le
substitut réaliste sur iPhone est **« Dis Siri, parle à IRIS »** (un *App Shortcut* qu'IRIS publie,
voir ARCHITECTURE.md), qui ouvre IRIS et enchaîne. Ce n'est pas le mot maison, mais c'est la seule
activation mains-libres qu'Apple autorise.

**Sources.**
- Autorisations micro/caméra et indicateurs (Apple, *AVFoundation* / *Privacy*).
- Écoute micro en arrière-plan non permise aux tiers ; mot d'activation réservé à Siri — comportement
  documenté d'iOS (*à confirmer sur la version d'iOS ciblée au moment de construire, mais aucune API
  publique ne l'ouvre aujourd'hui*).

---

## Ce que change (et ne change pas) l'installation en développeur sur SON iPhone

Miguel peut installer sur son propre iPhone une app qu'il signe (compte développeur payant,
TestFlight, ad hoc), **sans passer par la revue de l'App Store.** Ce que ça débloque, et ce que ça
ne débloque pas :

| Ça débloque | Ça ne débloque PAS |
|---|---|
| Utiliser une app qu'Apple **refuserait de publier** (usage perso, hors magasin) | Le *sandbox* : voir/piloter les autres apps (point 6, 7) reste impossible |
| Tester des entitlements en mode développement (ex. Family Controls) sans attendre l'approbation de distribution | Décrocher un appel **cellulaire** (points 2-3) : c'est du système, pas de la revue |
| Contourner des règles de **présentation** de l'App Store | Envoyer un SMS **en silence** (point 4) : `MFMessageComposeViewController` exige le geste, y compris en app signée |
| — | Lire le **numéro** de la ligne (point 1) : pas d'API, même privée fiable |

**En clair : la distribution personnelle ne franchit aucun des cinq murs.** Ces murs sont dans le
système, pas dans le règlement. Ce que la distribution personnelle offre vraiment, c'est de
**commencer à construire tout de suite** ce qui est possible, sans attendre une revue et sans
publier — exactement ce dont Miguel a besoin pour une v1 sur son propre téléphone.

Un mot sur l'**entitlement** (droit spécial) — une phrase : *un entitlement est une permission
inscrite dans l'app, qu'Apple doit accorder, pour toucher à une capacité sensible.* Deux nous
concernent : **Family Controls** (Temps d'écran) et, pour un jour, un droit VoIP. Family Controls
a un mode **développement** (local, sans approbation) et un mode **distribution** (demande à Apple,
approuvée « au cas par cas », quelques jours à quelques semaines, réservée aux vrais usages de
contrôle parental / bien-être numérique). Voir ARCHITECTURE.md : ce cadre sert à *surveiller/limiter*
des apps, **pas** à les piloter — il ne débloque donc pas le point 6.

---

## Le résumé pour Miguel, sans détour

- **La moitié « téléphone » de la demande est faisable, mais avec un geste du pouce imposé par
  Apple.** Textos et appels : IRIS prépare, l'utilisateur confirme d'un toucher. Ce n'est pas une
  limite d'IRIS, c'est une garantie d'iOS — et c'est un argument de vente, pas une faiblesse.
- **La moitié « pilotage » de la demande est un mur.** Voir l'écran en permanence, cliquer dans les
  autres apps, décrocher le téléphone cellulaire à la voix : le système iOS l'interdit à toute app
  tierce, et rien (ni temps, ni argent, ni compte développeur) ne l'ouvre.
- **La bonne nouvelle est structurelle.** Tout ce qui est un mur sur le téléphone **fonctionne déjà
  sur le PC** (voir l'écran, piloter les apps). L'app iPhone n'a donc pas à refaire ça : elle doit
  être **la voix et l'oreille**, et renvoyer le travail lourd au PC resté à la maison — un pont qui
  est **déjà à moitié construit** (page `/m`, jeton, backend). C'est là que se trouve le produit
  livrable, et il est proche.

Voir `ARCHITECTURE.md` pour le montage recommandé, `PLAN-CONSTRUCTION.md` pour l'ordre de
construction, et `PONT-TELEPHONE-PC.md` pour le protocole entre l'app et le PC.
