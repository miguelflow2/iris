# Audit juridique avant de pousser les précommandes

> **Ce document n'est pas un avis juridique.**
> C'est une liste de questions à faire valider par un avocat membre du Barreau du Québec (droit de la
> consommation, protection des renseignements personnels), et, pour les taxes, par un comptable. Les articles de
> loi cités servent à orienter la discussion ; leur portée exacte et leur application à VELA doivent être
> confirmées par l'avocat.

**Pour :** Miguel · **Établi le :** 13 septembre 2026
**Pages lues (version 1.0 du 9 septembre 2026) :** `site/conditions-vente.html`, `site/garantie-retour.html`,
`site/mentions-legales.html`, `site/politique-confidentialite.html`, `site/plans.html` — et, pour le parcours
d'achat, `site/lunettes.html`, `site/merci.html`, `site/faq.html`, `site/contact.html`.
**Contexte :** décisions de Miguel du 13 septembre (Édition fondatrice, statuts Disponible / En test / Prévu),
audit externe du 13 septembre, `deploy/FEUILLE-DE-ROUTE-VENDABLE.html` (9 septembre).

---

## En une page : les 5 points les plus urgents

1. **Ce que le site affirme engage VELA** (point 4). Plusieurs phrases promettent plus que la version publiée :
   photo et vidéo « à la voix », « rien ne se fait en cachette », « IRIS marche sans les lunettes ». À corriger
   avant de pousser les précommandes, et le texte « Édition fondatrice » à faire valider (point 5).
2. **Le parcours d'achat fait payer avant de donner les renseignements obligatoires** (point 2) : délai de
   livraison, adresse, frais et conditions d'annulation se règlent *après* le paiement ; le §8 des conditions de
   vente est resté une phrase-gabarit.
3. **Précommande sans date de livraison** (point 3) : sans date écrite, le client peut résoudre le contrat
   30 jours après la commande et être remboursé dans les 15 jours. Le virement Interac n'offre aucun recours de
   rétrofacturation au client.
4. **Identité du vendeur incomplète** (point 1) : ni adresse, ni NEQ ; vendre sous « VELA » demande
   normalement une immatriculation ; en entreprise individuelle, Miguel répond personnellement de tout.
5. **Certification radio des lunettes** (point 14) : un appareil Bluetooth doit être certifié par ISED avant
   d'être *offert en vente* au Canada — une précommande en est vraisemblablement une.

Juste derrière : l'offre « Lunettes + 12 mois Pro » qui encaisse un service pas encore ouvert, et « taxes en
sus » sans décision fiscale (points 8 et 15).

---

## Préparer le rendez-vous avec l'avocat

**Apporter (imprimé ou en PDF) :**
- les 5 pages juridiques du site et les pages Plans, Lunettes, Merci, FAQ ;
- une capture de la page de paiement Stripe, du bouton PayPal et des instructions Interac ;
- un exemple du courriel envoyé après un paiement ;
- ce que le fabricant a fourni sur les lunettes (fiche technique, certificats, rapports d'essais, photos et
  vidéos avec leurs droits) ;
- le texte prévu pour l'« Édition fondatrice » et pour la section « Ce qui marche aujourd'hui / ce qui arrive » ;
- ce document, avec les questions cochées par ordre de priorité.

**Demander :** une revue de conformité à prix fixe, point par point, avec des textes de remplacement.

**Information gratuite (ce ne sont pas des avis juridiques) :** Office de la protection du consommateur (section
commerçants) · Commission d'accès à l'information (guides sur l'EFVP et les incidents) · Office québécois de la
langue française · Innovation, Sciences et Développement économique Canada (certification radio) · Revenu Québec
et Agence du revenu du Canada · Centres de justice de proximité.

**Comment lire chaque point :**
- *Ce que le site dit aujourd'hui* — citation courte, avec la page ;
- *Pourquoi c'est à valider* — en langage courant ;
- *Questions à poser* — à lire telles quelles à l'avocat.

---

## 1. Qui vend ? L'identité exacte du vendeur

**Ce que le site dit aujourd'hui**
- `conditions-vente.html` §1 : « exploité par Miguel Goufack, à titre de commerçant établi dans la province de
  Québec » — coordonnées : un courriel et un téléphone, **aucune adresse, aucun NEQ**.
- `mentions-legales.html` §1 : « édités sous le nom commercial VELA » — sans forme juridique, alors que la
  politique de confidentialité (§2) y renvoie justement pour la « forme juridique ».

**Pourquoi c'est à valider**
- Pour un contrat conclu à distance, l'adresse du commerçant fait partie des renseignements à donner avant la
  vente (Loi sur la protection du consommateur, ci-après LPC, art. 54.4).
- Exploiter sous un nom qui n'est pas son prénom et son nom (« VELA ») demande normalement une immatriculation
  au Registraire des entreprises (Loi sur la publicité légale des entreprises). La feuille de route du
  9 septembre le classe « bloquant ».
- En entreprise individuelle, Miguel répond **personnellement** des remboursements de précommandes, des défauts
  et des réclamations (par exemple liées à la caméra).
- VELA se présente comme « entreprise canadienne » : la réalité juridique doit suivre.

**Questions à poser**
1. Dois-je être immatriculé au REQ avant la première précommande ? Quelles mentions exactes (nom, NEQ, adresse,
   forme juridique) sur le site, les reçus et les courriels ?
2. Entreprise individuelle ou société par actions (québécoise ou fédérale) **avant** d'encaisser de l'argent ?
   Qu'est-ce que ça change pour ma responsabilité personnelle ?
3. Puis-je publier une adresse d'affaires (case postale, service de domiciliation) plutôt que mon domicile ?
   Laquelle satisfait la LPC ?
4. Puis-je écrire « entreprise canadienne » avec la structure choisie ?
5. Si je constitue une société plus tard, que deviennent les contrats et précommandes conclus à mon nom ?

---

## 2. Le contrat conclu à distance : ce qu'il faut dire avant que le client paie

**Ce que le site dit aujourd'hui**
- `lunettes.html`, trois étapes : « Vous payez », puis « Vous nous écrivez : la version voulue (transparente ou
  teintée) et votre adresse », puis « On convient le délai dans le même échange ».
- `merci.html` : « Votre paiement est bien parti. » puis « Dites-nous où livrer ».
- `garantie-retour.html` §2 : « Délai d'expédition : communiqué au moment de la commande. »
- `conditions-vente.html` §7 : frais de livraison « précisés avant la validation de la commande » — mais le
  bouton ouvre une page Stripe avec « les 250 $ déjà remplis ».
- `conditions-vente.html` §8, resté à l'état de gabarit : « Le délai et les conditions exacts d'annulation […]
  doivent être précisés selon la loi. »
- `conditions-vente.html` §6 : « Le contrat est formé lorsque VELA confirme la commande ».

**Pourquoi c'est à valider**
- LPC art. 54.4 : **avant** la conclusion du contrat, le commerçant doit divulguer notamment son nom et son
  adresse, une description détaillée du bien (caractéristiques techniques), le prix détaillé avec les frais
  (livraison), le montant total, les modalités de paiement, **la date ou le délai de livraison**, le mode de
  livraison, les conditions d'annulation, de retour, d'échange et de remboursement, et toute autre restriction —
  de manière évidente et intelligible.
- LPC art. 54.5 : donner expressément au client la possibilité d'accepter ou de refuser, et de corriger ses
  erreurs, avant de conclure.
- LPC art. 54.6 et 54.7 : contenu du contrat, et exemplaire transmis dans les 15 jours, facile à conserver et à
  imprimer.
- LPC art. 54.8 : si ces règles ne sont pas respectées, le client peut résoudre le contrat (dans les 7 jours
  suivant la réception de l'exemplaire, ou 30 jours si l'exemplaire n'a pas été transmis à temps).
- Aujourd'hui, adresse, version, délai et frais se règlent **après** le paiement.
- Le site est aussi en anglais, espagnol et italien : un client d'une autre province peut être protégé par la
  loi de sa province, qui a ses propres règles pour la vente en ligne.

**Questions à poser**
1. Le parcours actuel (Stripe, PayPal, Interac) respecte-t-il les art. 54.4 et 54.5 ? Que doit afficher la page
   de paiement : case « j'accepte les conditions de vente », lien, récapitulatif, délai de livraison ?
2. Le courriel de confirmation peut-il servir d'exemplaire du contrat ? Contenu minimal ? Pouvez-vous fournir
   un modèle ?
3. Virement Interac : quand le contrat est-il conclu, et comment remettre les renseignements avant ?
4. Quel texte remplace la phrase-gabarit du §8 (droit de résolution) ?
5. Frais de livraison et choix des verres : faut-il les fixer et les afficher avant le paiement ?
6. Si je vends hors Québec, quelles règles de chaque province dois-je suivre ? Puis-je limiter le pilote aux
   adresses du Québec ?

---

## 3. Précommande et encaissement avant livraison

**Ce que le site dit aujourd'hui**
- `plans.html` : « Précommander les lunettes — 250 $ » et « Précommander — 250 $ » (l'audit externe compte
  8 occurrences de « Précommander » sur le site, placées avant les preuves).
- Les conditions de vente ne contiennent **pas** le mot « précommande ».
- `garantie-retour.html` §2 : « Nous n'affichons pas de délai tant qu'il n'est pas confirmé ».
- `conditions-vente.html` §5 : paiement « au moment de la commande », par carte (Stripe) ou virement Interac ;
  `plans.html` ajoute PayPal.

**Pourquoi c'est à valider**
- LPC art. 54.9 : si le bien n'est pas livré dans les 30 jours suivant la date indiquée au contrat — ou, **quand
  le contrat ne prévoit pas de date, dans les 30 jours suivant sa conclusion** — le client peut résoudre le
  contrat. Remboursement dans les 15 jours ; frais de retour à la charge du commerçant ; pour un paiement par
  carte de crédit, le client peut demander à l'émetteur d'annuler la transaction (art. 54.13 à 54.16).
- Sans date écrite, **chaque précommande payée aujourd'hui peut être résolue dans environ 30 jours.** Il faut une
  date réaliste, écrite, ou ne pas encaisser.
- Le virement Interac n'a pas de mécanisme de rétrofacturation : le client dépend entièrement de la capacité de
  VELA à rembourser.
- La feuille de route du 9 septembre liste encore à confirmer : stock réel, montage, délai d'expédition,
  transport de la pile au lithium.
- Les prestataires de paiement ont leurs propres règles sur les prépaiements à long délai (à lire chez Stripe et
  PayPal : risque de retenue de fonds ou de fermeture de compte).

**Questions à poser**
1. Ai-je le droit d'encaisser 100 % à la précommande ? Vaut-il mieux un dépôt, un paiement prélevé à
   l'expédition, ou une liste d'attente sans paiement ?
2. Comment formuler la date : « livraison au plus tard le … » ? Que se passe-t-il au 31ᵉ jour ? Comment proposer
   une nouvelle date par écrit, avec l'accord du client ?
3. Dois-je garder les sommes reçues à part (compte distinct) jusqu'à la livraison ?
4. Si l'« Édition fondatrice » est limitée en nombre, que dois-je écrire, et que dois-je pouvoir prouver ?
5. Dois-je retirer le virement Interac pour les précommandes ?

---

## 4. Ce que le site affirme = ce que VELA doit livrer

**Ce que le site dit aujourd'hui (exemples relevés le 13 septembre)**
- `lunettes.html` : « Photo et vidéo mains libres, à la voix » — la photo pilotée par IRIS n'est **pas**
  prouvée sur le vrai matériel ; dans la version publiée 0.1.0, l'outil photo refuse par défaut.
- `faq.html` et `politique-confidentialite.html` §8 : « Un témoin lumineux s'allume dès que la caméra filme, rien
  ne se fait en cachette. »
- `politique-confidentialite.html` §8 : « Les photos, les vidéos et leur analyse restent sur votre ordinateur ;
  elles ne sont jamais envoyées à un nuage. »
- `contact.html` : « IRIS marche sans les lunettes ? Oui. C'est une application Windows complète » — contraire à
  la règle « lunettes d'abord » (sans lunettes, la voix est verrouillée dans 0.1.0).
- Audit externe : « Rien ne part vers Internet » 7 fois, alors qu'un service d'IA en ligne est annoncé.
- Hors du site, les notes de version publiques de l'installateur (`release/notes-v0.1.0.md`) : « Lunettes
  VELA : connexion, batterie, photo » et « rien ne part sans votre accord ».
- `mentions-legales.html` §4 : « les fonctions annoncées « à venir » ne font l'objet d'aucun engagement de date
  ni de livraison ».

**Pourquoi c'est à valider**
- LPC art. 41 : le bien doit être conforme aux déclarations et aux messages publicitaires du commerçant ou du
  fabricant, **qui le lient**. Art. 42 : même règle pour les déclarations de son représentant (courriels,
  démonstrations, messages).
- LPC art. 219 et suivants : représentations fausses ou trompeuses interdites, y compris l'omission d'un fait
  important (art. 228) ; c'est l'impression générale laissée au client qui compte.
- Loi sur la concurrence (fédérale) : indications fausses ou trompeuses, notamment sur la performance d'un
  produit ; témoignages réels, lien avec l'entreprise dévoilé.
- Un avertissement général (« à venir ») ne neutralise probablement pas une affirmation précise faite ailleurs.
- VELA met son nom sur les lunettes : elle pourrait être traitée comme « fabricant » au sens de la LPC, avec les
  obligations qui vont avec.

**Questions à poser**
1. Un tableau de statuts (Disponible / En test / Prévu) suffit-il, ou chaque affirmation doit-elle porter son
   statut là où elle apparaît ?
2. Les phrases citées exposent-elles VELA ? Quelles formulations de remplacement ?
3. Des photos ou vidéos d'ambiance (fournies par le fabricant ?) peuvent-elles laisser croire à une fonction non
   disponible ? Faut-il une légende ?
4. Les notes de version, les publications sur les réseaux sociaux et les vidéos de démonstration sont-elles de la
   « publicité » au sens de la LPC ?
5. Suis-je « fabricant » au sens de la LPC parce que la marque VELA est sur le produit ?

---

## 5. L'engagement « Édition fondatrice »

**Ce que le site dit aujourd'hui**
- Rien encore : le texte n'est pas publié. Décision du 13 septembre : 250 $ = « Édition fondatrice VELA »,
  première génération assumée ; la section « Ce qui marche aujourd'hui / ce qui arrive » vient avant le bouton
  d'achat ; « remboursement intégral si la livraison n'arrive pas ou si une fonction marquée « Disponible » ne
  fonctionne pas comme décrit » ; « En test » et « Prévu » = intention, sans date garantie.

**Pourquoi c'est à valider**
- Une promesse volontaire et écrite peut constituer une **garantie conventionnelle**, avec des exigences de forme
  et de contenu (LPC, section sur les garanties, art. 43 et suivants).
- Une partie de la promesse existe déjà dans la loi : non-livraison (art. 54.9), défaut (garantie légale).
  Présenter un droit légal comme un avantage offert par VELA peut être trompeur si c'est mal formulé.
- « Fonctionne comme décrit » : qui en juge ? Pendant combien de temps ? Après une mise à jour ? Si la fonction
  dépend du service IRIS en ligne (et donc de fournisseurs tiers) ou d'un ordinateur trop ancien ?
- « Intention sans date garantie » ne protège que si aucune autre page ne présente la fonction comme acquise
  (point 4).

**Questions à poser**
1. Cet engagement est-il une garantie conventionnelle ? Quelles mentions obligatoires (durée, marche à suivre,
   exclusions, identité du garant) ?
2. « Remboursement intégral » : prix, taxes et livraison ? Retour des lunettes à nos frais ? Délai pour réclamer
   (par exemple 60 jours après la livraison) ?
3. Comment définir objectivement « ne fonctionne pas comme décrit » : fiche de chaque fonction, protocole de
   vérification, configuration minimale de l'ordinateur ?
4. Si une fonction « Disponible » est modifiée ou retirée par une mise à jour, l'engagement s'applique-t-il ?
5. La phrase « En test et Prévu = intention, sans date garantie » est-elle valable face à la LPC ? Où doit-elle
   apparaître pour compter (avant le paiement, dans le contrat) ?

---

## 6. Garantie légale de qualité et de durabilité

**Ce que le site dit aujourd'hui**
- `garantie-retour.html` §1 : « Un bien doit pouvoir servir à l'usage auquel il est normalement destiné et durer
  un temps raisonnable » — conforme à l'esprit de la loi.
- §4 : « Ne sont pas couverts les dommages résultant d'un usage anormal, d'un accident, d'une modification ou
  d'une usure normale au-delà de la durée raisonnable ».
- `lunettes.html` : « Autonomie non chronométrée par VELA : à confirmer. »

**Pourquoi c'est à valider**
- LPC art. 37 et 38 : usage normal et durée raisonnable, compte tenu du prix et de l'usage ; le client peut
  s'adresser au commerçant ou au fabricant (art. 53).
- **La garantie légale de bon fonctionnement (loi 29 de 2023) entre en vigueur le 5 octobre 2026**, avec des
  durées fixées par règlement pour certaines catégories (dont téléphones cellulaires, tablettes, ordinateurs) et
  des obligations d'information (durée affichée près du prix ; mention dans le contrat conclu à distance). Les
  lunettes connectées ne figurent pas dans la liste publiée, mais un règlement peut l'étendre.
- Les lunettes ne font ce qui est annoncé qu'avec IRIS et un ordinateur : l'« usage normal » comprend-il
  qu'IRIS reste compatible pendant une durée raisonnable ? (Rappel : un service du fabricant d'origine a disparu
  le 5 septembre 2026.)
- Pile au lithium : usure prévisible, à traiter clairement.

**Questions à poser**
1. Quelle « durée raisonnable » pour des lunettes connectées à 250 $ ? La pile est-elle couverte au même titre ?
2. La garantie de bon fonctionnement du 5 octobre 2026 s'applique-t-elle à nos lunettes ? Sinon, avons-nous
   d'autres obligations issues de la loi 29 (pièces de rechange, réparation, information) ?
3. Sommes-nous tenus de maintenir IRIS compatible avec les lunettes vendues ? Pendant combien de temps ?
4. Les exclusions du §4 sont-elles acceptables telles qu'écrites ?

---

## 7. Garantie supplémentaire et politique commerciale de retour

**Ce que le site dit aujourd'hui**
- `garantie-retour.html` §3 : « En plus de vos droits légaux, VELA prévoit une politique commerciale de retour et
  d'échange » — mais §5 renvoie au « délai commercial fixé », **qui n'est fixé nulle part**.
- §6 : pour un retour de convenance, « les frais de renvoi sont, sauf indication contraire, à la charge de
  l'acheteur ».
- `conditions-vente.html` §10 : « couverts par les garanties légales prévues par la loi québécoise ».

**Pourquoi c'est à valider**
- Une politique annoncée sans délai est une promesse floue, que le client peut interpréter en sa faveur.
- Si VELA vend un jour une garantie prolongée, la LPC impose d'abord d'informer le client de la garantie légale,
  de façon précise (art. 228.1), avec de nouvelles formalités à partir du 5 octobre 2026.
- L'Édition fondatrice (point 5) et le programme de testeurs pourraient créer des régimes différents : à
  harmoniser.

**Questions à poser**
1. Quel délai commercial de retour fixer, et à partir de quand (réception du colis) ?
2. Retour de convenance d'un objet porté sur le visage : quelles conditions (hygiène, état) sont acceptables ?
3. Si nous offrons une garantie supplémentaire plus tard : quelles mentions et quel formulaire ?

---

## 8. Prix et taxes (TPS, TVQ, TVH)

**Ce que le site dit aujourd'hui**
- `plans.html` : « Un seul versement, taxes en sus » et « Taxes selon votre province ».
- `conditions-vente.html` §4 : taxes « selon le lieu de résidence de l'acheteur et le statut fiscal du
  commerçant » ; abonnements : « Montants indicatifs, à confirmer ».
- `lunettes.html` : page Stripe « les 250 $ déjà remplis ».

**Pourquoi c'est à valider**
- Tant que VELA n'est pas inscrite aux fichiers de la TPS et de la TVQ (seuil du petit fournisseur : 30 000 $ de
  ventes taxables sur quatre trimestres consécutifs), elle ne perçoit pas de taxes. « Taxes en sus » induit alors
  en erreur. Si elle est inscrite, elle doit percevoir les taxes selon la province de livraison et remettre des
  reçus conformes. La feuille de route du 9 septembre note qu'**aucune taxe n'est calculée** par le parcours
  actuel.
- Le prix affiché doit comprendre tous les frais obligatoires, sauf les taxes (LPC ; la Loi sur la concurrence
  vise aussi le « prix partiel »).
- Un prix « indicatif, à confirmer » dans des conditions de vente n'est pas un prix.

**Questions pour le comptable**
1. M'inscrire tout de suite (volontairement) ou rester petit fournisseur pendant le pilote ?
2. Ventes hors Québec : TVH, et taxes provinciales de vente (Colombie-Britannique, Saskatchewan, Manitoba) ?
3. Quelles mentions sur le reçu ?

**Questions pour l'avocat**
4. Si je ne perçois aucune taxe, quelle mention remplace « taxes en sus » ?
5. Les frais de livraison doivent-ils être inclus dans le prix affiché ?

---

## 9. Caméra, micro et vie privée des personnes filmées ou entendues

**Ce que le site dit aujourd'hui**
- `faq.html` et `politique-confidentialite.html` §8 : « Un témoin lumineux s'allume dès que la caméra filme, rien
  ne se fait en cachette. »
- Aucune règle d'utilisation pour l'acheteur, ni dans les conditions de vente, ni dans un document
  d'utilisation.
- Dans le logiciel : un mode traduction où IRIS écoute « la personne en face » ; la reconnaissance d'une langue
  étrangère passe par un service en ligne.

**Pourquoi c'est à valider**
- Code civil du Québec, art. 3, 35 et 36 : capter ou utiliser l'image ou la voix d'une personne dans un lieu
  privé, ou utiliser son nom, son image ou sa voix à d'autres fins que l'information légitime du public, peut
  constituer une atteinte à sa vie privée. Charte des droits et libertés de la personne, art. 5.
- Code criminel : voyeurisme (art. 162) ; interception de communications privées (partie VI).
- Loi 25 : s'applique à VELA dès que VELA traite des images ou des voix (serveur en ligne, testeurs, vidéos).
- Des lunettes à caméra discrète peuvent servir à des usages interdits : examens, lieux de travail, hôpitaux,
  vestiaires ; et la conduite automobile pose ses propres questions.
- Le voyant peut être masqué : « rien ne se fait en cachette » est une promesse absolue.
- Reconnaissance faciale ou empreinte vocale : données biométriques, régime particulier (Loi concernant le cadre
  juridique des technologies de l'information, art. 44 et 45, déclaration à la Commission d'accès à
  l'information). **À ne pas ajouter sans avis.**

**Questions à poser**
1. Quelles règles d'utilisation et mises en garde imposer (conditions d'utilisation, notice dans la boîte, écran
   d'accueil d'IRIS) ?
2. Quelle est ma responsabilité si un client filme quelqu'un à son insu avec nos lunettes ?
3. Mode traduction : la voix de l'interlocuteur est envoyée à un service en ligne. Faut-il son consentement ?
   Faut-il l'avertir, ou retirer la fonction ?
4. Quelle formulation acceptable pour le voyant ?
5. Quelle mise en garde pour la conduite automobile ?

---

## 10. Consentement et conservation des renseignements (Loi 25)

**Ce que le site dit aujourd'hui**
- `politique-confidentialite.html` §4 : « Rien ne quitte votre ordinateur sans un accord donné pour le type de
  donnée concerné. »
- §5 : le serveur de VELA « ne conserve ni vos demandes ni les réponses », garde des compteurs et « les journaux
  techniques habituels d'un serveur » ; il reçoit « un identifiant d'appareil » et le courriel d'achat.
- §10 : formulaire « Prévenez-moi » traité par Netlify Forms. §11 : paiement par Stripe ou Interac — **PayPal,
  offert sur `plans.html`, n'y figure pas**.
- §12 : « Si vous avez moins de 14 ans, n'utilisez pas le logiciel sans l'accord et la supervision d'un parent ».
- `mentions-legales.html` §1 : responsable de la protection des renseignements personnels = Miguel.
- §5 de la politique nomme la voix locale par le nom de son fournisseur (mention existante, conservée : voir la
  question 2).

**Pourquoi c'est à valider**
- Loi sur la protection des renseignements personnels dans le secteur privé (Loi 25) :
  - consentement manifeste, libre, éclairé, donné à des fins précises, demandé fin par fin (art. 14) ;
    consentement **exprès** pour les renseignements sensibles (santé, handicap : programme de testeurs) ;
  - information au moment de la collecte : fins, moyens, droits, tiers ou catégories de tiers, possibilité de
    communication hors Québec (art. 8) ;
  - pour un produit technologique offert au public, paramètres assurant **par défaut** le plus haut niveau de
    confidentialité (art. 9.1) ;
  - moins de 14 ans : consentement du titulaire de l'autorité parentale ;
  - responsable publié (fait), politiques de gouvernance publiées, registre des incidents de confidentialité et
    avis à la Commission d'accès à l'information, destruction à la fin de l'utilité ;
  - évaluation des facteurs relatifs à la vie privée (EFVP) pour tout projet de système d'information ou de
    prestation électronique de services impliquant des renseignements personnels.
- Constat dans le code d'IRIS 0.1.0 : tous les consentements d'envoi sont **désactivés au départ** (bon point à
  documenter). Une fois accordés, le serveur de VELA est « utilisé par défaut ».
- Constat : le registre local peut afficher un identifiant technique qui nomme un fournisseur (reconnaissance
  vocale en ligne) — à confronter au masque de marque comme à l'obligation d'information.
- « Ne conserve pas » doit être vrai aussi chez l'hébergeur du serveur (journaux d'accès).

**Questions à poser**
1. La politique actuelle satisfait-elle l'art. 8 ? Que manque-t-il : durée de conservation des journaux et
   compteurs, pays des serveurs, PayPal, Netlify ?
2. **Masque de marque** : puis-je ne nommer que des catégories de fournisseurs (« un fournisseur d'intelligence
   artificielle tiers ») sans leur nom ? Dois-je garder, ou puis-je retirer, les noms déjà présents dans la
   politique ?
3. Le fonctionnement « serveur VELA par défaut une fois le consentement accordé » respecte-t-il l'art. 9.1 ?
4. Ai-je besoin d'une EFVP pour le serveur en ligne ? Existe-t-il un format simple pour une entreprise d'une
   personne ?
5. Politique de gouvernance et registre des incidents : quel minimum ?
6. Identifiant d'appareil + courriel d'achat : quelle durée de conservation annoncer ?

---

## 11. Transferts hors Québec (service IRIS en ligne)

**Ce que le site dit aujourd'hui**
- `politique-confidentialite.html` §5 : le serveur de VELA transmet les demandes « à un fournisseur
  d'intelligence artificielle tiers (situé hors du Québec) sans les garder ».
- `mentions-legales.html` §4 : « Le fonctionnement d'IRIS dépend de services tiers ».

**Pourquoi c'est à valider**
- Loi 25, art. 17 : **avant** de communiquer des renseignements personnels à l'extérieur du Québec — ou de confier
  leur traitement à quelqu'un hors du Québec —, une EFVP est obligatoire. La communication n'est permise que si
  les renseignements bénéficient d'une protection adéquate, et elle doit faire l'objet d'une **entente écrite**
  qui tient compte de l'évaluation.
- Destinataires probables : fournisseur(s) d'IA ; hébergeur du serveur en ligne ; hébergeur du site et de son
  formulaire ; prestataires de paiement ; service de reconnaissance vocale en ligne (renfort) ; service de
  traduction.
- Selon l'état du 6 septembre, la traduction passait par un point d'accès gratuit non officiel, **sans contrat** :
  aucune entente écrite n'est alors possible.

**Questions à poser**
1. Une EFVP par destinataire, ou une seule pour l'ensemble ? Contenu minimal ?
2. Les conditions standard des fournisseurs (annexes de traitement des données) valent-elles « entente écrite » ?
3. Dois-je désactiver la traduction et la reconnaissance vocale en ligne tant qu'aucun contrat n'existe ?
4. Dois-je indiquer le pays de chaque serveur ?
5. Quand le client utilise sa propre clé auprès d'un fournisseur, VELA communique-t-elle encore des
   renseignements ?

---

## 12. Langue française et accessibilité des conditions

**Ce que le site dit aujourd'hui**
- `conditions-vente.html` §11 : « la version française de ce document fait foi » ; site en français par défaut,
  pages en anglais, espagnol et italien.

**Pourquoi c'est à valider**
- Charte de la langue française (depuis le 1ᵉʳ juin 2023) : un contrat d'adhésion (conditions de vente,
  conditions d'utilisation, licence) doit être remis **d'abord en français** ; une autre langue n'est possible
  qu'à la volonté expresse des parties, après.
- Inscriptions sur le produit, l'emballage, le mode d'emploi et les documents de garantie : en français. La boîte,
  la notice et les messages vocaux intégrés des lunettes du fabricant le sont-ils ?
- Règles resserrées sur les marques de commerce apposées sur les emballages.
- Clarté : la LPC exige des renseignements « évidents et intelligibles », faciles à conserver et à imprimer.

**Questions à poser**
1. Un client arrive par une page anglaise : dans quel ordre présenter les conditions ?
2. Emballage et notice du fabricant : que faut-il franciser (autocollant, notice ajoutée) ?
3. Messages vocaux intégrés aux lunettes en anglais ou en chinois : est-ce un problème ?
4. « VELA » et « IRIS » sur l'emballage : conformes tels quels ?

---

## 13. Verres correcteurs

**Ce que le site dit aujourd'hui**
- `faq.html` : « Écrivez-nous à contact@velaglass.ca : selon votre correction, on regarde ensemble ce qui est
  possible. »

**Pourquoi c'est à valider**
- Au Québec, la vente et l'ajustement de lentilles ophtalmiques sur ordonnance sont réservés aux opticiens
  d'ordonnances et aux optométristes (Loi sur les opticiens d'ordonnances, art. 8 ; Loi sur l'optométrie). Les
  montures seules et les lunettes solaires sans ordonnance restent libres.
- La réponse actuelle peut laisser croire que VELA fournit une solution de correction.
- Santé Canada : des lunettes correctrices peuvent être des instruments médicaux.
- Version solaire (verres teintés) : mentions éventuelles sur la protection et la conduite de nuit.

**Questions à poser**
1. Puis-je écrire « compatible avec des verres faits par votre opticien » ? Que ne dois-je jamais écrire ?
2. Puis-je orienter vers un opticien partenaire ? Une commission est-elle permise ?
3. Des obligations particulières pour la version solaire ?

---

## 14. Certification radio (ISED), sécurité électrique, pile et sécurité du produit

**Ce que le site dit aujourd'hui**
- Aucun numéro de certification (« IC ») nulle part.
- `lunettes.html` : « Un casque Bluetooth, et bien plus. » ; `plans.html` : « Étui de charge USB-C et étui rigide
  compris ».

**Pourquoi c'est à valider**
- Loi sur la radiocommunication et son règlement : un appareil radio visé (le Bluetooth en fait partie) doit être
  certifié avant d'être fabriqué, importé, distribué, **offert en vente** ou vendu au Canada. Une précommande est
  vraisemblablement une offre de vente ; **prêter des lunettes à des testeurs** pourrait être une distribution.
- Normes probables : RSS-247 (Bluetooth), RSS-102 (exposition aux radiofréquences, appareil porté sur la tête),
  ICES-003 (brouillage) ; mentions bilingues dans la notice ; numéro affiché sur l'appareil ou à l'écran.
- La certification du fabricant d'origine vaut-elle pour une revente sous la marque VELA ? (Une inscription du
  modèle sous un autre nom existe chez ISED ; à vérifier.)
- Sécurité électrique : l'étui et tout adaptateur secteur fourni doivent porter une marque de certification
  reconnue au Canada.
- Loi canadienne sur la sécurité des produits de consommation : produits dangereux interdits ; **signalement d'un
  incident dans les 2 jours** ; conservation de documents sur les fournisseurs et les acheteurs.
- Pile au lithium : règles de transport (transporteurs, marchandises dangereuses) ; rapport d'essai UN 38.3 à
  obtenir du fabricant.
- Loi sur l'emballage et l'étiquetage des produits de consommation : étiquette bilingue, identité du fournisseur.
- Assurance responsabilité civile produits avant la première livraison.
- Un laboratoire accrédité ou un consultant en certification ISED répond aux questions techniques ; l'avocat, aux
  questions de responsabilité.

**Questions à poser**
1. Précommander un appareil pas encore certifié au Canada : est-ce « offrir en vente » ? Quels risques ? Une
   liste d'attente sans paiement est-elle permise ?
2. Prêter des lunettes non certifiées à des testeurs : permis ?
3. Quels documents exiger du fabricant (numéro ISED, rapports d'essai, UN 38.3, fiche de sécurité) et quelles
   clauses (garantie de conformité, indemnisation) ?
4. En important sous la marque VELA, suis-je l'importateur responsable (sécurité des produits, douanes) ?
5. Étui USB-C vendu sans adaptateur secteur : certification électrique nécessaire ?
6. Quelle assurance souscrire ?

---

## 15. Service IRIS en ligne, abonnement futur et conditions d'utilisation du logiciel

**Ce que le site dit aujourd'hui**
- `plans.html` : offre « Lunettes + 12 mois Pro — 489,88 $ » avec un bouton « Commander ce forfait », alors que
  « Le service d'IA en ligne du plan Pro » est marqué « Bientôt ».
- `conditions-vente.html` §4 : abonnements « Montants indicatifs, à confirmer » ; §9 : renouvellement automatique
  mensuel.
- `mentions-legales.html` §3 : « Le logiciel IRIS est distribué sous licence propriétaire » — **aucun texte de
  licence ni conditions d'utilisation publiés**.
- `mentions-legales.html` §4 : « notre responsabilité ne saurait excéder les sommes que vous nous avez
  effectivement versées au cours des douze mois précédents » et, à propos des services tiers, « Une interruption
  de leur part peut affecter le service sans que notre responsabilité soit engagée ».
- Même §4 : IRIS « ouvre des applications, écrit des fichiers et exécute des commandes ».

**Pourquoi c'est à valider**
- Vendre 12 mois d'un service qui n'est pas ouvert, c'est encaisser pour une prestation indisponible (art. 41,
  règles du contrat à distance, représentations).
- LPC art. 10 : est interdite la clause par laquelle le commerçant se libère des conséquences de son propre fait ;
  les limitations de responsabilité face à un consommateur sont à valider.
- LPC art. 11.2 : une clause de modification unilatérale (prix, quotas, fonctions) n'est permise qu'avec les
  mentions prévues et un préavis écrit de 30 jours ; les éléments essentiels d'un contrat à durée fixe (nature du
  service, prix, durée) ne peuvent pas être modifiés ainsi.
- À écrire : renouvellement, résiliation, remboursement au prorata, suspension, fin de vie d'une version.
- Des conditions d'utilisation sont nécessaires : usages interdits (caméra, sécurité), responsabilité des actions
  demandées à IRIS, confirmations, mises à jour, clé d'abonnement, services tiers, quotas, accès à distance.
- Les conditions des fournisseurs d'IA exigent souvent de reprendre certaines règles d'usage dans nos propres
  conditions.
- La feuille de route du 9 septembre recommande déjà : pilote = lunettes seules + IRIS gratuite, boutons
  d'abonnement désactivés.

**Questions à poser**
1. Dois-je retirer l'offre « Lunettes + 12 mois Pro » tant que le service n'est pas ouvert ? Que faire pour les
   personnes qui l'auraient déjà payée ?
2. La limitation de responsabilité et la clause « interruption » sont-elles valides, ou faut-il les réécrire ?
3. Contenu minimal des conditions d'utilisation d'IRIS (logiciel gratuit + service en ligne + abonnement) ? Faut-il
   une acceptation dans l'application à l'installation ?
4. Pour changer plus tard les quotas ou les prix : quelle clause, conforme à l'art. 11.2 ?
5. Les « 300 requêtes » du plan Gratuit affichées sur le site sont-elles un engagement ?
6. Accès à distance et pilotage de l'ordinateur : quelle responsabilité en cas d'incident de sécurité ?

---

## 16. Autres points repérés en lisant le site

| Sujet | Constat | Question à poser |
|---|---|---|
| Photos et clips du site | La liste du 6 septembre demande de « régler les droits des 6 photos du site » (accord écrit du fabricant ou clichés propres) ; les 4 clips vidéo du site ont une origine à confirmer | Ai-je une autorisation écrite suffisante pour un usage commercial de chaque image ? |
| Formulaire « Prévenez-moi » et courriels | Adresses recueillies pour « prévenir au lancement » | Loi canadienne anti-pourriel : preuve du consentement, identification de l'expéditeur, désabonnement ? |
| Recyclage | Produit électronique avec pile | Suis-je « premier fournisseur » au Québec au sens du règlement sur la récupération et la valorisation des produits (programme de l'ARPE-Québec, écofrais) ? |
| Marques VELA et IRIS | Noms courants | Faut-il une recherche de disponibilité (Office de la propriété intellectuelle du Canada) avant d'imprimer l'emballage ? |
| PayPal | Offert sur `plans.html`, absent des conditions (§5) et de la politique (§11) | Mettre à jour les deux documents ? |
| Programme « Premiers testeurs » (`docs/PROGRAMME-TESTEURS.md`) | Prêt de lunettes ; autorisations nom, voix, image ; renseignements de santé (profil accessibilité) ; résultats publiés avec l'avantage reçu | Valider le formulaire de consentement et la convention de prêt ; mention du lien avec VELA (Loi sur la concurrence) ? |
| Âge | Conditions : acheteur majeur ; politique : moins de 14 ans avec accord parental | Les deux règles sont-elles cohérentes ? |
| Sécurité de l'accès à distance | Faille du canal de commande relevée le 6 septembre (`docs/ETAT-IRIS-2026-09-06.md`), correction à confirmer | Obligation de mesures de sécurité raisonnables (Loi 25) : bloquant avant tout client ? |

---

## Tableau de synthèse : priorité, risque, action

**P0** = avant de pousser (ou de laisser actifs) les boutons de précommande · **P1** = avant la première
livraison ou avant d'activer la fonction concernée · **P2** = avant d'ouvrir les abonnements payants ·
**P3** = dans les trois mois.

| Priorité | Point | Risque si on n'agit pas | Action concrète | Avec qui |
|---|---|---|---|---|
| **P0** | 4. Promesses du site | Promesses qui lient VELA (LPC 41) ; pratiques trompeuses (LPC 219, Loi sur la concurrence) ; remboursements et plaintes | Corriger les phrases citées ; appliquer les statuts partout ; corriger les notes de version publiques | Équipe site + avocat |
| **P0** | 5. Édition fondatrice | Garantie mal formée ; promesse plus large que voulue | Faire valider le texte **avant** de le publier | Avocat |
| **P0** | 2. Contrat à distance | Contrats résolubles (LPC 54.8) ; plainte à l'OPC | Afficher délai, frais, conditions et case d'acceptation **avant** paiement ; remplacer le gabarit du §8 ; modèle de courriel-contrat | Avocat + équipe site |
| **P0** | 3. Précommande | Résolution à 30 jours et remboursement à 15 jours ; fonds déjà dépensés ; Interac sans recours | Date de livraison écrite et réaliste, ou liste d'attente sans paiement ; décider du sort d'Interac | Avocat + Miguel |
| **P0** | 1. Identité du vendeur | Renseignements obligatoires manquants ; responsabilité personnelle illimitée | Immatriculation REQ, adresse d'affaires, choix de structure, mise à jour des 5 pages | Avocat (+ comptable) |
| **P0** | 14. Certification ISED | Offre en vente d'un appareil non certifié ; retrait du marché | Obtenir du fabricant le numéro et les rapports ; sinon suspendre l'encaissement | Fabricant + laboratoire + avocat |
| **P0** | 15. Offre « + 12 mois Pro » | Encaissement d'un service non disponible | Retirer ou suspendre l'offre ; rembourser ou proposer une solution à qui l'a payée | Miguel + avocat |
| **P0** | 8. Taxes | « Taxes en sus » trompeur ; perception illégale ou oubli de perception | Décision fiscale ; corriger la mention et le parcours | Comptable |
| **P1** | 10. Loi 25 — consentement, conservation | Plainte à la CAI ; non-conformité de la politique | Compléter la politique (durées, pays, PayPal, Netlify) ; registre des incidents ; trancher la question du masque de marque | Avocat |
| **P1** | 11. Transferts hors Québec | Communication illégale hors Québec | EFVP + ententes écrites ; suspendre les services sans contrat | Avocat |
| **P1** | 9. Caméra et vie privée | Poursuites de tiers ; atteinte à la réputation | Conditions d'utilisation, mises en garde, formulation du voyant ; statut du mode traduction | Avocat |
| **P1** | 6. Garantie légale et loi 29 | Réclamations ; obligations nouvelles au 5 octobre 2026 | Fixer la durée raisonnable ; plan de compatibilité logicielle ; vérifier la loi 29 | Avocat |
| **P1** | 7. Retours commerciaux | Politique floue interprétée contre VELA | Fixer le délai et les conditions | Avocat |
| **P1** | 12. Langue française | Contrats et emballages non conformes ; sanctions | Ordre des langues pour les conditions ; franciser boîte, notice et garantie | Avocat + fabricant |
| **P1** | 13. Verres correcteurs | Exercice illégal d'un acte réservé ; promesse non tenable | Réécrire la réponse de la FAQ ; orienter vers un opticien | Avocat |
| **P1** | 14 bis. Sécurité produit, pile, assurance | Incident non signalé ; transport refusé ; dommages non assurés | Procédure de signalement 2 jours ; UN 38.3 ; assurance produits | Fabricant + courtier |
| **P1** | 16. Droits photos, anti-pourriel, recyclage, testeurs | Violation de droits d'auteur ; amendes ; écofrais | Autorisations écrites ; preuves de consentement ; inscription si requise ; formulaires validés | Avocat |
| **P2** | 15. Conditions d'utilisation et abonnements | Clauses nulles (LPC 10, 11.2) ; litiges | Rédiger conditions d'utilisation, licence, abonnement ; acceptation dans l'application | Avocat |
| **P3** | 16. Marques VELA et IRIS | Conflit de marque après investissement | Recherche de disponibilité, puis dépôt | Agent de marques ou avocat |
