# Programme « Premiers testeurs »

**Pour :** Miguel · **Établi le :** 13 septembre 2026
**Version testée par défaut :** IRIS 0.1.0 (installateur publié) avec les lunettes VELA
**But :** remplacer les témoignages « En attente » du site par des résultats **réels, datés et vérifiables** —
échecs compris. L'audit externe du 13 septembre donne 4/10 à la preuve produit : des personnes extérieures qui
testent pour de vrai, et dont on publie tout, sont la preuve la plus solide qu'une jeune marque puisse offrir.

> **Règle du programme.** On publie ce qui a été réellement testé, par qui (prénom ou pseudonyme), quand, sur
> quel appareil, avec quel résultat — y compris ce qui n'a pas marché. On ne paie jamais pour un avis positif, on
> n'écrit jamais un témoignage à la place de quelqu'un, on ne choisit pas les « bonnes » fiches.

**À faire valider avant de lancer :** le formulaire de consentement, la convention de prêt et le texte de
candidature (voir `docs/AUDIT-PRECOMMANDE-JURIDIQUE.md`, points 9, 10, 14 et 16). Point bloquant à vérifier :
prêter des lunettes Bluetooth pas encore certifiées au Canada pourrait être une « distribution » au sens de la Loi
sur la radiocommunication.

---

## Sommaire

1. [Ce que le programme est, et n'est pas](#1-ce-que-le-programme-est-et-nest-pas)
2. [Qui peut participer](#2-qui-peut-participer)
3. [Ce qu'on prête ou vend](#3-ce-quon-prête-ou-vend)
4. [Les quatre profils et ce qu'ils testent](#4-les-quatre-profils-et-ce-quils-testent)
5. [Le protocole commun](#5-le-protocole-commun)
6. [Le journal du testeur](#6-le-journal-du-testeur)
7. [Formulaire de consentement (modèle)](#7-formulaire-de-consentement-modèle)
8. [Ce qui sera publié](#8-ce-qui-sera-publié)
9. [Sélection des candidats](#9-sélection-des-candidats)
10. [Texte pour le site : candidater](#10-texte-pour-le-site--candidater)
11. [Liste de lancement](#11-liste-de-lancement)

---

## 1. Ce que le programme est, et n'est pas

**C'est :**
- un essai réel, en conditions de tous les jours, de ce que le site marque **Disponible** ;
- une vérification indépendante : un résultat de testeur peut faire passer une fonction de « Disponible » à
  « En test » sur le site ;
- une source de chiffres honnêtes (« mot d'activation reconnu 43 fois sur 50, pièce calme ») à la place des
  formules générales.

**Ce n'est pas :**
- un programme d'ambassadeurs ou d'influenceurs ;
- un échange « lunettes gratuites contre avis positif » ;
- une entente de confidentialité qui interdirait de publier un résultat négatif. La seule demande de réserve
  concerne une **faille de sécurité** : la signaler d'abord en privé à VELA, puis la publier librement après un
  délai raisonnable (proposition : 30 jours), qu'elle soit corrigée ou non ;
- une note globale en étoiles : avec quelques testeurs, une moyenne donnerait une fausse impression de précision.

**Taille proposée :** 8 testeurs, 2 par profil. **Durée :** 3 semaines par testeur.

---

## 2. Qui peut participer

- 18 ans ou plus.
- Adresse de livraison au Canada.
- Un ordinateur **Windows 10 ou 11 (64 bits)** qui peut rester allumé pendant l'utilisation : sans ordinateur
  allumé à portée, les lunettes ne pilotent pas IRIS aujourd'hui.
- Accepter de tenir un journal (section 6) et de faire un entretien final de 30 minutes.
- **Dire tout lien avec VELA ou avec Miguel** (ami, famille, collègue, client, investisseur). Ce lien n'exclut pas
  forcément la personne, mais il est **publié** avec ses résultats.
- Pas de téléphone requis : l'application téléphone est **Prévue** (application iPhone en préparation), pas
  disponible.

---

## 3. Ce qu'on prête ou vend

### Par défaut : un prêt

| | |
|---|---|
| **Prêté** | Une paire de lunettes VELA (modèle vendu), l'étui de charge USB-C, l'étui rigide |
| **Logiciel** | IRIS 0.1.0, téléchargée depuis le site, comme un client |
| **Durée** | 3 semaines, plus 1 semaine pour le retour |
| **Retour** | Étiquette de retour prépayée fournie par VELA |
| **Dépôt** | Aucun par défaut (à confirmer avec l'avocat ; en aucun cas pour le profil accessibilité) |
| **Usure normale ou bris accidentel** | Non facturés au testeur (proposition, à valider) |
| **Perte ou vol** | Règle à fixer avec l'avocat avant le premier envoi |
| **Interdit** | Revendre ou prêter les lunettes à quelqu'un d'autre |

### Option : garder les lunettes à la fin

- Au prix normal (250 $, taxes selon la décision prise au point 8 de l'audit juridique), **ou** avec une remise
  **annoncée publiquement** dans la fiche du testeur (« a acheté la paire prêtée avec une remise de X $ »).
- Un testeur qui achète redevient un client ordinaire : toutes les garanties légales s'appliquent, et le
  programme ne lui retire aucun droit.

### Rémunération du temps (option, profil accessibilité en priorité)

- Un montant fixe, identique pour tous les testeurs d'un même profil, **versé quel que soit le résultat**.
- Montant à décider par Miguel ; il est **publié** dans la fiche (« a reçu X $ pour son temps »).

### Versions non publiées

- Par défaut, on teste la version publiée. Une version d'essai (0.2.0 en développement) peut être confiée à un
  testeur technique, **seulement** si ses résultats sont étiquetés « version d'essai, non publiée » et ne servent
  jamais à marquer une fonction « Disponible ».

---

## 4. Les quatre profils et ce qu'ils testent

Chaque tâche a un code. Le **statut attendu** est celui du site au moment du test ; le testeur note le résultat
réel. Une tâche marquée « doit refuser proprement » vérifie qu'IRIS **dit** qu'elle ne sait pas faire, au lieu de
faire semblant.

### Profil 1 — Technique

**Qui :** une personne à l'aise avec Windows, le Bluetooth et la mesure (développeur, technicien, bricoleur
exigeant). **Temps :** environ 3 heures par semaine.

| Code | Tâche | Mesure | Statut attendu |
|---|---|---|---|
| T1 | Télécharger IRIS depuis le site et l'installer sur un Windows sans outils de développement | Durée, avertissement de Windows, erreurs, espace disque | Disponible |
| T2 | Appairer les lunettes ; les éteindre et rallumer 10 fois | Reconnexion automatique : n sur 10, temps moyen | À vérifier |
| T3 | 20 fois « Dis-moi Iris, quelle heure est-il ? » en pièce calme, puis 20 fois avec un bruit de fond | Réussites sur 20, dans chaque condition | Disponible |
| T4 | 1 heure de conversation normale à côté d'IRIS, sans l'appeler | Nombre de déclenchements non voulus | À vérifier |
| T5 | Ouvrir 5 applications installées à la voix | Réussites, temps entre la fin de la phrase et l'ouverture | Disponible |
| T6 | 10 demandes ouvertes (rédaction, question) | Temps de réponse minimum et maximum ; réponses fausses | Selon le site au moment du test |
| T7 | Internet coupé (sans couper le Bluetooth) : refaire T3 et T5, puis une question ouverte | Ce qui marche, ce qui ne marche pas, message d'IRIS | Voir `docs/VIDEOS-PREUVE.md`, vidéo 5 |
| T8 | Registre : « Vérifier l'intégrité », exporter en JSON, changer une lettre, vérifier dans le navigateur sur le site | La modification est-elle détectée, à la bonne entrée ? | Disponible |
| T9 | « Dis-moi Iris, prends une photo » | **Doit refuser proprement** dans 0.1.0 | En test |
| T10 | Démarrage d'IRIS et ressources (Gestionnaire des tâches) | Temps de démarrage, mémoire, processeur au repos | À mesurer |

**Livrable :** journal + rapports de bogues (modèle en section 6).

### Profil 2 — Accessibilité

**Qui :** des personnes pour qui la voix et le son à oreille ouverte changent vraiment l'usage de l'ordinateur —
par exemple basse vision ou cécité, mobilité réduite des mains, fatigue à l'écran. **Temps :** environ 2 à
3 heures par semaine, au rythme de la personne.

**Précautions propres à ce profil :**
- on ne demande **aucun diagnostic** ; la personne décrit ses besoins seulement si elle le souhaite ;
- toute information liée à la santé est un renseignement **sensible** : consentement exprès, séparé, et publication
  seulement si la personne coche la case prévue (section 7) ;
- un proche peut aider à l'installation ; on le note, sans jugement ;
- rémunération du temps recommandée (section 3).

| Code | Tâche | Mesure | Statut attendu |
|---|---|---|---|
| A1 | Installer IRIS avec l'aide technique habituelle de la personne (lecteur d'écran, loupe…) | Étapes bloquantes, aide extérieure nécessaire ou non | Disponible |
| A2 | Sur velaglass.ca, avec cette même aide : trouver le prix, les conditions de vente, le contact | Réussi ou non, temps, obstacles | — |
| A3 | 20 minutes d'usage à la voix seulement, sans clavier ni souris | Tâches réussies, moments de blocage | Disponible |
| A4 | « Dis-moi Iris, lis-moi l'écran » sur un document connu | Le texte lu est-il exact et complet ? | Selon le site au moment du test |
| A5 | Son à oreille ouverte : comprendre IRIS dans une pièce calme, puis bruyante | Compréhension, confort, volume | À vérifier |
| A6 | Trouver et utiliser les boutons des lunettes au toucher | Réussi ou non, remarques | À vérifier |
| A7 | Dire une phrase qu'IRIS ne comprend pas | IRIS le dit-elle clairement, à voix haute ? | À vérifier |

**Livrable :** journal (écrit, audio ou dicté, au choix) + entretien final.

### Profil 3 — Quotidien

**Qui :** des personnes non techniques, curieuses, qui porteraient les lunettes dans leur journée (travail de
bureau, études, maison). **Temps :** 20 à 30 minutes par jour.

| Code | Tâche | Mesure | Statut attendu |
|---|---|---|---|
| Q1 | Porter les lunettes au moins 1 heure par jour | Confort, poids, chaleur, marques sur le nez ou les oreilles | — |
| Q2 | Mesurer l'autonomie : de pleine charge à l'arrêt, en notant l'usage (musique, IRIS, veille) | Heures et minutes, avec la méthode | « À confirmer » sur le site : cette mesure peut le remplacer, méthode publiée |
| Q3 | Trois usages quotidiens choisis par la personne (musique, heure, ouvrir une application, routine…) | Réussites et échecs notés au journal | Selon le site |
| Q4 | Utiliser les lunettes comme écouteurs Bluetooth ordinaires (musique, appel sur l'ordinateur) | Qualité, coupures | Fonction du matériel |
| Q5 | Porter les lunettes en présence d'autres personnes | Réactions, questions sur la caméra ; lieux évités | — |
| Q6 | En fin de test : « Paieriez-vous 250 $ ? Pourquoi ? » | Réponse libre, publiée telle quelle si la personne l'accepte | — |

**Sécurité :** arrêter immédiatement et écrire à VELA en cas de chauffe anormale, d'irritation de la peau, de pile
gonflée ou d'odeur. VELA doit pouvoir signaler un incident de produit dans les 2 jours.

**Règle de conduite :** ne pas filmer ni photographier des personnes sans leur accord ; retirer ou éteindre les
lunettes là où les appareils d'enregistrement sont interdits (vestiaires, examens, certains lieux de travail ou de
soins) ; ne pas utiliser IRIS en conduisant.

### Profil 4 — Confidentialité

**Qui :** une personne capable de vérifier des promesses de confidentialité (sécurité informatique, journalisme
technique, protection des données). **Temps :** environ 3 heures par semaine.

| Code | Tâche | Mesure | Ce qu'on compare |
|---|---|---|---|
| C1 | Installation neuve : état des consentements d'envoi | Tous désactivés au départ ? | Politique §4 |
| C2 | Observer les connexions réseau pendant 1 heure d'usage normal, avec l'outil de surveillance réseau de son choix | Destinations, moments, volume | Politique §5 |
| C3 | Activer le mode 100 % local, refaire C2 | Reste-t-il des connexions vers le service en ligne ? | Politique §4 |
| C4 | Mode confidentiel : micro et captures | Micro réellement coupé ? Pastille visible ? | Politique §4 et §8 |
| C5 | Pour chaque envoi observé en C2 : existe-t-il une ligne au registre ? | Envois non inscrits = **constat majeur** | Politique §6 |
| C6 | Purge, durée de conservation, désinstallation : que reste-t-il dans `%APPDATA%\IRIS` ? | Liste des fichiers restants | Politique §7 |
| C7 | Clé d'abonnement et identifiant d'appareil : ce qui part, et vers où | Constat | Politique §5 et §11 |
| C8 | Relire les pages du site et lister toute phrase absolue ou invérifiable | Liste de phrases, avec la page | Règle du fondateur |

**Ce que ce testeur ne pourra pas vérifier, et que sa fiche dira :** ce que fait le serveur en ligne après avoir
reçu une demande (conservation, journaux). On ne voit que ce qui part de l'ordinateur.

**Failles de sécurité :** signalement privé à contact@velaglass.ca d'abord, publication libre après le délai
convenu (section 1).

---

## 5. Le protocole commun

### Avant

1. Candidature reçue par la page contact (section 10), réponse d'une personne.
2. Appel de 15 minutes : profil, ordinateur, disponibilité, lien éventuel avec VELA.
3. Signature du **formulaire de consentement** (section 7) et de la **convention de prêt** (section 3).
4. Envoi des lunettes ; le testeur installe IRIS lui-même depuis le site.

### Semaine 1 — Installation et bases

- Tâches d'installation et d'appairage du profil (T1–T2, A1–A2, Q1, C1).
- Un court questionnaire de départ : attentes, ce que la personne a compris du produit en lisant le site. C'est
  aussi un test du site : ce qu'elle croit que le produit fait avant de l'avoir essayé.

### Semaine 2 — Usage réel

- Tâches du profil, à son rythme.
- Journal tenu chaque jour d'utilisation.
- Point hebdomadaire facultatif de 15 minutes.

### Semaine 3 — Mesures et vérifications

- Tâches de mesure (T3–T10, A3–A7, Q2–Q6, C2–C8).
- Entretien final de 30 minutes, enregistré seulement si la case correspondante est cochée.
- Retour des lunettes (ou achat, section 3).

### Après

- VELA rédige la fiche publique (section 8) **à partir du journal**, sans reformuler les résultats.
- Le testeur relit la fiche et la vidéo éventuelle ; il peut refuser la publication ou demander une correction
  factuelle. VELA, de son côté, ne retire jamais d'elle-même un résultat négatif exact.
- Chaque fonction du site est revue : un échec répété fait passer la fonction de « Disponible » à « En test » —
  et le site est corrigé avant la publication des fiches.
- Les défauts trouvés sont transmis à l'équipe application.

---

## 6. Le journal du testeur

### Une ligne par essai

| Date | Heure | Version d'IRIS | Lunettes connectées ? | Micro utilisé | Code de tâche | Ce que j'ai dit ou fait | Ce qui s'est passé | Réussi ? | Temps mesuré | Confort (1–5) | Remarque |
|---|---|---|---|---|---|---|---|---|---|---|---|
| | | 0.1.0 | oui / non | lunettes / ordinateur | | | | oui / non / en partie | | | |

Format au choix : tableur partagé, feuille papier photographiée, ou notes vocales.
**Ne jamais noter** d'informations sur d'autres personnes (noms, visages, conversations entendues).

### Rapport de bogue

```
Version d'IRIS :
Ordinateur et version de Windows :
Lunettes connectées : oui / non — micro utilisé :
Ce que j'ai fait (étapes) :
Ce que j'attendais :
Ce qui s'est passé :
Combien de fois sur combien d'essais :
Pièces jointes (capture, export du registre) : relire avant d'envoyer, retirer toute donnée personnelle
```

---

## 7. Formulaire de consentement (modèle)

> **Modèle à faire valider par un avocat avant utilisation.** Il vise le Code civil du Québec (art. 35 et 36 :
> image, voix, nom) et la Loi 25 (consentement manifeste, libre, éclairé, fin par fin ; consentement exprès pour
> les renseignements sensibles). Chaque case se coche séparément ; ne rien cocher reste possible.

---

**Programme « Premiers testeurs » — Consentement à l'utilisation de mes résultats, de mon nom, de ma voix et de
mon image**

**Qui recueille :** VELA, [nom légal et NEQ une fois immatriculée], [adresse], contact@velaglass.ca,
819 524-2804. Responsable de la protection des renseignements personnels : Miguel Goufack.

**Pourquoi :** tester les lunettes VELA et le logiciel IRIS, améliorer le produit, et publier des résultats
réels — réussites et échecs — pour que les futurs acheteurs sachent ce qui fonctionne vraiment.

**Ce que VELA recueille :** mon journal de test, mes réponses aux questionnaires, les rapports de bogues et
fichiers que j'envoie moi-même, l'enregistrement de l'entretien final (si je coche la case 6), les vidéos ou
photos où j'apparais (si je coche la case 5).

**Ce que je comprends :**
- Ma participation est volontaire. Je peux arrêter le test à tout moment, sans frais.
- Aucun avantage ne dépend du caractère positif de mes résultats. Tout avantage reçu (prêt, remise,
  rémunération) sera publié avec mes résultats.
- Je relis la fiche et toute vidéo me concernant **avant** leur publication, et je peux refuser.
- Je peux retirer mon consentement à tout moment par courriel. VELA retirera alors de ses propres pages et comptes
  les contenus me concernant dans un délai de [X] jours. Je comprends que VELA ne peut pas effacer les copies
  déjà faites par d'autres personnes (partages, captures).
- Mes renseignements sont conservés [durée] après la fin du programme, puis détruits, sauf les contenus publiés
  avec mon accord, conservés tant que je ne retire pas ce consentement.
- Hébergement : [lieux, dont d'éventuels services situés hors du Québec, par exemple une plateforme vidéo].
- J'ai le droit d'accéder à mes renseignements et d'en demander la correction.

**J'accepte que VELA (cocher chaque case voulue) :**

- [ ] 1. utilise mes résultats **de façon anonyme** (sans nom ni détail qui m'identifie), en interne et sur son site ;
- [ ] 2. publie mes résultats avec **mon prénom** : __________ **ou** avec le **pseudonyme** : __________ ;
- [ ] 3. publie ma **région** (pas mon adresse) : __________ ;
- [ ] 4. publie des **citations** de mon journal ou de mon entretien, que j'aurai relues ;
- [ ] 5. publie des **vidéos ou photos où mon visage apparaît** ;
- [ ] 6. enregistre l'**entretien final** et publie des extraits de **ma voix** ;
- [ ] 7. mentionne mon **profil accessibilité** et les besoins que j'ai choisi de décrire (renseignement sensible,
      consentement exprès) ;
- [ ] 8. utilise les contenus des cases cochées ci-dessus dans des **publicités payantes** (en plus du site et des
      pages de VELA sur les réseaux sociaux) ;
- [ ] 9. transmette mes coordonnées à un **journaliste** qui souhaite me parler, après m'avoir demandé à chaque fois.

**Personnes filmées avec moi :** toute autre personne reconnaissable dans une vidéo signe son propre formulaire.

**Durée de l'autorisation de publication :** [par exemple 2 ans], renouvelable avec mon accord.

**Lien avec VELA ou Miguel :** ☐ aucun ☐ oui, lequel : __________

Nom : __________ Date : __________ Signature : __________
Je confirme avoir 18 ans ou plus. Un exemplaire signé m'est remis.

---

## 8. Ce qui sera publié

### La fiche publique de chaque testeur (modèle)

```
Premier testeur — [prénom ou pseudonyme]
Profil : [technique / accessibilité / quotidien / confidentialité]
Dates du test : du [JJ mois] au [JJ mois AAAA]
Version d'IRIS : 0.1.0 (version publiée)   [ou : version d'essai non publiée]
Ordinateur : Windows [10/11], [type d'ordinateur si accepté]
Lunettes : prêtées par VELA   [ou : achetées au prix de X $]
Avantage reçu : [aucun / prêt / remise de X $ / X $ pour son temps]
Lien avec VELA : [aucun / précisé]

Ce qui a été réellement testé : [codes et intitulés des tâches]

Résultats :
- [tâche] : [n réussites sur m essais], [conditions : pièce calme, bruit, Internet coupé…]
- [tâche] : [mesure], [méthode]

Ce qui n'a pas marché : [liste, dans les mots du testeur]

En ses mots : « [citation relue et acceptée] »

Ce que ce test ne permet pas de conclure : [par exemple : un seul ordinateur, 3 semaines, pas de test en extérieur]
```

### Règles de publication

- **Toutes** les fiches dont les testeurs acceptent la publication sont publiées, pas seulement les bonnes. Si
  certains refusent, le total le dit : « 8 testeurs, 6 fiches publiées ».
- **Chaque chiffre porte son nombre d'essais et ses conditions.** Jamais « fonctionne à 95 % » sans « sur 40 essais,
  en pièce calme ».
- Pas de note en étoiles, pas de moyenne entre profils.
- Les échecs restent publiés même après correction ; on ajoute simplement « corrigé dans la version X, vérifié
  le [date] ».
- Les fiches remplacent les emplacements « En attente » du site ; elles sont datées et rattachées à une version.
- Le masque de marque s'applique aux fiches : aucun nom de fournisseur d'IA ou de voix, même si le testeur l'a
  découvert — on écrit « un service en ligne tiers ».

---

## 9. Sélection des candidats

**Ce qu'on demande dans la candidature (et rien de plus) :** profil souhaité, ordinateur (Windows 10 ou 11, âge
approximatif), région, disponibilité sur 3 semaines, lien éventuel avec VELA, pourquoi le programme les intéresse.
**Aucune information de santé** dans la candidature : on en parle seulement plus tard, si la personne le souhaite.

**Critères :**
- des ordinateurs variés, y compris des modèles modestes ou anciens ;
- des régions et des milieux variés ;
- au moins une personne sceptique ou critique par profil : **on n'écarte pas quelqu'un parce qu'il risque de
  trouver des défauts** ;
- les proches de Miguel ne sont pas exclus, mais pas plus d'un sur huit, et le lien est publié.

**Réponse :** chaque candidature est lue par une personne ; les candidats non retenus reçoivent une réponse et
peuvent rester sur une liste pour une prochaine vague.

---

## 10. Texte pour le site : candidater

### Emplacement

- Page `contact.html`, et un lien depuis `feuille-de-route.html` et `accessibilite.html`.
- **À ajouter par l'équipe site :** l'option « Premier testeur » dans la liste « Sujet » du formulaire de contact
  (le courriel pré-rempli portera alors l'objet « VELA — Premier testeur »). Dans les pages traduites :
  « First tester », « Primer probador », « Primo tester ». En attendant, le texte dit de choisir « Autre » et
  d'écrire « Premier testeur ».

### Texte court (français)

> **Devenir premier testeur**
>
> Nous cherchons quelques personnes au Canada pour essayer les lunettes VELA et IRIS 0.1.0 dans leur vraie vie,
> pendant trois semaines — et nous dire ce qui marche, comme ce qui ne marche pas encore.
>
> Quatre profils : **technique**, **accessibilité**, **quotidien**, **confidentialité**.
>
> Il faut avoir 18 ans ou plus, un ordinateur Windows 10 ou 11 (64 bits) et un peu de temps chaque semaine. Les
> lunettes sont prêtées, puis retournées à nos frais.
>
> Avec votre accord écrit seulement, nous publions ce que vous avez réellement testé et vos résultats, échecs
> compris, sous votre prénom ou un pseudonyme. On ne vous demandera jamais un avis positif.
>
> **Pour candidater :** écrivez-nous par le formulaire de contact, sujet « Premier testeur » (ou « Autre » en
> précisant « Premier testeur »). Dites-nous quel profil vous intéresse, quel ordinateur vous avez et pourquoi.
> Inutile de nous parler de votre santé à cette étape. Une personne lit chaque candidature. Places limitées.

*À ajuster avant publication :* si la rémunération du temps est retenue, ajouter « Le temps des testeurs du profil
accessibilité est rémunéré. » ; si le prêt n'est pas possible (certification radio), ne pas publier ce texte.

---

## 11. Liste de lancement

- [ ] Certification radio des lunettes vérifiée, ou avis de l'avocat sur le prêt d'appareils non certifiés.
- [ ] Formulaire de consentement et convention de prêt validés par l'avocat ; délais et durées remplis.
- [ ] Assurance couvrant les lunettes prêtées et la responsabilité produit.
- [ ] Procédure d'incident prête (qui reçoit, qui décide, signalement dans les 2 jours si nécessaire).
- [ ] Montant de rémunération décidé (ou décision de ne pas rémunérer), identique par profil.
- [ ] Option « Premier testeur » ajoutée au formulaire de contact, dans les quatre langues.
- [ ] Modèles de journal et de rapport de bogue envoyés avec les lunettes.
- [ ] Page du site prête à recevoir les fiches, à la place des emplacements « En attente ».
- [ ] Règle écrite : un échec répété fait passer une fonction de « Disponible » à « En test » **avant** la
      publication des fiches.
