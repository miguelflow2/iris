# mobile-web — ancien site téléphone (Netlify), PAS la page de référence

> Mis au clair le 2026-09-13. **La page téléphone de référence d'IRIS est `/m`, servie par
> l'ordinateur lui-même** (fichiers dans `backend/iris/mobile_static/`, routes dans
> `backend/iris/main.py` et `backend/iris/routes_mobile.py`). Pour s'en servir dehors, suivre
> `docs/MODE-DEHORS.md`. Ce dossier-ci est un site statique séparé, plus ancien, qui ne parle pas à
> l'ordinateur de la même façon.

---

## Ce qui est où

| | `/m` servie par l'ordinateur (référence) | `mobile-web/` (ce dossier) |
|---|---|---|
| Hébergée par | IRIS, sur l'ordinateur de l'utilisateur | Netlify (site statique) |
| Joignable dehors par | le réseau privé (Tailscale, `https://<machine>.ts.net/m`) | Internet public |
| Connexion | mot de passe d'IRIS, puis session de 30 jours | aucune pour la voix ; courriel + code d'appairage pour la télécommande |
| Parler à IRIS | oui : reconnaissance du téléphone, réponse de l'IRIS de l'utilisateur, lue par le téléphone | widget vocal d'un fournisseur tiers (voir plus bas) |
| Décrire une photo, « où ai-je posé », sous-titres, alertes plein écran, brouillons de textos | oui | non |
| Guidage, zones sans mémoire, vision partagée, achats, mode invité, interprète | modules chargés par `/m` (équipe mobile-dehors) | non |
| Mémoire et données de l'utilisateur | celles de son ordinateur | aucune |

## À faire avant le lancement (constat de revue du 2026-09-14)

**Déploiement Netlify de ce dossier : NON vérifié.** L'adresse du site Netlify de `mobile-web/`
n'est écrite nulle part dans le dépôt, et la revue n'a pas accès au compte Netlify. Tant que Miguel ne
l'a pas confirmé, il faut supposer que la page est **encore en ligne**, sur Internet public, avec le
widget vocal d'un fournisseur tiers et son attribution visible.

Ce qui a été fait dans ce dossier le 2026-09-14 :
- `index.html` est **remplacé** par une page d'information sans aucun script tiers ni identifiant
  d'agent : « Cette page n'est plus utilisée », avec le chemin vers la page téléphone de l'ordinateur
  (IRIS › Mode dehors) et la voie iPhone (app native). `assets/app.js` et `sw.js` ne servent plus
  qu'à désinscrire l'ancien agent de service et vider ses caches sur les téléphones qui l'avaient installée.
- `_headers` garde `script-src 'self'`, `microphone=(self)`, `noindex` et l'interdiction de cadre.
- Test : `backend/tests/test_demandes_croisees.py` vérifie qu'aucun fichier de ce dossier ne contient
  plus l'identifiant ni le script du widget.

Ce qui reste à faire, par Miguel (hors dépôt) :
1. **Redéployer ou dépublier** le site Netlify de `mobile-web/` : tant que ce n'est pas fait, l'ancienne
   page reste en ligne. Noter ici la date : « Redéployé le … » ou « Dépublié le … ».
2. **Désactiver l'agent vocal chez le fournisseur** : son identifiant public reste lisible dans
   l'historique git et dans les copies déjà servies ; seul le fournisseur peut le rendre inutilisable.

## Ce que contient ce dossier, tel quel

- `index.html` + `assets/` : depuis le 2026-09-14, une page d'information qui renvoie vers `/m`.
  L'ancienne page intégrait un widget vocal tiers qui affichait l'attribution de son fournisseur,
  incompatible avec le masque de marque ; elle ne doit pas revenir.
- `telecommande.html` + `telecommande.js` : une télécommande qui passe par le relais VELA
  (WebSocket `/telecommande/ws`, courriel + code d'appairage de l'ordinateur). Voir
  `backend/iris/telecommande.py` et `serveur/relais.py`. Revérifiée le 2026-09-14 contre le code :
  - corrigé : promesse absolue (« avant tout envoi ou toute action irréversible ») remplacée par ce que
    le code fait (courriel, texto et appel attendent toujours l'accord ; les autres actions, dont les
    suppressions, suivent le réglage « Confirmation avant une commande », et rien n'est demandé avec « Jamais ») ;
    limites écrites (ordinateur allumé, délai non garanti, rien pendant le verrouillage, aperçu limité
    sans lunettes VELA) ; adresse d'exemple d'un tunnel éphémère remplacée par `relais.velaglass.ca` ;
    lien « Revenir à la voix » (la voix n'existe plus ici) ; raison réelle du relais affichée (429, 503)
    au lieu de « injoignable » ; aucune reconnexion en rafale ; `noindex` ;
  - **pas corrigé, à trancher** : l'application de bureau n'affiche PAS le code d'appairage (il n'est
    que dans le fichier `telecommande-pairing` du dossier de données et dans le journal) et n'indique
    nulle part l'adresse de cette page. Un client ne peut donc pas s'en servir sans aide : ce n'est pas
    une fonction prête à vendre. La page le dit.
- `manifest.webmanifest`, `sw.js`, icônes : installation sur l'écran d'accueil. Le manifeste ne
  décrit plus une « assistante vocale » : il dit que la page n'est plus utilisée.
- `_headers` : en-têtes Netlify. Caméra, micro, position et écran allumé permis pour cette origine
  seulement. Depuis le 2026-09-14, la politique de contenu n'admet que les scripts de ce site, ce qui
  bloque le widget vocal (explication dans le fichier).
- `netlify.toml` : publication du dossier tel quel, sans compilation.

## Pourquoi `/m` sur l'ordinateur est la bonne page

- **C'est l'IRIS de l'utilisateur qui répond** : sa mémoire, ses réglages, ses consentements, ses
  brouillons de textos. Un site public n'a rien de tout cela.
- **Rien n'est publié sur Internet** : avec Tailscale, l'adresse `.ts.net` ne répond qu'aux appareils
  de l'utilisateur, et IRIS exige en plus le mot de passe (le jeton écrit dans une adresse ne vaut
  plus rien depuis l'extérieur dès qu'un mot de passe existe).
- **Aucun nom de fournisseur** n'apparaît dans la page, et chaque limite est écrite là où elle compte
  (photo et non surveillance en direct, micro de l'ordinateur pour les sous-titres, latence mesurée).

## Lancer ce dossier en développement (s'il le faut encore)

Site statique, aucun build. Le micro et l'agent de service exigent un contexte sûr (`localhost` ou
HTTPS).

```bash
# depuis la racine du dépôt
python -m http.server 8899 --directory mobile-web
# puis ouvrir http://127.0.0.1:8899/
```

Déploiement : glisser le dossier sur Netlify Drop, ou relier le dépôt avec `mobile-web` comme dossier
de base (voir `netlify.toml`). Netlify applique `_headers` automatiquement.

## Limites connues, sans enjolivure

- L'agent de service échoue à s'enregistrer dans l'aperçu intégré des outils (« An unknown error
  occurred when fetching the script ») alors que le fichier est servi correctement : limite de cet
  aperçu, constatée aussi sur `/m`. Rien ne dépend de lui pour fonctionner.
- Sur iPhone, une page web ne reçoit rien en arrière-plan ni écran verrouillé, ne vibre pas, et ne
  s'installe que par Safari › Partager › « Sur l'écran d'accueil ». Voir `mobile-ios/REALITE-IOS.md`.
