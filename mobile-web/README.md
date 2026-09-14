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

## Ce que contient ce dossier, tel quel

- `index.html` + `assets/` : une page d'accueil PWA qui intègre le **widget vocal ElevenLabs**
  (script chargé depuis `elevenlabs.io`). Le widget affiche sa propre attribution de fournisseur :
  c'est **incompatible avec le masque de marque** (aucun nom de fournisseur visible par le client).
  Ne pas remettre cette page à un client en l'état.
- `telecommande.html` + `telecommande.js` : une télécommande qui passe par le relais VELA
  (WebSocket, courriel d'achat + code d'appairage affiché par l'ordinateur). Voir
  `backend/iris/telecommande.py` et `serveur/relais.py`. Non revérifiée dans ce chantier.
- `manifest.webmanifest`, `sw.js`, icônes : installation sur l'écran d'accueil.
- `_headers` : en-têtes Netlify. Depuis le 2026-09-13, la caméra, la position et l'écran allumé ne
  sont plus bloqués pour cette origine (ils l'étaient : `camera=()`, `geolocation=()`), pour qu'une
  fonction du téléphone servie ici un jour n'échoue pas en silence. La politique de contenu reste
  ouverte à cause du widget vocal (explication dans le fichier).
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
