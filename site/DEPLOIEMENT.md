# Mettre le site en ligne

Marche à suivre pour quelqu'un qui n'a jamais publié un site. Comptez une dizaine de minutes.

Le site est un simple dossier de fichiers : il n'y a rien à compiler, aucune commande à lancer,
aucun compte de développeur à créer.

---

## Option recommandée — Netlify Drop

Gratuit, en ligne en deux minutes, HTTPS inclus automatiquement, et le fichier d'installation de
246 Mo passe sans problème.

### 1. Préparer le dossier

Vérifiez que `site/` contient bien ces éléments :

```
site/
  index.html  lunettes.html  fonctionnalites.html  confidentialite.html  plans.html
  installer.html  contact.html  suivi.html  merci.html
  politique-confidentialite.html  mentions-legales.html          (onze pages)
  assets/         (style.css, site.js, photos/)
  telechargement/ (IRIS-Setup-0.1.0.exe)
  _headers        (en-têtes de sécurité et politique de cache)
  robots.txt  sitemap.xml
```

**⚠ Retirez `README.md` et `DEPLOIEMENT.md` du dossier avant de le déposer.** Un hébergeur
statique sert ces fichiers en texte brut à qui devine leur adresse (`/README.md`) : ils ne sont
pas des pages, mais ils sont bel et bien publics. Or `README.md` contient des informations
internes — dont le fait que les droits sur les photos du produit ne sont pas encore réglés. Le
plus simple : copiez `site/` ailleurs, supprimez-y les deux `.md`, déposez cette copie.

### 2. Déposer le dossier

1. Ouvrez **https://app.netlify.com/drop** dans votre navigateur.
2. Glissez le dossier `site/` **en entier** dans le grand rectangle de la page. Pas les fichiers un
   par un : le dossier lui-même.
3. Le téléversement prend une à trois minutes, à cause de l'installeur de 246 Mo. Ne fermez pas
   l'onglet.
4. Le site est en ligne. Netlify vous donne une adresse du genre
   `https://scintillant-praline-a1b2c3.netlify.app`.

Aucun compte n'est demandé pour ce premier dépôt. **Créez-en un tout de suite** (bouton en haut à
droite) : sans compte, vous ne pourrez ni remettre le site à jour, ni brancher votre nom de domaine,
et le site est effacé au bout de quelques heures.

### 3. Changer le nom fourni

L'adresse `scintillant-praline-a1b2c3` est tirée au hasard. Pour la remplacer par quelque chose de
présentable :

*Site configuration › General › Site details › Change site name* → tapez `vela-iris`.
L'adresse devient `https://vela-iris.netlify.app`.

C'est déjà une adresse tout à fait honorable pour une démonstration ou une entrevue.

### 4. Brancher un vrai nom de domaine

Un nom en `.ca` ou `.com` coûte une quinzaine à une trentaine de dollars par année, chez un
registraire comme Namecheap, Porkbun, Hover ou Cloudflare Registrar.

1. Achetez le domaine chez le registraire de votre choix.
2. Dans Netlify : *Domain management › Add a domain* → tapez votre domaine.
3. Netlify affiche deux façons de procéder. La plus simple est de laisser Netlify gérer le
   domaine : il vous donne quatre adresses de serveurs de noms (`dns1.p0x.nsone.net`, etc.).
4. Chez votre registraire, cherchez « serveurs de noms » ou *nameservers*, et remplacez ceux qui
   sont là par ceux de Netlify.
5. Attendez. La propagation prend de quelques minutes à 24 heures.
6. Le certificat HTTPS est émis automatiquement, gratuitement, dès que le domaine répond.

### 5. Mettre le site à jour plus tard

*Deploys › Drag and drop your site folder here* → glissez à nouveau le dossier `site/`.
La nouvelle version remplace l'ancienne, à la même adresse. L'historique des versions est conservé,
et un bouton permet de revenir à la précédente si quelque chose casse.

---

## Alternative — Cloudflare Pages

Un peu plus de manipulations, mais un réseau de diffusion plus rapide et des limites plus généreuses.

1. Créez un compte sur **https://dash.cloudflare.com**.
2. *Workers & Pages › Create › Pages › Upload assets*.
3. Donnez un nom au projet, puis glissez le dossier `site/`.
4. Le site est publié sur `https://<projet>.pages.dev`, HTTPS inclus.
5. Pour un domaine : *Custom domains › Set up a domain*. Si le domaine est déjà chez Cloudflare, le
   branchement est immédiat.

À savoir : Cloudflare Pages plafonne à **25 Mo par fichier**. L'installeur de 246 Mo **ne passe
pas**. Voir la section suivante.

---

## Le cas de l'installeur de 246 Mo

C'est le seul point délicat de la publication. Chaque hébergeur a ses limites :

| Hébergeur | Limite par fichier | L'installeur passe ? |
|---|---|---|
| **Netlify** | Aucune limite documentée en pratique pour ce format ; le quota gratuit est de 100 Go de bande passante par mois | **Oui** |
| Cloudflare Pages | 25 Mo par fichier | Non |
| GitHub Pages | 100 Mo par fichier, 1 Go par dépôt | **Non** — le dépôt est refusé |
| Vercel | 100 Mo par fichier sur l'offre gratuite | Non |
| Hébergement classique (FTP) | Selon le forfait | En général oui |

**Si vous restez sur Netlify**, il n'y a rien à faire : le fichier part avec le site et le bouton de
téléchargement fonctionne tel quel.

**Si vous choisissez un hébergeur qui refuse le fichier**, mettez l'installeur ailleurs et changez le
lien :

1. Téléversez `IRIS-Setup-0.1.0.exe` sur un service de stockage — une *release* GitHub (limite de
   2 Go par fichier, gratuite et parfaitement adaptée), Google Drive, Dropbox ou un stockage objet.
2. Récupérez le lien de **téléchargement direct** — pas le lien vers la page d'aperçu, sinon le
   visiteur atterrit sur un écran intermédiaire.
3. Dans `installer.html`, remplacez les **deux** occurrences de
   `href="telechargement/IRIS-Setup-0.1.0.exe"` par ce lien : une dans la carte Windows, une à
   l'étape 1.
4. Supprimez le dossier `telechargement/` du site avant de le déposer.

**Attention à la bande passante.** À 246 Mo par téléchargement, le quota gratuit de 100 Go de
Netlify représente environ 400 téléchargements par mois. C'est large pour un lancement, mais si le
site est mentionné à la télévision, prévoyez le coup : surveillez le tableau de bord, et basculez
l'installeur vers une *release* GitHub si le trafic grimpe. Une *release* GitHub ne consomme pas la
bande passante de votre hébergement.

---

## Vérifier après publication

À faire dans l'ordre, sur le site en ligne, **pas** sur les fichiers locaux. Comptez cinq minutes.

### Les pages

- [ ] Les onze pages s'ouvrent : accueil, les lunettes, ce qu'IRIS fait, confidentialité, plans,
      installer, contact, suivre ma commande, merci, politique de confidentialité, mentions légales.
- [ ] L'adresse commence bien par `https://` et le cadenas s'affiche.
- [ ] Le menu fonctionne sur téléphone : ouvrez le site sur votre cellulaire, appuyez sur « Menu ».
- [ ] Aucune barre de défilement horizontale sur téléphone.
- [ ] Dans l'onglet Réseau du navigateur, `style.css?v=…` et `site.js?v=…` portent bien le **même**
      numéro que celui inscrit dans le README (aujourd'hui `v=5`).

### Les sept boutons de paiement

Chacun doit ouvrir PayPal **dans un nouvel onglet**, avec le bon montant déjà rempli et la
devise CAD. Il n'existe que quatre liens distincts, mais ils sont posés à sept endroits :

- [ ] `plans.html` — S'abonner · 19,99 $ (Pro) → `paypal.me/irisvela461/19.99CAD`
- [ ] `plans.html` — S'abonner · 29,99 $ (Premium) → `paypal.me/irisvela461/29.99CAD`
- [ ] `plans.html` — S'abonner · 99,99 $ (Entreprise) → `paypal.me/irisvela461/99.99CAD`
- [ ] `plans.html` — Acheter les lunettes · 250 $ → `paypal.me/irisvela461/250.00CAD`
- [ ] `index.html` — les **deux** boutons « Acheter · 250 $ » (le hero, puis le rappel du bas)
- [ ] `lunettes.html` — les **deux** boutons « Acheter · 250 $ » (le hero, puis la section « L'achat »)
- [ ] Le plan Gratuit n'a **aucun** bouton de paiement.

### Le suivi de commande

- [ ] `suivi.html` affiche bien l'encadré jaune « le suivi automatique n'est pas encore branché ».
- [ ] Le formulaire refuse un champ vide, puis, avec un numéro et un courriel valides, renvoie vers
      le courriel **sans** rien afficher dans l'adresse de la page (ni `?`, ni `#`).
- [ ] `merci.html` s'ouvre depuis les liens « Vous venez de payer ? » de l'accueil et de la fiche.

**N'allez pas jusqu'au paiement.** Vérifiez seulement que la page PayPal s'ouvre au bon montant,
puis fermez l'onglet.

### Le téléchargement

- [ ] Sur `installer.html`, le bouton « Télécharger pour Windows » lance bien le téléchargement.
- [ ] Le fichier reçu pèse environ 246 Mo et s'appelle `IRIS-Setup-0.1.0.exe`.
- [ ] Les deux boutons « Me prévenir » (macOS et Linux) ouvrent un courriel avec l'objet déjà rempli.

### Le formulaire de contact

- [ ] Sur `contact.html`, cliquez « Ouvrir mon logiciel de courriel » sans rien remplir : trois
      messages d'erreur doivent apparaître.
- [ ] Remplissez les champs, avec des accents dans le message, puis cliquez : votre logiciel de
      courriel s'ouvre, destinataire et texte déjà remplis, accents intacts.
- [ ] Le message de confirmation s'affiche sous le bouton.

### La démonstration du registre

Sur `confidentialite.html`, section « Essayez de falsifier le registre » :

- [ ] « Vérifier la chaîne » → « Intact — 5 entrées vérifiées ».
- [ ] « Réécrire l'entrée n° 2 », puis « Vérifier la chaîne » → « Altération détectée à l'entrée
      n° 2 », et les lignes suivantes passent en rouge.
- [ ] « Rétablir » → tout redevient normal.

C'est la démonstration à faire en entrevue : elle tient en quinze secondes et elle est vérifiable
par la personne en face.

---

## Après la mise en ligne

- Complétez le bloc jaune des **mentions légales** avec l'hébergeur retenu (pour Netlify, la mention
  est déjà rédigée dans le bloc, il suffit de la vérifier) et vos informations d'entreprise.
- Faites relire les deux pages légales par un juriste avant la première vente.
- Notez l'adresse du site dans vos documents de présentation.
