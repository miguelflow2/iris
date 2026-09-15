# Mode dehors — IRIS sur le téléphone, l'ordinateur resté à la maison

Écrit le 2026-09-13 pour Miguel, revu le 2026-09-14 (règle « lunettes d'abord », Android, en-têtes).
Pas à pas, sans supposer qu'on est administrateur système. Complète `docs/ACCES-DISTANT.md` (le
pourquoi du réseau privé) : ici, le comment, de bout en bout.

> **Règle « lunettes d'abord » (Miguel, 2026-09-13).** VELA vend des lunettes ; IRIS est la
> technologie qu'elles contiennent. Toute fonction qui capte (voir, écouter) ou qui agit exige des
> lunettes VELA **présentes** : vues par l'ordinateur (Bluetooth ou micro des lunettes), ou attestées
> par un téléphone qui leur est connecté. Sans lunettes, ces fonctions répondent « Cette fonction marche
> avec les lunettes VELA ». Le chat offre un **aperçu de 10 messages écrits au total** pour
> l'installation, pas plus. Consulter et effacer ses données, le mode invité, les zones sans mémoire,
> les réglages et le verrouillage à distance restent accessibles sans lunettes. C'est un verrou
> logiciel : il s'applique à l'application IRIS, pas au matériel.

**Le montage en une phrase.** L'ordinateur de la maison fait tourner IRIS (le cerveau, la mémoire,
les consentements) ; le téléphone ouvre la page `https://<machine>.ts.net/m` à travers le réseau privé
Tailscale ; les lunettes passent leur son par le Bluetooth audio du téléphone ; et leur **présence** est
prouvée à l'ordinateur par le téléphone : sur Android, par la page elle-même (Chrome, Bluetooth web) ;
sur iPhone, par l'app IRIS native, parce que Safari n'a pas de Bluetooth web. Rien n'est publié sur
Internet et aucun port n'est ouvert sur la box.

```
lunettes ──Bluetooth audio──────────> téléphone ──Tailscale──> ordinateur (IRIS)
   micro et haut-parleur                 page /m (ou app IRIS)    mémoire, vision, moteur,
lunettes ──Bluetooth basse énergie──> téléphone                  brouillons, alertes,
   présence seulement (Android : page /m ; iPhone : app IRIS)    présence des lunettes
```

---

## 1. Sur l'ordinateur, une seule fois

1. **Ouvrez IRIS** et laissez-la ouverte. Si l'ordinateur se met en veille, IRIS ne répond plus :
   réglez la mise en veille de Windows sur « Jamais » quand il est branché (Paramètres › Système ›
   Alimentation).
2. **Posez un mot de passe** : IRIS › Profil › Compte et sécurité. C'est la serrure de tout le reste ;
   le script de l'étape 4 refuse de publier sans lui.
3. **Activez l'accès téléphone** au même endroit. Ce réglage fige le port (8765) et garde le même
   jeton d'un démarrage à l'autre ; sans lui, le tunnel pointerait dans le vide après un redémarrage.
4. **Installez et publiez le réseau privé.** PowerShell *en administrateur* (menu Démarrer, tapez
   `powershell`, clic droit, « Exécuter en tant qu'administrateur »), dans le dossier d'IRIS :
   ```powershell
   .\scripts\installer-tunnel.ps1 -Installer
   ```
   Fermez la console, ouvrez-en une nouvelle, puis :
   ```powershell
   tailscale up
   ```
   Le navigateur s'ouvre : connectez-vous ou créez le compte Tailscale. **C'est vous qui choisissez
   ce compte** ; mettez-y la double authentification.
5. **Deux interrupteurs dans la console Tailscale** (https://login.tailscale.com/admin/dns) :
   *MagicDNS*, puis *HTTPS Certificates*. Sans le second, pas de `https://`, donc pas de micro dans
   Safari et pas de Bluetooth web dans Chrome.
6. **Publiez IRIS sur le réseau privé :**
   ```powershell
   .\scripts\installer-tunnel.ps1 -Servir
   ```
   Le script affiche l'adresse finale, du genre `https://bureau.tail1234.ts.net/m`. Notez-la.
   `.\scripts\installer-tunnel.ps1` sans option ne change rien : il vérifie et dit ce qui bloque.

## 2. Sur le téléphone, une seule fois

### 2.1 Pour tous les téléphones

1. **Installez l'application Tailscale** (App Store ou Play Store), connectez-vous avec **le même
   compte**, et laissez l'interrupteur activé.
2. **Ouvrez l'adresse notée** : `https://<machine>.ts.net/m`. N'ajoutez **jamais** `?token=…` : une
   adresse finit dans l'historique et dans les captures d'écran ; le mot de passe suffit.
3. **Entrez le mot de passe d'IRIS.** La session dure 30 jours sur ce téléphone.
4. **Autorisez le micro et la reconnaissance vocale** à la première pression sur « Appuyez pour
   parler », l'appareil photo à la première photo, et la position seulement si vous utilisez le
   guidage ou les zones sans mémoire.

### 2.2 iPhone

- **Dehors, la voie prévue est l'app IRIS native** (`mobile-ios/`) : elle se connecte aux lunettes
  (CoreBluetooth), atteste leur présence à l'ordinateur toutes les 60 secondes et retire l'attestation
  à la déconnexion. **État au 2026-09-14 : son code est écrit mais n'a jamais été compilé ni installé
  sur un iPhone** (voir `mobile-ios/COMPILER-SUR-MAC.md`). Tant qu'elle n'est pas livrée, rien sur
  iPhone ne peut attester les lunettes.
- **Dans Safari, la page `/m` ne peut pas se connecter aux lunettes** : Safari n'a pas de Bluetooth
  web. Les fonctions qui captent ou agissent n'y marchent que si les lunettes sont reliées à
  **l'ordinateur**, donc à la maison, à portée de lui (une dizaine de mètres). La page le dit.
- Pour poser la page sur l'écran d'accueil : Safari (pas Chrome : sur iPhone, seul Safari sait le
  faire) › Partager › « Sur l'écran d'accueil » › Ajouter. L'icône a sa propre mémoire, séparée de
  Safari : **il faudra entrer le mot de passe une seconde fois** en l'ouvrant la première fois.
- Micro ou reconnaissance refusés : Réglages › Safari › Micro, et Réglages › Confidentialité et
  sécurité › Reconnaissance vocale.

### 2.3 Android

1. Ouvrez l'adresse **dans Chrome**, en `https://` (le Bluetooth web n'est permis qu'à une page
   sécurisée).
2. Menu de Chrome › « Installer l'application » (ou « Ajouter à l'écran d'accueil »).
3. **Mes lunettes › Connecter mes lunettes** : Chrome affiche la liste des lunettes à proximité ;
   choisissez les vôtres. Autorisez « Appareils à proximité » (ou la localisation, sur certains
   Android) si Chrome le demande.
4. **Gardez la page ouverte** : elle confirme la présence des lunettes à l'ordinateur chaque minute ;
   l'ordinateur ne croit plus une confirmation de plus de 150 secondes. Fermée ou longtemps en
   arrière-plan, la page cesse de le prouver.

Ce que cette connexion ne fait **pas** : elle ne transporte ni le son (Bluetooth audio du téléphone) ni
les images (la commande photo des lunettes n'est pas pilotée depuis le téléphone). Elle prouve seulement
que les lunettes sont là. Non essayée sur un vrai Android avec les vraies lunettes (section 10).

## 3. Relier le son des lunettes au téléphone (audio Bluetooth)

1. **Ce que cela coupe à la maison.** Des écouteurs Bluetooth ne se relient en général qu'à un appareil
   à la fois pour l'audio ; la connexion simultanée à deux appareils (« multipoint ») n'est **pas
   confirmée** pour ces lunettes. Relier les lunettes au téléphone les retire donc souvent de
   l'ordinateur : l'ordinateur ne les voit plus, et, sur iPhone dans Safari, les fonctions des lunettes
   répondent « Cette fonction marche avec les lunettes VELA ». Sur Android, la page les atteste elle-même
   (section 2.3). À l'inverse, connecter les lunettes à la page Android peut couper leur liaison basse
   énergie avec l'ordinateur : déconnectez-les de la page avant d'utiliser IRIS sur l'ordinateur.
2. Mettez les lunettes en mode appairage (geste décrit par la notice du fabricant ; il n'est pas
   documenté ici).
3. Réglages du téléphone › Bluetooth › touchez les lunettes.
4. Vérifiez la sortie audio (iPhone : Centre de contrôle › carré Musique › icône AirPlay › les lunettes).
   La voix d'IRIS (synthèse du téléphone) sort alors dans les lunettes.
5. Le micro des lunettes sert à la dictée **si le téléphone le choisit** comme entrée (en général pour
   des écouteurs mains libres ; non vérifié avec ces lunettes).

**Caméra et boutons.** La commande photo des lunettes n'est **pas encore confirmée sur le vrai
matériel** : l'ordinateur la refuse (réponse 409 avec le message exact). La caméra des lunettes arrive ;
en attendant, quand les lunettes sont présentes, la photo à décrire, le reçu, le prix et la vision
partagée utilisent la caméra **du téléphone**, en secours, et l'écran le dit. Les boutons des lunettes ne
sont lus par aucune page du téléphone.

## 4. À chaque sortie

- **Tailscale activé** sur le téléphone (il se met parfois en veille : rouvrez l'application).
- **Android** : ouvrez IRIS, vérifiez « Mes lunettes » (connectées à ce téléphone, présence confirmée).
  **iPhone** : l'app IRIS, quand elle sera livrée ; dans Safari, seules les fonctions sans lunettes et
  l'aperçu du chat marchent loin de l'ordinateur.
- **Gardez IRIS à l'écran.** Réglages de la page › « Garder l'écran allumé » (section 6).
- Regardez la pastille en haut à droite : « Connectée au PC · 240 ms » (aller-retour mesuré à
  l'instant) ou « Hors ligne », avec la raison possible écrite en clair.

## 5. Ce qui marche dehors, fonction par fonction

« Lunettes » : lunettes VELA présentes, vues par l'ordinateur ou attestées par un téléphone (Android :
page `/m` ; iPhone : app IRIS). « Ordinateur » : l'ordinateur allumé, IRIS ouverte, joignable par
Tailscale. Les délais affichés sont **mesurés sur le téléphone**, jamais promis.

| Fonction | Lunettes requises | Réseau requis | Source du son ou de l'image | À savoir |
|---|---|---|---|---|
| Parler à IRIS ou lui écrire | **Non** pour un aperçu de 10 messages au total ; **oui** ensuite | Ordinateur ; moteur VELA selon la demande | Dictée du téléphone | Le compte restant s'affiche sous le champ quand les lunettes manquent. |
| Décrire une photo (devant moi, lire, billets, objet, couleur, personnes, affichage) | **Oui** | Ordinateur ; moteur VELA pour certains modes, avec le consentement « Images » | Caméra du téléphone, en secours | Photo réduite à 1 280 px sur le téléphone, non gardée par IRIS. Description d'une photo, pas une surveillance en direct. |
| « Où ai-je posé ? » | **Oui** | Ordinateur | Souvenirs datés de l'ordinateur | Ne sait rien d'un objet jamais décrit. |
| Sous-titres géants | **Oui, vues par l'ordinateur** | Ordinateur | **Micro de l'ordinateur**, à la maison | Ne transcrit pas votre conversation dehors. Refusé (409) quand les lunettes ne sont attestées que par le téléphone : l'ordinateur n'ouvre pas le micro d'une maison où vous n'êtes pas (constat du 2026-09-14). Confirmation avant d'ouvrir le micro ; arrêt quand la page quitte l'écran. |
| Alertes sonores (affichage) | Non pour recevoir ; les activer se fait sur l'ordinateur, lunettes vues par l'ordinateur | Ordinateur, page ouverte à l'écran | Micro de l'ordinateur, à la maison | Ne remplace pas un avertisseur homologué. Lunettes attestées par le téléphone seulement : l'ordinateur n'écoute pas. |
| Textos et appels préparés par IRIS | Non | Ordinateur | — | C'est vous qui envoyez, depuis Messages ou le composeur. |
| Guidage à pied | **Oui** (vérifié par la page) | Internet vers OpenStreetMap ; ordinateur pour la présence | GPS du téléphone | Position envoyée à OpenStreetMap, jamais à IRIS. Service public gratuit, sans engagement de service : il peut limiter ou refuser les demandes. |
| Zones sans mémoire | Non | Ordinateur | GPS du téléphone, comparé sur le téléphone | Seul l'identifiant de la zone part à l'ordinateur. |
| Vision partagée | **Oui** | Ordinateur (création) et relais VELA (images) | Caméra du téléphone, en secours | Rien n'est enregistré ; 3 spectateurs au plus. |
| Reçus : analyser | **Oui** | Ordinateur ; moteur VELA seulement avec « Images » | Caméra du téléphone, en secours | Montants contrôlés, jamais inventés. |
| Reçus : consulter, corriger, effacer, exporter | Non | Ordinateur | — | Ce sont vos données. |
| Comparer un prix | **Oui** | Ordinateur et une clé de recherche web configurée | Caméra du téléphone, en secours | Sans clé, l'ordinateur répond 409 et la page affiche pourquoi. |
| Interprète | **Oui** | Ordinateur (traduction) ; reconnaissance vocale du téléphone, souvent en ligne | Micro du téléphone | N'ouvre jamais le micro de l'ordinateur. L'interlocuteur n'a rien accepté : prévenez-le. |
| Mode invité | Non | Ordinateur | — | |
| Réglages de la page | Non | Ordinateur | — | |
| Verrouillage à distance | Non | Relais VELA (page « Verrouiller IRIS à distance ») | — | Sert justement quand le téléphone ou les lunettes sont perdus. |

**Exige dans tous les cas** : l'ordinateur allumé et hors veille, IRIS ouverte, Internet des deux
côtés, Tailscale actif sur le téléphone, la page IRIS à l'écran.

**Ne marche pas dehors :**
- Les **sous-titres de votre conversation** : les sous-titres transcrivent le micro de l'ordinateur,
  donc la pièce où il se trouve.
- Sur iPhone dans Safari, toutes les fonctions marquées « Oui » ci-dessus, dès que les lunettes ne sont
  plus reliées à l'ordinateur.
- Recevoir quoi que ce soit page fermée, en arrière-plan ou écran verrouillé ; aucune notification.
- La vibration des alertes : Safari sur iPhone ne permet pas aux pages web de vibrer.
- Une réponse en un temps garanti : le trajet est téléphone › réseau cellulaire › Tailscale (parfois
  par un serveur relais de Tailscale quand la liaison directe échoue) › ordinateur › parfois le moteur
  VELA › retour.

## 6. Pourquoi l'écran doit rester allumé

iOS suspend une page web quelques secondes après qu'elle quitte l'écran (autre application, écran
verrouillé) ; Android le fait plus tard, mais le fait aussi. Concrètement :
- la liaison en direct avec l'ordinateur (WebSocket) est coupée : **les alertes sonores, les
  sous-titres, les rappels et les messages de vision partagée n'arrivent plus** ;
- sur Android, la page cesse de confirmer la présence des lunettes : après environ deux minutes et
  demie, l'ordinateur les considère absentes ;
- des sous-titres démarrés depuis la page sont arrêtés dès qu'elle quitte l'écran, pour que le micro
  de la maison ne reste pas ouvert sans vous ;
- la voix du téléphone s'interrompt, et une réponse arrivée pendant ce temps ne sera lue qu'au retour ;
- il n'existe pas de notification pour prendre le relais : les notifications web exigent un service
  d'envoi côté VELA qui **n'est pas construit**.

Au retour à l'écran, la page se reconnecte d'elle-même et vérifie les brouillons en attente. D'où le
réglage « Garder l'écran allumé » (verrou d'écran du navigateur). Il coûte de la batterie. S'il est
refusé par le téléphone, la page le dit : réglez alors le verrouillage automatique du téléphone sur
« Jamais » pendant l'usage.

## 7. Vérifier que tout marche vraiment (quatre essais)

1. **À la maison, en WiFi** : ouvrez l'adresse ; le cadenas apparaît ; le mot de passe est demandé ;
   la pastille dit « Connectée au PC ».
2. **WiFi coupé** (données cellulaires seulement) : rouvrez la page. Si la pastille reste verte, le
   trajet par Internet fonctionne sans port ouvert. C'est le seul essai qui prouve le mode dehors.
3. **Lunettes** : sans lunettes, « Décrire une photo » doit afficher « Cette fonction marche avec les
   lunettes VELA » **sans ouvrir l'appareil photo**. Sur Android, « Mes lunettes › Connecter » puis la
   même tuile doit s'ouvrir.
4. **Parlez** : « Quelle heure est-il ? ». La réponse doit sortir dans les lunettes, avec son délai
   mesuré affiché sous la bulle (ou, sans lunettes, le compte de l'aperçu doit baisser d'un message).

## 8. Dépannage

| La page affiche | Cause probable | Quoi faire |
|---|---|---|
| « Hors ligne » | ordinateur éteint ou en veille, IRIS fermée, pas d'Internet, Tailscale désactivé sur le téléphone | vérifier dans cet ordre ; « Réessayer » |
| « Cette fonction marche avec les lunettes VELA » | lunettes ni vues par l'ordinateur, ni attestées par un téléphone | Android : Mes lunettes › Connecter ; iPhone : lunettes reliées à l'ordinateur (l'app IRIS n'est pas encore disponible) |
| « Aperçu sans lunettes terminé » | les 10 messages d'aperçu de l'installation sont utilisés | connecter les lunettes |
| « Le navigateur demande un geste » (Android) | la liste Bluetooth s'est ouverte trop tard après le toucher | toucher de nouveau « Connecter mes lunettes » |
| « Reconnexion automatique suspendue » (Android) | l'ordinateur voit déjà les lunettes | normal à la maison ; « Connecter mes lunettes » pour les reprendre sur le téléphone |
| « Voix indisponible — écrivez » | micro ou reconnaissance refusés ; adresse en `http://` ; reconnaissance non proposée dans une page posée sur l'écran d'accueil (non vérifié) | autoriser dans les réglages ; utiliser l'adresse `https://` ; essayer la même adresse dans le navigateur |
| « Session expirée » | 30 jours passés, ou mot de passe changé (révoque tout) | entrer le mot de passe |
| « IRIS est verrouillée » | verrouillage sur place ou à distance | mot de passe du propriétaire, sur l'écran affiché |
| « Liaison en direct coupée » | le tunnel a fermé le WebSocket | rien : nouvel essai automatique ; les demandes marchent encore |
| « IRIS ne s'ouvre pas à l'intérieur d'une autre page » | la page a été chargée dans un cadre d'un autre site | ouvrir l'adresse directement dans le navigateur |
| Pas de son dans les lunettes | sortie audio restée sur le téléphone | réglages audio ou Centre de contrôle › AirPlay › lunettes |

## 9. Confidentialité, dit franchement

- **La dictée** utilise la reconnaissance vocale intégrée au téléphone : selon ses réglages, vos phrases
  peuvent être envoyées aux serveurs du fabricant du téléphone pour être reconnues. La page le dit (sans
  nommer de fournisseur). Pour l'éviter, écrivez.
- **Les photos** sont réduites sur le téléphone, envoyées à votre ordinateur, et décrites localement
  quand le mode le permet (lecture, couleur, affichage), sinon par le moteur VELA **seulement avec
  votre consentement** « Images » (Confidentialité, sur l'ordinateur). IRIS ne garde pas la photo.
- **Le guidage** envoie la position du téléphone et la destination aux services publics
  d'OpenStreetMap, jamais à IRIS. Depuis le 2026-09-14, aucun en-tête Referer n'accompagne ces
  requêtes : le nom de votre machine (`.ts.net`) n'est plus transmis avec vos coordonnées.
  OpenStreetMap peut garder l'adresse Internet du téléphone dans ses journaux techniques.
  **Avant une mise en marché à grande échelle** : ces services bénévoles limitent à une requête par
  seconde pour l'ensemble des utilisateurs d'une application, sans engagement de service, et aucun code
  dans les téléphones ne peut tenir cette limite globale. Il faut une instance propre ou un fournisseur
  de données OSM sous contrat. Ils se branchent sans changer le code, par deux réglages de l'ordinateur
  (`PATCH /api/settings`) : `guidage_recherche` (adresse d'un service compatible Nominatim) et
  `guidage_itineraire` (préfixe d'un service compatible OSRM à pied, auquel la page ajoute
  `lon,lat;lon,lat`). Adresses en https seulement ; la politique de contenu de `/m` suit ; l'accord
  est redemandé sur le téléphone quand le service change. Vides : services publics (état actuel).
- **La page Android** envoie à l'ordinateur le nom et l'identifiant Bluetooth des lunettes, et leur
  niveau de batterie quand elles le donnent ; rien d'autre.
- **Tailscale** chiffre le trajet entre le téléphone et l'ordinateur ; il voit quels appareils se
  parlent, pas ce qu'ils se disent. Le nom de la machine (`bureau.tail1234.ts.net`) figure dans les
  registres publics de certificats.
- **Un téléphone perdu** garde sa session 30 jours : retirez-le dans la console Tailscale et changez le
  mot de passe d'IRIS (cela déconnecte tous les appareils), ou verrouillez IRIS à distance.

## 10. Ce qui a été vérifié, et ce qui ne l'a pas été

**Prouvé par tests automatiques** (`backend/tests/test_mobile.py`, sans téléphone ni lunettes) : la
composition de la page, la connexion et la session, le verrouillage, la syntaxe de tous les scripts de
la page, l'ordre de chargement (lunettes.js avant les modules), le comportement de `api.js` et de
`lunettes.js` face à un faux Bluetooth et un faux ordinateur (filtres de la liste, attestation, retrait
à la déconnexion, arrêt après un refus 403, liste ouverte sans attente réseau), l'absence de nom de
fournisseur et de formulation absolue dans les textes.

**En-têtes de sécurité du document `/m`** (en place depuis le 2026-09-14) : l'ordinateur pose sur `/m`
la politique de contenu avec `frame-ancestors 'none'`, `X-Frame-Options: DENY`, `Permissions-Policy` et
`nosniff`, fabriqués par `routes_mobile` (`reponse_page`) et appelés par `backend/iris/main.py` ; `/sw.js`
et le manifeste reçoivent aussi les leurs. Le test strict `test_la_page_m_porte_les_entetes` le vérifie
sur la page réellement servie. La balise de politique de la page et son refus de démarrer dans un cadre
restent en place en second rideau : si `routes_mobile` ne se chargeait pas, `main.py` servirait la page
sans ces en-têtes (il le journalise) plutôt que de la faire disparaître.

**Rien de ce guide n'a été essayé sur un vrai téléphone avec les vraies lunettes.** Restent à
constater sur place :
- la connexion Bluetooth web d'un vrai Chrome Android aux lunettes, l'attestation toutes les minutes,
  et le délai du geste avant l'ouverture de la liste Bluetooth ;
- la cohabitation d'une connexion basse énergie téléphone et ordinateur avec ces lunettes ;
- l'app IRIS pour iPhone (jamais compilée) ;
- la dictée dans une page posée sur l'écran d'accueil ;
- le verrou d'écran dans une page posée sur l'écran d'accueil (il a longtemps été ignoré par iOS
  dans ce mode) ;
- l'arrêt des sous-titres par une requête envoyée pendant la suspension de la page ;
- le WebSocket à travers `tailscale serve` sur réseau cellulaire ;
- l'agent de service (coquille hors ligne) sur iPhone ;
- le choix du micro des lunettes comme entrée par le téléphone, et le multipoint Bluetooth.
