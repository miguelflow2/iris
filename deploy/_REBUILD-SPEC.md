# VELA — contrat de refonte (2026-09-09)

Ce document est le **contrat partagé** pour la refonte totale du site VELA. Chaque agent
qui reconstruit une page part de ce fichier. `index.html` est déjà refaite : elle sert de
**page de référence** — copiez-en les patrons (hero, cartes, bandes, actions).

## Règles d'or

- **On garde** : le nom « VELA », le **logo** (la voile, mêmes chemins SVG, mêmes classes
  `.voile/.v-foc/.v-grand` — ne pas changer l'image ni le favicon), le nom de l'assistante
  « IRIS », les **noms de fichiers** et tous les **liens internes**.
- **Beaucoup moins de texte.** Court, humain, scannable. Phrases brèves. On coupe le gras
  rédactionnel de l'ancien site. Une section = une idée + 2 à 4 phrases max.
- **Français d'abord**, ton québécois, chaleureux, honnête.
- **Interdit** : toute mention de Relay / RelayGlass / relay.glass / @RelayGlass (aucun lien
  X nulle part — ni pied de page, ni JSON-LD). Interdit aussi de réutiliser les formules du
  concurrent (« your AI all day », « hears your day », « remembers it », « gets things done »,
  « say its name », « answers in your ear », « all day ») **et** l'ancien slogan VELA « des
  lunettes qui vous écoutent, sans jamais vous regarder ».
- **Honnêteté** : rien de faux (pas d'autonomie chiffrée non mesurée, pas d'avis, pas de faux
  témoignages). Garder les mentions **« Bientôt »** là où le service d'IA en ligne n'est pas
  prêt, et le bandeau Beta en tête de page.
- **Cache** : la CSS/JS sont référencées en `?v=8`. Si vous modifiez `assets/style.css` ou
  `assets/site.js`, incrémentez le `?v=` **dans toutes les pages à la fois**.
- **Thème clair et sombre** : géré entièrement par la CSS (préférence système). Ne rien coder.
- **Différenciateurs à mettre en avant** (VELA ≠ concurrent) : aucune caméra (les lunettes
  écoutent, ne filment pas) ; fabriqué au Québec, en français ; IRIS tourne **chez vous**
  (données locales, vie privée) ; voix française locale (Piper) ; **250 $ CAD, un seul paiement**.

---

## 1. Slogan et voix

**Trois slogans proposés :**
1. « Votre voix donne le cap. IRIS tient la barre. »  ← **RETENU**
2. « Une assistante à bord, jamais un œil sur vous. »
3. « Prenez le large. Vos données restent à quai. »

**Slogan retenu (à utiliser partout) :**

```
Votre voix donne le cap. IRIS tient la barre.
```

**La voix / le ton.** On parle comme un artisan québécois qui tient à sa parole : chaleureux,
direct, sans jargon ni superlatif. On dit ce qui est vrai et on nomme ce qui n'existe pas
encore. On file la métaphore maritime avec légèreté (cap, voile, barre, quai, vent) sans en
abuser — jamais plus d'une image par section. On tutoie l'idée, on vouvoie le lecteur.
Phrases courtes, verbes concrets, zéro remplissage.

---

## 2. `<head>` partagé (EXACT)

Collez ce bloc au début de chaque page. Remplacez **uniquement** les trois repères
`{{…}}` : `{{TITRE}}`, `{{DESCRIPTION}}`, `{{CHEMIN}}` (ex. `lunettes.html`, ou vide pour
l'accueil). Ajoutez le `<script type="application/ld+json">` seulement là où il a un sens
(accueil, fiches produit) et **sans jamais de lien X**.

```html
<!DOCTYPE html>
<html lang="fr-CA">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{{TITRE}}</title>
<meta name="description" content="{{DESCRIPTION}}">
<link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 158 158'><rect width='158' height='158' rx='34' fill='%231B140E'/><g transform='translate(31.9 17) scale(0.785)'><path d='M 36.5 46.3 L 36.6 158 L 0 158 Z' fill='%23B36B3B'/><path d='M 41.4 0 C 93.3 52.6 115 105.2 120 157.8 Q 80.4 149.2 41.4 158 Z' fill='%23F8F0E7'/></g></svg>">
<link rel="canonical" href="https://velaglass.ca/{{CHEMIN}}">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Fraunces:ital,opsz,wght@0,9..144,400..600;1,9..144,400..600&family=Mulish:wght@400;500;600;700;800&display=swap">
<link rel="stylesheet" href="assets/style.css?v=8">
<meta property="og:type" content="website">
<meta property="og:site_name" content="VELA">
<meta property="og:locale" content="fr_CA">
<meta property="og:title" content="{{TITRE}}">
<meta property="og:description" content="{{DESCRIPTION}}">
<meta property="og:url" content="https://velaglass.ca/{{CHEMIN}}">
<meta property="og:image" content="https://velaglass.ca/assets/photos/lunettes-fond-sombre.jpg">
<meta property="og:image:width" content="900">
<meta property="og:image:height" content="900">
<meta property="og:image:alt" content="Lunettes VELA">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="{{TITRE}}">
<meta name="twitter:description" content="{{DESCRIPTION}}">
<meta name="twitter:image" content="https://velaglass.ca/assets/photos/lunettes-fond-sombre.jpg">
</head>
```

**Titres/descriptions par page** (format `{{TITRE}}` — court, distinctif) :

| Page | `{{TITRE}}` |
|---|---|
| index.html | `VELA — Votre voix donne le cap` |
| lunettes.html | `Les lunettes VELA` |
| fonctionnalites.html | `Ce qu’IRIS fait — VELA` |
| plans.html | `Plans et prix — VELA` |
| installer.html | `Installer IRIS — VELA` |
| contact.html | `Nous joindre — VELA` |
| suivi.html | `Suivre ma commande — VELA` |
| merci.html | `Merci — VELA` |
| confidentialite.html | `Confidentialité — VELA` |
| politique-confidentialite.html | `Politique de confidentialité — VELA` |
| mentions-legales.html | `Mentions légales — VELA` |
| conditions-vente.html | `Conditions de vente — VELA` |
| garantie-retour.html | `Garantie et retour — VELA` |

---

## 3. `<body>` d'ouverture : lien d'évitement + bandeau Beta (EXACT)

```html
<body>
<a class="skip" href="#contenu">Aller au contenu</a>

<div class="beta-banner">
  <div class="wrap"><b>Beta</b> — le service d’IA en ligne se déploie&nbsp;; certaines réponses ne sont pas encore disponibles.</div>
</div>
```

---

## 4. `<header>` + navigation (EXACT)

Sur la page courante, ajoutez `aria-current="page"` au lien correspondant. Le lien
« Contact » garde la classe `nav-cta`. Le menu mobile est piloté par `assets/site.js`
(bouton `.nav-toggle` + `#nav`) — ne pas y toucher.

```html
<header class="site-head">
  <div class="wrap head-inner">
    <a class="brand" href="index.html">
      <svg class="voile" viewBox="0 0 120 158" role="img" aria-label="Le logo de VELA : une voile">
        <path class="v-foc" d="M 36.5 46.3 L 36.6 158 L 0 158 Z"/>
        <path class="v-grand" d="M 41.4 0 C 93.3 52.6 115 105.2 120 157.8 Q 80.4 149.2 41.4 158 Z"/>
      </svg>
      <span class="brand-txt"><b>VELA</b><i>IRIS</i></span>
    </a>
    <button class="nav-toggle" type="button" aria-expanded="false" aria-controls="nav">Menu</button>
    <nav id="nav" class="site-nav" aria-label="Navigation principale">
      <a href="index.html">Accueil</a>
      <a href="lunettes.html">Les lunettes</a>
      <a href="fonctionnalites.html">Ce qu’IRIS fait</a>
      <a href="confidentialite.html">Confidentialité</a>
      <a href="plans.html">Plans</a>
      <a href="installer.html">Installer</a>
      <a href="contact.html" class="nav-cta">Contact</a>
    </nav>
  </div>
</header>

<main id="contenu">
```

---

## 5. `<footer>` (EXACT) — sans X

Réseaux : Instagram, LinkedIn, YouTube **uniquement** (pas de X, pas encore de compte VELA).

```html
<footer class="site-foot">
  <div class="wrap">
    <div class="foot-grid">
      <div>
        <a class="brand" href="index.html" style="margin-bottom:12px">
          <svg class="voile" viewBox="0 0 120 158" role="img" aria-label="Le logo de VELA : une voile">
            <path class="v-foc" d="M 36.5 46.3 L 36.6 158 L 0 158 Z"/>
            <path class="v-grand" d="M 41.4 0 C 93.3 52.6 115 105.2 120 157.8 Q 80.4 149.2 41.4 158 Z"/>
          </svg>
          <span class="brand-txt"><b>VELA</b><i>IRIS</i></span>
        </a>
        <p>Votre voix donne le cap.<br>IRIS tient la barre.</p>
        <nav class="foot-social" aria-label="VELA sur les réseaux sociaux">
          <a href="https://www.instagram.com/vela_iris2026/" target="_blank" rel="noopener noreferrer me">Instagram</a>
          <a href="https://www.linkedin.com/in/vela-glass-427361431/" target="_blank" rel="noopener noreferrer me">LinkedIn</a>
          <a href="https://www.youtube.com/channel/UCLQ3OFNFoCiRkYGt4YQasHw" target="_blank" rel="noopener noreferrer me">YouTube</a>
        </nav>
      </div>
      <div>
        <h3>Le produit</h3>
        <ul>
          <li><a href="lunettes.html">Les lunettes VELA</a></li>
          <li><a href="fonctionnalites.html">Ce qu’IRIS fait</a></li>
          <li><a href="confidentialite.html">Confidentialité</a></li>
          <li><a href="plans.html">Plans et prix</a></li>
          <li><a href="installer.html">Installer IRIS</a></li>
        </ul>
      </div>
      <div>
        <h3>Nous joindre</h3>
        <ul>
          <li><a href="suivi.html">Suivre ma commande</a></li>
          <li><a href="mailto:miguelfreddy65@gmail.com">miguelfreddy65@gmail.com</a></li>
          <li><a href="tel:+18195242804">819&nbsp;524-2804</a></li>
          <li><a href="contact.html">Formulaire de contact</a></li>
        </ul>
      </div>
    </div>
    <div class="foot-bottom">
      <p>© 2026 VELA. IRIS version 0.1.0, pour Windows 10 et 11 (64&nbsp;bits).</p>
      <p class="foot-legal">
        <a href="politique-confidentialite.html">Politique de confidentialité</a>
        <a href="mentions-legales.html">Mentions légales</a>
      </p>
    </div>
  </div>
</footer>

<script src="assets/site.js?v=8"></script>
</body>
</html>
```

---

## 6. Boîte à outils CSS (classes prêtes à l'emploi)

Tout est dans `assets/style.css`. Les blocs utiles :

- **Structure** : `.wrap` (conteneur), `.wrap.narrow` (colonne de lecture ~760 px),
  `<section>` (rythme vertical auto), `<section class="band">` (bande crème alternée),
  `.sec-head` / `.sec-head.center` (en-tête de section : `.section-label` + `h2` + `p`).
- **Boutons** : `.btn`, `.btn.primary`, `.btn.btn-xl`, `.btn.sm` ; rangée `.actions`.
- **Cartes/grilles** : `.grid.grid-2|grid-3|grid-4`, `.card`, `.card.feat` (avec
  `.ico-wrap` + `<svg class="ico"><use href="#i-…"></svg>`).
- **Pastilles** : `.pill`, `.pill.ok` (Disponible), `.pill.warn` (Bientôt), `.pill.err`.
- **Photos** : `.pv-plaque` (cadre) + `.pv-plaque.est-sombre` (fond noir), `.galerie` (grille).
- **Prix** : `.prix-bloc` (bloc d'achat), `.table-scroll > table` (tableaux comparatifs),
  cellule `.price`, cartes `.plan-mini` (`.pm-prix/.pm-par/.pm-quoi`).
- **Listes** : `ul.check` (à cocher), `ol.steps-list` (étapes numérotées), `ul.boite`
  (`.n` + `<b>` + `.d`).
- **Encadrés** : `.callout`, `.callout.warn` ; repli `.plus > summary + .plus-body`.
- **Formulaires** : `.field` (label + input/textarea/select), `.err-msg`, `.form-reponse`
  (`.succes/.erreur`). **Ne pas renommer** les `id` utilisés par `site.js` : `form-contact`,
  `nom`, `courriel`, `sujet`, `message`, `reponse` ; `form-suivi`, `numero`, `courriel-suivi`,
  `reponse-suivi`, `[data-suivi-avis]` ; démonstration du registre : `[data-chain-demo]`,
  `[data-entries]`, `[data-status]`, `[data-state]`, `[data-verify]`, `[data-tamper]`,
  `[data-reset]`.
- **Pictogrammes** : rangez le sprite `<svg width="0" height="0">…<symbol id="i-…">` en haut
  du `<body>` (voir `index.html`) et appelez `#i-micro`, `#i-son`, `#i-sans-camera`,
  `#i-local`, `#i-fais`, `#i-memoire`, `#i-check`, `#i-chaine`. Les icônes sont au trait
  (`stroke`), la couleur suit `currentColor`.

Les icônes doivent toujours porter `aria-hidden="true"` ; tout `<img>` a un `alt` réel ;
un seul `<h1>` par page.

---

## 7. Faits vérifiés (ne pas contredire)

- **Prix lunettes** : 250 $ CAD, taxes en sus, **un seul versement**. Lien de paiement carte :
  `https://buy.stripe.com/3cIbJ33UI78a91ZbsS0Ny04`. Virement Interac : `miguelfreddy65@gmail.com`.
- **Plans IRIS** (mensuel, CAD, taxes en sus) : Gratuit 0 $ (**Disponible**) · Pro 19,99 $ ·
  Premium 29,99 $ · Entreprise 99,99 $. Le **service d'IA en ligne** est en déploiement →
  garder « Bientôt » sur ce qui en dépend (réponses des modèles, voix ElevenLabs). Liens
  d'abonnement Stripe : Pro `…0Ny03`, Premium `…0Ny02`, Entreprise `…0Ny01` (voir plans.html
  actuel pour les URL complètes).
- **Matériel** : monture noire, micro + haut-parleurs, connexion Bluetooth au PC, étui de
  charge USB-C. **Aucune caméra, aucun écran.** Deux montures (verres transparents / teintés).
- **Non mesuré → ne pas annoncer** : autonomie en heures, poids, dimensions, indice d'eau,
  verres correcteurs. On laisse la case vide et on le dit.
- **Logiciel** : IRIS 0.1.0, Windows 10/11 64 bits. Gratuit dès l'install (mot d'activation,
  routines, rappels, registre, gouvernance de confidentialité, voix locale Piper, mode 100 %
  local). Fonctionne aussi **sans les lunettes**.
- **Limite honnête** : commander IRIS depuis le téléphone, loin de la maison, n'existe pas
  encore.
- **Contact** : `miguelfreddy65@gmail.com`, tél. `819 524-2804`. Fondateur : Miguel Goufack.

---

## 8. Plan de contenu par page (COURT — peu de texte)

> Rappel : chaque section = 1 idée, 2–4 phrases max. Réutiliser les patrons d'`index.html`.

### index.html — *déjà faite (référence)*
Hero (slogan + prix + « Précommander les lunettes — 250 $ ») → « Ce qui nous distingue »
(4 cartes : sans caméra, chez vous, voix locale, un seul paiement) → « Ce qu'IRIS fait »
(séquence vocale + 3 cartes écoute/agit/se souvient) → mot du fondateur (court) → teaser
plans → appel final.

### lunettes.html
Fiche produit. **H1** : « Les lunettes VELA ». Sections : (1) hero produit + prix + CTA
précommander ; (2) galerie de photos réelles (`.galerie`, 6 photos existantes) ; (3) « Dans
la boîte » (`ul.boite` : monture, étui de charge, étui rigide, appli gratuite) ; (4) tableau
`Caractéristiques` avec les cases « non mesuré » honnêtes ; (5) « L'achat en 3 étapes »
(`ol.steps-list` : payer, écrire avec le reçu + monture choisie, recevoir). 2–3 phrases par bloc.

### fonctionnalites.html
Ce qu'IRIS fait. **H1** : « Ce qu'IRIS fait, vraiment ». Sections : (1) hero court ; (2) grille
de capacités (`.grid.grid-3`, cartes courtes) avec pastilles de plan (`Dès le plan Gratuit` /
`À partir du plan Premium`) ; (3) accessibilité (tout à la voix, lecture d'écran à voix haute,
piloter sans voir l'écran) ; (4) **« Ce qui n'existe pas encore »** (encadré honnête :
contrôle depuis le téléphone hors maison). CTA vers installer/plans.

### plans.html
**H1** : « Quatre plans. Un gratuit qui sert vraiment. » Sections : (1) hero — les lunettes
(250 $, une fois) et l'abonnement sont **séparés** ; l'accès à l'IA est compris dans
l'abonnement, en déploiement (« Bientôt ») ; (2) tableau comparatif (`.table-scroll`) des 4
paliers (prix, requêtes/mois, voix, ce que le plan ajoute) ; (3) le matériel à part
(`.card` 250 $) + l'accès IA compris ; (4) comment le quota se comporte (`ul.check`) ;
(5) « Comment on s'abonne » (`ol.steps-list`) + encadré résiliation. Garder les liens Stripe.

### installer.html
**H1** : « Installer IRIS ». Sections : (1) hero + bouton de téléchargement (ancre
`#telecharger`) — préciser Windows 10/11 64 bits ; (2) cartes système (`.os-card`) avec état
`Disponible` / `Bientôt` selon la plateforme ; (3) étapes d'installation (`ol.steps-list`) ;
(4) « Ça marche même sans lunettes ». Ne rien promettre de non livré.

### contact.html
**H1** : « Nous joindre ». Court : (1) coordonnées (courriel, tél, réseaux) ; (2) formulaire
`#form-contact` avec les `id` intacts (`nom`, `courriel`, `sujet`, `message`, `reponse`) —
piloté par `site.js` (mailto). 1–2 phrases d'intro, pas plus.

### suivi.html
**H1** : « Suivre ma commande ». (1) intro honnête : le suivi automatique n'est pas branché ;
(2) formulaire `#form-suivi` (`numero`, `courriel-suivi`, `reponse-suivi`, `[data-suivi-avis]`)
intact ; (3) rappel : on répond par courriel. Ton rassurant, bref.

### merci.html
**H1** : « Merci ! ». Page post-paiement. (1) confirmation chaleureuse ; (2) « Et maintenant »
(`ol.steps-list` : faire suivre le reçu + monture + adresse ; installer IRIS ; on convient la
livraison par courriel) ; (3) liens vers installer / suivi. Très court.

### confidentialite.html
**H1** : « Une confidentialité qui se vérifie ». (1) principes courts (consentement par type,
indicateur de capture, mode 100 % local, chiffré au repos) en cartes ; (2) le **registre
chaîné** + démonstration interactive `[data-chain-demo]` (garder tous les `data-*`, ancre
`#demonstration`) ; (3) « Vos données sont à vous » (export JSON/CSV, tout reste sur l'appareil).

### politique-confidentialite.html
Document légal (`.doc`). **H1** : « Politique de confidentialité ». Sommaire (`.doc-sommaire`),
date de mise à jour (`.doc-maj`), sections numérotées : données traitées, base locale, service
IA en ligne (en déploiement), consentements, conservation, droits, contact. Texte factuel,
sobre — pas de marketing.

### mentions-legales.html
Document légal (`.doc`). **H1** : « Mentions légales ». Éditeur (VELA, Miguel Goufack),
coordonnées, hébergement, propriété intellectuelle, responsabilité. Bref et exact.

### conditions-vente.html
Document légal (`.doc`). **H1** : « Conditions de vente ». Objet (lunettes 250 $ + abonnements),
prix/taxes CAD, paiement (Stripe/Interac), livraison convenue par courriel, versement unique
(pas d'abonnement rattaché aux lunettes), abonnements mensuels & résiliation, renvoi vers
garantie-retour.

### garantie-retour.html
Document légal (`.doc`). **H1** : « Garantie et retour ». Délai de rétractation/retour,
conditions (état, frais), marche à suivre par courriel, garantie sur défaut, ce qui n'est pas
couvert. Honnête et clair, aucune promesse non tenable.
