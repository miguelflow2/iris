"""Fichiers de la page téléphone (/m/app.css, /m/js/<module>.js, /m/icones/…) et leurs en-têtes de sécurité.

Branché par main._brancher_modules SANS authentification, comme /m : ce ne sont que la coquille
(styles, scripts, icônes), aucune donnée. Tout ce qui compte passe ensuite par l'API, derrière la
session ouverte avec le mot de passe. main.py garde /m, /manifest.webmanifest, /sw.js et les icônes
de l'écran d'accueil (voir mobile.py) ; ce module sert le reste de mobile_static/.

En-têtes posés sur chaque fichier :
- Content-Security-Policy : scripts de cette origine, plus la coquille que /m embarque en ligne,
  admise par son empreinte sha256 exacte (jamais 'unsafe-inline', jamais eval) ;
  connexions vers cette origine, le WebSocket de l'hôte courant, les deux services OpenStreetMap du
  guidage (recherche d'adresse et itinéraire) et le relais VELA (vision partagée). Calculée à chaque
  requête : l'hôte (nom .ts.net, adresse de la maison) et le relais (réglages) changent.
- Permissions-Policy : caméra, micro, position et écran allumé pour cette origine, rien pour les autres.
- Cache court : une mise à jour d'IRIS doit atteindre le téléphone en une minute, pas en un jour.

`entetes_securite(ctx, request)` est exportée pour que /m (servie par main.py) porte les mêmes.
"""
from __future__ import annotations

import hashlib
import logging
import re
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response

log = logging.getLogger("iris.routes_mobile")

DOSSIER = Path(__file__).parent / "mobile_static"

# Services cartographiques du guidage (mobile-dehors). Rien d'autre n'est joignable depuis la page.
CARTOGRAPHIE = ("https://nominatim.openstreetmap.org", "https://routing.openstreetmap.de")

PERMISSIONS = "camera=(self), microphone=(self), geolocation=(self), screen-wake-lock=(self), payment=(), usb=()"

TYPES = {
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".png": "image/png",
    ".svg": "image/svg+xml",
    ".webp": "image/webp",
}

# Noms de fichiers admis : minuscules, chiffres, tirets. Ni point-point, ni barre, ni encodage :
# un nom qui ne ressemble pas à un module est refusé avant de toucher au disque.
NOM_MODULE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,40}\.js$")
NOM_ICONE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,40}\.(png|svg|webp)$")
# Hôte tel que le navigateur l'envoie : nom ou IPv4 avec port facultatif, ou IPv6 entre crochets.
# Tout le reste (espace, point-virgule, guillemet…) pourrait injecter une directive : on l'écarte.
HOTE_SUR = re.compile(r"^(?:[A-Za-z0-9](?:[A-Za-z0-9.-]{0,251}[A-Za-z0-9])?|\[[0-9A-Fa-f:.]{2,45}\])(?::\d{1,5})?$")

CACHE_COURT = "public, max-age=60, must-revalidate"


def _bases_relais(ctx) -> list[str]:
    """Le relais principal, son repli actif et les replis connus, filtrés comme le fait le cerveau."""
    settings = getattr(ctx, "settings", None)
    if settings is None:
        return []
    bases: list[str] = []
    try:
        from .connectors import bases_relais  # même filtre que le cerveau : https, ou http en boucle locale

        bases = list(bases_relais(settings))
    except Exception as exc:  # module absent ou réglages étranges : on retombe sur le réglage brut
        log.debug("page téléphone : bases de relais indisponibles (%s)", exc)
        brut = str(getattr(getattr(settings, "user", None), "relay_server", "") or "").strip().rstrip("/")
        if brut.startswith("https://"):
            bases = [brut]
    repli = str(getattr(settings, "relay_base_override", "") or "").strip().rstrip("/")
    if repli and repli not in bases and repli.startswith("https://"):
        bases.append(repli)
    return bases


def _origines_relais(bases: list[str]) -> list[str]:
    """https://hote et wss://hote pour chaque base (http/ws seulement pour un relais en boucle locale)."""
    origines: list[str] = []
    for base in bases:
        try:
            parts = urlsplit(base)
        except ValueError:
            continue
        hote = parts.netloc
        if not hote or not HOTE_SUR.match(hote):
            continue
        if parts.scheme == "https":
            paire = (f"https://{hote}", f"wss://{hote}")
        elif parts.scheme == "http" and (parts.hostname or "") in ("127.0.0.1", "localhost", "::1"):
            paire = (f"http://{hote}", f"ws://{hote}")
        else:
            continue
        for origine in paire:
            if origine not in origines:
                origines.append(origine)
    return origines


def politique_contenu(ctx, hote: str | None) -> str:
    """La Content-Security-Policy de la page téléphone pour cet hôte."""
    connexions = ["'self'"]
    if hote and HOTE_SUR.match(hote):
        # « 'self' » couvre ws(s) de la même origine dans les navigateurs récents ; on l'écrit quand
        # même en toutes lettres pour les Safari qui ne l'appliquaient pas encore au WebSocket.
        connexions += [f"wss://{hote}", f"ws://{hote}"]
    connexions += list(CARTOGRAPHIE)
    connexions += _origines_relais(_bases_relais(ctx))
    scripts = "script-src 'self'"
    try:  # la page /m embarque la coquille en ligne : seule son empreinte exacte est admise
        from .mobile import EMPREINTE_COQUILLE

        if EMPREINTE_COQUILLE:
            scripts += f" '{EMPREINTE_COQUILLE}'"
    except Exception as exc:  # pragma: no cover - mobile.py est importé par main.py bien avant
        log.debug("page téléphone : empreinte de la coquille indisponible (%s)", exc)
    directives = [
        "default-src 'self'",
        scripts,
        # 'unsafe-inline' pour les styles seulement : les modules posent parfois un style en ligne ;
        # un style ne peut pas exécuter de code.
        "style-src 'self' 'unsafe-inline'",
        "img-src 'self' data: blob:",
        "media-src 'self' data: blob:",
        "font-src 'self'",
        "connect-src " + " ".join(connexions),
        "worker-src 'self'",
        "manifest-src 'self'",
        "frame-src 'none'",
        "object-src 'none'",
        "base-uri 'self'",
        "form-action 'self'",
        "frame-ancestors 'none'",
    ]
    return "; ".join(directives)


def entetes_securite(ctx, request: Request, cache: str = CACHE_COURT) -> dict[str, str]:
    """En-têtes communs à tout ce que sert la page téléphone (fichiers ici, /m dans main.py)."""
    return {
        "Content-Security-Policy": politique_contenu(ctx, request.headers.get("host")),
        "Permissions-Policy": PERMISSIONS,
        "X-Content-Type-Options": "nosniff",
        # Le guidage interroge OpenStreetMap depuis le navigateur : leur règle d'usage demande que
        # l'application soit identifiable. On envoie l'origine seule, jamais le chemin ni ?token=.
        "Referrer-Policy": "strict-origin-when-cross-origin",
        "Cache-Control": cache,
    }


def _servir(ctx, request: Request, chemin: Path) -> Response:
    try:
        contenu = chemin.read_bytes()
    except FileNotFoundError:
        raise HTTPException(404, "Fichier introuvable.")
    except OSError as exc:
        log.warning("page téléphone : %s illisible (%s)", chemin.name, exc)
        raise HTTPException(404, "Fichier introuvable.")
    etiquette = '"' + hashlib.sha256(contenu).hexdigest()[:32] + '"'
    entetes = entetes_securite(ctx, request)
    entetes["ETag"] = etiquette
    if etiquette in [e.strip() for e in request.headers.get("if-none-match", "").split(",")]:
        return Response(status_code=304, headers=entetes)
    return Response(contenu, media_type=TYPES[chemin.suffix], headers=entetes)


def creer_routeur(ctx) -> APIRouter:
    routeur = APIRouter()

    @routeur.get("/m/app.css", include_in_schema=False)
    def feuille_de_style(request: Request):
        return _servir(ctx, request, DOSSIER / "app.css")

    @routeur.get("/m/js/{nom}", include_in_schema=False)
    def script(nom: str, request: Request):
        # Un module absent répond 404 : la page le tolère (chaque module est un script distinct).
        if not NOM_MODULE.match(nom):
            raise HTTPException(404, "Fichier introuvable.")
        return _servir(ctx, request, DOSSIER / "js" / nom)

    @routeur.get("/m/icones/{nom}", include_in_schema=False)
    def icone(nom: str, request: Request):
        if not NOM_ICONE.match(nom):
            raise HTTPException(404, "Fichier introuvable.")
        return _servir(ctx, request, DOSSIER / "icones" / nom)

    return routeur
