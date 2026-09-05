"""Relais VELA : l'accès IA d'IRIS, fourni par VELA plutôt que par le client.

Pourquoi ce service existe. Jusqu'ici, IRIS demandait sa propre clé OpenRouter à chaque
utilisateur, dès l'accueil. C'était faux sur le fond : ce qu'on vend, c'est une assistante qui
marche, pas un formulaire à remplir. Et c'était faux sur le plan commercial : si le client
apporte sa clé, l'abonnement ne sert plus à grand-chose.

Le principe est donc inversé. La clé est ici, sur le serveur de VELA. IRIS s'y présente avec un
jeton d'appareil, le relais reconnaît l'abonnement rattaché au courriel, et décide quel modèle
répond : gratuit pour le plan Gratuit, Claude pour le plan Entreprise. Le client ne colle rien.

Ce que le relais n'est pas. Il ne conserve aucune conversation : il transmet, il ne garde pas.
Les messages passent, seuls les compteurs restent. C'est la seule promesse qu'un proxy puisse
tenir, et il vaut mieux l'écrire que la sous-entendre.

Déploiement : voir README.md. Une seule variable est indispensable, VELA_OPENROUTER_KEY.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import re
import time
from datetime import date, datetime, timezone
from pathlib import Path
from threading import Lock

import httpx
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("vela.relais")

AMONT = "https://openrouter.ai/api/v1"
CLE_AMONT = os.environ.get("VELA_OPENROUTER_KEY", "").strip()
SECRET_JETON = os.environ.get("VELA_SECRET", "").strip().encode() or b"VELA-relais-jeton-a-remplacer"
# Doit rester identique à LICENSE_SECRET dans backend/iris/plans.py : sinon les clés émises ici
# seront rejetées par IRIS.
SECRET_LICENCE = os.environ.get("VELA_LICENCE_SECRET", "VELA-IRIS-2026-license-v1").encode()
DONNEES = Path(os.environ.get("VELA_DONNEES") or (Path(__file__).parent / "donnees"))
DUREE_JETON = 90 * 24 * 3600

# Quels modèles répondent, selon l'abonnement. Repris de backend/iris/plans.py : c'est la même
# promesse commerciale, et un plan Gratuit ne doit jamais atteindre Claude par accident.
GRATUITS = [
    "minimax/minimax-m3:free",
    "google/gemma-4-31b-it:free",
    "nvidia/nemotron-3.5-lightning:free",
    "z-ai/glm-5.2:free",
]
MODELES_PAR_PLAN: dict[str, list[str]] = {
    "gratuit": GRATUITS,
    "pro": ["google/gemini-2.5-flash", "openai/gpt-5-mini"] + GRATUITS,
    "premium": ["anthropic/claude-sonnet-5", "google/gemini-2.5-flash", "openai/gpt-5-mini"] + GRATUITS,
    "entreprise": ["anthropic/claude-opus-5", "anthropic/claude-sonnet-5", "google/gemini-2.5-flash"] + GRATUITS,
}
QUOTAS = {"gratuit": 300, "pro": 600, "premium": 1000, "entreprise": 1500}

_verrou = Lock()


# --------------------------------------------------------------------------- petits utilitaires
def _b64(donnees: bytes) -> str:
    return base64.urlsafe_b64encode(donnees).decode().rstrip("=")


def _debase64(texte: str) -> bytes:
    return base64.urlsafe_b64decode(texte + "=" * (-len(texte) % 4))


def _lire(nom: str) -> dict:
    try:
        return json.loads((DONNEES / nom).read_text(encoding="utf-8"))
    except Exception:
        return {}


def _ecrire(nom: str, contenu: dict) -> None:
    DONNEES.mkdir(parents=True, exist_ok=True)
    tmp = DONNEES / (nom + ".tmp")
    tmp.write_text(json.dumps(contenu, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(DONNEES / nom)


def normaliser(courriel: str) -> str:
    return (courriel or "").strip().lower()


# --------------------------------------------------------------------------- abonnements
_CACHE: dict[str, tuple[float, dict]] = {}
CACHE_SECONDES = 300


def _demander_au_serveur_de_licences(courriel: str) -> dict | None:
    """Interroge le serveur de licences, seule source de vérité sur qui est abonné.

    Le serveur de licences (dossier `server/`) reçoit les webhooks PayPal, crée les abonnements
    et émet les clés. Tenir ici une seconde liste d'abonnés reviendrait à avoir deux vérités qui
    finiraient par diverger — et c'est toujours le client qui paierait la différence."""
    base = os.environ.get("VELA_LICENCES_URL", "").strip().rstrip("/")
    if not base or not courriel:
        return None
    frais = _CACHE.get(courriel)
    if frais and time.time() - frais[0] < CACHE_SECONDES:
        return frais[1]
    try:
        with httpx.Client(timeout=8) as client:
            reponse = client.get(base + "/api/licence", params={"email": courriel})
        etat = {"plan": "gratuit", "expires": ""} if reponse.status_code == 404 else {
            "plan": reponse.json().get("plan", "gratuit"),
            "expires": reponse.json().get("expires", ""),
        }
    except Exception as exc:
        log.warning("serveur de licences injoignable (%s) : repli sur le fichier local", exc)
        return None
    if etat["plan"] not in MODELES_PAR_PLAN:
        etat["plan"] = "gratuit"
    _CACHE[courriel] = (time.time(), etat)
    return etat


def abonnement(courriel: str) -> dict:
    """Le plan rattaché à un courriel. Inconnu, expiré ou vide : c'est le plan gratuit.

    On demande d'abord au serveur de licences. S'il n'est pas configuré ou ne répond pas, on
    retombe sur un fichier JSON local, édité à la main — utile pour un dépannage ou un essai,
    jamais destiné à devenir la référence."""
    du_serveur = _demander_au_serveur_de_licences(normaliser(courriel))
    if du_serveur is not None:
        return du_serveur
    fiche = _lire("abonnes.json").get(normaliser(courriel))
    if not isinstance(fiche, dict):
        return {"plan": "gratuit", "expires": ""}
    plan = fiche.get("plan", "gratuit")
    if plan not in MODELES_PAR_PLAN:
        plan = "gratuit"
    echeance = (fiche.get("expires") or "").strip()
    if echeance:
        try:
            if date.fromisoformat(echeance) < datetime.now(timezone.utc).date():
                return {"plan": "gratuit", "expires": echeance, "expire": True}
        except ValueError:
            pass
    return {"plan": plan, "expires": echeance}


def cle_licence(plan: str, echeance: str, courriel: str) -> str:
    """Clé IRIS-<charge>-<signature>, dans le format exact qu'attend backend/iris/plans.py."""
    charge = _b64(json.dumps({"p": plan, "e": echeance, "u": courriel}, separators=(",", ":")).encode())
    signature = hmac.new(SECRET_LICENCE, charge.encode(), hashlib.sha256).hexdigest()[:20]
    return "IRIS-" + charge + "-" + signature


# --------------------------------------------------------------------------- jetons d'appareil
def emettre_jeton(courriel: str, machine: str) -> str:
    corps = "{}.{}.{}".format(
        _b64(normaliser(courriel).encode()),
        _b64((machine or "?")[:64].encode()),
        int(time.time() + DUREE_JETON),
    )
    return corps + "." + _b64(hmac.new(SECRET_JETON, corps.encode(), hashlib.sha256).digest()[:24])


def lire_jeton(jeton: str) -> dict | None:
    """Renvoie {courriel, machine} si le jeton est authentique et non périmé, sinon None."""
    try:
        courriel_b64, machine_b64, echeance, signature = (jeton or "").rsplit(".", 3)
    except ValueError:
        return None
    corps = "{}.{}.{}".format(courriel_b64, machine_b64, echeance)
    attendue = _b64(hmac.new(SECRET_JETON, corps.encode(), hashlib.sha256).digest()[:24])
    if not hmac.compare_digest(attendue, signature):
        return None
    try:
        if int(echeance) < time.time():
            return None
    except ValueError:
        return None
    try:
        return {
            "courriel": _debase64(courriel_b64).decode(errors="replace"),
            "machine": _debase64(machine_b64).decode(errors="replace"),
        }
    except Exception:
        return None


# --------------------------------------------------------------------------- quotas
def consommer(identite: str, plan: str) -> tuple[int, int]:
    """Incrémente le compteur du mois. Lève une 429 quand la limite du plan est franchie."""
    limite = QUOTAS.get(plan, QUOTAS["gratuit"])
    mois = datetime.now(timezone.utc).strftime("%Y-%m")
    with _verrou:
        compteurs = _lire("quotas.json")
        if compteurs.get("mois") != mois:
            compteurs = {"mois": mois}
        utilise = int(compteurs.get(identite, 0)) + 1
        if utilise > limite:
            raise HTTPException(429, "Quota mensuel atteint ({} requêtes pour le plan {}).".format(limite, plan))
        compteurs[identite] = utilise
        _ecrire("quotas.json", compteurs)
    return utilise, limite


def modele_autorise(demande: str, plan: str) -> str:
    """Le client propose, le relais dispose. Un plan Gratuit n'obtient jamais Claude, quoi qu'il envoie."""
    permis = MODELES_PAR_PLAN.get(plan, GRATUITS)
    return demande if demande in permis else permis[0]


# --------------------------------------------------------------------------- l'application
app = FastAPI(title="Relais VELA", docs_url=None, redoc_url=None)


class Appareil(BaseModel):
    machine: str = ""
    email: str = ""


@app.get("/sante")
def sante():
    return {"ok": True, "amont": bool(CLE_AMONT)}


@app.post("/api/appareil")
def enregistrer_appareil(corps: Appareil):
    """Premier contact d'une installation d'IRIS. Aucun mot de passe : le jeton n'ouvre l'accès
    qu'à l'IA, jamais aux données de qui que ce soit."""
    if not CLE_AMONT:
        raise HTTPException(503, "Le relais n'a pas de clé IA configurée.")
    etat = abonnement(corps.email)
    return {
        "jeton": emettre_jeton(corps.email, corps.machine),
        "plan": etat["plan"],
        "expires": etat["expires"],
        "modeles": MODELES_PAR_PLAN[etat["plan"]],
    }


@app.get("/api/licence")
def licence(email: str = ""):
    """Consulté par IRIS pour activer l'abonnement toute seule (backend/iris/licence.py)."""
    etat = abonnement(email)
    if etat["plan"] == "gratuit":
        return JSONResponse({"message": "Aucun abonnement actif pour ce courriel."}, status_code=404)
    return {
        "key": cle_licence(etat["plan"], etat["expires"], normaliser(email)),
        "plan": etat["plan"],
        "expires": etat["expires"],
    }


def _identifier(autorisation: str | None) -> tuple[str, str]:
    jeton = (autorisation or "").replace("Bearer ", "", 1).strip()
    info = lire_jeton(jeton)
    if not info:
        raise HTTPException(401, "Jeton d'appareil invalide ou expiré. Relancez IRIS pour en obtenir un nouveau.")
    etat = abonnement(info["courriel"])
    return (info["courriel"] or "anonyme:" + info["machine"]), etat["plan"]


# Les forfaits payants promettent une voix ElevenLabs. Sans ce relais, chaque abonné devrait
# fournir sa propre clé ElevenLabs : il paierait donc une voix qu'il n'entendrait jamais. La
# voix fait partie de ce qu'on vend, au même titre que le modèle.
AMONT_VOIX = "https://api.elevenlabs.io/v1"
CLE_VOIX = os.environ.get("VELA_ELEVENLABS_KEY", "").strip()
VOIX_INCLUSE = {"pro", "premium", "entreprise"}  # le plan Gratuit garde la voix de Windows


@app.post("/v1/voix/{voice_id}")
async def voix(voice_id: str, request: Request, authorization: str | None = Header(default=None)):
    """Fabrique la voix d'IRIS pour un abonné, avec la clé de VELA.

    Le texte transite, il n'est pas conservé. Un plan Gratuit est refusé ici : sa voix est celle
    de Windows, et le dire franchement vaut mieux que de laisser une requête échouer sans raison."""
    if not CLE_VOIX:
        raise HTTPException(503, "Le relais n'a pas de clé de synthèse vocale configurée.")
    identite, plan = _identifier(authorization)
    if plan not in VOIX_INCLUSE:
        raise HTTPException(403, "La voix naturelle fait partie des forfaits payants. Le plan Gratuit utilise la voix de Windows.")
    if not re.fullmatch(r"[A-Za-z0-9]{1,40}", voice_id):
        raise HTTPException(400, "Identifiant de voix invalide.")
    try:
        charge = await request.json()
    except Exception:
        raise HTTPException(400, "Corps de requête illisible.")
    texte = (charge or {}).get("text") or ""
    if not texte.strip():
        raise HTTPException(400, "Rien à prononcer.")
    consommer(identite + "|voix", plan)

    parametres = str(request.url.query or "output_format=pcm_16000&optimize_streaming_latency=3")
    entetes = {"xi-api-key": CLE_VOIX, "Content-Type": "application/json"}

    async def flux():
        async with httpx.AsyncClient(timeout=None) as client:
            async with client.stream("POST", f"{AMONT_VOIX}/text-to-speech/{voice_id}/stream?{parametres}",
                                     json=charge, headers=entetes) as amont:
                if amont.status_code >= 400:
                    log.warning("voix amont %s", amont.status_code)
                    return
                async for morceau in amont.aiter_bytes():
                    yield morceau

    return StreamingResponse(flux(), media_type="audio/basic")


@app.get("/v1/models")
def modeles(authorization: str | None = Header(default=None)):
    _, plan = _identifier(authorization)
    return {"object": "list", "data": [{"id": m, "object": "model", "owned_by": "vela"} for m in MODELES_PAR_PLAN[plan]]}


@app.post("/v1/chat/completions")
async def completions(request: Request, authorization: str | None = Header(default=None)):
    """Transmet la demande à l'IA, sous le modèle auquel l'abonnement donne droit.

    Rien n'est conservé du contenu : ni les messages reçus, ni la réponse renvoyée."""
    if not CLE_AMONT:
        raise HTTPException(503, "Le relais n'a pas de clé IA configurée.")
    identite, plan = _identifier(authorization)
    try:
        charge = await request.json()
    except Exception:
        raise HTTPException(400, "Corps de requête illisible.")
    if not isinstance(charge, dict) or not charge.get("messages"):
        raise HTTPException(400, "Requête sans messages.")

    consommer(identite, plan)
    charge["model"] = modele_autorise(str(charge.get("model") or ""), plan)
    entetes = {
        "Authorization": "Bearer " + CLE_AMONT,
        "HTTP-Referer": "https://vela.app/iris",
        "X-Title": "IRIS (VELA)",
        "Content-Type": "application/json",
    }
    log.info("relais : plan=%s modele=%s flux=%s", plan, charge["model"], bool(charge.get("stream")))

    if not charge.get("stream"):
        async with httpx.AsyncClient(timeout=180) as client:
            reponse = await client.post(AMONT + "/chat/completions", json=charge, headers=entetes)
        return JSONResponse(reponse.json(), status_code=reponse.status_code)

    async def flux():
        async with httpx.AsyncClient(timeout=None) as client:
            async with client.stream("POST", AMONT + "/chat/completions", json=charge, headers=entetes) as amont:
                if amont.status_code >= 400:
                    detail = (await amont.aread()).decode(errors="replace")[:400]
                    log.warning("amont %s : %s", amont.status_code, detail)
                    message = "Le service IA a refusé la demande ({}).".format(amont.status_code)
                    yield ("data: " + json.dumps({"error": {"message": message}}) + "\n\n").encode()
                    return
                async for morceau in amont.aiter_bytes():
                    yield morceau

    return StreamingResponse(flux(), media_type="text/event-stream")
