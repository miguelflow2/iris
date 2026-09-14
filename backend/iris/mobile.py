"""Page téléphone : parler à IRIS et utiliser ses fonctions depuis le téléphone, ordinateur resté à la maison.

Pourquoi une page dédiée plutôt que l'interface de bureau : dans une voiture ou en marchant, on ne
navigue pas dans quatre colonnes. Il faut un gros bouton, une réponse, et quelques tuiles.

Comment ça se tient ensemble : dehors, les lunettes se connectent en Bluetooth au TÉLÉPHONE (audio
mains libres, une dizaine de mètres) ; le téléphone porte cette page, et la page parle à l'ordinateur
de la maison par le réseau (réseau privé ou relais). Les lunettes n'ont ni WiFi ni carte SIM.

Depuis le 2026-09-13, la page n'est plus une chaîne géante dans ce fichier : c'est une coquille dans
mobile_static/ (index.html, app.css, js/api.js, js/coeur.js) sur laquelle les modules des fonctions
(guidage, zones, vision partagée, achats, mode invité, interprète) viennent s'enregistrer par
window.IRIS. main.py sert toujours /m, /manifest.webmanifest et /sw.js à partir des noms exportés
ici (PAGE, MANIFESTE, AGENT_SERVICE, urls_locales) ; routes_mobile.py sert le reste de mobile_static.
PAGE embarque la coquille en ligne (voir composer_page) : une requête au lieu de quatre sur le réseau
cellulaire, et une page qui tient même si routes_mobile.py ne se branche pas.

La reconnaissance vocale est celle du navigateur (gratuite, pas de clé) ; la réponse est lue par la
synthèse du téléphone, donc entendue dans les lunettes quand elles en sont la sortie audio. Les
textos et appels qu'IRIS a préparés (telephonie.py, voie « iphone ») s'ouvrent d'un geste.

Le téléphone de Miguel est un iPhone : Safari iOS d'abord (installation par « Sur l'écran d'accueil »,
synthèse vocale à amorcer depuis un vrai geste, reconnaissance capricieuse dont on ne dépend jamais).

Robustesse : main.py importe ce module au démarrage. Un fichier de mobile_static manquant (mauvais
empaquetage) ne doit JAMAIS empêcher IRIS de démarrer : on retombe sur une page qui dit le problème.
"""
from __future__ import annotations

import base64
import hashlib
import json
import logging
import re
from pathlib import Path

log = logging.getLogger("iris.mobile")

DOSSIER_STATIQUE = Path(__file__).parent / "mobile_static"


def lire_statique(nom: str) -> str | None:
    """Texte d'un fichier de mobile_static, ou None s'il manque ou ne se lit pas."""
    try:
        return (DOSSIER_STATIQUE / nom).read_text(encoding="utf-8")
    except Exception as exc:
        log.warning("page téléphone : fichier %s illisible (%s)", nom, exc)
        return None


# Page de repli : la vraie coquille manque à cette installation. Elle ne prétend rien faire.
PAGE_ABSENTE = """<!doctype html>
<html lang="fr-CA">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="theme-color" content="#1b1b1d">
<title>IRIS</title>
</head>
<body style="margin:0;background:#1b1b1d;color:#fff;font:17px/1.5 -apple-system,system-ui,sans-serif;padding:32px">
<h1 style="font-size:22px">IRIS</h1>
<p>La page téléphone n'est pas installée correctement sur cet ordinateur : ses fichiers sont absents.
Réinstallez IRIS ou mettez-la à jour. Rien ne peut être demandé à IRIS depuis ce téléphone tant que ce n'est pas réglé.</p>
</body>
</html>"""

MANIFESTE_DEFAUT = {
    "id": "/m",
    "name": "IRIS",
    "short_name": "IRIS",
    "description": "Parlez à IRIS depuis votre téléphone. Elle répond depuis votre ordinateur, qui doit rester allumé et joignable.",
    "start_url": "/m",
    "scope": "/",
    "display": "standalone",   # plein écran, sans barre de navigateur
    "orientation": "portrait",
    "background_color": "#1b1b1d",
    "theme_color": "#1b1b1d",
    "lang": "fr-CA",
    "icons": [
        {"src": "/icone-192.png", "sizes": "192x192", "type": "image/png", "purpose": "any maskable"},
        {"src": "/icone-512.png", "sizes": "512x512", "type": "image/png", "purpose": "any maskable"},
    ],
}

# Agent de service de repli, si sw.js manque : Android exige un gestionnaire `fetch` pour proposer
# l'installation. Il ne met rien en cache, et surtout pas l'API.
AGENT_SERVICE_DEFAUT = """
self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', (e) => e.waitUntil(self.clients.claim()));
self.addEventListener('fetch', (e) => {
  const url = new URL(e.request.url);
  if (url.pathname.startsWith('/api/') || url.pathname === '/ws') return;  // jamais de cache sur les données
  return;
});
"""


MARQUE_CSS = '<link rel="stylesheet" href="/m/app.css">'
MARQUE_SCRIPTS = '<script type="module" src="/m/js/api.js"></script>\n<script type="module" src="/m/js/coeur.js"></script>'
MARQUE_CSP = "script-src 'self';"


def composer_page(gabarit: str | None, api_js: str | None, coeur_js: str | None, css: str | None) -> tuple[str, str | None]:
    """La page servie à /m, avec la coquille EN LIGNE. Rend (page, empreinte du script en ligne).

    Pourquoi en ligne alors que les fichiers existent : dehors, chaque requête traverse le réseau
    cellulaire puis le tunnel jusqu'à la maison — une page, c'est une requête au lieu de quatre. Et
    la page tient debout même si routes_mobile.py ne se branche pas : un module qui plante ne doit
    jamais laisser le téléphone devant une page blanche. Les fichiers restent servis à /m/js/ pour le
    cache hors ligne et pour les modules qui importent api.js (qui reprend alors la même liaison).

    Le script en ligne est autorisé par son empreinte sha256 dans la politique de contenu, jamais
    par 'unsafe-inline'. Si un repère manque ou si une transformation ne tombe pas juste, on rend le
    gabarit tel quel (fichiers externes) : la page marche encore, simplement en quatre requêtes."""
    if not gabarit:
        return PAGE_ABSENTE, None
    if not (api_js and coeur_js and css):
        return gabarit, None
    if MARQUE_CSS not in gabarit or MARQUE_SCRIPTS not in gabarit or gabarit.count(MARQUE_CSP) != 1:
        log.warning("page téléphone : repères du gabarit introuvables, coquille servie en fichiers séparés")
        return gabarit, None
    liaison, n_export = re.subn(r"^export const \{", "const {", api_js, flags=re.M)
    liaison, n_defaut = re.subn(r"^export default [^\n]*;[ \t]*$", "", liaison, flags=re.M)
    coquille, n_import = re.subn(r"^import \{[^}\n]*\} from '\./api\.js';[ \t]*$", "", coeur_js, flags=re.M)
    code = "\n" + liaison.strip("\n") + "\n\n" + coquille.strip("\n") + "\n"
    if (n_export, n_defaut, n_import) != (1, 1, 1) or re.search(r"^[ \t]*(import|export)[ \t{]", code, flags=re.M):
        log.warning("page téléphone : api.js ou coeur.js a changé de forme, coquille servie en fichiers séparés")
        return gabarit, None
    # Dans un script en ligne, « </script » fermerait l'élément et « <!-- » dérèglerait l'analyseur HTML.
    if "</script" in code.lower() or "<!--" in code or "</style" in css.lower():
        log.warning("page téléphone : séquence interdite dans un script en ligne, coquille servie en fichiers séparés")
        return gabarit, None
    empreinte = "sha256-" + base64.b64encode(hashlib.sha256(code.encode("utf-8")).digest()).decode("ascii")
    page = gabarit.replace(MARQUE_CSS, "<style>\n" + css.strip("\n") + "\n</style>")
    page = page.replace(MARQUE_SCRIPTS, '<script type="module">' + code + "</script>")
    page = page.replace(MARQUE_CSP, f"script-src 'self' '{empreinte}';")
    return page, empreinte


def _manifeste() -> dict:
    brut = lire_statique("manifest.webmanifest")
    if brut is None:
        return dict(MANIFESTE_DEFAUT)
    try:
        donnees = json.loads(brut)
        if isinstance(donnees, dict) and donnees.get("start_url"):
            return donnees
    except ValueError as exc:
        log.warning("page téléphone : manifeste illisible (%s)", exc)
    return dict(MANIFESTE_DEFAUT)


# Lus une fois à l'import : main.py les sert tels quels. Une mise à jour d'IRIS remplace les fichiers
# et relance le service, donc rien n'est figé plus longtemps qu'une version.
GABARIT: str | None = lire_statique("index.html")
PAGE: str
EMPREINTE_COQUILLE: str | None  # « sha256-… » du script en ligne, None si la page charge des fichiers
PAGE, EMPREINTE_COQUILLE = composer_page(GABARIT, lire_statique("js/api.js"), lire_statique("js/coeur.js"),
                                         lire_statique("app.css"))
MANIFESTE: dict = _manifeste()
AGENT_SERVICE: str = lire_statique("sw.js") or AGENT_SERVICE_DEFAUT


def urls_locales(port: int, token: str) -> list[dict]:
    """Adresses à ouvrir sur le téléphone, pour chaque carte réseau de la machine."""
    import socket

    adresses: list[str] = []
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if ip.startswith("127.") or ip in adresses:
                continue
            adresses.append(ip)
    except Exception:
        pass
    return [{"ip": ip, "url": f"http://{ip}:{port}/m?token={token}"} for ip in adresses]
