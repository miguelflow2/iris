"""Fichiers de la page téléphone (/m/app.css, /m/js/<module>.js, /m/icones/…) et les en-têtes de la page.

Branché par main._brancher_modules SANS authentification, comme /m : ce ne sont que la coquille
(styles, scripts, icônes), aucune donnée. Tout ce qui compte passe ensuite par l'API, derrière la
session ouverte avec le mot de passe. main.py garde /m, /manifest.webmanifest, /sw.js et les icônes
de l'écran d'accueil (voir mobile.py) ; ce module sert le reste de mobile_static/.

Où chaque en-tête a un effet, et où il n'en a AUCUN (revue du 2026-09-14) :
- Content-Security-Policy, frame-ancestors et Permissions-Policy ne s'appliquent qu'à un DOCUMENT
  (/m) ou à un agent de service (/sw.js). Posés sur un fichier JS, CSS ou une icône, le navigateur
  les ignore. Ils ne sont donc plus posés sur les fichiers : les y laisser faisait croire à une
  protection qui n'existait pas.
- Les fichiers portent seulement ce qui compte pour eux : nosniff (un script servi avec un mauvais
  type est refusé), cache court et étiquette (une mise à jour atteint le téléphone en une minute).
- Les en-têtes du document sont fabriqués ici (entetes_document, reponse_page) et main.py les pose sur
  /m, /sw.js et le manifeste (test strict : test_mobile.py::test_la_page_m_porte_les_entetes). La
  politique de la balise meta de /m et la garde anti-cadre de coeur.js restent en second rideau : si ce
  module ne se chargeait pas, main.py servirait /m sans ces en-têtes (sans frame-ancestors, qu'une
  balise meta ne peut pas porter) plutôt que de faire disparaître la page.

Politique du document : scripts de cette origine, plus la coquille que /m embarque en ligne, admise
par son empreinte sha256 exacte (jamais 'unsafe-inline', jamais eval) ; connexions vers cette
origine, le WebSocket de l'hôte courant, les deux services OpenStreetMap du guidage (recherche
d'adresse et itinéraire) et le relais VELA (vision partagée) ; aucun cadre, ni dedans ni autour.
Calculée à chaque requête : l'hôte (nom .ts.net, adresse de la maison) et le relais (réglages) changent.
"""
from __future__ import annotations

import hashlib
import logging
import re
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response

log = logging.getLogger("iris.routes_mobile")

DOSSIER = Path(__file__).parent / "mobile_static"

# Services cartographiques PUBLICS du guidage (mobile-dehors), utilisés quand aucun service n'est configuré
# (réglages guidage_recherche / guidage_itineraire, voir config.py). Rien d'autre n'est joignable depuis la page.
CARTOGRAPHIE = ("https://nominatim.openstreetmap.org", "https://routing.openstreetmap.de")

PERMISSIONS = "camera=(self), microphone=(self), geolocation=(self), screen-wake-lock=(self), payment=(), usb=()"
# Aucun en-tête Referer vers une autre origine : il porterait le nom de la machine de l'utilisateur
# (https://<pc>.tailXXXX.ts.net) à OpenStreetMap ou à tout site ouvert depuis la page. Rien sur
# l'ordinateur ne lit le Referer des requêtes de la page elle-même.
REFERENT = "same-origin"

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
# /m et /sw.js : revalidés à chaque ouverture (la page est composée au démarrage d'IRIS ; un agent de
# service figé dans un cache garderait l'ancienne coquille).
CACHE_DOCUMENT = "no-cache"


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


def services_guidage(ctx) -> dict:
    """Services réellement utilisés par le guidage de la page téléphone : ceux configurés sur cet ordinateur,
    sinon les services publics d'OpenStreetMap. Les adresses sont revalidées ici (un réglage écrit à la main
    dans settings.json ne passe pas forcément par le modèle)."""
    from .config import GUIDAGE_ITINERAIRE_PUBLIC, GUIDAGE_RECHERCHE_PUBLIQUE, adresse_service_cartographique

    user = getattr(getattr(ctx, "settings", None), "user", None)
    recherche = adresse_service_cartographique(getattr(user, "guidage_recherche", ""))
    itineraire = adresse_service_cartographique(getattr(user, "guidage_itineraire", ""), dossier=True)
    return {
        "recherche": recherche or GUIDAGE_RECHERCHE_PUBLIQUE,
        "itineraire": itineraire or GUIDAGE_ITINERAIRE_PUBLIC,
        "recherche_publique": not recherche,
        "itineraire_public": not itineraire,
    }


def origines_guidage(ctx) -> list[str]:
    """Origines (schéma://hôte[:port]) des deux services du guidage, pour connect-src."""
    origines: list[str] = []
    services = services_guidage(ctx)
    for adresse in (services["recherche"], services["itineraire"]):
        parts = urlsplit(adresse)
        origine = f"{parts.scheme}://{parts.netloc}"
        if parts.netloc and HOTE_SUR.match(parts.netloc) and origine not in origines:
            origines.append(origine)
    return origines


def politique_contenu(ctx, hote: str | None) -> str:
    """La Content-Security-Policy de la page téléphone pour cet hôte."""
    connexions = ["'self'"]
    if hote and HOTE_SUR.match(hote):
        # « 'self' » couvre ws(s) de la même origine dans les navigateurs récents ; on l'écrit quand
        # même en toutes lettres pour les Safari qui ne l'appliquaient pas encore au WebSocket.
        connexions += [f"wss://{hote}", f"ws://{hote}"]
    connexions += [o for o in origines_guidage(ctx) if o not in connexions]
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


def politique_agent_service() -> str:
    """La politique de /sw.js : il ne fait de requêtes que vers sa propre origine (voir sw.js)."""
    return "; ".join([
        "default-src 'self'",
        "script-src 'self'",
        "connect-src 'self'",
        "object-src 'none'",
        "base-uri 'none'",
    ])


def entetes_document(ctx, request: Request, cache: str = CACHE_DOCUMENT) -> dict[str, str]:
    """En-têtes du document /m : c'est là, et seulement là, que la politique protège la page."""
    return {
        "Content-Security-Policy": politique_contenu(ctx, request.headers.get("host")),
        "Permissions-Policy": PERMISSIONS,
        # frame-ancestors couvre les navigateurs récents ; X-Frame-Options, les plus anciens. Sans eux,
        # un site tiers peut intégrer /m dans un cadre invisible et faire toucher « Se connecter » ou
        # « Autoriser » à l'insu de l'utilisateur.
        "X-Frame-Options": "DENY",
        "X-Content-Type-Options": "nosniff",
        "Referrer-Policy": REFERENT,
        "Cache-Control": cache,
    }


def entetes_securite(ctx, request: Request, cache: str = CACHE_DOCUMENT) -> dict[str, str]:
    """Ancien nom de entetes_document, gardé pour les appels existants."""
    return entetes_document(ctx, request, cache)


def entetes_agent_service() -> dict[str, str]:
    return {
        "Content-Security-Policy": politique_agent_service(),
        "X-Content-Type-Options": "nosniff",
        "Cache-Control": CACHE_DOCUMENT,
    }


def entetes_fichier() -> dict[str, str]:
    """Styles, scripts, icônes, manifeste : aucune politique de contenu, elle n'y aurait aucun effet."""
    return {
        "X-Content-Type-Options": "nosniff",
        "Referrer-Policy": REFERENT,
        "Cache-Control": CACHE_COURT,
    }


# Réponses prêtes pour main.py (une ligne par route) : /m, /sw.js et /manifest.webmanifest.
def reponse_page(ctx, request: Request, page: str) -> HTMLResponse:
    # La balise meta de /m s'applique EN PLUS de l'en-tête (le navigateur retient l'intersection) : elle
    # nomme les services publics du guidage. Quand d'autres services sont configurés, elle est ajustée ici,
    # sinon elle bloquerait le service configuré. Seule la meta change : l'empreinte du script en ligne tient.
    publics = " ".join(CARTOGRAPHIE)
    configures = " ".join(origines_guidage(ctx))
    if configures != publics and publics in page:
        page = page.replace(publics, configures, 1)
    return HTMLResponse(page, headers=entetes_document(ctx, request))


def reponse_agent_service(code: str) -> Response:
    return Response(code, media_type="application/javascript", headers=entetes_agent_service())


def reponse_manifeste(manifeste: dict) -> JSONResponse:
    return JSONResponse(manifeste, media_type="application/manifest+json", headers=entetes_fichier())


def _servir(ctx, request: Request, chemin: Path) -> Response:
    try:
        contenu = chemin.read_bytes()
    except FileNotFoundError:
        raise HTTPException(404, "Fichier introuvable.")
    except OSError as exc:
        log.warning("page téléphone : %s illisible (%s)", chemin.name, exc)
        raise HTTPException(404, "Fichier introuvable.")
    etiquette = '"' + hashlib.sha256(contenu).hexdigest()[:32] + '"'
    entetes = entetes_fichier()
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
