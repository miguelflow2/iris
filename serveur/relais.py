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
VELA_ELEVENLABS_KEY s'ajoute pour la voix, incluse dans tous les forfaits depuis le 5 septembre
2026 : sans elle le relais transmet la parole à personne et /v1/voix répond 503.
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
from contextlib import asynccontextmanager
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
# Point d'acces compatible OpenAI d'Anthropic. Quand cette cle est presente, les modeles Claude
# partent DIRECTEMENT chez Anthropic plutot que par OpenRouter — utile en test (on ne paie que le
# compte Anthropic deja recharge) et souvent moins cher qu'OpenRouter, qui prend une marge.
AMONT_ANTHROPIC = "https://api.anthropic.com/v1"
CLE_ANTHROPIC = os.environ.get("VELA_ANTHROPIC_KEY", "").strip()
SECRET_JETON = os.environ.get("VELA_SECRET", "").strip().encode() or b"VELA-relais-jeton-a-remplacer"
# Doit rester identique à LICENSE_SECRET dans backend/iris/plans.py : sinon les clés émises ici
# seront rejetées par IRIS.
SECRET_LICENCE = os.environ.get("VELA_LICENCE_SECRET", "VELA-IRIS-2026-license-v1").encode()
DONNEES = Path(os.environ.get("VELA_DONNEES") or (Path(__file__).parent / "donnees"))
DUREE_JETON = 90 * 24 * 3600

# Quels modèles répondent, selon l'abonnement. Repris de backend/iris/plans.py : c'est la même
# promesse commerciale, et un plan Gratuit ne doit jamais atteindre Claude par accident.
# Modèles gratuits, dans l'ordre de préférence. Chacun est VÉRIFIÉ présent au catalogue OpenRouter
# par serveur/verifier_modeles.py — lancé le 6 septembre 2026, il a écarté « z-ai/glm-5.2:free »,
# qui n'existait pas et aurait échoué en direct sur le forfait gratuit. Relancer ce vérificateur
# avant chaque déploiement : OpenRouter renomme et retire des modèles sans prévenir.
GRATUITS = [
    "minimax/minimax-m3:free",
    "google/gemma-4-31b-it:free",
    "nvidia/nemotron-3.5-lightning:free",
]
# Décision de Miguel du 6 septembre 2026 : « Claude aux payants, gratuit aux gratuits ». Chaque
# abonnement finance son propre cerveau. Le PREMIER modèle de chaque liste est le défaut du forfait
# (voir modele_autorise), donc tout forfait payant MÈNE avec Claude — c'est ce que le client paie.
# Le gratuit ne l'atteint jamais, quoi qu'il demande : sa facture serait à la charge de VELA.
MODELES_PAR_PLAN: dict[str, list[str]] = {
    "gratuit": GRATUITS,
    "pro": ["anthropic/claude-sonnet-5", "google/gemini-2.5-flash", "openai/gpt-5-mini"] + GRATUITS,
    "premium": ["anthropic/claude-sonnet-5", "google/gemini-2.5-flash", "openai/gpt-5-mini"] + GRATUITS,
    "entreprise": ["anthropic/claude-opus-5", "anthropic/claude-sonnet-5", "google/gemini-2.5-flash"] + GRATUITS,
}
QUOTAS = {"gratuit": 300, "pro": 600, "premium": 1000, "entreprise": 1500}

# Un quota en NOMBRE DE REQUÊTES ne protège pas grand-chose. Une question courte et une demande
# accompagnée d'une capture d'écran, de la mémoire et d'un long historique comptent toutes les deux
# pour un : la seconde peut coûter cent fois la première. Comme la clé qui paie est celle de
# Miguel, il faut aussi compter les jetons.
#
# Ces plafonds sont des FILETS, pas des prévisions : personne ne peut deviner la consommation réelle
# avant d'avoir des clients. Miguel doit les ajuster à partir de sa vraie facture OpenRouter. Le
# service dit à son démarrage lesquels sont actifs.
def _plafond(nom: str, defaut: int) -> int:
    try:
        return int(os.environ.get(nom, "") or defaut)
    except ValueError:
        return defaut


PLAFONDS_JETONS = {
    "gratuit": _plafond("VELA_JETONS_GRATUIT", 2_000_000),
    "pro": _plafond("VELA_JETONS_PRO", 5_000_000),
    "premium": _plafond("VELA_JETONS_PREMIUM", 8_000_000),
    "entreprise": _plafond("VELA_JETONS_ENTREPRISE", 15_000_000),
}
# Le dernier rempart : tous abonnés confondus. C'est celui qui empêche un compte OpenRouter d'être
# vidé pendant une nuit. 0 le désactive, et le service le signale au démarrage.
PLAFOND_GLOBAL = _plafond("VELA_JETONS_TOTAL", 30_000_000)

# Le même raisonnement, pour la VOIX. Depuis le 5 septembre 2026 la voix ElevenLabs est incluse dans
# tous les forfaits, Gratuit compris : plus rien ne borne la dépense côté abonnement, et ElevenLabs
# facture au caractère. Compter les APPELS n'y suffirait pas — « oui » et une tirade de mille
# caractères comptent chacune pour un appel, alors que la seconde coûte cent fois la première.
#
# Ces plafonds sont des FILETS, pas des prévisions : personne ne peut deviner la consommation réelle
# avant d'avoir des clients. Miguel doit les ajuster sur sa vraie facture ElevenLabs. Ordre de
# grandeur relevé le 5 septembre 2026 : environ 0,05 US$ par millier de caractères en Turbo v2.5,
# donc le plafond global ci-dessous vaut à peu près cent dollars par mois dans le pire cas.
PLAFONDS_CARACTERES = {
    "gratuit": _plafond("VELA_CARACTERES_GRATUIT", 60_000),
    "pro": _plafond("VELA_CARACTERES_PRO", 150_000),
    "premium": _plafond("VELA_CARACTERES_PREMIUM", 300_000),
    "entreprise": _plafond("VELA_CARACTERES_ENTREPRISE", 600_000),
}
PLAFOND_CARACTERES_GLOBAL = _plafond("VELA_CARACTERES_TOTAL", 2_000_000)
# Aucune réplique d'assistante ne fait cette longueur : IRIS tronque déjà ses phrases à 1 500
# caractères (speakable(), backend/iris/voice/tts.py). Au-delà, ce n'est plus IRIS qui parle, c'est
# quelqu'un qui se sert du relais comme d'un service de synthèse gratuit. Refusé avant tout compteur.
CARACTERES_MAX_PAR_REQUETE = _plafond("VELA_CARACTERES_PAR_REQUETE", 2_000)

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
            # En POST : un courriel dans une URL finit dans tous les journaux traversés.
            # POST seulement : le repli GET remettait le courriel dans l'URL (donc dans les
            # journaux de tout intermédiaire). Retiré le 6 septembre 2026.
            reponse = client.post(base + "/api/licence", json={"email": courriel})
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
def _mois() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m")


def consommer(identite: str, plan: str) -> tuple[int, int]:
    """Vérifie les deux plafonds du mois, puis compte une requête de plus.

    Deux refus distincts, et il faut qu'ils se distinguent dans le message : dépasser son nombre de
    requêtes n'a rien à voir avec dépasser sa consommation. Quelqu'un à qui on dit « quota atteint »
    alors qu'il en est à sa dixième requête du mois croira à une panne."""
    limite = QUOTAS.get(plan, QUOTAS["gratuit"])
    plafond = PLAFONDS_JETONS.get(plan, PLAFONDS_JETONS["gratuit"])
    with _verrou:
        compteurs = _lire("quotas.json")
        if compteurs.get("mois") != _mois():
            compteurs = {"mois": _mois()}

        jetons = int(compteurs.get(identite + "|jetons", 0))
        if plafond and jetons >= plafond:
            raise HTTPException(429, "Consommation mensuelle atteinte pour le plan {}. Elle repart au début du mois prochain.".format(plan))
        total = int(compteurs.get("tous|jetons", 0))
        if PLAFOND_GLOBAL and total >= PLAFOND_GLOBAL:
            log.error("PLAFOND GLOBAL ATTEINT (%s jetons) : le service refuse tout le monde.", total)
            raise HTTPException(503, "Le service est temporairement indisponible. Réessayez plus tard.")

        utilise = int(compteurs.get(identite, 0)) + 1
        if utilise > limite:
            raise HTTPException(429, "Quota mensuel atteint ({} requêtes pour le plan {}).".format(limite, plan))
        compteurs[identite] = utilise
        _ecrire("quotas.json", compteurs)
    return utilise, limite


def enregistrer_jetons(identite: str, jetons: int) -> None:
    """Ajoute les jetons réellement consommés, une fois la réponse rendue.

    On compte après coup, jamais avant : personne ne sait ce que coûtera une réponse tant qu'elle
    n'est pas écrite. La conséquence assumée est qu'une requête peut dépasser le plafond ; c'est la
    SUIVANTE qui sera refusée. Un dépassement d'une requête vaut mieux qu'un refus à l'aveugle."""
    if jetons <= 0:
        return
    with _verrou:
        compteurs = _lire("quotas.json")
        if compteurs.get("mois") != _mois():
            compteurs = {"mois": _mois()}
        compteurs[identite + "|jetons"] = int(compteurs.get(identite + "|jetons", 0)) + jetons
        compteurs["tous|jetons"] = int(compteurs.get("tous|jetons", 0)) + jetons
        _ecrire("quotas.json", compteurs)


def consommer_voix(identite: str, plan: str, caracteres: int) -> None:
    """Vérifie les deux plafonds de caractères du mois, puis compte le texte à prononcer.

    Différence avec les jetons : ici, le coût est connu AVANT d'appeler ElevenLabs — c'est la
    longueur du texte. On compte donc d'avance plutôt qu'après coup, et le dépassement ne peut
    jamais excéder CARACTERES_MAX_PAR_REQUETE.

    Deux refus, et ils ne doivent pas dire la même chose : « vous avez beaucoup parlé ce mois-ci »
    n'a rien à voir avec « le service entier est à sec ». Les deux disent aussi ce qui reste — la
    voix de Windows — parce qu'une assistante qui se tait a l'air cassée, alors qu'une assistante
    qui change de voix a seulement l'air moins jolie."""
    plafond = PLAFONDS_CARACTERES.get(plan, PLAFONDS_CARACTERES["gratuit"])
    with _verrou:
        compteurs = _lire("quotas.json")
        if compteurs.get("mois") != _mois():
            compteurs = {"mois": _mois()}

        utilise = int(compteurs.get(identite + "|caracteres", 0))
        if plafond and utilise >= plafond:
            raise HTTPException(429, "Voix : consommation mensuelle atteinte pour le plan {} ({} caractères). IRIS continue avec la voix de Windows jusqu'au début du mois prochain.".format(plan, plafond))
        total = int(compteurs.get("tous|caracteres", 0))
        if PLAFOND_CARACTERES_GLOBAL and total >= PLAFOND_CARACTERES_GLOBAL:
            log.error("PLAFOND GLOBAL DE VOIX ATTEINT (%s caracteres) : plus personne n'obtient ElevenLabs.", total)
            raise HTTPException(503, "La voix naturelle est momentanément indisponible pour tout le monde. IRIS continue avec la voix de Windows.")

        compteurs[identite + "|caracteres"] = utilise + caracteres
        compteurs["tous|caracteres"] = total + caracteres
        _ecrire("quotas.json", compteurs)


def jetons_de(charge: dict | None) -> int:
    """Le nombre de jetons annoncé par le service en amont, ou 0 s'il n'en dit rien."""
    try:
        return int((charge or {}).get("usage", {}).get("total_tokens") or 0)
    except (AttributeError, TypeError, ValueError):
        return 0


def jetons_du_flux(ligne: bytes) -> int:
    """Les jetons annoncés dans une ligne de flux SSE. OpenRouter les envoie dans le dernier bloc,
    parce que le client demande stream_options.include_usage."""
    texte = ligne.decode("utf-8", errors="ignore")
    if "usage" not in texte:
        return 0
    total = 0
    for morceau in texte.splitlines():
        morceau = morceau.strip()
        if not morceau.startswith("data:"):
            continue
        corps = morceau[5:].strip()
        if not corps or corps == "[DONE]":
            continue
        try:
            total = max(total, jetons_de(json.loads(corps)))
        except ValueError:
            continue
    return total


def amont_pour(modele: str) -> tuple[str, dict, str]:
    """Ou envoyer cette demande : (adresse, en-tetes, modele effectif).

    Un modele Claude part chez Anthropic si sa cle est configuree (on retire le prefixe
    « anthropic/ » qu'Anthropic n'attend pas) ; sinon, et pour tout le reste, chez OpenRouter."""
    est_claude = modele.startswith("anthropic/claude") or modele.startswith("claude-")
    if est_claude and CLE_ANTHROPIC:
        effectif = modele.split("/", 1)[1] if modele.startswith("anthropic/") else modele
        entetes = {"Authorization": "Bearer " + CLE_ANTHROPIC, "Content-Type": "application/json"}
        return AMONT_ANTHROPIC, entetes, effectif
    entetes = {
        "Authorization": "Bearer " + CLE_AMONT,
        "HTTP-Referer": "https://vela.app/iris",
        "X-Title": "IRIS (VELA)",
        "Content-Type": "application/json",
    }
    return AMONT, entetes, modele


def modele_autorise(demande: str, plan: str) -> str:
    """Le client propose, le relais dispose. Un plan Gratuit n'obtient jamais Claude, quoi qu'il envoie."""
    permis = MODELES_PAR_PLAN.get(plan, GRATUITS)
    return demande if demande in permis else permis[0]


# --------------------------------------------------------------------------- l'application
@asynccontextmanager
async def au_demarrage(_app: FastAPI):
    """Une protection silencieuse n'en est pas une : on dit au démarrage ce qui tient vraiment."""
    if not PLAFOND_GLOBAL:
        log.warning("AUCUN plafond global de jetons (VELA_JETONS_TOTAL=0) : rien n'arretera la depense.")
    else:
        log.info("plafond global : %s jetons par mois, tous abonnes confondus", PLAFOND_GLOBAL)
    log.info("plafonds par abonne : %s", PLAFONDS_JETONS)
    log.info("ces valeurs sont des filets, a ajuster sur la vraie facture OpenRouter")
    log.info("voix ElevenLabs : incluse dans TOUS les forfaits, gratuit compris")
    if not PLAFOND_CARACTERES_GLOBAL:
        log.warning("AUCUN plafond global de voix (VELA_CARACTERES_TOTAL=0) : rien n'arretera la facture ElevenLabs.")
    else:
        log.info("plafond global de voix : %s caracteres par mois, tous abonnes confondus", PLAFOND_CARACTERES_GLOBAL)
    log.info("plafonds de voix par abonne : %s (maximum %s caracteres par requete)",
             PLAFONDS_CARACTERES, CARACTERES_MAX_PAR_REQUETE)
    log.info("ces valeurs sont des filets, a ajuster sur la vraie facture ElevenLabs")
    yield


app = FastAPI(title="Relais VELA", docs_url=None, redoc_url=None, lifespan=au_demarrage)


class Appareil(BaseModel):
    machine: str = ""
    email: str = ""


@app.get("/sante")
def sante():
    compteurs = _lire("quotas.json")
    return {
        "ok": True,
        "amont": bool(CLE_AMONT),
        "voix": bool(CLE_VOIX),
        "plafond_global": PLAFOND_GLOBAL,
        "consomme": int(compteurs.get("tous|jetons", 0)) if compteurs.get("mois") == _mois() else 0,
        # La voix a sa propre monnaie : ElevenLabs facture au caractère, pas au jeton.
        "plafond_caracteres": PLAFOND_CARACTERES_GLOBAL,
        "caracteres": int(compteurs.get("tous|caracteres", 0)) if compteurs.get("mois") == _mois() else 0,
    }


@app.post("/api/appareil")
def enregistrer_appareil(corps: Appareil):
    """Premier contact d'une installation d'IRIS. Aucun mot de passe : le jeton n'ouvre l'accès
    qu'à l'IA, jamais aux données de qui que ce soit."""
    if not CLE_AMONT and not CLE_ANTHROPIC:
        raise HTTPException(503, "Le relais n'a pas de clé IA configurée.")
    etat = abonnement(corps.email)
    return {
        "jeton": emettre_jeton(corps.email, corps.machine),
        "plan": etat["plan"],
        "expires": etat["expires"],
        "modeles": MODELES_PAR_PLAN[etat["plan"]],
    }


@app.post("/api/licence")
async def licence_post(request: Request):
    """Même réponse, courriel dans le corps : une adresse n'a rien à faire dans une URL."""
    try:
        corps = await request.json()
    except Exception:
        corps = {}
    return licence(str((corps or {}).get("email") or ""))


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


# Tous les forfaits ont droit à la voix ElevenLabs, Gratuit compris. Sans ce relais, chaque abonné
# devrait fournir sa propre clé ElevenLabs : il paierait donc une voix qu'il n'entendrait jamais.
# La voix fait partie de ce qu'on offre, au même titre que le modèle — mais contrairement au
# modèle, elle n'est plus ce qui distingue un palier d'un autre. Ce qui la borne désormais, ce
# n'est pas le nom du forfait, c'est PLAFONDS_CARACTERES.
AMONT_VOIX = "https://api.elevenlabs.io/v1"
CLE_VOIX = os.environ.get("VELA_ELEVENLABS_KEY", "").strip()


@app.post("/v1/voix/{voice_id}")
async def voix(voice_id: str, request: Request, authorization: str | None = Header(default=None)):
    """Fabrique la voix d'IRIS pour un abonné, avec la clé de VELA.

    Le texte transite, il n'est pas conservé. Aucun forfait n'est refusé à l'entrée : ce qui décide,
    c'est le nombre de caractères déjà prononcés ce mois-ci. Et un refus ici n'est jamais un
    silence — IRIS repasse à la voix de Windows (voir _handle_failure dans
    backend/iris/voice/elevenlabs.py), c'est pour cela que les messages le disent."""
    if not CLE_VOIX:
        raise HTTPException(503, "Le relais n'a pas de clé de synthèse vocale configurée.")
    identite, plan = _identifier(authorization)
    if not re.fullmatch(r"[A-Za-z0-9]{1,40}", voice_id):
        raise HTTPException(400, "Identifiant de voix invalide.")
    try:
        charge = await request.json()
    except Exception:
        raise HTTPException(400, "Corps de requête illisible.")
    texte = (charge or {}).get("text") or ""
    if not texte.strip():
        raise HTTPException(400, "Rien à prononcer.")
    if len(texte) > CARACTERES_MAX_PAR_REQUETE:
        raise HTTPException(413, "Texte trop long à prononcer d'un seul coup ({} caractères, maximum {}).".format(len(texte), CARACTERES_MAX_PAR_REQUETE))
    consommer(identite + "|voix", plan)
    consommer_voix(identite, plan, len(texte))

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
    if not CLE_AMONT and not CLE_ANTHROPIC:
        raise HTTPException(503, "Le relais n'a pas de clé IA configurée.")
    identite, plan = _identifier(authorization)
    try:
        charge = await request.json()
    except Exception:
        raise HTTPException(400, "Corps de requête illisible.")
    if not isinstance(charge, dict) or not charge.get("messages"):
        raise HTTPException(400, "Requête sans messages.")

    consommer(identite, plan)
    modele = modele_autorise(str(charge.get("model") or ""), plan)
    base, entetes, charge["model"] = amont_pour(modele)
    # En mode « Claude seul » (une seule cle configuree), un forfait gratuit demande un modele
    # OpenRouter dont la cle est absente : sans ce garde, on enverrait « Bearer  » (vide), qu httpx
    # refuse avec une erreur illisible. On repond proprement a la place.
    if entetes["Authorization"].strip() == "Bearer":
        raise HTTPException(503, "Ce modele n est pas disponible sur ce relais (cle du fournisseur absente).")
    log.info("relais : plan=%s modele=%s amont=%s flux=%s", plan, charge["model"],
             "anthropic" if base == AMONT_ANTHROPIC else "openrouter", bool(charge.get("stream")))

    if not charge.get("stream"):
        async with httpx.AsyncClient(timeout=180) as client:
            reponse = await client.post(base + "/chat/completions", json=charge, headers=entetes)
        rendu = reponse.json()
        enregistrer_jetons(identite, jetons_de(rendu))
        return JSONResponse(rendu, status_code=reponse.status_code)

    async def flux():
        async with httpx.AsyncClient(timeout=None) as client:
            async with client.stream("POST", base + "/chat/completions", json=charge, headers=entetes) as amont:
                if amont.status_code >= 400:
                    detail = (await amont.aread()).decode(errors="replace")[:400]
                    log.warning("amont %s : %s", amont.status_code, detail)
                    message = "Le service IA a refusé la demande ({}).".format(amont.status_code)
                    yield ("data: " + json.dumps({"error": {"message": message}}) + "\n\n").encode()
                    return
                jetons = 0
                async for morceau in amont.aiter_bytes():
                    jetons = max(jetons, jetons_du_flux(morceau))
                    yield morceau
                # Une fois le dernier octet parti : ce que la réponse a réellement coûté.
                enregistrer_jetons(identite, jetons)

    return StreamingResponse(flux(), media_type="text/event-stream")
