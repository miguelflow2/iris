# Site public de VELA

Site statique de présentation d'IRIS. Écrit à la main en HTML, CSS et un peu de JavaScript :
aucune dépendance, aucun outil de compilation, aucun appel réseau. Il s'ouvre tel quel, même hors ligne.

## Ouvrir le site

Double-cliquez sur `index.html`. C'est tout.

Pour le servir sur un vrai serveur local (utile pour tester les chemins comme en production) :

```bash
# Python (déjà présent si le backend IRIS est installé)
cd site
python -m http.server 8080
# puis ouvrir http://localhost:8080
```

## Contenu

| Fichier | Page |
|---|---|
| `index.html` | Accueil : hero plein écran avec la voile qui se hisse, registre chaîné animé, commande vocale animée, trois piliers, « Pourquoi VELA existe », garanties, aperçu des plans |
| `confidentialite.html` | La confidentialité vérifiable expliquée simplement + démonstration interactive du registre chaîné |
| `fonctionnalites.html` | Tableau complet de ce qu'IRIS sait faire, avec le plan requis, et ce qui n'existe pas encore |
| `plans.html` | Plans et prix exacts, boutons de paiement PayPal, offre groupée, comportement du quota |
| `installer.html` | Installation pas à pas pour un débutant + section développeurs (commandes réelles du dépôt) |
| `contact.html` | Courriel, téléphone et formulaire fonctionnel (ouvre le logiciel de courriel du visiteur) |
| `politique-confidentialite.html` | Ce que le logiciel fait des données, vérifié dans le code : local, chiffrement, consentements, tiers, registre, rétention, droits |
| `mentions-legales.html` | Éditeur, hébergement, propriété intellectuelle, responsabilité, droit applicable |
| `DEPLOIEMENT.md` | Marche à suivre pour publier (Netlify Drop, alternative Cloudflare) et liste de vérification après mise en ligne |
| `_headers` | En-têtes de sécurité au format Netlify (CSP, HSTS, anti-cadre, cache) |
| `robots.txt`, `sitemap.xml` | Indexation. **Contiennent l'adresse du site : à corriger si le domaine change.** |
| `assets/style.css` | Système visuel, repris de `renderer/src/styles.css` (mêmes variables, même palette : crème, encre, terracotta) |
| `assets/site.js` | Menu sur téléphone + démonstration du registre : SHA-256 implémenté dans la page |
| `assets/photos/` | Les six photos du produit, en 900 px et en 450 px (suffixe `-450`). **Droits à régler : voir plus bas.** |
| `telechargement/` | L'installeur `IRIS-Setup-0.1.0.exe` servi par le bouton de `installer.html` (voir plus bas) |

Le logo est la voile de VELA, reprise en SVG en ligne dans chaque page — **exactement les deux mêmes
chemins** que `renderer/src/components/Voile.tsx`, jamais redessinés :

    foc          M 36.5 46.3 L 36.6 158 L 0 158 Z
    grand-voile  M 41.4 0 C 93.3 52.6 115 105.2 120 157.8 Q 80.4 149.2 41.4 158 Z

Le site est sur fond sombre, donc c'est la variante **grand-voile crème + foc terracotta** partout
(entête, pied, hero, filigranes, favicon). La variante grand-voile encre est réservée aux fonds
clairs : posée ici, elle disparaîtrait.

### Les visuels : dessinés, sauf les photos du produit

Les schémas et les pictogrammes du site sont **fabriqués en SVG et en CSS**, dans les fichiers
eux-mêmes : aucune police distante, aucun CDN. Les seules images importées sont les six photos des
lunettes, dans `assets/photos/`, servies depuis le site lui-même. Le site reste donc identique ouvert
en `file://` et hors ligne.

| Visuel | Où | Comment |
|---|---|---|
| Voile qui se hisse | `index.html`, classe `.hero-mark` | Le mât se trace du pied vers la tête (`stroke-dasharray: 158`), puis les deux voiles montent le long : un `clip-path: inset()` qui remonte du pied vers la tête. Ensuite la grand-voile se remplit de vent, très légèrement (`scaleX` 1 → 1,022 sur 9 s) |
| Registre chaîné animé | `index.html`, `.viz-chain` | Cinq blocs, quatre liens. Une boucle CSS de 9 s : la 2ᵉ entrée est réécrite, la cassure descend la chaîne bloc par bloc (`animation-delay: calc(var(--i) * 0.32s)`) |
| Commande vocale animée | `index.html`, `.viz-voice` | Boucle de 8 s : onde sonore, phrase dévoilée de gauche à droite (`clip-path`), action, puis inscription au registre |
| Photos des lunettes | `index.html` (`.pv`, `.pv-grappe`), `fonctionnalites.html` (`.pv-vignette`) | Vraies photos du produit. Elles ont remplacé le dessin au trait qui occupait la place ; voir la section suivante |
| Pictogrammes | `index.html`, `<symbol>` en haut du fichier, appelés par `<use href="#…">` | Douze icônes au trait. Même document, donc aucune requête réseau |

**`prefers-reduced-motion` coupe tout.** La règle en haut de `style.css` ramène la durée à 0,001 ms **et
force `animation-iteration-count: 1`** : sans ça, une boucle infinie clignoterait mille fois par seconde.
Chaque visuel est donc écrit pour que son **état de repos** soit celui qu'on veut montrer à l'arrêt :
voile entièrement hissée, chaîne intacte, phrase entière. Les photos, elles, ne sont pas animées.

### Les photos du produit

Six photos, chacune en deux tailles — 900 px, et 450 px avec le suffixe `-450`. Toutes carrées, servies
par un `srcset`/`sizes` qui donne la petite aux téléphones et la grande au-delà. Chaque `<img>` porte un
`width` et un `height` explicites pour que rien ne saute au chargement, et `loading="lazy"` partout sauf
sur la première image de chaque page.

| Fichier | Où il est utilisé |
|---|---|
| `lunettes-trois-quarts.jpg` | `index.html`, section « Pourquoi VELA existe » — remplace le dessin au trait |
| `lunettes-fond-sombre.jpg` | `index.html`, section « Les lunettes VELA » — la grande photo de gauche |
| `lunettes-et-etuis.jpg` | `index.html`, même section, en haut à droite |
| `lunettes-en-charge.jpg` | `index.html`, même section, en bas à droite |
| `lunettes-face.jpg` | `fonctionnalites.html`, carte « Lunettes VELA » |
| `lunettes-solaires.jpg` | Pas utilisée. Gardée en réserve : trois photos suffisaient |

**Le fond blanc sur un site sombre.** Cinq des six photos sont détourées sur blanc ou sur gris très
clair. Plutôt que de les découper, on les pose sur une **plaque crème** (`.pv-plaque`) et on passe
l'image en `mix-blend-mode: multiply` : blanc × crème = crème, donc le fond de la photo se fond
exactement dans la plaque pendant que la monture noire reste noire. `isolation: isolate` enferme le
mélange dans la plaque, sinon le `multiply` irait chercher le fond sombre de la section et noircirait
tout. Si un navigateur ignore `mix-blend-mode`, l'image reste blanche sur crème : à peine visible,
jamais cassé. `lunettes-fond-sombre.jpg`, déjà photographiée sur fond noir, garde une plaque noire
(`.est-sombre`) et aucun mélange.

> **⚠ Ces photos viennent du fabricant du matériel. Elles ne sont pas les nôtres.**
>
> Elles ont été fournies pour la présentation du produit, et **rien n'autorise aujourd'hui leur usage
> commercial**. Avant toute publicité, toute campagne, toute fiche de vente ou toute publication payante,
> il faut **l'accord écrit du fabricant** — ou, mieux, **les remplacer par des photos prises par VELA**,
> dont les droits nous appartiendraient. Le nom du fabricant n'apparaît nulle part sur le site et ne doit
> pas y apparaître ; l'autorisation se règle par écrit, en dehors du site.
>
> Tant que ce n'est pas réglé, ces photos sont à considérer comme **provisoires**. Les remplacer ne
> demande aucun changement de code : mêmes noms de fichiers, mêmes deux tailles, format carré.

### Ce qu'on dit des lunettes

Les lunettes VELA portent le micro et le son. **Elles n'ont pas de caméra, et le site n'en promet
aucune** — ni sur l'accueil, ni dans `fonctionnalites.html`, ni dans les pages légales. C'est assumé
plutôt que caché : à ce prix, la catégorie entière est faite de micros et de haut-parleurs, et la
différence se joue dans le logiciel. Toute formulation qui laisserait croire à une caméra des lunettes
doit être corrigée. (L'indicateur de capture du logiciel, lui, couvre bien un état « caméra » : c'est la
caméra **de l'ordinateur**, et les pages le précisent.)

### Pourquoi une implémentation de SHA-256 dans `site.js`

`crypto.subtle` n'existe que dans un contexte sécurisé : ouvert en `file://`, il est indisponible.
La démonstration du registre calcule donc les empreintes avec une implémentation de SHA-256 écrite dans
le fichier (vérifiée contre `crypto.createHash('sha256')` de Node). Le site fonctionne ainsi à
l'identique depuis le disque, depuis un serveur local ou en production.

### Le dossier `telechargement/`

Il contient une **copie** de `release/IRIS-Setup-0.1.0.exe` (246 Mo, version du 3 septembre 2026), pour
que le bouton « Télécharger IRIS pour Windows » de `installer.html` fonctionne réellement en local et en
démonstration, même sans connexion. L'original reste dans `release/`, qui sert aux constructions : après
un nouveau `npm run dist:full`, recopier le fichier ici et corriger la taille et la date affichées à côté
du bouton (deux endroits dans `installer.html` : la carte Windows et l'étape 1).

Pour vérifier que la copie est bien à jour :

```powershell
(Get-FileHash ..\release\IRIS-Setup-0.1.0.exe).Hash -eq (Get-FileHash telechargement\IRIS-Setup-0.1.0.exe).Hash
```

Au moment de publier en ligne, deux possibilités :

- **téléverser le fichier avec le site**, en gardant le chemin relatif `telechargement/IRIS-Setup-0.1.0.exe`
  — vérifier alors que l'hébergeur accepte un fichier de cette taille (Netlify, Cloudflare Pages et un
  serveur classique l'acceptent ; GitHub Pages plafonne à 100 Mo par fichier, donc ce n'est pas possible
  tel quel) ;
- ou **héberger l'installeur ailleurs** (stockage objet, page de publication GitHub, lien de partage) et
  remplacer le `href` du bouton par cette adresse.

> **À ne pas committer dans Git.** 246 Mo de binaire n'ont rien à faire dans l'historique d'un dépôt.
> Ajouter `site/telechargement/` au `.gitignore` avant tout premier commit du site.

### Le formulaire de contact et les boutons « Me prévenir »

Aucun service tiers, aucune inscription, aucun serveur : tout passe par `mailto:`.

- **Formulaire** (`contact.html` + `assets/site.js`) : à la soumission, le script vérifie le nom, le
  courriel et le message, puis construit un lien `mailto:miguelfreddy65@gmail.com` avec l'objet et le
  corps déjà remplis (`encodeURIComponent`, sauts de ligne en CRLF) et ouvre le logiciel de courriel du
  visiteur. Un message de confirmation s'affiche, avec l'adresse en clair au cas où rien ne s'ouvrirait.
- **Boutons « Me prévenir »** (`installer.html`, cartes macOS et Linux) : de simples liens `mailto:`
  avec objet et corps pré-remplis — ils fonctionnent même sans JavaScript.

Pour changer l'adresse de destination : la constante `COURRIEL` en haut du bloc « formulaire de
contact » dans `assets/site.js`, plus les `href` `mailto:` des pages.

### Le paiement

`plans.html` porte quatre liens `paypal.me`, en dur, identiques à ceux que l'application construit
elle-même (`payment_link()` dans `backend/iris/plans.py`) :

| Bouton | Lien |
|---|---|
| S'abonner · 19,99 $ | `https://paypal.me/irisvela461/19.99CAD` |
| S'abonner · 29,99 $ | `https://paypal.me/irisvela461/29.99CAD` |
| S'abonner · 99,99 $ | `https://paypal.me/irisvela461/99.99CAD` |
| Acheter les lunettes · 839 $ | `https://paypal.me/irisvela461/839.00CAD` |

Format : `https://paypal.me/<compte>/<montant à deux décimales><devise>`. Tous s'ouvrent dans un
nouvel onglet avec `rel="noopener noreferrer"`. Le plan Gratuit n'a évidemment aucun bouton.

**Un lien paypal.me est un versement unique.** Il ne crée aucun abonnement récurrent, ne prévient pas
IRIS et n'active rien : c'est la clé `IRIS-…` envoyée à la main (`scripts/make-license-key.py`) qui
débloque le plan. La section « Comment on s'abonne » de `plans.html` le dit noir sur blanc, dans les
mêmes termes que la vue Abonnement de l'application — les deux doivent rester d'accord. Le jour où un
vrai renouvellement automatique existera (PayPal Business avec abonnements, ou Stripe), c'est ce texte
et ces liens qu'il faudra remplacer.

Si un prix change dans `backend/iris/plans.py`, il faut le répercuter à trois endroits de
`plans.html` : le montant du tableau, le libellé du bouton et le montant dans l'URL.

## Les pages légales

`politique-confidentialite.html` décrit le comportement réel du logiciel, relu dans le code source :
types de consentement de `consent.py`, chiffrement de `security/crypto.py`, chaînage SHA-256 de
`ConsentGate.log/verify`, rétention et purge de `memory.py`, repli de reconnaissance vocale de
`voice/stt.py`, et la liste exacte des services tiers contactés. **Si le comportement du logiciel
change, ce document doit changer avec lui.**

Les deux pages portent en tête un avis indiquant qu'elles ont été rédigées sans avis juridique
professionnel. `mentions-legales.html` contient un encadré jaune listant précisément ce que Miguel
doit fournir (forme juridique, NEQ, hébergeur…). **Cet encadré est visible publiquement : il doit
disparaître une fois rempli.**

## Ce qui reste à faire avant publication

1. **Héberger l'installeur** — voir la section `telechargement/` ci-dessus, et `DEPLOIEMENT.md`.
2. **Remplir l'encadré des mentions légales** puis le supprimer, et faire relire les deux pages
   légales par un juriste avant la première vente.
3. **Adresse du site** — `robots.txt` et `sitemap.xml` contiennent `https://vela-iris.netlify.app` :
   à remplacer par l'adresse retenue.
4. **Taxes** — `plans.html` indique « Prix en dollars canadiens, taxes en sus ». Confirmer le régime de
   taxes applicable (TPS/TVQ) avant d'encaisser un premier paiement, et le cas échéant afficher les
   montants toutes taxes comprises.
5. **Renouvellement automatique** — aujourd'hui le renouvellement est manuel, dit tel quel sur le site.
   Un compte PayPal Business avec abonnements, ou Stripe, permettrait de l'automatiser.
6. **Signature de code** — tant que l'installeur n'est pas signé, Windows affiche un avertissement
   SmartScreen. C'est expliqué au visiteur dans `installer.html`, étape 2 ; ce paragraphe pourra être
   retiré une fois le certificat en place.
7. **Versions macOS et Linux** — les cartes de la page Installer disent « en préparation » et
   recueillent les courriels intéressés. À remplacer par un vrai bouton le jour où ces versions
   existent.
8. **Droits sur les photos du produit** — les six images de `assets/photos/` sont celles du fabricant
   du matériel, pas les nôtres. Obtenir son **accord écrit** pour l'usage commercial, ou faire
   photographier les lunettes par VELA et remplacer les fichiers, **avant toute campagne ou publicité**.
   Voir la section « Les photos du produit » ci-dessus.

## Publier

Le site est un dossier de fichiers statiques : n'importe quel hébergement statique convient.

- **GitHub Pages** : pousser le contenu de `site/` dans une branche `gh-pages` (ou un dossier `docs/`
  du dépôt), puis activer Pages dans les réglages du dépôt.
- **Netlify / Cloudflare Pages / Vercel** : glisser-déposer le dossier `site/`, ou relier le dépôt en
  indiquant `site` comme répertoire à publier et aucune commande de compilation.
- **Hébergement classique** : téléverser le contenu de `site/` par FTP à la racine du domaine.

Attention au dossier `telechargement/` dans tous les cas : voir la section qui lui est consacrée
plus haut avant de publier.

Tous les liens sont relatifs : le site fonctionne aussi bien à la racine d'un domaine que dans un
sous-dossier.

## Règles de rédaction

- Français du Québec, ton direct, pas d'anglicismes inutiles.
- Aucune fonctionnalité annoncée qui n'existe pas dans le code ; ce qui n'est pas livré porte la
  mention « à venir ».
- Aucun chiffre, témoignage, logo de client ou récompense inventé.
- Les prix et quotas viennent de `backend/iris/plans.py` et de `docs/PLANS.md` : si le code change,
  mettre `plans.html` à jour.
- Le nom du fournisseur du matériel n'apparaît nulle part.
- La section « Pourquoi VELA existe » de l'accueil raconte le parcours de Miguel à la première personne.
  Elle ne nomme **aucune entreprise, aucune personne**, ne raconte aucun conflit et n'accuse personne :
  elle parle de ce qu'il a voulu construire, jamais de ce que d'autres auraient mal fait. Toute
  réécriture doit garder cette règle.
