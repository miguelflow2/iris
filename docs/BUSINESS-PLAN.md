# Plan d'affaires — VELA / IRIS

**Version de travail — 2026-09-10**
Marque : VELA · Produit logiciel : IRIS · Fondateur : Miguel Goufack · Entreprise **canadienne**, basée à Trois-Rivières (Mauricie), Canada · Site : velaglass.ca

> **Règle d'honnêteté de ce document.** VELA se vend sur la transparence vérifiable. Ce plan respecte la même règle en interne : **aucun chiffre de vente, de revenu, de marché ou de coût n'est présenté comme un fait**. Tout chiffre non établi est marqué **« Hypothèse — à valider »** ou **« [À COMPLÉTER par Miguel : … ] »**. Les projections sont un **scénario illustratif**, pas une prévision. Elles servent à raisonner, pas à promettre.

---

## 1. Résumé exécutif

VELA est une jeune entreprise canadienne qui conçoit des **lunettes intelligentes** (audio + caméra, photo et vidéo mains libres, sans écran) reliées en Bluetooth à l'ordinateur, et **IRIS**, une assistante vocale qui tourne **sur l'ordinateur de l'utilisateur** et se pilote à la voix (« Dis-moi Iris »).

Le positionnement tient en une idée : **une IA que l'on peut vérifier, pas seulement croire.** Les conversations, la mémoire, les photos et le registre d'activité restent sur la machine de l'utilisateur. La voix française fonctionne hors ligne. Le produit est pensé et écrit en français, au Canada. Et il est conçu dès l'origine pour l'accessibilité : piloter l'ordinateur entièrement à la voix, ou se faire lire l'écran à voix haute.

Le modèle d'affaires sépare deux choses :

- **Le matériel** — les lunettes VELA à **250 $ CAD**, paiement unique, sans abonnement forcé ;
- **Le logiciel** — IRIS, gratuite à l'installation, avec des **abonnements mensuels** (Pro 19,99 $, Premium 29,99 $, Entreprise 99,99 $) qui débloquent un service d'IA en ligne plus capable et des quotas plus larges.

**État au 2026-09-10.** IRIS 0.1.0 fonctionne sur Windows 10/11 (contrôle vocal du PC, mémoire locale, voix française hors ligne, registre de confidentialité). L'infrastructure du service d'IA en ligne (le « relais ») est déployée ; l'ouverture commerciale des paliers payants suit. La première série de lunettes est en préparation. Chantiers réglementaires et opérationnels en cours : vérification d'identité du compte de paiement (KYC), immatriculation au Registre des entreprises du Québec (NEQ), certification radio des lunettes (ISED), et un différend juridique avec un concurrent.

**Ce que ce plan demande de décider.** Voir la section 11 (Besoins). Les deux décisions qui conditionnent tout le reste sont le **coût d'achat unitaire réel des lunettes** (devis fournisseur) et le **capital de départ disponible**.

---

## 2. Problème et solution

### Le problème

- **Les objets qui nous écoutent et nous filment demandent une confiance aveugle.** Lunettes, enceintes, assistants : on promet que rien n'est conservé ou envoyé, mais l'utilisateur n'a aucun moyen de le vérifier lui-même. La méfiance est documentée et croissante (encadrement des caméras portées, débats sur les assistants vocaux).
- **L'assistance vocale grand public est anglophone d'abord.** Le français canadien est souvent une traduction tardive, et la voix de synthèse dépend d'un nuage.
- **L'accessibilité est traitée comme une option.** Piloter un ordinateur entièrement à la voix, ou se le faire lire à voix haute, reste difficile, cher ou fragmenté pour une personne à basse vision ou à mobilité réduite.

### La solution

IRIS répond à chacun de ces points par une décision d'architecture, pas par une promesse marketing :

| Problème | Réponse VELA / IRIS |
|---|---|
| Confiance aveugle | **Traitement local par défaut** + **registre d'activité vérifiable** (chaque capture et chaque envoi est inscrit ; l'utilisateur vérifie lui-même l'intégrité d'un clic) + indicateur de capture visible + consentement par type de donnée |
| Assistant anglophone | **Voix française locale**, conçue en français, fonctionnant **hors ligne** dès le plan gratuit |
| Accessibilité en option | **Pilotage 100 % à la voix** (aucun clic obligatoire) et **lecture de l'écran à voix haute** — au cœur du produit, pas en périphérie |
| Méfiance envers la caméra | Caméra **qui ne se déclenche qu'à la demande**, **témoin lumineux** quand elle filme, **images rangées sur l'ordinateur** de l'utilisateur, jamais dans un nuage |

---

## 3. Produit

### 3.1 Les lunettes VELA

Monture sobre, deux versions (verres transparents ou teintés), fabriquée à partir d'un modèle fournisseur personnalisé aux couleurs de VELA.

- **Micro et son** : l'ordinateur voit les lunettes comme un casque Bluetooth. IRIS écoute par le micro et répond dans l'oreille ; elles servent aussi d'écouteurs pour n'importe quelle application.
- **Caméra intégrée** : photo et vidéo mains libres, à la voix (« Dis-moi Iris, prends une photo »). Un **témoin lumineux** s'allume quand elle filme. Les images se rangent **sur l'ordinateur** de l'utilisateur.
- **Aucun écran.** Rien ne s'affiche dans les verres.
- **Connexion Bluetooth**, reconnexion automatique mémorisée.
- **Étui de charge** (USB-C, câble fourni) + étui rigide de transport.

> **Note d'honnêteté produit.** Le site VELA n'affiche que ce qui a été constaté sur l'exemplaire en main ; ce qui n'a pas été mesuré (poids, autonomie chronométrée, résistance à l'eau) est explicitement laissé « à confirmer ». Ce plan reprend la même prudence.

### 3.2 IRIS (le logiciel)

Application de bureau installable, gratuite. Mot d'éveil **« Dis-moi Iris »**, puis dialogue de suivi sans répéter le mot.

- **Contrôle de l'ordinateur à la voix** : ouvrir une application, chercher un fichier, écrire, lancer, rappeler.
- **Routines et rappels**, **mémoire gardée sur l'appareil** (préférences, décisions).
- **Voix française locale** (hors ligne).
- **Confidentialité** : conversations, mémoire et registre restent sur l'ordinateur ; consentement par type de donnée ; indicateur de capture ; mode confidentiel.
- **Selon le plan** : modèles d'IA en ligne plus capables, navigation web avec comptes enregistrés, contrôle complet de l'écran (lecture à voix haute, clic par libellé), tâches de fond et résumé quotidien.

**Plateformes.** Windows 10/11 aujourd'hui (IRIS 0.1.0). macOS et Linux sont au plan de route (une bonne partie du code s'y prête ; restent l'empaquetage et les essais par système).

---

## 4. Marché et concurrence

### 4.1 Taille du marché — ordres de grandeur, à valider

> **Hypothèse — à valider.** Les chiffres ci-dessous sont des **ordres de grandeur** à confirmer auprès de sources primaires. Ne pas les citer comme des faits avant vérification.

- **Lunettes intelligentes (monde).** Catégorie en forte croissance, tirée par l'arrivée de produits grand public à caméra. Ordre de grandeur des prévisions du secteur : **plusieurs milliards de dollars US**, avec une croissance annuelle élevée. *À sourcer (ex. IDC, Grand View Research, Statista) avant tout usage public.*
- **Assistance et accessibilité (Canada).** Le marché pertinent pour VELA n'est pas « toutes les lunettes intelligentes » mais l'intersection **francophones + soucieux de vie privée + besoins d'accessibilité**. Pour dimensionner le volet accessibilité, sources à consulter : **Statistique Canada** (incapacités visuelles et motrices), **INCA/CNIB**, **Institut Nazareth et Louis-Braille**, **Institut de la statistique du Québec**. *À compléter avec des chiffres sourcés.*

**Marché adressable, raisonné (pas chiffré).** VELA ne vise pas à battre les géants sur le volume mondial. Son marché initial est une **niche défendable** : les francophones du Canada qui veulent une IA locale et vérifiable, les personnes en situation de handicap pour qui le pilotage vocal est un moyen d'autonomie, et les organismes qui les accompagnent. L'expansion (reste du Canada, international francophone) vient ensuite.

### 4.2 Concurrence

| Concurrent | Ce qu'il fait | Forces | Limites face à VELA |
|---|---|---|---|
| **Relay** (Les campagnes Jappuie inc., relay.glass) | Lunettes + IA, caméra, code ouvert | Produit en vente, prix matériel bas (~**299 $ US**, *à revérifier — prix concurrent variable*), code open source, communauté | Anglophone, orchestration d'agents comme cœur de promesse, pas de preuve d'exécution vérifiable par l'utilisateur non-programmeur, pas de positionnement accessibilité francophone |
| **Ray-Ban Meta** | Lunettes caméra grand public | Marque, distribution mondiale, matériel | Modèle économique fondé sur la donnée ; inquiétudes documentées sur l'information des personnes filmées ; VELA ne joue pas dans cette catégorie de volume |
| **Lunettes audio génériques** (type Dymesty et OEM divers) | Audio Bluetooth sans logiciel propre | Nombreuses, peu chères | Pas de logiciel, pas d'assistant, pas de gouvernance |

#### Analyse du concurrent direct : Relay

Relay est le concurrent qu'un interlocuteur informé citera en premier. Il faut le traiter en face, **en interne** (il n'apparaît pas dans le discours public de VELA).

- **Ne pas se battre sur son terrain.** Le prix du matériel seul et l'open source sont *ses* arguments ; il les a pris en premier. Les reprendre, c'est perdre.
- **Déplacer la question.** Le code ouvert dit *ce que le logiciel est censé faire* — encore faut-il savoir programmer. Le **registre vérifiable** de VELA dit *ce que l'appareil a réellement fait*, et n'importe qui le vérifie d'un clic. C'est une **preuve d'exécution**, pas une promesse de conception. C'est le seul terrain où VELA est seule.
- **Les autres axes propres à VELA** : le **local intégral** (données, photos, mémoire sur la machine), le **français/Canada**, l'**accessibilité** comme raison d'être, et un **prix matériel accessible** (250 $ CAD, paiement unique).
- **Modèles d'affaires différents.** Relay vend surtout un objet. VELA vend un **logiciel qui s'améliore** (abonnement) plus un matériel à prix unique. Ce ne sont pas deux versions du même produit.

> **Différend juridique.** Un différend oppose VELA à ce concurrent. Il relève du privé, ne se plaide pas en public, et n'a pas sa place dans le discours client (voir Risques, §10). En interne : documenter, cloisonner, et ne jamais en faire un argument de vente.

### 4.3 Avantages concurrentiels durables

1. **La preuve, pas la promesse** — registre d'activité vérifiable par l'utilisateur lui-même.
2. **Le local** — rien ne part dans un nuage par défaut ; un atout de confiance *et* de coût (pas de serveur d'inférence pour le plan gratuit).
3. **Le français et le Canada** — conçu ici, en français d'abord, avec une vraie personne qui répond.
4. **L'accessibilité native** — un segment mal servi pour qui la voix est un moyen, pas un confort.

---

## 5. Modèle d'affaires et prix

Deux sources de revenus **séparées et complémentaires** :

### 5.1 Matériel — les lunettes

- **250 $ CAD, paiement unique** (taxes en sus). Aucun abonnement rattaché : elles fonctionnent dès le plan gratuit d'IRIS.
- Paiement par carte (Stripe) ou virement **Interac**. La monture choisie et la livraison se règlent ensuite par courriel, avec une personne.

### 5.2 Logiciel — abonnements IRIS (par mois, CAD, taxes en sus)

| Plan | Prix / mois | Requêtes / mois | Voix | Ce que le plan ajoute |
|---|---|---|---|---|
| **Gratuit** | 0 $ | 300 | Française **locale, hors ligne** | Contrôle du PC à la voix, routines, rappels, mémoire, **toute la confidentialité** — dès l'installation |
| **Pro** | 19,99 $ | 600 | Naturelle, en ligne *(bientôt)* | + modèles d'IA plus capables, navigation web avec comptes enregistrés |
| **Premium** | 29,99 $ | 1 000 | Naturelle, en ligne *(bientôt)* | + raisonnement et code avancés, contrôle complet de l'écran, résumé quotidien |
| **Entreprise** | 99,99 $ | 1 500 | Naturelle, en ligne *(bientôt)* | + modèle le plus capable, gouvernance d'entreprise *(à venir)* |

**Principes tarifaires.**

- Le **plan gratuit sert vraiment** : il n'est pas une démo bridée. C'est la porte d'entrée et la preuve de confiance.
- Les quotas **s'arrêtent proprement** à la limite (alerte à 80 % et 95 %, arrêt annoncé au-delà) : **pas de facture surprise**. C'est cohérent avec la marque.
- La distinction entre paliers est **la capacité du modèle et le quota**, pas un sabotage artificiel des plans bas.
- **Organismes / volume** : offre de commande groupée à négocier par courriel (voir §7 et §11).

---

## 6. Économie unitaire (avec hypothèses étiquetées)

> Toutes les valeurs non décidées ci-dessous sont des **hypothèses** ou des **[À COMPLÉTER]**. Elles reprennent la structure du modèle financier de Miguel (`docs/finance/VELA-IRIS-plan-financier.xlsx`), où les mêmes postes sont déjà marqués comme hypothèses à remplacer par des devis réels.

### 6.1 Matériel (par paire de lunettes)

| Poste | Valeur | Statut |
|---|---|---|
| Prix de vente public | **250,00 $ CAD** (hors taxes) | **Décidé** |
| Coût d'achat OEM (lunettes caméra + audio) | **[À COMPLÉTER par Miguel : coût unitaire réel — devis fournisseur]** | À obtenir |
| — ordre de grandeur d'hypothèse | ~45 à 205 US$ / unité selon volume et composants | Hypothèse — à valider (relevés de places de marché B2B) |
| Fret + assurance par unité | **[À COMPLÉTER]** | Hypothèse — à valider |
| Droits de douane + courtage | **[À COMPLÉTER]** (vérifier le code SH auprès de l'ASFC ; certains codes à 0 %) | Hypothèse — à valider |
| Réserve garantie (1 an) | **[À COMPLÉTER]** (hyp. ~4 % de taux de défaut) | Hypothèse — à valider |
| **Coût rendu entrepôt** | **[À COMPLÉTER — somme des postes ci-dessus]** | Dépend du devis |
| **Marge brute matériel** | Cible **45 %** (levier fixé par Miguel ; standard électronique grand public 35–50 %) | Hypothèse — à valider |

> **Lecture prudente.** Tant que le coût OEM réel n'est pas connu, on ne peut pas affirmer la marge. À titre **purement illustratif**, une marge cible de 45 % sur 250 $ laisserait un coût rendu d'environ 137 $ CAD et une marge brute d'environ 113 $ CAD par paire — **à confirmer uniquement par le devis réel**. Le matériel doit être au minimum **non déficitaire** ; il n'est pas le moteur de rentabilité, le logiciel l'est.

### 6.2 Abonnements (par utilisateur payant, par mois)

| Poste | Valeur | Statut |
|---|---|---|
| Prix (Pro / Premium / Entreprise) | 19,99 / 29,99 / 99,99 $ | Décidé |
| Coût variable par utilisateur (service d'IA en ligne + voix en ligne) | **[À COMPLÉTER — mesure réelle par la consommation]** | Hypothèse — à valider |
| Plafond du coût variable | **Borné par le quota mensuel** (arrêt à la limite) | Mécanisme en place |
| Coût marginal du plan gratuit | ≈ 0 (voix locale hors ligne + modèles gratuits, à débit limité) | Établi par conception |

> **Pourquoi le logiciel est le moteur.** Le backend d'IRIS tourne **chez l'utilisateur** : il n'y a pas de serveur d'inférence à payer pour le plan gratuit. Pour les plans payants, le seul coût variable est l'accès au service d'IA en ligne et à la voix naturelle, **plafonné par le quota**. La marge d'un abonnement dépend donc de la consommation réelle vs le prix — à mesurer dès l'ouverture commerciale, puis à ajuster. C'est le levier n° 1 de rentabilité, et il est pilotable.

### 6.3 Coûts fixes mensuels (structure, hypothèses)

D'après le modèle de Miguel, les coûts fixes sont volontairement **légers** (entreprise solo, backend local) : hébergement léger + domaine + courriel, outils (Stripe, certificat de signature de code Windows amorti), comptabilité / assurance / frais bancaires, et un budget marketing de démarrage. **Montants exacts : [À COMPLÉTER par Miguel]** — les valeurs du tableur sont des hypothèses de démarrage à figer.

---

## 7. Stratégie de mise en marché (go-to-market)

**Le pilote = lunettes + IA, vendus ensemble, à petite échelle, auprès de gens qui répondent.**

1. **Phase pilote (premier lot).** Un nombre **limité** de paires (quantité **[À COMPLÉTER]**), vendues à des **early adopters** et à quelques **utilisateurs accessibilité** volontaires. Objectif : prouver la chaîne complète (commande → paiement → livraison → usage réel → retour), pas maximiser le volume. Chaque commande est suivie à la main, par courriel, par Miguel.
2. **Canaux d'amorçage.** Le site velaglass.ca (vente directe), les réseaux sociaux (Instagram, LinkedIn, YouTube), le bouche-à-oreille, et des **contacts directs avec des organismes** (CLSC, centres de réadaptation, programmes d'aide technique, employeurs). Voir le Plan marketing pour le détail.
3. **Preuve avant promesse.** La démonstration du registre vérifiable et du pilotage 100 % vocal est l'argument central, en vidéo et en personne.
4. **Organismes et volume.** Une fois le pilote validé, approcher les organismes pour des **commandes groupées** (matériel + plan adapté). Rien n'est signé de ce côté aujourd'hui ; c'est un axe à ouvrir honnêtement (« on regarde ensemble »).
5. **Expansion.** Le Canada francophone d'abord, puis anglophone, puis international francophone — à mesure que macOS/Linux et le service en ligne s'ouvrent.

---

## 8. Feuille de route

> Reprise de la page publique « Feuille de route ». Les trimestres cibles ne sont **pas arrêtés** et sont marqués comme tels — cohérent avec la règle « pas de date qu'on n'est pas sûr de tenir ».

| État | Éléments |
|---|---|
| **Fait** (IRIS 0.1.0) | Contrôle vocal du PC · mot d'éveil « Dis-moi Iris » + dialogue de suivi · routines et rappels · mémoire sur l'appareil · voix française locale hors ligne · confidentialité (conversations/mémoire/registre locaux) |
| **En cours** | Installateur Windows avec voix embarquée (un clic) · service d'IA en ligne (ce qui distingue les paliers payants) · première série de lunettes |
| **Prévu** (trimestre **[À COMPLÉTER]**) | Ouverture publique des paliers payants · mode 100 % local et autonome · gouvernance d'équipe (Entreprise) · macOS et Linux |

**Jalons réglementaires et opérationnels à intégrer au calendrier** (voir Risques) : KYC du compte de paiement, immatriculation REQ (NEQ), certification radio ISED des lunettes.

---

## 9. Équipe

**Fondateur solo : Miguel Goufack** (Trois-Rivières / Mauricie). Conçoit le produit, écrit le logiciel, tient le site, répond lui-même aux courriels.

- **Force** : cohérence totale entre le discours et le produit ; coûts de structure minimes ; décisions rapides.
- **Limite à gérer** : point de défaillance unique (temps, santé, compétences). **Besoins de renfort à prévoir** : soutien comptable/juridique (déjà un poste de coût fixe), et, à terme, aide sur le support client, la logistique d'expédition et le développement multiplateforme.
- **[À COMPLÉTER par Miguel]** : conseillers, mentors, ou partenaires éventuels ; statut juridique visé (entreprise individuelle vs société par actions).

---

## 10. Risques et atténuations

| Risque | Description | Atténuation |
|---|---|---|
| **KYC / paiement** | L'activation du compte Stripe (et des paliers payants) dépend d'une vérification d'identité et d'entreprise non terminée | Prioriser la complétion du KYC ; garder **Interac** comme moyen de paiement de repli ; ne pas annoncer les paliers payants comme ouverts tant qu'ils ne le sont pas (déjà le cas : mention « bientôt ») |
| **Certification ISED** | Les lunettes émettent en Bluetooth : la mise en marché au Canada exige la conformité radio (ISED) | Traiter la certification comme un **préalable à l'expédition** ; obtenir du fournisseur les rapports/ID existants ; budgéter délais et coûts **[À COMPLÉTER]** |
| **Immatriculation REQ (NEQ)** | Statut légal de l'entreprise à finaliser | Compléter l'immatriculation ; aligner facturation, taxes (TPS/TVQ) et conditions de vente |
| **Différend avec un concurrent** | Un différend juridique est en cours | Le **cloisonner du produit et du discours public** ; documenter ; conseil juridique ; ne jamais en faire un argument de vente (voir §4.2) |
| **Dépendance à un fournisseur d'IA tiers** | Les paliers payants reposent sur un service d'IA en ligne opéré par un tiers (prix, disponibilité, conditions hors du contrôle de VELA) | Ne **nommer aucun fournisseur** dans le discours client ; concevoir le routage pour pouvoir **changer de fournisseur** ; le plan gratuit reste utile **sans** dépendance en ligne ; le **mode 100 % local** (feuille de route) réduit structurellement cette dépendance |
| **Matériel et expédition** | Qualité, délais, taux de défaut, douane, logistique d'un fabricant lointain | Lot pilote **petit** ; réserve garantie provisionnée ; suivi de commande manuel ; devis et codes de douane vérifiés avant engagement |
| **Hébergement / infrastructure** | Le relais et le site doivent rester disponibles | Backend d'inférence **chez l'utilisateur** (réduit la surface) ; hébergement léger ; sauvegardes ; surveillance |
| **Point de défaillance unique (solo)** | Tout repose sur une personne | Procédures documentées ; automatisation ; renforts progressifs (§9) |
| **Promesse vs réalité** | Le risque de marque le plus grave pour VELA serait de survendre | Règle déjà appliquée : ne déclarer que ce qui est livré, marquer « à venir » le reste, laisser les dates « à compléter » quand elles ne sont pas sûres |

---

## 11. Besoins — ce que Miguel doit décider ou fournir

| # | Décision / donnée | Pourquoi c'est bloquant |
|---|---|---|
| 1 | **Coût d'achat unitaire réel des lunettes** (devis fournisseur, par palier de volume) | Conditionne toute l'économie unitaire du matériel et le prix plancher |
| 2 | **Capital de départ disponible** | Détermine la taille du premier lot et le budget marketing |
| 3 | **Taille du premier lot** (nombre de paires) | Pilote vs stock ; engagement financier |
| 4 | **Budgets et délais de certification ISED** | Préalable légal à l'expédition |
| 5 | **Statut juridique (REQ/NEQ) et fiscalité** (TPS/TVQ) | Facturation et conformité |
| 6 | **Coûts fixes mensuels réels** (hébergement, outils, compta, marketing) | Seuil de rentabilité |
| 7 | **Coût variable mesuré par utilisateur payant** (service d'IA + voix en ligne) | Marge réelle des abonnements |
| 8 | **Trimestres cibles** de la feuille de route | Crédibilité du calendrier |
| 9 | **Politique organismes / volume** (remises, conditions) | Ouvre le canal B2B |

---

## 12. Projections financières — SCÉNARIO illustratif (pas une prévision)

> **Avertissement.** Ce qui suit est un **exemple de raisonnement**, construit sur des **hypothèses explicites**. Aucun chiffre n'est une donnée réelle ni une promesse. Les cases **[À COMPLÉTER]** doivent être remplies avant tout usage (banque, investisseur, subvention). Tant qu'elles le sont, **ne présenter ce tableau à personne comme une prévision.**

### Hypothèses du scénario (toutes « à valider »)

- Prix lunettes : 250 $ CAD (décidé). Coût rendu et marge matériel : **[À COMPLÉTER]** (voir §6.1).
- Prix abonnements : 19,99 / 29,99 / 99,99 $ (décidé). Coût variable par abonné : **[À COMPLÉTER]**.
- Volumes (paires vendues, abonnés par palier, taux de conversion du gratuit vers payant) : **[À COMPLÉTER — aucune de ces valeurs n'est connue]**.
- Coûts fixes mensuels : **[À COMPLÉTER]**.

### Forme du modèle (à remplir avec les vraies valeurs)

| Ligne | Formule | Valeur |
|---|---|---|
| Revenu matériel (mois) | paires vendues × 250 $ | [À COMPLÉTER] |
| Marge brute matériel | paires × (250 $ − coût rendu) | [À COMPLÉTER] |
| Revenu abonnements (mois) | Σ (abonnés par palier × prix) | [À COMPLÉTER] |
| Marge brute abonnements | revenu − (abonnés × coût variable) | [À COMPLÉTER] |
| Coûts fixes (mois) | hébergement + outils + compta + marketing | [À COMPLÉTER] |
| **Résultat mensuel** | marges brutes − coûts fixes | [À COMPLÉTER] |
| **Seuil de rentabilité** | nombre d'abonnés payants (+ ventes matériel) qui couvre les coûts fixes | [À COMPLÉTER] |

> Le fichier `docs/finance/VELA-IRIS-plan-financier.xlsx` contient déjà cette structure avec les cellules d'entrée en bleu (et en jaune pour les leviers clés). **C'est là qu'il faut saisir les vraies valeurs**, pas ici.

---

*Document de travail interne. À mettre à jour à chaque décision prise (voir §11). La crédibilité de VELA repose sur le fait que ce plan ne contient aucun chiffre inventé : garder cette discipline.*
