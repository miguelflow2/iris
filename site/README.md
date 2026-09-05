# Site public de VELA

Site statique qui **vend les lunettes VELA**. IRIS, l'application, est l'argument qui les rend
utiles — pas le sujet principal. Écrit à la main en HTML, CSS et un peu de JavaScript : aucune
dépendance, aucun outil de compilation, aucun appel réseau. Il s'ouvre tel quel, même hors ligne.

## ⚠ Le numéro de version des ressources — à lire avant toute modification

`assets/style.css` et `assets/site.js` sont appelés avec un **numéro de version** :

```html
<link rel="stylesheet" href="assets/style.css?v=3">
<script src="assets/site.js?v=3"></script>
```

**Chaque fois que vous modifiez la CSS ou le JavaScript, incrémentez ce numéro dans les neuf
pages.** Sinon, le navigateur d'un visiteur déjà venu continue de servir l'ancienne feuille depuis
son cache : le HTML neuf arrive, la vieille CSS n'a pas de règle pour les nouvelles classes, et le
site s'affiche cassé — c'est exactement ce qui est arrivé en septembre 2026 (logo noir, accents
verts, parce que la vieille feuille ne connaissait pas la classe `.v-grand`).

En une commande, depuis `site/` :

```bash
# remplacer 3 par l'ancien numéro et 4 par le nouveau
sed -i 's/style\.css?v=3/style.css?v=4/; s/site\.js?v=3/site.js?v=4/' *.html
grep -c 'v=4' *.html    # doit afficher 2 pour chacune des neuf pages
```

En PowerShell :

```powershell
Get-ChildItem *.html | ForEach-Object {
  (Get-Content $_ -Raw) -replace 'style\.css\?v=3','style.css?v=4' -replace 'site\.js\?v=3','site.js?v=4' |
    Set-Content $_ -Encoding utf8
}
```

Deuxième filet, dans `_headers` : `assets/style.css` et `assets/site.js` sont servis en
`Cache-Control: public, max-age=0, must-revalidate`. Le navigateur garde le fichier mais demande à
chaque visite s'il a changé ; la réponse est un 304 vide quand rien n'a bougé. Une correction part
donc immédiatement **même si le numéro de version a été oublié**. Les photos, elles, sont en cache
24 h. Les pages HTML ne doivent jamais être mises en cache longtemps : ce sont elles qui portent le
numéro de version.

Après un déploiement, vérifier dans le navigateur (onglet Réseau) que `style.css?v=…` porte bien le
nouveau numéro. Un rechargement forcé (<kbd>Ctrl</kbd>+<kbd>Maj</kbd>+<kbd>R</kbd>) ne prouve rien :
il contourne le cache, ce que le visiteur ne fera pas.

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
| `index.html` | Accueil : **hero produit** (photo des lunettes, prix, bouton d'achat), l'objet, IRIS comme ce qui vient avec, registre chaîné animé, photos, garanties, « Pourquoi VELA existe », plans, rappel d'achat |
| `lunettes.html` | **Fiche du produit** : hero d'achat, galerie des six photos, contenu de l'envoi, caractéristiques vérifiées, ce que les lunettes changent avec IRIS, les trois étapes de l'achat |
| `confidentialite.html` | La confidentialité vérifiable expliquée simplement + démonstration interactive du registre chaîné |
| `fonctionnalites.html` | Tableau complet de ce qu'IRIS sait faire, avec le plan requis, et ce qui n'existe pas encore |
| `plans.html` | Les **quatre plans** (Gratuit, Pro, Premium, Entreprise), prix exacts, boutons de paiement PayPal, carte des lunettes à 250 $, « l'accès à l'IA est compris », comportement du quota |
| `installer.html` | Installation pas à pas pour un débutant + section développeurs (commandes réelles du dépôt) |
| `contact.html` | Courriel, téléphone et formulaire fonctionnel (ouvre le logiciel de courriel du visiteur) |
| `politique-confidentialite.html` | Ce que le logiciel fait des données, vérifié dans le code : local, chiffrement, consentements, tiers, registre, rétention, droits |
| `mentions-legales.html` | Éditeur, hébergement, propriété intellectuelle, responsabilité, droit applicable |
| `DEPLOIEMENT.md` | Marche à suivre pour publier (Netlify Drop, alternative Cloudflare) et liste de vérification après mise en ligne |
| `_headers` | En-têtes de sécurité au format Netlify (CSP, HSTS, anti-cadre) **et politique de cache** — voir l'avertissement en tête de ce fichier |
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
| Hero produit | `index.html` et `lunettes.html`, `.hero-produit` / `.hp-grid` | Deux colonnes : le texte, le prix et le bouton d'achat à gauche, la photo à droite. Sur téléphone la photo passe **en premier** (`order: -1`) et le paragraphe de présentation passe **après** le bloc de prix (`order: 3`), pour que le bouton d'achat reste au-dessus de la ligne de flottaison |
| Bloc de prix | `.prix-bloc`, sur les deux pages produit | Le seul bloc du site cerné de terracotta : c'est là qu'on achète, ça doit se voir sans lire |
| Registre chaîné animé | `index.html`, `.viz-chain` | Cinq blocs, quatre liens. Une boucle CSS de 9 s : la 2ᵉ entrée est réécrite, la cassure descend la chaîne bloc par bloc (`animation-delay: calc(var(--i) * 0.32s)`) |
| Commande vocale animée | `index.html`, `.viz-voice` | Boucle de 8 s : onde sonore, phrase dévoilée de gauche à droite (`clip-path`), action, puis inscription au registre |
| Photos des lunettes | `index.html` (`.hp-photo`, `.pv-grappe`), `lunettes.html` (`.hp-photo`, `.galerie`), `fonctionnalites.html` (`.pv-vignette`) | Vraies photos du produit ; voir la section suivante |
| Filigrane de la voile | pages secondaires, `.hero-voile-bg` | La voile se hisse une fois (`clip-path: inset()`), à 11 % d'opacité. **Les deux pages produit ne le portent pas** : la photo y est la vedette |
| Pictogrammes | `index.html` et `lunettes.html`, `<symbol>` en haut du fichier, appelés par `<use href="#…">` | Icônes au trait. Même document, donc aucune requête réseau. `lunettes.html` n'embarque que les six dont il se sert |

**L'ancien hero à la voile animée a été retiré.** L'accueil montrait un logo plein écran ; il montre
maintenant le produit. Les règles CSS correspondantes (`.hero-full`, `.hero-mark`, `.hm-*`,
`.scroll-cue`, et les animations `hisse-mat`, `souffle`, `descend`) ont été **supprimées** de
`style.css` — elles n'étaient utilisées que par `index.html`. `@keyframes hisser` reste : le
filigrane des pages secondaires s'en sert.

**`prefers-reduced-motion` coupe tout.** La règle en haut de `style.css` ramène la durée à 0,001 ms **et
force `animation-iteration-count: 1`** : sans ça, une boucle infinie clignoterait mille fois par seconde.
Chaque visuel est donc écrit pour que son **état de repos** soit celui qu'on veut montrer à l'arrêt :
voile entièrement hissée, chaîne intacte, phrase entière. Les photos, elles, ne sont pas animées.

### Les photos du produit

Six photos, chacune en deux tailles — 900 px, et 450 px avec le suffixe `-450`. Toutes carrées, servies
par un `srcset`/`sizes` qui donne la petite aux téléphones et la grande au-delà. Chaque `<img>` porte un
`width` et un `height` explicites pour que rien ne saute au chargement, et `loading="lazy"` partout sauf
sur la première image de chaque page.

Les six sont utilisées : `lunettes.html` les montre toutes.

| Fichier | Où il est utilisé |
|---|---|
| `lunettes-fond-sombre.jpg` | **Le hero des deux pages produit** (`index.html`, `lunettes.html`) — la plus belle, et la seule déjà prise sur fond noir. Aussi dans la galerie de `lunettes.html` |
| `lunettes-trois-quarts.jpg` | `index.html`, grande photo de la grappe « En vrai » ; galerie de `lunettes.html` |
| `lunettes-et-etuis.jpg` | `index.html`, grappe « En vrai » ; galerie de `lunettes.html` |
| `lunettes-en-charge.jpg` | `index.html`, grappe « En vrai » ; galerie de `lunettes.html` |
| `lunettes-face.jpg` | `fonctionnalites.html`, carte « Lunettes VELA » ; galerie de `lunettes.html` |
| `lunettes-solaires.jpg` | `index.html`, section « Pourquoi VELA existe » ; galerie de `lunettes.html` |

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

### Le slogan

**« Des lunettes qui vous écoutent, sans jamais vous regarder. »**

Il est en `h1` sur l'accueil (`.hp-titre`, avec « écoutent » en terracotta) et en signature dans le
pied de page des neuf pages. Il remplace « Parlez. Elle agit. Vous vérifiez. », qui empilait trois
verbes et sonnait comme un logiciel plutôt que comme un objet à porter.

Ce qu'il doit continuer de dire, si on le réécrit un jour :

- **c'est un objet qu'on porte** — le mot « lunettes » vient en premier, pas « IA » ni « assistante » ;
- **il est intelligent** — « écoutent », donc le micro, donc la voix ;
- **on peut lui faire confiance parce que c'est vérifiable** — « sans jamais vous regarder » n'est
  pas une promesse morale, c'est un fait : **il n'y a pas de caméra**, ça se voit sur les photos et
  c'est écrit dans la fiche du produit. Le jour où un modèle à caméra existerait, **ce slogan devrait
  changer le même jour**.

À fuir : les tirades en trois temps, les verbes empilés, et les mots « révolutionnaire »,
« expérience », « solution », « redéfinit ».

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

### Le parcours d'achat

Le visiteur doit pouvoir acheter sans chercher. Trois entrées, dans cet ordre :

1. **Le hero de l'accueil** — photo, prix (250 $), bouton « Acheter · 250 $ » qui ouvre PayPal, et
   un second bouton vers la fiche du produit. Le bouton d'achat tient au-dessus de la ligne de
   flottaison à 1440 × 900, à 860 × 900 et à 375 × 812 (vérifié ; à 375 × 667 il affleure le bas).
2. **`lunettes.html`** — la fiche : galerie, contenu de l'envoi, caractéristiques, et le même bouton
   d'achat répété en tête et à la fin, dans la section « L'achat ».
3. **Le bas de l'accueil** (`.rappel-achat`) et **`plans.html#acheter`**, pour qui descend jusque-là.

Le parcours annoncé est celui qui existe vraiment, et il est écrit tel quel partout. **Les lunettes :**
PayPal, puis un reçu par courriel, puis la livraison convenue par courriel au cas par cas — aucune clé
n'est due, puisque rien n'est abonné. **L'abonnement, séparément :** PayPal, reçu par courriel, puis une
clé d'activation par courriel. Aucun panier, aucun suivi de colis, aucun prélèvement récurrent. Si un
jour un vrai tunnel de commande existe, c'est ce texte qu'il faudra remplacer — aux trois endroits
ci-dessus.

`plans.html` et les deux pages produit portent quatre liens `paypal.me`, en dur, identiques à ceux
que l'application construit elle-même (`payment_link()` dans `backend/iris/plans.py`) :

| Bouton | Lien | Où |
|---|---|---|
| S'abonner · 19,99 $ (Pro) | `https://paypal.me/irisvela461/19.99CAD` | `plans.html` |
| S'abonner · 29,99 $ (Premium) | `https://paypal.me/irisvela461/29.99CAD` | `plans.html` |
| S'abonner · 99,99 $ (Entreprise) | `https://paypal.me/irisvela461/99.99CAD` | `plans.html` |
| Acheter · 250 $ (lunettes) | `https://paypal.me/irisvela461/250.00CAD` | `index.html` (× 2), `lunettes.html` (× 2), `plans.html` |

### Les quatre plans, et l'offre groupée qui n'existe plus

Les paliers s'appelaient Gratuit / Essentiel / Pro / Ultra. Ils s'appellent maintenant **Gratuit / Pro /
Premium / Entreprise**, aux mêmes prix (0, 19,99, 29,99, 99,99 $) : le nom « Pro » a donc **changé de
palier** — il désigne aujourd'hui l'ancien Essentiel à 19,99 $. Attention en relisant de vieux textes.
Les noms, les prix, les quotas et le contenu de chaque palier viennent de `PLANS` dans
`backend/iris/plans.py` et doivent y rester identiques, au mot près : c'est le même argumentaire que
la vue Abonnement de l'application.

**L'offre groupée « lunettes + 12 mois Pro » à 839 $ a été retirée du site** (septembre 2026), en même
temps que `LUNETTES = {"price": 250.0}` est apparu dans `plans.py`. Son montant n'était défendable que
tant que les lunettes n'avaient pas de prix affiché. **Aucun prix de remplacement n'a été calculé** :
si une offre groupée revient, c'est une décision de Miguel, avec un montant qu'il arrête lui-même.

**L'accès à l'IA est fourni avec l'abonnement**, et le site le dit sur l'accueil, sur `plans.html` et
sur `fonctionnalites.html` : le client ne crée aucun compte chez un fournisseur d'IA et ne colle aucune
clé. C'est `serveur/relais.py` qui détient la clé et choisit le modèle selon le plan. Toute page qui
redemanderait une clé au visiteur contredit ça — c'est pour cette raison que l'étape « Clé OpenRouter »
de `installer.html` a été remplacée par « Votre compte » (courriel d'achat + mot de passe), conforme à
`renderer/src/views/Onboarding.tsx`.

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

## Ce que Miguel doit décider lui-même

Ces points-là ne sont pas des oublis : ce sont des décisions commerciales qui n'appartiennent pas au
site. Rien n'a été inventé pour les combler, et les pages sont écrites de façon à ne pas mentir en
attendant.

1. **Une éventuelle offre groupée.** Le prix des lunettes est fixé : **250 $**, seules. L'ancienne offre
   « lunettes + 12 mois Pro » à 839 $ a donc été retirée du parcours d'achat, faute d'arithmétique
   défendable. Si Miguel veut de nouveau vendre matériel et abonnement ensemble, c'est **à lui** de
   fixer le montant et la durée : rien n'a été recalculé ici, et aucun rabais n'a été inventé. Il
   faudrait alors un cinquième lien `paypal.me`, une ligne dans `plans.py` et le texte des trois
   entrées du parcours d'achat.
2. **Le contenu exact de la boîte.** `lunettes.html` liste la monture, l'étui de charge avec son
   câble et l'étui rigide de rangement — c'est ce que **montrent les photos**, et la page dit
   explicitement que le contenu exact est confirmé par courriel avant l'expédition. Confirmer ce qui
   part réellement, puis retirer cette réserve.
3. **Les deux montures.** Verres transparents et verres teintés existent tous les deux en photo.
   Le site demande au client de préciser son choix par courriel. Décider si les deux sont vraiment
   proposées, si l'une coûte plus cher, et si l'on tient un stock des deux.
4. **Autonomie, poids, dimensions, résistance à l'eau, verres correcteurs.** Les lignes existent
   dans le tableau de `lunettes.html` et disent « non mesuré par VELA ». Les remplir demande de
   chronométrer et de peser l'exemplaire — pas de recopier une fiche du fabricant.
5. **Délai de livraison et politique de retour.** Le site dit « convenu par courriel, au cas par
   cas ». C'est honnête, mais un délai annoncé et une politique de retour rassurent davantage —
   et le droit québécois de la consommation en impose une part.

## Ce qui reste à faire avant publication

1. **⚠ La politique de confidentialité contredit maintenant le relais.** `politique-confidentialite.html`,
   section 5, dit : « IRIS ne s'adresse qu'aux services que vous avez configurés, avec les clés que vous
   fournissez. **Nous ne sommes pas intermédiaires de ces échanges** : votre ordinateur parle directement
   au fournisseur. » Ce n'est plus vrai : `relay_server = "https://relais.vela.app"` est la valeur par
   défaut de `backend/iris/config.py`, et `serveur/relais.py` reçoit les demandes, choisit le modèle selon
   l'abonnement et les transmet avec **la clé de VELA**. VELA est donc bien intermédiaire. Le relais dit
   ne conserver aucune conversation (« il transmet, il ne garde pas », seuls les compteurs restent) — c'est
   cela qu'il faut écrire, et le faire relire avant la première vente. Les pages légales n'ont
   volontairement pas été retouchées ici : c'est une décision juridique, pas rédactionnelle.
2. **Héberger l'installeur** — voir la section `telechargement/` ci-dessus, et `DEPLOIEMENT.md`.
3. **Remplir l'encadré des mentions légales** puis le supprimer, et faire relire les deux pages
   légales par un juriste avant la première vente.
4. **Adresse du site** — `robots.txt` et `sitemap.xml` contiennent `https://vela-iris.netlify.app` :
   à remplacer par l'adresse retenue.
5. **Taxes** — `plans.html` indique « Prix en dollars canadiens, taxes en sus ». Confirmer le régime de
   taxes applicable (TPS/TVQ) avant d'encaisser un premier paiement, et le cas échéant afficher les
   montants toutes taxes comprises.
6. **Renouvellement automatique** — aujourd'hui le renouvellement est manuel, dit tel quel sur le site.
   Un compte PayPal Business avec abonnements, ou Stripe, permettrait de l'automatiser.
7. **Signature de code** — tant que l'installeur n'est pas signé, Windows affiche un avertissement
   SmartScreen. C'est expliqué au visiteur dans `installer.html`, étape 2 ; ce paragraphe pourra être
   retiré une fois le certificat en place.
8. **Versions macOS et Linux** — les cartes de la page Installer disent « en préparation » et
   recueillent les courriels intéressés. À remplacer par un vrai bouton le jour où ces versions
   existent.
9. **Droits sur les photos du produit** — les six images de `assets/photos/` sont celles du fabricant
   du matériel, pas les nôtres. Obtenir son **accord écrit** pour l'usage commercial, ou faire
   photographier les lunettes par VELA et remplacer les fichiers, **avant toute campagne ou publicité**.
   Voir la section « Les photos du produit » ci-dessus.
10. **La voix ElevenLabs n'est pas encore fournie comme les modèles le sont.** Le site promet, dès le
    plan Pro, « la voix naturelle ElevenLabs » — et c'est bien ce que dit `plans.py`. Mais
    `backend/iris/voice/elevenlabs.py` lit toujours la clé dans `ELEVENLABS_API_KEY`, sur la machine du
    client, sans passer par le relais. Tant que VELA ne livre pas cette clé avec l'application, un abonné
    Pro paie une voix qu'il n'entendra pas : IRIS retombera sur la voix de Windows. À régler dans le code,
    pas sur le site.
11. **« Comment on s'abonne » décrit encore le parcours manuel** (PayPal → reçu par courriel → clé
    `IRIS-…` à coller), ce qui reste exact aujourd'hui : `server/README.md` rappelle que sans compte
    PayPal Business, aucun webhook n'arrive. Mais `renderer/src/views/Onboarding.tsx` annonce déjà au
    client que « votre abonnement s'activera tout seul, sans clé à recopier », et `backend/iris/licence.py`
    sait aller chercher la clé. **Le jour où le serveur de licences est en ligne, ce texte devient faux** —
    il faudra réécrire les trois étapes de `plans.html#acheter`.

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

- **Les lunettes sont le produit ; IRIS est ce qui vient avec.** L'accueil et `lunettes.html`
  vendent l'objet ; IRIS y est l'argument qui justifie le prix, pas le sujet. `fonctionnalites.html`
  et `confidentialite.html` restent les pages du logiciel.
- Français du Québec, ton direct, pas d'anglicismes inutiles.
- Aucune fonctionnalité annoncée qui n'existe pas dans le code ; ce qui n'est pas livré porte la
  mention « à venir ».
- **Aucune caractéristique matérielle non mesurée par VELA.** Une ligne vide qui dit « non mesuré »
  vaut mieux qu'un chiffre recopié d'une fiche commerciale. C'est la même règle que le registre
  d'IRIS : rien qui ne se vérifie.
- Aucun prix inventé. Les lunettes valent **250 $**, seules ; les quatre abonnements valent 0, 19,99,
  29,99 et 99,99 $ par mois. Il n'existe aucune offre groupée et aucun rabais.
- Aucun chiffre, témoignage, logo de client ou récompense inventé.
- Les prix et quotas viennent de `backend/iris/plans.py` et de `docs/PLANS.md` : si le code change,
  mettre `plans.html` à jour.
- Le nom du fournisseur du matériel n'apparaît nulle part.
- La section « Pourquoi VELA existe » de l'accueil raconte le parcours de Miguel à la première personne.
  Elle ne nomme **aucune entreprise, aucune personne**, ne raconte aucun conflit et n'accuse personne :
  elle parle de ce qu'il a voulu construire, jamais de ce que d'autres auraient mal fait. Toute
  réécriture doit garder cette règle.
