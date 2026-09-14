# Vidéos de preuve — guide de tournage

**Pour :** Miguel · **Établi le :** 13 septembre 2026
**Version de référence :** IRIS 0.1.0, l'installateur publié (GitHub Releases, bouton « Télécharger » du site)
**Pourquoi ce document :** l'audit externe du 13 septembre donne 4/10 à la *preuve produit*. La question de
l'acheteur est simple : « est-ce que ça marche vraiment aujourd'hui, ou c'est une vision ? ». Ces six vidéos
y répondent en **montrant**, pas en affirmant.

> **Règle de ce document.** Une vidéo de preuve montre ce que fait la version publiée, sur une vraie machine,
> en temps réel. Quand ce n'est pas possible aujourd'hui, la fiche le dit et propose quoi filmer à la place —
> jamais de maquillage. En cas de doute entre impressionner et être exact : être exact.

---

## Sommaire

0. [Ce qu'on peut filmer aujourd'hui, et ce qu'on ne peut pas](#0-ce-quon-peut-filmer-aujourdhui)
1. [Les règles d'or (valables pour les six vidéos)](#1-les-règles-dor)
2. [Le texte à mettre sous chaque vidéo](#2-le-texte-sous-chaque-vidéo)
3. [Vidéo 1 — Contrôle du PC : « Dis-moi Iris, ouvre Chrome »](#3-vidéo-1--dis-moi-iris-ouvre-chrome)
4. [Vidéo 2 — Vision : « Qu'est-ce qu'il y a devant moi ? »](#4-vidéo-2--quest-ce-quil-y-a-devant-moi-)
5. [Vidéo 3 — Photo avec le voyant des lunettes](#5-vidéo-3--photo-avec-le-voyant-des-lunettes)
6. [Vidéo 4 — Confidentialité : capture → registre → fichier local → vérification](#6-vidéo-4--confidentialité)
7. [Vidéo 5 — Hors ligne : Internet coupé](#7-vidéo-5--hors-ligne)
8. [Vidéo 6 — Les limites : ce qu'IRIS ne sait pas encore faire](#8-vidéo-6--les-limites)
9. [Sous-titres et accessibilité](#9-sous-titres-et-accessibilité)
10. [Formats : horizontal 16:9 et vertical 9:16](#10-formats)
11. [Où publier sur le site](#11-où-publier-sur-le-site)
12. [Journal des prises et liste du jour de tournage](#12-journal-des-prises-et-liste-du-jour-de-tournage)

---

## 0. Ce qu'on peut filmer aujourd'hui

**Sources lues :** code de la version 0.1.0 (`git show 7df2105:backend/iris/...`), contenu de l'installateur
construit le 12 septembre (`release/win-unpacked`), `docs/ETAT-IRIS-2026-09-06.md`,
`deploy/FEUILLE-DE-ROUTE-VENDABLE.html`. **Le code dit ce qui devrait marcher ; seul un essai réel dit ce qui
marche.** Chaque fiche contient donc une case « prérequis techniques à vérifier avant de filmer ».

| # | Vidéo | Filmable avec 0.1.0 ? | Statut à afficher | Pourquoi (d'après le code) |
|---|---|---|---|---|
| 1 | « Dis-moi Iris, ouvre Chrome » | **Oui**, après vérification | Disponible | « Ouvre » + une application installée est reconnu sur l'ordinateur, sans modèle d'IA ni réseau. Le modèle d'écoute français et la voix française locale sont bien dans l'installateur. |
| 2 | « Qu'est-ce qu'il y a devant moi ? » | **Non, pas telle quelle** | En test | 0.1.0 ne sait pas décrire une scène sur l'ordinateur, et la caméra des lunettes n'est pas pilotée (voir 3). La seule lecture locale est celle du texte affiché à l'écran. |
| 3 | Photo + voyant | **Non, pas par IRIS** | En test | L'outil photo de 0.1.0 refuse volontairement d'écrire dans la puce des lunettes tant que le format des trames caméra n'est pas confirmé sur le vrai matériel. |
| 4 | Registre de confidentialité | **Oui** | Disponible | Chaîne SHA-256, « Vérifier l'intégrité », export JSON et CSV, purge : dans le code et dans l'interface de 0.1.0. |
| 5 | Hors ligne | **Oui, pour une liste courte** | Disponible (lignes vérifiées seulement) | Écoute, voix française et commandes simples tournent sur l'ordinateur. Les questions ouvertes, non (sans modèle d'IA installé localement). |
| 6 | Limites | **Oui** | En test / Prévu, selon la limite | La vidéo la plus crédible des six, et elle est prête à tourner. |

**Ordre de tournage conseillé :** 6 → 4 → 1 → 5. Les vidéos 2 et 3 attendent que la caméra soit prouvée.

> **Attention — quelle version filmer.** Le commit `7df2105` ne contient pas deux fichiers que l'installateur
> 0.1.0 embarque pourtant (le module de voix locale et le module caméra) : l'installateur du 12 septembre a été
> construit depuis un dossier de travail qui avait des fichiers non commités. Conséquence : **la seule référence
> qui vaut pour une vidéo de preuve est l'installateur publié lui-même**, téléchargé depuis le bouton du site.
> Toute prise faite avec autre chose (version 0.2.0 en développement, lancement depuis le code source) porte
> l'étiquette « En test — version non publiée ».

> **Attention — une formule retenue à nuancer.** « Quand vous activez une fonction en ligne, IRIS vous montre
> ce qui part avant l'envoi. » D'après le code 0.1.0, IRIS demande un **consentement par type de donnée**
> avant tout envoi, montre un **aperçu avant envoi pour une capture d'écran jointe à la main**, puis
> **inscrit chaque envoi au registre**. Elle n'affiche pas un aperçu de chaque demande avant qu'elle parte.
> Ne pas dire cette phrase dans une vidéo tant que l'image ne la montre pas exactement.

---

## 1. Les règles d'or

### Ce qui DOIT être vrai dans chaque vidéo

1. **Version publiée, visible.** Au début, ouvrir « À propos » dans IRIS : 0.1.0 à l'écran.
2. **Réglages honnêtes.** L'échappatoire de démonstration « sans lunettes » et le « plan de démonstration »
   sont désactivés (ces réglages n'apparaissent pas dans l'interface : faire vérifier par l'équipe
   application avant la prise). Aucune clé personnelle de fournisseur si la vidéo parle du service IRIS en ligne.
3. **Plan-séquence au moment clé.** De la dernière syllabe de la demande jusqu'au résultat visible : aucune
   coupe, aucun fondu, aucun changement d'angle qui cache du temps. Couper *avant* et *après* : permis.
4. **Le temps se voit.** Un chronomètre de téléphone posé dans le champ, démarré avant la phrase, ou l'horloge
   de Windows avec les secondes (Windows 11 : Paramètres › Heure et langue › Date et heure, option d'affichage
   des secondes si votre version la propose).
5. **Deux sources synchronisées.**
   - (a) un téléphone sur trépied qui filme la personne, les lunettes sur la tête, les mains et l'écran ;
   - (b) un enregistrement de tout l'écran (OBS Studio convient ; la Xbox Game Bar n'enregistre qu'une
     fenêtre et raterait l'ouverture de Chrome).
   - Côte à côte ou en incrustation, calées sur un clap (claquement de mains visible et audible au début).
6. **Le vrai son.** La phrase et la réponse d'IRIS s'entendent telles quelles. Pas de musique par-dessus le
   moment clé. Une voix hors champ explicative est permise avant et après, jamais par-dessus IRIS.
7. **Les mains loin du clavier et de la souris** pendant toute commande vocale.
8. **La latence reste.** Si IRIS met 9 secondes, la vidéo dure 9 secondes de plus. Le temps mesuré est écrit
   sous la vidéo.
9. **Toutes les prises sont gardées** (journal des prises, section 12). Sous la vidéo : « Prises : n,
   réussies : m ».
10. **Le fichier original est conservé** avec son empreinte, calculée le jour même dans PowerShell :
    `Get-FileHash .\prise-01.mp4 -Algorithm SHA256`. On peut le remettre sur demande (presse, testeur, client
    sceptique). C'est la même logique que le registre : la preuve, pas la promesse.

### Ce qu'il ne faut JAMAIS faire

- **Monter une réponse** : coller la réponse d'une prise sur la question d'une autre, doubler la voix d'IRIS,
  retaper un texte dans la fenêtre.
- **Accélérer, ralentir, couper ou « resserrer » l'attente** entre la demande et le résultat.
- **Rejouer une prise en cachant l'échec.** Refaire une prise est permis ; cacher qu'elle a échoué ne l'est
  pas. Si 3 prises sur 5 ont échoué, on l'écrit.
- **Préparer le résultat en coulisse** : application déjà ouverte en réduit, routine qui simule, quelqu'un hors
  champ au clavier, contrôle à distance, raccourci clavier.
- **Filmer la version de développement** en laissant croire que c'est la version publiée.
- **Utiliser un clip d'ambiance du site** (`site/assets/videos/`, par exemple `vela-camera-led.mp4`) comme
  preuve d'IRIS : ce sont des images du matériel, dont l'origine et les droits restent à confirmer.
- **Montrer un nom de fournisseur d'IA ou de voix** : Réglages › Moteurs IA, écran de test des moteurs, journaux
  techniques, et même certaines lignes du registre (voir vidéo 4). Le masque de marque vaut aussi pour les vidéos.
- **Dire ou écrire** « instantané », « toujours », « tout », « entièrement », « rien ne part » sans condition.
- **Filmer une personne** qui n'a pas signé d'autorisation, ou des visages reconnaissables dans un lieu public.

### Préparer l'écran

- Mode « Ne pas déranger » activé : aucune notification pendant la prise.
- Courriel, messageries et onglets personnels fermés ; barre de favoris masquée ; aucun mot de passe, adresse ou
  numéro de téléphone visible.
- Fond d'écran neutre, icônes du bureau masquées.
- Fenêtre IRIS lisible (agrandir l'interface au besoin), placée là où les sous-titres ne la couvriront pas.

### Mentionner une limite à l'écran

- Un carton simple (fond sombre, texte clair), 3 à 4 secondes, **pendant** ou **juste après** le moment
  concerné — jamais en petits caractères à la toute fin.
- Toujours avec l'étiquette de statut, mêmes libellés que sur le site : **Disponible**, **En test**, **Prévu**.
- Formules types (les chiffres sont des exemples, à remplacer par la mesure réelle) :
  - « Ici, la voix d'IRIS sort des haut-parleurs de l'ordinateur, pas des lunettes. »
  - « Temps mesuré : 4,2 s entre la fin de la phrase et l'ouverture. »
  - « Réussi à la 2ᵉ prise sur 3. »
  - « Sans ordinateur allumé à portée, les lunettes ne pilotent pas IRIS aujourd'hui. »
  - « En test — pas dans la version publiée 0.1.0. »

---

## 2. Le texte sous chaque vidéo

À copier sous chaque vidéo publiée (site et réseaux), rempli avec les valeurs réelles :

```
Vidéo réelle, sans accélération ni coupe entre la demande et le résultat.
Filmée le [JJ mois AAAA] avec IRIS 0.1.0 (installateur public), sur [ordinateur], Windows [10/11].
Lunettes VELA : [connectées en Bluetooth / non utilisées].
Micro utilisé : [lunettes / ordinateur]. Voix d'IRIS : [lunettes / haut-parleurs de l'ordinateur].
Internet : [branché / coupé].
Temps mesuré entre la fin de la phrase et le résultat : [x s].
Prises : [n], réussies : [m].
Statut : [Disponible / En test / Prévu].
Ce que cette vidéo ne montre pas : [une phrase].
Fichier original non monté disponible sur demande : contact@velaglass.ca
```

---

## 3. Vidéo 1 — « Dis-moi Iris, ouvre Chrome »

| | |
|---|---|
| **Objectif** | Prouver qu'une phrase dite avec les lunettes sur la tête ouvre vraiment une application sur l'ordinateur, en temps réel. |
| **Statut à afficher** | **Disponible** — seulement si tous les prérequis passent. |
| **Durée** | 25 à 40 s |
| **Matériel** | Ordinateur Windows 10/11, Chrome installé et fermé · lunettes VELA chargées et appairées · téléphone sur trépied (1080p) · OBS Studio · 2ᵉ téléphone en chronomètre · pièce calme |

### Prérequis techniques à vérifier avant de filmer

- [ ] IRIS installé depuis le bouton « Télécharger » du site ; « À propos » affiche **0.1.0**.
- [ ] Mot d'activation réglé exactement sur **« Dis-moi Iris »** (constat du 6 septembre : un réglage
      « Iris » seul, avec une espace parasite, traînait sur le portable de démonstration).
- [ ] **Le micro utilisé est celui des lunettes.** Micro choisi dans IRIS = lunettes ; Windows › Son › Entrée =
      lunettes. Pour une preuve nette, désactiver le micro intégré de l'ordinateur le temps de la prise (et le
      réactiver après). Sinon, la vidéo prouve que l'ordinateur entend, pas les lunettes. (Constat du
      6 septembre : le micro réel était le plus souvent celui du portable.)
- [ ] **Savoir où sort la voix d'IRIS** : lunettes ou haut-parleurs de l'ordinateur ? L'écrire sous la vidéo.
      (Constat du 6 septembre : elle sortait du PC.) Rappel : le Bluetooth mains libres ne porte qu'un lien audio
      à la fois ; pendant que le micro des lunettes écoute, le son dans les lunettes baisse en qualité.
- [ ] « Contrôle de l'ordinateur » et commandes rapides activés (réglages par défaut de 0.1.0 : oui).
- [ ] **Verrou des lunettes vérifié** : lunettes éteintes, IRIS doit afficher « Connectez vos lunettes VELA
      pour parler à IRIS ». S'il n'apparaît pas, l'échappatoire de démonstration est probablement active.
- [ ] **10 essais hors caméra** de « Dis-moi Iris, ouvre Chrome » : noter le nombre de réussites (ex. 9 sur 10)
      et le temps minimum et maximum. Ces chiffres se publient. Sous 8 sur 10, ne pas publier sans le dire.
      Ne jamais publier le meilleur temps seul.

### Préparation

- Chrome vraiment fermé (barre des tâches et Gestionnaire des tâches : pas en réduit, pas en arrière-plan).
- Fenêtre IRIS ouverte sur la moitié droite de l'écran, fil de conversation visible.
- Chronomètre posé à côté de l'écran, dans le champ du téléphone qui filme.

### Plan par plan

| Plan | Temps | Image | Son / paroles |
|---|---|---|---|
| 1 | 0–4 s | Plan large : Miguel, lunettes sur la tête, écran visible, mains posées à plat sur la table. Carton : « Vidéo réelle · IRIS 0.1.0 · sans coupe ». | Clap des mains. |
| 2 | 4–10 s | Écran : « À propos » (0.1.0), puis Son › Entrée = lunettes. Coupe permise ici (avant le moment clé). | Miguel : « IRIS version 0.1.0. Le micro, ce sont les lunettes. » |
| **3 — clé, sans coupe** | 10–25 s | Côte à côte : caméra (visage, lunettes, mains, chronomètre) + écran. On voit le signal d'écoute, la phrase transcrite dans IRIS, Chrome qui s'ouvre. | Miguel démarre le chronomètre, repose la main et dit : **« Dis-moi Iris, ouvre Chrome. »** Réponse attendue, du type « J'ouvre Chrome. » |
| 4 | 25–32 s | Gros plan sur le chronomètre arrêté. | Miguel : « [x] secondes entre la fin de ma phrase et l'ouverture. » |
| 5 | 32–38 s | Carton final. | — |

**Option utile (même plan clé, 10 s de plus) :** « Dis-moi Iris, quelle heure est-il ? ». La réponse est
calculée sur l'ordinateur, et l'horloge visible permet à n'importe qui de vérifier.

### Phrases exactes

- **« Dis-moi Iris, ouvre Chrome. »**
- (option) **« Dis-moi Iris, quelle heure est-il ? »**
- Si la version filmée demande une pause après « Dis-moi Iris » (signal d'écoute), la respecter et la laisser
  visible. Ne pas la couper.

### Ce qui DOIT être visible

Lunettes sur la tête · mains loin du clavier et de la souris · chronomètre ou horloge à secondes · fenêtre IRIS
avec la phrase transcrite · Chrome qui s'ouvre · aucune coupe entre la phrase et le résultat.

### Jamais

Chrome déjà ouvert en réduit · raccourci clavier · coupe dans l'attente · réponse d'IRIS doublée · routine
préenregistrée · version de développement · le mot « instantané ».

### Cartons de limite (selon ce que les essais ont montré)

- « Voix d'IRIS : haut-parleurs de l'ordinateur. » (si c'est le cas)
- « Les demandes simples (ouvrir une application, l'heure) sont reconnues sur l'ordinateur. Les demandes
  ouvertes passent par un modèle d'IA et prennent plus de temps. »
- Carton final : « Disponible dans IRIS 0.1.0, pour Windows 10 et 11. Les lunettes ont besoin de l'ordinateur
  allumé, à portée Bluetooth. »

---

## 4. Vidéo 2 — « Qu'est-ce qu'il y a devant moi ? »

| | |
|---|---|
| **Objectif demandé** | Montrer IRIS qui décrit ce que la personne a devant elle. |
| **Constat** | **Impossible à filmer comme preuve avec 0.1.0.** |
| **Statut à afficher** | **En test** |

**Pourquoi, d'après le code :**

1. la caméra des lunettes n'est pas pilotée par la version publiée (voir vidéo 3) ;
2. 0.1.0 n'embarque aucun modèle capable de décrire une image sur l'ordinateur : la « reconnaissance » prévue
   pour les photos des lunettes se limite à préparer l'image ;
3. la politique de confidentialité (§8) dit aujourd'hui que les photos des lunettes « et leur analyse restent
   sur votre ordinateur ». Une description faite par le service IRIS en ligne contredirait ce texte : il faudrait
   d'abord décider, puis corriger la politique et le site, **avant** de filmer.

### Ce qu'on peut filmer à la place, maintenant — en le disant

**Option A — « IRIS lit l'écran » (usage accessibilité).**
- Ce que c'est : IRIS lit mot pour mot le texte affiché à l'écran, grâce à une reconnaissance de caractères qui
  tourne sur l'ordinateur. **Ce n'est pas de la vision du monde réel.**
- Titre obligatoire : « IRIS lit l'écran » — jamais « vision ».
- Prérequis : la demande passe par un modèle d'IA qui décide de lancer la lecture (le texte, lui, est lu sur
  l'ordinateur). Vérifier que ça fonctionne avec le plan Gratuit et le service IRIS en ligne de la version
  publiée. Sinon : statut « En test », et on ne tourne pas.
- Phrase : **« Dis-moi Iris, lis-moi l'écran. »** Écran préparé : un document court et daté
  (« Essai du [date], [heure] »), pour que chacun compare ce qu'IRIS lit à ce qui est affiché.
- Carton : « IRIS lit le texte de l'écran. Elle ne voit pas encore ce qui est devant vous : la caméra des
  lunettes est En test. »

**Option B — photo prise au téléphone, jointe à IRIS.**
- Seulement si la fenêtre de conversation de 0.1.0 permet de joindre une image (à vérifier) et si le service
  IRIS en ligne répond.
- **L'image quitte l'ordinateur** vers le service IRIS en ligne, après le consentement « Images jointes » : le
  montrer à l'écran, puis montrer la ligne correspondante dans le registre.
- Carton obligatoire : « Photo prise au téléphone, pas avec les lunettes. Analyse faite par le service IRIS en
  ligne : l'image a quitté l'ordinateur, avec votre accord, et le registre l'a inscrit. »
- Statut : En test. Ne pas tourner tant que les textes du site peuvent laisser croire que toute analyse d'image
  reste sur l'ordinateur.

### Prérequis pour la vraie vidéo 2 (plus tard)

- [ ] Vidéo 3 réussie (photo des lunettes prouvée sur la paire vendue).
- [ ] Décision écrite : où se fait l'analyse de la scène (sur l'ordinateur, ou par le service IRIS en ligne) ;
      politique de confidentialité et site alignés sur cette décision.
- [ ] Fonction présente dans une version **publiée**.
- [ ] 10 essais hors caméra sur des scènes variées ; taux de réussite noté, erreurs de description comprises.

### Plan par plan (vraie vidéo 2, quand elle sera possible) — 30 à 45 s

| Plan | Image | Paroles |
|---|---|---|
| 1 | Plan large, lunettes sur la tête, devant une table préparée : trois objets simples et une feuille avec la date écrite à la main. | — |
| **2 — clé, sans coupe** | Caméra sur la scène + voyant des lunettes + fenêtre IRIS + chronomètre. | **« Dis-moi Iris, qu'est-ce qu'il y a devant moi ? »** Réponse complète, non coupée. |
| 3 | Le téléphone balaie lentement la table pour que chacun compare. | Miguel : « Elle a trouvé [ceci]. Elle a raté [cela]. » |
| 4 | Carton : statut, lieu de l'analyse (ordinateur ou en ligne), temps mesuré, prises. | — |

### Jamais

Choisir la meilleure scène parmi dix essais sans le dire · compléter ou reformuler la réponse d'IRIS · filmer
une personne sans autorisation écrite · laisser croire que l'analyse est locale si elle ne l'est pas.

---

## 5. Vidéo 3 — Photo avec le voyant des lunettes

| | |
|---|---|
| **Objectif** | Prouver que « Dis-moi Iris, prends une photo » déclenche la caméra des lunettes, que le voyant s'allume et que l'image arrive sur l'ordinateur. |
| **Constat** | Dans 0.1.0, l'outil photo existe mais **refuse par défaut** : tant que le format des trames caméra n'est pas confirmé sur le vrai matériel, il n'écrit rien dans la puce (pour ne pas l'abîmer) et l'explique. Un réglage d'exploration, caché, lève ce refus : il sert au banc d'essai, pas à une preuve pour les clients. |
| **Statut à afficher** | **En test** |
| **Durée** | 30 à 45 s |
| **Matériel** | Lunettes VELA du modèle vendu (avec caméra) · 2 téléphones (plan large + gros plan sur le voyant) · un 3ᵉ écran ou téléphone qui affiche l'heure avec les secondes · OBS Studio |

### Prérequis techniques à vérifier avant de filmer

- [ ] Protocole caméra confirmé sur la vraie paire (`docs/LUNETTES-CAMERA-PROTOCOLE.md`) ; photo reconstituée
      correctement sur 10 essais, ou taux noté.
- [ ] Une version **publiée** prend la photo **sans** le réglage d'exploration. Sinon, on peut filmer au banc
      d'essai pour documenter, mais avec l'étiquette « En test — version non publiée, réglage d'essai ».
- [ ] Voyant vérifié **sur la paire vendue** (pas sur une vidéo du fabricant) : s'allume-t-il à chaque prise,
      et combien de temps ?
- [ ] La photo arrive dans le dossier local d'IRIS (noter le chemin) et une ligne « photo des lunettes »
      apparaît au registre (le code de 0.1.0 prévoit cette inscription).
- [ ] Internet coupé pendant la prise (Bluetooth actif), pour montrer que la photo simple n'a pas besoin du réseau.

### L'astuce de preuve

Tenir devant les lunettes un téléphone qui affiche l'heure avec les secondes. La photo reçue doit montrer cette
heure-là, à la seconde près : une image difficile à préparer à l'avance.

### Plan par plan

| Plan | Temps | Image | Paroles |
|---|---|---|---|
| 1 | 0–5 s | Plan large, lunettes sur la tête ; à l'écran, l'icône réseau « Pas d'Internet ». | — |
| **2 — clé, sans coupe** | 5–25 s | Écran partagé : gros plan sur le voyant · fenêtre IRIS · téléphone-horloge tenu devant les lunettes. | **« Dis-moi Iris, prends une photo. »** |
| **3 — sans coupe** | 25–35 s | Explorateur Windows : le nouveau fichier et son heure de création. On l'ouvre : on y voit le téléphone-horloge. | Miguel : « La photo montre [heure lue] ; elle est sur l'ordinateur. » |
| 4 | 35–42 s | Registre : la ligne de la photo avec le chemin du fichier. Carton de statut. | — |

### Jamais

Prendre la photo avec le bouton des lunettes ou avec un téléphone en laissant croire que c'est IRIS · montrer
l'application du fabricant · réutiliser `vela-camera-led.mp4` comme preuve · activer le réglage d'exploration
sans le dire.

### Cartons de limite

- « En test : la photo pilotée par IRIS n'est pas dans la version publiée 0.1.0. » (tant que c'est vrai)
- « Le voyant est un témoin matériel. S'il est masqué (doigt, ruban), il ne se voit plus : c'est un signal,
  pas une garantie absolue. »

### Ce qu'on peut filmer dès maintenant

Dans la vidéo 6 : la demande « Dis-moi Iris, prends une photo » et le **refus expliqué** d'IRIS 0.1.0. C'est une
vraie preuve de sérieux, et elle ne dépend de rien.

---

## 6. Vidéo 4 — Confidentialité

**Capture → registre → fichier local → vérification**

| | |
|---|---|
| **Objectif** | Montrer, sans rien affirmer, qu'un geste sensible laisse une trace, que cette trace est sur l'ordinateur, et que toute modification après coup se détecte — dans IRIS, puis dans le navigateur, sur le site. |
| **Statut à afficher** | **Disponible** pour le registre (chaîne, vérification, export, purge). La partie « capture d'écran envoyée » dépend du service IRIS en ligne : à vérifier. |
| **Durée** | 45 à 60 s |
| **Lien avec le site** | Décision du 13 septembre : la page Confidentialité aura deux blocs, « Démo du principe » et « Preuve : registre produit par IRIS lors d'une session d'essai du 13 septembre 2026 » (fichier `site/assets/preuves/registre-session-essai-2026-09-13.json`). La vidéo 4 est la version filmée du second bloc. |

### Prérequis techniques à vérifier avant de filmer

- [ ] **La vérification du site applique exactement la formule d'IRIS 0.1.0** (encadré ci-dessous). Test : le
      fichier de preuve du 13 septembre doit ressortir intègre ; le même fichier avec une lettre changée doit
      ressortir « rupture à l'entrée n° X ». *(Contrôlé le 13 septembre avec la formule d'IRIS : ce fichier se
      vérifie, 10 entrées, chaîne intacte.)*
- [ ] **La page du site accepte un fichier choisi par le visiteur.** Sinon, demander l'ajout à l'équipe site :
      c'est ce qui rend la preuve reproductible par n'importe qui.
- [ ] **Le fichier de preuve du 13 septembre** : ses 10 entrées portent toutes la même seconde, ce qui ressemble
      à une session scriptée. Le texte du site doit dire comment il a été produit (script ou gestes manuels) et
      avec quelle version d'IRIS. La vidéo 4, elle, doit montrer une vraie session, à vitesse humaine.
- [ ] **Le champ « agent » du registre** peut afficher un identifiant technique qui nomme un fournisseur (c'est
      le cas, dans le code 0.1.0, pour la reconnaissance vocale en ligne). Regarder les lignes avant de filmer ;
      si un nom apparaît, choisir des gestes qui n'en produisent pas, ou masquer **en le disant** (« identifiant
      technique masqué ») — et signaler le défaut à l'équipe application.
- [ ] Variante avec capture : consentement « Captures d'écran » désactivé au départ (dans le code 0.1.0, tous
      les consentements sont désactivés à l'installation — le vérifier sur une installation neuve), service IRIS
      en ligne joignable, pastille de capture visible quand IRIS prend la capture.
- [ ] Savoir où arrive le fichier exporté (Téléchargements ?) et où vivent les données (`%APPDATA%\IRIS`).

### Encadré — la formule de la chaîne (IRIS 0.1.0, `backend/iris/consent.py`)

Pour chaque entrée, dans l'ordre des numéros :

```
empreinte = SHA-256( précédente | created_at | event_type | data_type | agent | detail )
```

- `|` est le caractère barre verticale ; un champ vide ou nul vaut une chaîne vide ;
- `précédente` = empreinte de l'entrée d'avant (vide pour la première) ; elle doit aussi être égale au champ
  `prev_hash` de l'entrée ;
- texte encodé en UTF-8, empreinte écrite en hexadécimal minuscule ;
- une entrée sans empreinte (antérieure à la chaîne) est tolérée et remet `précédente` à vide.

### Plan par plan (variante avec capture)

| Plan | Temps | Image | Paroles |
|---|---|---|---|
| 1 | 0–5 s | IRIS › Confidentialité : interrupteurs, « Captures d'écran » désactivé. | Miguel : « Par défaut, IRIS n'envoie pas mon écran. » |
| **2 — sans coupe** | 5–20 s | Il active « Captures d'écran ». Puis il demande. La pastille de capture apparaît. | **« Dis-moi Iris, regarde mon écran et dis-moi quelle page est ouverte. »** |
| **3 — sans coupe** | 20–32 s | Registre : lignes « consentement accordé » et « envoi externe — capture ». « Vérifier l'intégrité » → intègre. « Exporter JSON ». | « C'est inscrit ici, sur mon ordinateur. » |
| 4 | 32–40 s | Explorateur : le fichier .json dans Téléchargements. Ouverture dans le Bloc-notes ; on change **une** lettre dans un champ `detail` ; on enregistre. | « Je change une seule lettre. » |
| **5 — sans coupe** | 40–52 s | Navigateur : page Confidentialité du site, bloc de vérification. Dépôt du fichier modifié → rupture à l'entrée n° X. Dépôt de l'original (copie gardée) → intègre. | « La page trouve la ligne modifiée. » |
| 6 | 52–58 s | Cartons de limite. | — |

**Variante sans service en ligne** (si la capture ne peut pas être tournée) : le plan 2 devient une suite de
gestes locaux — activer puis désactiver le mode confidentiel, accorder puis retirer un consentement,
« Purger maintenant ». Chaque geste crée une ligne. Le reste est identique.

### Ce qui DOIT être visible

État par défaut des interrupteurs · pastille de capture · lignes du registre avec date et heure · bouton
« Vérifier l'intégrité » et son résultat · le fichier dans l'explorateur · la modification d'une seule lettre ·
le résultat dans le navigateur (échec avec le fichier modifié, succès avec l'original).

### Jamais

Préparer le fichier modifié à l'avance · couper entre le dépôt du fichier et le résultat · montrer le contenu
d'une capture qui contient des données personnelles · laisser un nom de fournisseur lisible.

### Cartons de limite (obligatoires)

- « Le registre prouve qu'une ligne n'a pas été modifiée après coup. Il ne prouve pas, à lui seul, qu'aucune ligne
  n'a été omise : la personne qui contrôle l'ordinateur peut le vider. »
- « Le registre inscrit ce qui part de l'ordinateur. Il ne voit pas ce qui se passe ensuite sur le serveur. »
- En fin de vidéo, la formule retenue : « En mode local, vos données restent sur votre ordinateur. » La suite
  (« IRIS vous montre ce qui part avant l'envoi ») seulement si l'image vient de le montrer — voir la section 0.

---

## 7. Vidéo 5 — Hors ligne

| | |
|---|---|
| **Objectif** | Montrer, Internet coupé, ce qui marche encore **et** ce qui ne marche pas, sans rien laisser deviner. |
| **Statut à afficher** | **Disponible** pour les lignes vérifiées ; les autres sont dites « ne fonctionne pas hors ligne ». |
| **Durée** | 45 à 60 s |
| **Matériel** | Celui de la vidéo 1 · câble réseau visible s'il y en a un · un navigateur pour prouver la coupure |

### Ce que le code 0.1.0 laisse attendre (sans modèle d'IA installé localement) — à confirmer par essai

| Fonction | Hors ligne | Pourquoi |
|---|---|---|
| Mot d'activation « Dis-moi Iris » et reconnaissance de la parole en français | Devrait marcher | Modèle d'écoute français embarqué dans l'installateur |
| Voix française d'IRIS | Devrait marcher | Voix locale embarquée (si une voix en ligne est configurée, vérifier le repli) |
| Ouvrir une application installée (« ouvre le Bloc-notes ») | Devrait marcher | Commande reconnue sur l'ordinateur, sans modèle |
| L'heure et la date | Devrait marcher | Calculées sur l'ordinateur |
| Routines déjà enregistrées, aux étapes locales | Devrait marcher | Rejouées sans modèle |
| Registre (vérifier, exporter), mode confidentiel, purge | Devrait marcher | Entièrement local |
| Liaison Bluetooth avec les lunettes | Devrait marcher | Directe ordinateur–lunettes ; l'affichage de la batterie reste une interprétation non prouvée |
| Retenir une phrase explicite (« souviens-toi que… ») | À vérifier | La phrase est retenue sans modèle, mais IRIS risque d'enchaîner sur un message d'erreur |
| Rappel déjà programmé | À vérifier | Déclenché sur l'ordinateur ; en créer un nouveau à la voix passe par le modèle |
| Questions ouvertes, conversation, rédaction, résumé | **Ne marche pas** | Besoin du service IRIS en ligne (sauf modèle installé localement, option avancée non incluse) |
| « Lis-moi l'écran » à la voix | **Ne marche pas** | La lecture est locale, mais c'est le modèle qui décide de la lancer |
| Recherche web, ouvrir un site | **Ne marche pas** | Réseau |
| Traduction | **Ne marche pas** | Langue étrangère reconnue en ligne, puis modèle |
| Courriel, SMS, appel | **Ne marche pas** | Réseau — et à ne pas démontrer de toute façon (non prouvés) |

### Prérequis techniques à vérifier avant de filmer

- [ ] Faire tout le tableau hors caméra, Internet coupé, et ajouter une colonne « résultat réel ». **Ne filmer
      que ce qui a passé** ; publier le tableau réel sous la vidéo.
- [ ] **Couper Internet sans couper le Bluetooth** : débrancher le câble réseau et désactiver le Wi-Fi.
      **Ne pas utiliser le mode Avion** : sous Windows, il coupe aussi le Bluetooth, donc les lunettes.
- [ ] **Redémarrer IRIS après la coupure** (démarrage à froid hors ligne) : vérifier qu'elle démarre et noter en
      combien de temps (au démarrage, IRIS cherche le serveur en ligne ; mesurer l'effet).
- [ ] Aucun modèle d'IA local configuré : on filme le cas d'un client ordinaire. Si vous en avez un pour vos
      essais, le désactiver et le dire.
- [ ] Écouter ce que dit IRIS quand une question ouverte échoue : message clair, à voix haute ? **Un échec
      silencieux est un défaut à corriger avant de filmer**, ou à montrer comme limite en le disant.
- [ ] Aucun téléphone en partage de connexion avec l'ordinateur.

### Plan par plan

| Plan | Temps | Image | Paroles |
|---|---|---|---|
| 1 | 0–8 s | Câble débranché (caméra), Wi-Fi désactivé, icône « Pas d'Internet ». Navigateur : une page qui ne charge pas. | « J'ai coupé Internet. Le Bluetooth reste actif. » |
| 2 | 8–14 s | Fermer puis relancer IRIS. Si le démarrage dépasse 20 s, coupe permise **avec** un carton « Démarrage hors ligne : x s ». | — |
| **3 — clé, sans coupe** | 14–30 s | Caméra + écran + chronomètre. | **« Dis-moi Iris, ouvre le Bloc-notes. »** → s'ouvre. **« Dis-moi Iris, quelle heure est-il ? »** → réponse, horloge visible. |
| **4 — clé, sans coupe** | 30–42 s | Même cadrage. | **« Dis-moi Iris, quelle est la capitale de l'Australie ? »** → la réponse réelle d'IRIS, quelle qu'elle soit. |
| 5 | 42–55 s | Carton en deux colonnes « Marche hors ligne » / « Ne marche pas hors ligne », tiré de l'essai réel. | — |

### Jamais

Laisser un câble réseau branché hors champ · partager la connexion d'un téléphone · utiliser un modèle local sans
le dire · dire ou écrire « IRIS fonctionne entièrement hors ligne ».

### Cartons de limite

- « Hors ligne, IRIS entend, parle et exécute les commandes simples. Les questions ouvertes ont besoin du service
  IRIS en ligne. »
- Ne pas confondre « hors ligne » et « mode 100 % local » : le mode local est un **réglage** qui bloque les
  envois même quand Internet est branché. Formule retenue, à utiliser seulement pour le mode local : « En mode
  local, vos données restent sur votre ordinateur. »

---

## 8. Vidéo 6 — Les limites

| | |
|---|---|
| **Objectif** | Dire, en le montrant, ce qu'IRIS 0.1.0 ne sait pas encore faire. C'est la réponse la plus directe à « est-ce une vision ? » : on sépare nettement aujourd'hui et demain. |
| **Durée** | 50 à 60 s (version longue possible, jusqu'à 90 s, pour le site) |
| **Matériel** | Celui de la vidéo 1 · une enceinte pour un bruit de café |

### Prérequis techniques à vérifier avant de filmer

- [ ] Chaque limite est revérifiée **le jour même** sur l'installateur publié : une limite peut avoir été levée,
      ou être pire que prévu.
- [ ] Les statuts affichés sont exactement ceux de la page Feuille de route du site.
- [ ] L4 : si IRIS **invente** une description de ce qui est devant vous, c'est un défaut grave à corriger avant
      de filmer (leçon connue : « IRIS qui invente ses limites »).

### Les limites (d'après le code 0.1.0 et les constats des 6 et 9 septembre — à revérifier)

| # | Limite | Comment la montrer | Statut |
|---|---|---|---|
| L1 | Sans ordinateur allumé à portée, les lunettes ne pilotent pas IRIS. | Ordinateur éteint ; « Dis-moi Iris, ouvre Chrome » → rien ne se passe. | Limite actuelle · application téléphone : Prévu |
| L2 | Sans lunettes, la voix est verrouillée ; la conversation écrite reste. | Éteindre les lunettes → « Connectez vos lunettes VELA pour parler à IRIS ». | Voulu (les lunettes d'abord) |
| L3 | La caméra des lunettes n'est pas pilotée par la version publiée. | « Dis-moi Iris, prends une photo. » → refus expliqué. | En test |
| L4 | IRIS ne décrit pas ce qui est devant vous. | « Dis-moi Iris, qu'est-ce qu'il y a devant moi ? » → réponse réelle. | En test |
| L5 | Windows 10 et 11 seulement. | Carton. | Mac et Linux : Prévu · iPhone : Prévu (en préparation) |
| L6 | Les demandes ouvertes prennent plusieurs secondes. | Une vraie demande, chronomètre visible, sans coupe. | Limite actuelle |
| L7 | La reconnaissance vocale se trompe dans le bruit. | La même phrase avec un bruit de café : montrer l'erreur. | Limite actuelle |
| L8 | L'installateur n'est pas encore signé : Windows affiche un avertissement. | Enregistrement de l'installation : écran de protection de Windows, « Informations complémentaires » › « Exécuter quand même ». | Limite actuelle |
| L9 | Pas de SMS ni d'appel fiables depuis IRIS. | **Carton seulement.** Au 6 septembre, IRIS annonçait un envoi qui n'avait pas lieu : c'est un défaut à signaler à l'équipe application, pas une scène. | En test |
| L10 | Traduction : après chaque phrase (pas pendant), avec Internet, jamais prouvée en conditions réelles. | Carton. | En test |

Pour la version de 60 s : L3, L4, L1, L6, L7, L8 filmées ; L2, L5, L9, L10 en cartons.

### Script (Miguel face caméra : permis ici, en dehors des moments clés)

1. Ouverture : « Voici ce qu'IRIS ne sait pas encore faire. Version 0.1.0, filmée aujourd'hui. »
2. L3 : **« Dis-moi Iris, prends une photo. »** → réponse réelle, sans coupe. Carton « En test ».
3. L4 : **« Dis-moi Iris, qu'est-ce qu'il y a devant moi ? »** → réponse réelle, sans coupe. Carton « En test ».
4. L1 : « J'éteins l'ordinateur. » Puis **« Dis-moi Iris, ouvre Chrome. »** → rien. Carton « Sans ordinateur
   allumé à portée, les lunettes ne pilotent pas IRIS aujourd'hui. »
5. L6 : **« Dis-moi Iris, donne-moi trois idées de titre pour une vidéo sur le vélo. »** → attente réelle,
   chronomètre visible. Carton « Temps mesuré : x s ».
6. L7 : même phrase qu'en 5, bruit de café en fond → l'erreur telle qu'elle arrive.
7. L8 : l'avertissement de Windows à l'installation.
8. Fin : « Ce qui est marqué Disponible, vous pouvez le vérifier aujourd'hui. Ce qui est En test ou Prévu est
   une intention, sans date garantie. » Puis « La preuve, pas la promesse. »
   *Ne mentionner l'engagement de remboursement de l'Édition fondatrice qu'une fois son texte validé par
   l'avocat (voir `docs/AUDIT-PRECOMMANDE-JURIDIQUE.md`).*

### Jamais

Jouer la comédie de l'échec (provoquer une erreur qui n'arrive pas naturellement) · couper une réponse gênante ·
montrer une limite déjà levée comme si elle existait encore · minimiser (« petit détail », rires).

---

## 9. Sous-titres et accessibilité

- **Deux sortes de sous-titres.** Activables (fichier `.vtt`) pour le site ; incrustés dans l'image pour les
  réseaux sociaux, où la plupart des vidéos se regardent sans le son.
- **Mot pour mot**, y compris les erreurs d'IRIS. Ne jamais « corriger » ce qu'IRIS a dit : le sous-titre fait
  partie de la preuve.
- **Qui parle** : « MIGUEL : », « IRIS : ».
- **Les sons et l'attente** : [signal d'écoute], [silence — 4 secondes], [Chrome s'ouvre], [bruit de café].
  L'attente doit se *lire* aussi pour une personne sourde.
- **Lisibilité** : 2 lignes au maximum, environ 40 caractères par ligne, au moins 1 seconde à l'écran, vitesse de
  lecture raisonnable (autour de 15 caractères par seconde) ; texte clair sur bandeau sombre semi-opaque. Ne
  jamais couvrir la fenêtre IRIS, le chronomètre ou le voyant : monter le sous-titre en haut au besoin.
- **Transcription et description** sous chaque vidéo sur le site, pour les personnes aveugles ou malvoyantes :
  les paroles, et ce qu'on voit (« Chrome s'ouvre sur la moitié gauche ; le chronomètre indique 3,4 s »).
- **Pas de lecture automatique** pour les vidéos de preuve ; commandes du lecteur visibles et utilisables au
  clavier ; aucun clignotement rapide.
- Un brouillon automatique de sous-titres est permis ; **relecture humaine complète obligatoire**.
- **Langues** : français d'abord ; anglais, espagnol et italien par sous-titres traduits (`.vtt` séparés),
  jamais par doublage de la voix d'IRIS.
- Repères WCAG 2.1 : sous-titres (critère 1.2.2) ; transcription ou audiodescription (1.2.3 et 1.2.5).

---

## 10. Formats

| | Horizontal 16:9 | Vertical 9:16 |
|---|---|---|
| **Usage** | Site, YouTube, LinkedIn, presse | Reels, Shorts, TikTok, stories |
| **Résolution** | 1920 × 1080 | 1080 × 1920 |
| **Tournage** | La source maître | Soit tournée à part (téléphone à la verticale), soit mise en page : moitié haute = personne et lunettes, moitié basse = recadrage de la fenêtre IRIS et du chronomètre |
| **Zone sûre** | — | Garder texte et éléments clés hors d'environ 15 % en haut et 20 % en bas (boutons des applications) |
| **Sous-titres** | `.vtt` activables | Incrustés |
| **Durée** | 20 à 60 s ; version longue non montée sur demande | 20 à 45 s |

**Commun aux deux :**
- 30 images par seconde **constantes** (une cadence variable désynchronise son et image) ; MP4 H.264 + AAC ;
  volume normalisé autour de −16 LUFS ; une image d'affiche JPG.
- Pour le site : viser environ 10 à 15 Mo au plus par vidéo (720p ou 1080p bien compressé).
- **Le recadrage vertical ne doit jamais faire disparaître** le chronomètre, les mains ou les lunettes au moment
  clé. Si c'est impossible, tourner la version verticale à part.
- Chaque version montée vient du même original, dont l'empreinte est notée au journal.

---

## 11. Où publier sur le site

**Héberger les vidéos sur le site lui-même** (`site/assets/videos/preuves/`), pas en intégration YouTube :
- la politique de sécurité du site (`site/_headers` : `default-src 'self'`) bloque les lecteurs externes ;
- la politique de confidentialité promet l'absence de témoins tiers : un lecteur externe en déposerait.

Les réseaux sociaux reçoivent une copie et renvoient vers le site.

**Noms de fichiers :** `preuve-1-controle-pc-2026-09-JJ.mp4`, `preuve-1-controle-pc-2026-09-JJ.fr.vtt`,
`preuve-1-controle-pc-2026-09-JJ-affiche.jpg`.

| Vidéo | Page | Emplacement |
|---|---|---|
| 1 et 5 | `index.html` | Dans la section « Ce qui marche aujourd'hui / ce qui arrive », **avant** le bouton d'achat (décision 1). Chaque ligne « Disponible » renvoie à sa preuve. |
| 1 et 5 | `fonctionnalites.html` | À côté de la fonction concernée. |
| 4 | `confidentialite.html` | Sous le bloc « Preuve : registre produit par IRIS lors d'une session d'essai du 13 septembre 2026 ». |
| 2 et 3 | `lunettes.html` | Seulement une fois prouvées. D'ici là, légender les clips existants : « Images du matériel. La photo pilotée par IRIS est En test. » |
| 6 | `feuille-de-route.html` | En tête de page. Et un lien depuis `plans.html`, près du bouton d'achat : « Voir ce qui ne marche pas encore ». |
| toutes | `accessibilite.html`, `presse.html` | Versions sous-titrées et transcriptions ; pour la presse, originaux sur demande et empreintes. |

- **À proposer à l'équipe site** : une page unique « Preuves » (`preuves.html`) qui regroupe les six fiches,
  liée depuis l'accueil et la page Plans.
- **Bloc sous chaque vidéo** : titre · étiquette de statut · date de tournage · version · temps mesuré · prises
  et réussites · « ce que la vidéo ne montre pas » · lien vers la transcription.
- **Balisage** : `<video controls preload="metadata" poster="…">` avec
  `<track kind="captions" srclang="fr" label="Français" src="….fr.vtt" default>`. Sans `autoplay`, `loop` ni
  `muted` : ces attributs restent réservés aux clips d'ambiance.
- **Péremption** : quand une nouvelle version d'IRIS est publiée, chaque vidéo garde sa mention « filmée avec
  0.1.0 ». Refilmer si le comportement a changé.
- Le site existe en quatre langues : prévoir légendes, transcriptions et `.vtt` en français, anglais, espagnol et
  italien.

---

## 12. Journal des prises et liste du jour de tournage

### Journal des prises (à remplir pendant le tournage, à garder)

| Vidéo | Prise | Date et heure | Version | Micro | Voix sortie | Internet | Réussie ? | Temps mesuré | Empreinte SHA-256 du fichier | Remarque |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | 1 | | 0.1.0 | lunettes | | branché | oui / non | | | |
| 1 | 2 | | | | | | | | | |

### Liste du jour de tournage

- [ ] Lunettes, téléphones et ordinateur chargés ; chargeurs à portée.
- [ ] IRIS 0.1.0 installé depuis le site ; « À propos » vérifié.
- [ ] Échappatoire de démonstration et plan de démonstration désactivés (vérifié avec l'équipe application).
- [ ] Micro de l'ordinateur désactivé pour les vidéos 1, 5 et 6 ; micro des lunettes sélectionné.
- [ ] Mode « Ne pas déranger » ; écran nettoyé ; aucun nom de fournisseur visible.
- [ ] OBS Studio testé (tout l'écran, son) ; téléphone sur trépied ; clap.
- [ ] Chronomètre ou horloge à secondes dans le champ.
- [ ] Autorisation écrite signée par toute personne qui apparaît (voir `docs/PROGRAMME-TESTEURS.md`, modèle de
      consentement).
- [ ] Rushs copiés sur deux supports le soir même ; empreintes calculées et notées au journal.
- [ ] Défauts découverts pendant le tournage transmis à l'équipe application (et non cachés dans le montage).
