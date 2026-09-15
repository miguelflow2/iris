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

import asyncio
import base64
import hashlib
import hmac
import json
import logging
import os
import re
import secrets
import smtplib
import time
import uuid
from contextlib import asynccontextmanager
from datetime import date, datetime, timezone
from email.message import EmailMessage
from pathlib import Path
from threading import Lock
from typing import Any

import httpx
from fastapi import FastAPI, Header, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("vela.relais")

def _cles(nom_env: str) -> list[str]:
    """Lit une variable d'environnement qui peut porter PLUSIEURS clés, séparées par virgule,
    point-virgule ou espaces — autant de comptes amont sur lesquels basculer quand l'un refuse
    (401/402/429), exactement comme le pool ElevenLabs le fait déjà côté voix. Doublons retirés,
    ordre conservé. Une seule clé : liste d'un seul élément, donc comportement identique à avant."""
    vues: set[str] = set()
    cles: list[str] = []
    for morceau in re.split(r"[,;\s]+", os.environ.get(nom_env, "") or ""):
        c = morceau.strip()
        if c and c not in vues:
            vues.add(c)
            cles.append(c)
    return cles


AMONT = "https://openrouter.ai/api/v1"
# VELA_OPENROUTER_KEY peut désormais porter PLUSIEURS clés OpenRouter (séparées par virgule) : le
# relais bascule de l'une à l'autre dès qu'une répond 401/402/429. CLE_AMONT reste la première, pour
# tout ce qui ne teste que la PRÉSENCE d'une clé (/sante, gardes d'entrée, tests historiques).
CLES_AMONT = _cles("VELA_OPENROUTER_KEY")
CLE_AMONT = CLES_AMONT[0] if CLES_AMONT else ""
# Point d'acces compatible OpenAI d'Anthropic. Quand cette cle est presente, les modeles Claude
# partent DIRECTEMENT chez Anthropic plutot que par OpenRouter — utile en test (on ne paie que le
# compte Anthropic deja recharge) et souvent moins cher qu'OpenRouter, qui prend une marge.
# Comme OpenRouter, VELA_ANTHROPIC_KEY accepte plusieurs clés séparées par virgule.
AMONT_ANTHROPIC = "https://api.anthropic.com/v1"
CLES_ANTHROPIC = _cles("VELA_ANTHROPIC_KEY")
CLE_ANTHROPIC = CLES_ANTHROPIC[0] if CLES_ANTHROPIC else ""
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

# --------------------------------------------------------------------------- façade des noms
# Le client final ne doit jamais lire le nom d'un fournisseur. Or l'identifiant brut d'un modèle
# LE nomme : « anthropic/… », « openai/… », « google/… » disent tout de suite d'où vient l'IA. À
# l'INTÉRIEUR, on continue de travailler sur ces identifiants bruts — c'est eux qu'attendent
# OpenRouter et Anthropic. Cette table ne sert qu'à la FAÇADE : ce que /v1/models et /api/appareil
# montrent au client, et la retraduction d'un nom neutre s'il nous le renvoie. « rapide » = les
# modèles gratuits, « avance » = les payants intermédiaires, « max » = le sommet.
NOMS_NEUTRES: dict[str, str] = {
    "minimax/minimax-m3:free": "vela-rapide",
    "google/gemma-4-31b-it:free": "vela-rapide-2",
    "nvidia/nemotron-3.5-lightning:free": "vela-rapide-3",
    "anthropic/claude-sonnet-5": "vela-avance",
    "google/gemini-2.5-flash": "vela-avance-2",
    "openai/gpt-5-mini": "vela-avance-3",
    "anthropic/claude-opus-5": "vela-max",
}


def nom_neutre(modele: str) -> str:
    """Le nom neutre à MONTRER pour un identifiant brut. Jamais l'identifiant lui-même : un modèle
    absent de la table reçoit tout de même un nom stable dérivé d'une empreinte — opaque, sans
    marque — pour que rien ne fuite même après un ajout oublié dans MODELES_PAR_PLAN."""
    connu = NOMS_NEUTRES.get(modele)
    if connu:
        return connu
    return "vela-" + hashlib.sha256(modele.encode()).hexdigest()[:8]


# Retraduction : un client qui renvoie un nom neutre (« vela-avance ») doit retrouver le vrai
# modèle. Ne couvre que les noms explicitement exposés ; un nom inconnu laisse modele_autorise
# retomber sur le défaut du forfait.
_DEPUIS_NOM_NEUTRE: dict[str, str] = {v: k for k, v in NOMS_NEUTRES.items()}

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


# --------------------------------------------------------------------------- limitation de débit
# Fenêtres glissantes en mémoire (constat du 2026-09-14 : /api/appareil n'était pas limité). Un redémarrage
# du relais les remet à zéro : c'est un frein contre l'abus, pas une comptabilité.
APPAREIL_PAR_IP = 30
APPAREIL_PAR_COURRIEL = 10
FENETRE_APPAREIL_S = 900.0
_TENTATIVES: dict[str, list[float]] = {}
_TENTATIVES_VERROU = Lock()


def adresse_ip(entetes, client) -> str:
    """L'adresse de l'appelant. Derrière le mandataire de l'hébergeur, on prend la DERNIÈRE entrée de
    X-Forwarded-For (celle qu'ajoute le mandataire le plus proche ; les premières sont forgeables)."""
    transmis = (entetes.get("x-forwarded-for") or "") if entetes is not None else ""
    if transmis.strip():
        return transmis.split(",")[-1].strip()[:64]
    return ((getattr(client, "host", "") if client else "") or "inconnue")[:64]


def limiter(cles: list[str], maximum: int, fenetre_s: float) -> float:
    """Compte une tentative pour chaque clé ; renvoie le délai d'attente en secondes (0 = permis, rien n'est
    compté si l'une des clés est déjà au plafond)."""
    maintenant = time.time()
    with _TENTATIVES_VERROU:
        if len(_TENTATIVES) > 20000:
            for cle in [c for c, t in _TENTATIVES.items() if not t or t[-1] < maintenant - 3600 * 24]:
                _TENTATIVES.pop(cle, None)
        attente = 0.0
        for cle in cles:
            recentes = [t for t in _TENTATIVES.get(cle, []) if t > maintenant - fenetre_s]
            _TENTATIVES[cle] = recentes
            if len(recentes) >= maximum:
                attente = max(attente, recentes[0] + fenetre_s - maintenant)
        if attente > 0:
            return attente
        for cle in cles:
            _TENTATIVES[cle].append(maintenant)
    return 0.0


# --------------------------------------------------------------------------- liaison ordinateur ↔ courriel
# Constat bloquant du 2026-09-14. Le jeton d'appareil s'obtient sans preuve pour n'importe quel courriel :
# il ne peut donc pas, à lui seul, désigner l'ordinateur qui reçoit un verrouillage ou un effacement. Un
# ordinateur est LIÉ à un courriel quand :
# 1. il a publié une clé secrète de 32 octets (générée chez lui) par POST /api/appareil/liaison ;
# 2. le propriétaire du courriel a ouvert le lien envoyé à cette adresse et confirmé (POST /api/appareil/confirmer).
# Ensuite, /appareil/ws exige de lui la preuve d'un défi (HMAC-SHA256 de la clé sur un nonce tiré ici) : un
# ordinateur qui ne la donne pas ne peut ni remplacer l'ordinateur lié, ni recevoir de message « verrou ».
# La clé est gardée ici emballée (XOR avec une clé dérivée de VELA_SECRET et d'un identifiant propre à chaque
# liaison) : le fichier de données seul ne suffit pas à se faire passer pour l'ordinateur.
# Limites dites telles quelles : sans serveur de courriel configuré (VELA_SMTP_HOTE), aucune liaison ne peut être
# confirmée, et le verrouillage à distance reste inutilisable ; tant qu'aucun ordinateur n'est lié à un courriel,
# la télécommande garde l'ancien fonctionnement (le dernier ordinateur connecté remplace le précédent).
FICHIER_LIAISONS = "liaisons-pc.json"
DUREE_CONFIRMATION_S = 24 * 3600.0
RENVOI_CONFIRMATION_S = 600.0
LIAISONS_PAR_IP = 20  # demandes de liaison par heure depuis une adresse
LIAISONS_PAR_CLE = 5  # par (courriel, clé d'ordinateur) et par jour
LIAISONS_PAR_COURRIEL_IP = 5  # par (courriel, adresse) et par jour : un tiers n'épuise pas le quota de la victime
COURRIELS_LIAISON_PAR_JOUR = 20  # anti-pourriel ; au-delà, les attentes restent confirmables par un lien déjà reçu
ATTENTES_PAR_COURRIEL = 20
# Finition B du 2026-09-14 : une rafale de clés depuis quelques adresses évinçait l'attente du propriétaire. Une
# adresse garde au plus ATTENTES_PAR_ADRESSE attentes pour un courriel (deux ordinateurs derrière la même box) ; quand
# la table du courriel est pleine, seule cède l'attente la moins récemment vue d'une adresse qui en garde PLUSIEURS.
# L'attente seule de son adresse (celle du propriétaire, en pratique) ne cède jamais ; si toutes sont seules, la
# nouvelle demande est refusée. Limite dite : un tiers disposant de ATTENTES_PAR_COURRIEL adresses distinctes
# empêche une NOUVELLE attente pendant 24 h, sans jamais retirer celles qui existent.
ATTENTES_PAR_ADRESSE = 2
ECHECS_CONFIRMATION_MAX = 5  # codes erronés recopiés depuis un même lien
CONFIRMATIONS_PAR_IP = 20
FENETRE_PREUVE_S = 300.0
ITERATIONS_MIN, ITERATIONS_MAX = 100_000, 2_000_000
_COURRIEL_VALIDE = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,255}$")
_LIAISONS_VERROU = Lock()
_PREUVES_VUES: dict[str, float] = {}
MESSAGE_PC_NON_LIE = (
    "Un autre ordinateur est lié à ce compte pour le verrouillage à distance. Limite actuelle : un seul ordinateur "
    "par compte peut être lié, et tant qu'il l'est, les autres ordinateurs du compte ne reçoivent ni la "
    "télécommande du téléphone ni la création de partage. Pour lier celui-ci à sa place, activez le verrouillage "
    "à distance dans IRIS et confirmez le courriel reçu avec le code affiché."
)


def _cle_emballage(courriel: str, ident: str) -> bytes:
    return hmac.new(SECRET_JETON, f"liaison-pc|{courriel}|{ident}".encode("utf-8"), hashlib.sha256).digest()


def _xor(a: bytes, b: bytes) -> bytes:
    return bytes(x ^ y for x, y in zip(a, b))


def _lire_liaisons() -> dict:
    donnees = _lire(FICHIER_LIAISONS)
    return donnees if isinstance(donnees, dict) else {}


def smtp_configure() -> bool:
    return bool(os.environ.get("VELA_SMTP_HOTE", "").strip())


def envoyer_courriel(destinataire: str, sujet: str, corps: str) -> bool:
    """Envoie un courriel par SMTP (variables VELA_SMTP_*). Bloquant : à appeler dans un fil. Ne lève jamais ;
    le destinataire et le contenu ne sont pas journalisés."""
    hote = os.environ.get("VELA_SMTP_HOTE", "").strip()
    if not hote:
        return False
    try:
        port = int(os.environ.get("VELA_SMTP_PORT", "587") or 587)
    except ValueError:
        port = 587
    message = EmailMessage()
    message["From"] = os.environ.get("VELA_COURRIEL_EXPEDITEUR", "").strip() or "VELA <no-reply@velaglass.ca>"
    message["To"] = destinataire
    message["Subject"] = sujet
    message.set_content(corps)
    try:
        serveur = smtplib.SMTP_SSL(hote, port, timeout=20) if port == 465 else smtplib.SMTP(hote, port, timeout=20)
        with serveur:
            if port != 465 and os.environ.get("VELA_SMTP_TLS", "1").strip().lower() not in ("0", "non", "false"):
                serveur.starttls()
            utilisateur = os.environ.get("VELA_SMTP_UTILISATEUR", "").strip()
            if utilisateur:
                serveur.login(utilisateur, os.environ.get("VELA_SMTP_MOTDEPASSE", ""))
            serveur.send_message(message)
        return True
    except Exception as exc:
        log.warning("liaison : courriel de confirmation non envoyé (%s)", type(exc).__name__)
        return False


def liaison_confirmee(courriel: str) -> dict | None:
    fiche = _lire_liaisons().get(normaliser(courriel))
    if isinstance(fiche, dict) and fiche.get("confirme_le") and fiche.get("cle"):
        return fiche
    return None


def _cle_de(courriel: str, fiche: dict) -> bytes | None:
    try:
        emballee = _debase64(str(fiche["cle"]))
        return _xor(emballee, _cle_emballage(courriel, str(fiche["id"])))
    except Exception:
        return None


def verifier_preuve_pc(courriel: str, message: str, preuve: str) -> bool:
    """La preuve (HMAC-SHA256, base64 URL) a-t-elle été faite avec la clé de l'ordinateur LIÉ à ce courriel ?"""
    courriel = normaliser(courriel)
    fiche = liaison_confirmee(courriel)
    cle = _cle_de(courriel, fiche) if fiche else None
    if not cle or not isinstance(preuve, str) or len(preuve) > 128:
        return False
    attendue = _b64(hmac.new(cle, message.encode("utf-8"), hashlib.sha256).digest())
    return hmac.compare_digest(attendue, preuve)


def verifier_preuve_horodatee(courriel: str, contexte: str, horodatage: Any, preuve: str) -> bool:
    """Preuve sans aller-retour (création d'un partage) : HMAC de « contexte|v1|courriel|horodatage », horodatage
    à moins de FENETRE_PREUVE_S de l'heure du relais, et chaque preuve n'est acceptée qu'une fois."""
    try:
        instant = int(horodatage)
    except (TypeError, ValueError):
        return False
    maintenant = time.time()
    if abs(maintenant - instant) > FENETRE_PREUVE_S:
        return False
    courriel = normaliser(courriel)
    if not verifier_preuve_pc(courriel, f"{contexte}|v1|{courriel}|{instant}", preuve):
        return False
    with _LIAISONS_VERROU:
        for vue in [p for p, t in _PREUVES_VUES.items() if t < maintenant - 2 * FENETRE_PREUVE_S]:
            _PREUVES_VUES.pop(vue, None)
        if preuve in _PREUVES_VUES:
            return False
        _PREUVES_VUES[preuve] = maintenant
    return True


def publier_infos_verrou(courriel: str, infos: Any) -> None:
    """Sel et nombre d'itérations du code de secours, publiés par l'ordinateur LIÉ (jamais le code) : la page
    /verrou en a besoin pour calculer sa preuve. Ignoré si mal formé."""
    courriel = normaliser(courriel)
    sel, iterations = None, None
    if isinstance(infos, dict):
        try:
            brut = _debase64(str(infos.get("sel") or ""))
            valeur = int(infos.get("iterations") or 0)
            if 16 <= len(brut) <= 64 and ITERATIONS_MIN <= valeur <= ITERATIONS_MAX:
                sel, iterations = _b64(brut), valeur
        except Exception:
            sel, iterations = None, None
    with _LIAISONS_VERROU:
        liaisons = _lire_liaisons()
        fiche = liaisons.get(courriel)
        if not isinstance(fiche, dict) or not fiche.get("confirme_le"):
            return
        if fiche.get("sel") == sel and fiche.get("iterations") == iterations:
            return
        fiche["sel"], fiche["iterations"] = sel, iterations
        _ecrire(FICHIER_LIAISONS, liaisons)


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


# --------------------------------------------------------------------------- rotation des clés amont
# Même principe que le pool de voix ElevenLabs : plusieurs clés OpenRouter (ou Anthropic) possibles,
# et l'on bascule dès qu'une répond « refusée » ou « quota atteint ». Une clé écartée est réessayée
# après un court délai — une limite de débit se lève vite, un quota se recharge, et ré-essayer une
# clé rétablie évite qu'un incident passager la mette définitivement au rebut.
CODES_BASCULE_AMONT = (401, 402, 429)  # 401 clé refusée · 402 crédit épuisé · 429 débit dépassé
_AMONT_COOLDOWN_S = float(_plafond("VELA_AMONT_COOLDOWN_S", 300))
_amont_cooldown: dict[str, float] = {}
_anthropic_cooldown: dict[str, float] = {}

# Un flux amont sans borne de LECTURE peut pendre indéfiniment si le fournisseur cesse d'émettre
# sans fermer la connexion (avant, timeout=None). On borne le temps SANS nouvel octet ; la durée
# TOTALE d'un flux reste libre, car une longue réponse est légitime.
TIMEOUT_LECTURE_FLUX = float(_plafond("VELA_TIMEOUT_FLUX_S", 120))


def _timeout_flux() -> httpx.Timeout:
    return httpx.Timeout(connect=15.0, read=TIMEOUT_LECTURE_FLUX, write=30.0, pool=15.0)


def _pool_pour(base: str) -> tuple[list[str], dict[str, float]]:
    """Le pool de clés et son registre de pénalités, selon l'amont choisi. Si le pool est vide mais
    qu'une clé scalaire existe (cas des tests qui fixent CLE_AMONT/CLE_ANTHROPIC à la main), on
    retombe sur elle : comportement d'avant, une seule clé."""
    if base == AMONT_ANTHROPIC:
        return (CLES_ANTHROPIC or ([CLE_ANTHROPIC] if CLE_ANTHROPIC else [])), _anthropic_cooldown
    return (CLES_AMONT or ([CLE_AMONT] if CLE_AMONT else [])), _amont_cooldown


def _cles_a_essayer(cles: list[str], cooldown: dict[str, float]) -> list[str]:
    """Les clés à tenter, dans l'ordre : d'abord celles hors pénalité (ordre du pool), puis, en
    dernier recours, les pénalisées (la moins récemment pénalisée d'abord). Une seule clé : elle."""
    maintenant = time.time()
    libres = [c for c in cles if cooldown.get(c, 0.0) <= maintenant]
    penalisees = sorted((c for c in cles if cooldown.get(c, 0.0) > maintenant),
                        key=lambda c: cooldown[c])
    return libres + penalisees


def _amont_marquer_epuisee(cle: str, cooldown: dict[str, float]) -> None:
    cooldown[cle] = time.time() + _AMONT_COOLDOWN_S


def _json_amont(reponse) -> dict:
    """Le corps JSON d'une réponse amont, ou une erreur PROPRE si l'amont a renvoyé autre chose que
    du JSON — page HTML d'un 502, passerelle en maintenance, corps vide. Sans cette protection,
    `reponse.json()` lève, la requête finit en 500 illisible côté IRIS, et les jetons ne sont pas
    comptés. Ne lève jamais."""
    code = getattr(reponse, "status_code", "?")
    try:
        donnees = reponse.json()
    except Exception:
        extrait = (getattr(reponse, "text", "") or "")[:200]
        log.warning("amont %s : réponse non-JSON (%r)", code, extrait)
        return {"error": {"message": "Réponse inattendue du service IA ({}).".format(code)}}
    if not isinstance(donnees, dict):
        log.warning("amont %s : JSON inattendu (type %s)", code, type(donnees).__name__)
        return {"error": {"message": "Réponse inattendue du service IA ({}).".format(code)}}
    return donnees


def _sse_erreur(message: str) -> bytes:
    """Une trame SSE d'erreur, au format que le client OpenAI-compatible d'IRIS sait lire."""
    return ("data: " + json.dumps({"error": {"message": message}}) + "\n\n").encode()


def _test_disque() -> tuple[bool, str]:
    """Écrit puis relit un octet dans le dossier de données. C'est ce qui distingue un service vivant
    d'un service qui répond encore mais ne peut plus rien écrire (disque plein, volume démonté, droits
    cassés) — auquel cas chaque compteur de quota échoue en silence. Pas de réseau, quasi gratuit."""
    sonde = DONNEES / ".sante"
    try:
        DONNEES.mkdir(parents=True, exist_ok=True)
        sonde.write_bytes(b"1")
        if sonde.read_bytes() != b"1":
            return False, "relecture de la sonde disque incoherente"
        sonde.unlink(missing_ok=True)
        return True, ""
    except Exception as exc:
        return False, "disque non accessible en ecriture ({}: {})".format(type(exc).__name__, exc)


def modele_autorise(demande: str, plan: str) -> str:
    """Le client propose, le relais dispose. Un plan Gratuit n'obtient jamais Claude, quoi qu'il envoie.

    La demande peut être un identifiant brut OU un nom neutre exposé par la façade (« vela-avance ») :
    on retraduit d'abord le nom neutre vers le vrai modèle, puis on vérifie le droit du forfait."""
    reel = _DEPUIS_NOM_NEUTRE.get(demande, demande)
    permis = MODELES_PAR_PLAN.get(plan, GRATUITS)
    return reel if reel in permis else permis[0]


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

# L'app web du téléphone (autre origine) appelle /api/appareil depuis un navigateur : sans CORS, le
# navigateur bloque. Les endpoints restent protégés par le jeton (et l'appairage pour la
# télécommande) ; ouvrir CORS ne relâche donc aucun secret. Pas d'identifiants de session ici.
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


class Appareil(BaseModel):
    machine: str = ""
    email: str = ""


@app.get("/sante")
def sante():
    """L'état du service, vraiment testé. Avant, ce point renvoyait « ok: true » en dur : un disque
    plein ou une clé absente passaient pour « tout va bien » pendant que chaque appel IA échouait.
    Désormais « ok » n'est vrai que si une clé IA est configurée ET que le dossier de données est
    accessible en écriture. On ne fait AUCUN appel réseau en amont (trop cher à chaque sonde) : on
    vérifie la seule PRÉSENCE d'une clé. Les champs historiques (amont, voix, plafonds…) restent."""
    compteurs = _lire("quotas.json")
    cle_presente = bool(CLE_AMONT or CLE_ANTHROPIC)
    disque_ok, detail_disque = _test_disque()
    ok = cle_presente and disque_ok
    reponse = {
        "ok": ok,
        "amont": bool(CLE_AMONT),
        "voix": bool(CLES_VOIX),
        "plafond_global": PLAFOND_GLOBAL,
        "consomme": int(compteurs.get("tous|jetons", 0)) if compteurs.get("mois") == _mois() else 0,
        # La voix a sa propre monnaie : ElevenLabs facture au caractère, pas au jeton.
        "plafond_caracteres": PLAFOND_CARACTERES_GLOBAL,
        "caracteres": int(compteurs.get("tous|caracteres", 0)) if compteurs.get("mois") == _mois() else 0,
        # Contre-vérification du 2026-09-14 : sans serveur de courriel, aucun ordinateur ne peut être lié, donc
        # le verrouillage à distance n'atteint personne. Dit ici, et lu par la page /verrou pour l'écrire.
        "liaison_possible": smtp_configure(),
    }
    if not ok:
        reponse["detail"] = ("aucune cle IA configuree (VELA_OPENROUTER_KEY ou VELA_ANTHROPIC_KEY)"
                             if not cle_presente else detail_disque)
    return reponse


@app.post("/api/appareil")
def enregistrer_appareil(corps: Appareil, request: Request):
    """Premier contact d'une installation d'IRIS. Aucun mot de passe : le jeton n'ouvre l'accès
    qu'à l'IA, jamais aux données de qui que ce soit. Il ne prouve PAS que le courriel appartient à
    l'appelant : piloter ou verrouiller un ordinateur exige en plus la liaison confirmée par courriel
    (voir « liaison ordinateur ↔ courriel » plus bas). Limité en débit (constat du 2026-09-14)."""
    delai = limiter([f"appareil-ip:{adresse_ip(request.headers, request.client)}"], APPAREIL_PAR_IP, FENETRE_APPAREIL_S) \
        or limiter([f"appareil-courriel:{normaliser(corps.email)}"], APPAREIL_PAR_COURRIEL, FENETRE_APPAREIL_S)
    if delai:
        raise HTTPException(429, "Trop de demandes d'accès en peu de temps. Réessayez dans quelques minutes.",
                            headers={"Retry-After": str(int(delai) + 1)})
    if not CLE_AMONT and not CLE_ANTHROPIC:
        raise HTTPException(503, "Le relais n'a pas de clé IA configurée.")
    etat = abonnement(corps.email)
    return {
        "jeton": emettre_jeton(corps.email, corps.machine),
        "plan": etat["plan"],
        "expires": etat["expires"],
        # Noms NEUTRES : même une réponse que le client n'affiche pas ne doit pas nommer de fournisseur.
        "modeles": [nom_neutre(m) for m in MODELES_PAR_PLAN[etat["plan"]]],
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


def _cles_voix() -> list[str]:
    """VELA_ELEVENLABS_KEY peut porter PLUSIEURS clés (séparées par virgule/point-virgule/espaces) :
    autant de comptes ElevenLabs sur lesquels étaler la parole, souvent gratuits (10 000 caractères
    par mois chacun). Une seule clé : comportement d'avant."""
    return _cles("VELA_ELEVENLABS_KEY")


CLES_VOIX = _cles_voix()
CLE_VOIX = CLES_VOIX[0] if CLES_VOIX else ""  # compat : présence = au moins une clé configurée
CODES_BASCULE_VOIX = (401, 402, 429)  # quota atteint ou clé refusée : basculer sur une autre
_VOIX_COOLDOWN_S = 3600.0  # une clé qui a refusé est écartée une heure, puis réessayée
_voix_cooldown: dict[str, float] = {}
_voix_i = 0


def _cle_voix_courante() -> str:
    """À partir de l'index courant, la première clé hors pénalité (sinon la moins fraîchement pénalisée)."""
    maintenant = time.time()
    n = len(CLES_VOIX)
    if n == 0:
        return ""
    for pas in range(n):
        c = CLES_VOIX[(_voix_i + pas) % n]
        if _voix_cooldown.get(c, 0.0) <= maintenant:
            return c
    return min(CLES_VOIX, key=lambda c: _voix_cooldown.get(c, 0.0))


def _voix_marquer_epuisee(cle: str) -> None:
    global _voix_i
    if cle in CLES_VOIX:
        _voix_cooldown[cle] = time.time() + _VOIX_COOLDOWN_S
        _voix_i = (CLES_VOIX.index(cle) + 1) % len(CLES_VOIX)


def _voix_apres_usage() -> None:
    global _voix_i
    if CLES_VOIX:
        _voix_i = (_voix_i + 1) % len(CLES_VOIX)


@app.post("/v1/voix/{voice_id}")
async def voix(voice_id: str, request: Request, authorization: str | None = Header(default=None)):
    """Fabrique la voix d'IRIS pour un abonné, avec la clé de VELA.

    Le texte transite, il n'est pas conservé. Aucun forfait n'est refusé à l'entrée : ce qui décide,
    c'est le nombre de caractères déjà prononcés ce mois-ci. Et un refus ici n'est jamais un
    silence — IRIS repasse à la voix de Windows (voir _handle_failure dans
    backend/iris/voice/elevenlabs.py), c'est pour cela que les messages le disent."""
    if not CLES_VOIX:
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

    async def flux():
        # Rotation : on essaie les clés du pool tour à tour ; une clé « quota atteint » (401/402/429)
        # est mise en pénalité et on bascule. Toutes épuisées : silence, et IRIS repasse à Windows.
        # Timeout borné en lecture (avant : None, donc infini) : un ElevenLabs muet ne fige plus le flux.
        async with httpx.AsyncClient(timeout=_timeout_flux()) as client:
            for _ in range(max(1, len(CLES_VOIX))):
                cle = _cle_voix_courante()
                if not cle:
                    log.warning("voix : aucune clé disponible")
                    return
                entetes = {"xi-api-key": cle, "Content-Type": "application/json"}
                async with client.stream("POST", f"{AMONT_VOIX}/text-to-speech/{voice_id}/stream?{parametres}",
                                         json=charge, headers=entetes) as amont:
                    if amont.status_code in CODES_BASCULE_VOIX and len(CLES_VOIX) > 1:
                        log.warning("voix amont %s (clé …%s) : bascule sur une autre clé", amont.status_code, cle[-4:])
                        _voix_marquer_epuisee(cle)
                        continue
                    if amont.status_code >= 400:
                        log.warning("voix amont %s", amont.status_code)
                        return
                    _voix_apres_usage()
                    async for morceau in amont.aiter_bytes():
                        yield morceau
                    return

    return StreamingResponse(flux(), media_type="audio/basic")


@app.get("/v1/models")
def modeles(authorization: str | None = Header(default=None)):
    _, plan = _identifier(authorization)
    # Noms NEUTRES uniquement : le client ne doit jamais lire le nom d'un fournisseur dans sa liste.
    return {"object": "list", "data": [{"id": nom_neutre(m), "object": "model", "owned_by": "vela"} for m in MODELES_PAR_PLAN[plan]]}


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

    pool, cooldown = _pool_pour(base)

    if not charge.get("stream"):
        a_essayer = _cles_a_essayer(pool, cooldown) or [None]
        reponse = None
        async with httpx.AsyncClient(timeout=180) as client:
            for i, cle in enumerate(a_essayer):
                if cle is not None:
                    entetes["Authorization"] = "Bearer " + cle
                try:
                    reponse = await client.post(base + "/chat/completions", json=charge, headers=entetes)
                except httpx.HTTPError as exc:
                    # Réseau : connexion refusée, DNS, délai dépassé. Ni 500 opaque, ni jetons perdus.
                    log.warning("amont injoignable (%s)", exc)
                    if cle is not None and i < len(a_essayer) - 1:
                        _amont_marquer_epuisee(cle, cooldown)
                        continue
                    raise HTTPException(502, "Le service IA est injoignable. Réessayez dans un instant.")
                if cle is not None and reponse.status_code in CODES_BASCULE_AMONT:
                    _amont_marquer_epuisee(cle, cooldown)
                    if i < len(a_essayer) - 1:
                        log.warning("amont %s (clé …%s) : bascule sur une autre clé", reponse.status_code, cle[-4:])
                        continue
                break
        # `reponse.json()` protégé : une réponse non-JSON (HTML d'un 502, maintenance) ne doit ni
        # planter en 500, ni faire sauter la comptabilisation. jetons_de() lit 0 d'une erreur.
        rendu = _json_amont(reponse)
        enregistrer_jetons(identite, jetons_de(rendu))
        return JSONResponse(rendu, status_code=reponse.status_code)

    async def flux():
        a_essayer = _cles_a_essayer(pool, cooldown) or [None]
        async with httpx.AsyncClient(timeout=_timeout_flux()) as client:
            for i, cle in enumerate(a_essayer):
                if cle is not None:
                    entetes["Authorization"] = "Bearer " + cle
                try:
                    async with client.stream("POST", base + "/chat/completions", json=charge, headers=entetes) as amont:
                        # Le code est connu avant le moindre octet : c'est le seul moment où basculer.
                        if amont.status_code >= 400:
                            if cle is not None and amont.status_code in CODES_BASCULE_AMONT:
                                _amont_marquer_epuisee(cle, cooldown)
                                if i < len(a_essayer) - 1:
                                    log.warning("amont %s (clé …%s) : bascule sur une autre clé", amont.status_code, cle[-4:])
                                    continue
                            detail = (await amont.aread()).decode(errors="replace")[:400]
                            log.warning("amont %s : %s", amont.status_code, detail)
                            yield _sse_erreur("Le service IA a refusé la demande ({}).".format(amont.status_code))
                            return
                        # Engagé dans le flux : des octets partent, on ne bascule plus.
                        jetons = 0
                        try:
                            async for morceau in amont.aiter_bytes():
                                jetons = max(jetons, jetons_du_flux(morceau))
                                yield morceau
                        except httpx.HTTPError as exc:
                            # Coupure/délai en cours de flux : on ne réémet pas la demande (le client
                            # a déjà reçu des octets), on signale proprement et on compte ce qui a été lu.
                            log.warning("amont : flux interrompu (%s)", exc)
                            yield _sse_erreur("Le flux du service IA a été interrompu.")
                        # Une fois le dernier octet parti : ce que la réponse a réellement coûté.
                        enregistrer_jetons(identite, jetons)
                        return
                except httpx.HTTPError as exc:
                    # Échec AVANT le moindre octet (connexion, lecture d'en-têtes) : bascule possible.
                    log.warning("amont : connexion au flux impossible (%s)", exc)
                    if cle is not None and i < len(a_essayer) - 1:
                        _amont_marquer_epuisee(cle, cooldown)
                        continue
                    yield _sse_erreur("Le service IA est injoignable.")
                    return

    return StreamingResponse(flux(), media_type="text/event-stream")


# --------------------------------------------------------------------------- liaison : routes
ENTETES_PAGES_SENSIBLES = {
    "Cache-Control": "no-store",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Content-Security-Policy": ("default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; "
                                "connect-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'"),
    "X-Content-Type-Options": "nosniff",
    "X-Robots-Tag": "noindex",
}


def _base_publique(request: Request) -> str:
    """Adresse du relais pour le lien de confirmation envoyé par courriel. VELA_URL_PUBLIQUE prime (à définir en
    production). Sans elle, on ne suit PAS X-Forwarded-Host : ce lien part chez le propriétaire du courriel, et
    c'est l'appelant qui choisit cet en-tête — il y mettrait son propre site pour recevoir le jeton de
    confirmation dès que le lien est ouvert. Seul l'en-tête Host (celui par lequel l'hébergeur a routé la
    requête jusqu'ici) sert, en HTTPS sauf sur un poste local."""
    imposee = os.environ.get("VELA_URL_PUBLIQUE", "").strip().rstrip("/")
    if imposee:
        return imposee
    hote = (request.headers.get("host") or "").split(",")[0].strip()
    if not re.match(r"^[A-Za-z0-9.\-]+(:\d{1,5})?$", hote):
        hote = request.url.netloc
    local = hote.split(":")[0].lower() in ("localhost", "127.0.0.1", "testserver")
    return f"{'http' if local else 'https'}://{hote}"


async def _corps_json(request: Request) -> dict:
    # Lu à la main : une erreur de validation automatique renverrait les valeurs reçues (clé comprise).
    try:
        corps = await request.json()
    except Exception:
        corps = None
    return corps if isinstance(corps, dict) else {}


@app.post("/api/appareil/liaison")
async def demander_liaison(request: Request):
    """Un ordinateur demande à être lié au courriel de son jeton, avec sa clé. Rien n'est lié avant la
    confirmation par courriel. Réponses : 200 confirmee · 202 en_attente · 503 confirmation_indisponible.
    La réponse porte `empreinte` : le code de 6 caractères qu'IRIS affiche et que la page de confirmation
    demande de recopier.

    Contre-vérification du 2026-09-14 : une seule attente par courriel, écrasée à chaque demande, et un
    compteur de 5 demandes par jour partagé par tous. Un tiers muni d'un jeton pour le courriel de la victime
    épuisait ce compteur (le vrai PC recevait 429 pendant 24 h) et le seul lien encore valable liait SA clé.
    Désormais : une attente PAR CLÉ (indexée par empreinte), des limites par (courriel, clé), par (courriel,
    adresse IP) et par adresse IP, et la confirmation exige de recopier l'empreinte affichée dans IRIS — un lien
    ouvert ne lie jamais la clé d'un autre ordinateur, et n'importe quel lien encore valable lie la sienne."""
    corps = await _corps_json(request)
    info = lire_jeton(str(corps.get("jeton") or ""))
    courriel = normaliser((info or {}).get("courriel") or "")
    if not info or not _COURRIEL_VALIDE.match(courriel):
        return JSONResponse({"etat": "refuse", "message": "Jeton d'appareil invalide, ou aucun courriel de compte."},
                            status_code=401)
    try:
        cle = _debase64(str(corps.get("cle") or ""))
    except Exception:
        cle = b""
    if len(cle) != 32:
        return JSONResponse({"etat": "invalide", "message": "Clé d'ordinateur mal formée."}, status_code=422)
    machine = " ".join(str(corps.get("machine") or "").split())[:64] or "ordinateur"
    empreinte = empreinte_cle(cle)
    maintenant = time.time()
    fiche = _lire_liaisons().get(courriel)
    fiche = fiche if isinstance(fiche, dict) else {}
    if fiche.get("confirme_le"):
        actuelle = _cle_de(courriel, fiche)
        if actuelle and hmac.compare_digest(actuelle, cle):
            return {"etat": "confirmee", "empreinte": empreinte,
                    "message": "Cet ordinateur est lié à votre compte pour le verrouillage à distance."}
    message_attente = (
        "Un courriel de confirmation a été envoyé à l'adresse de votre compte VELA. Ouvrez son lien (valable "
        f"24 heures) et recopiez le code {empreinte} affiché ici pour lier cet ordinateur au verrouillage à distance."
    )
    ip = adresse_ip(request.headers, request.client)
    deja = _attentes_valides(fiche, maintenant).get(empreinte)
    if deja and _cle_attente(courriel, deja) == cle:
        # Finition B du 2026-09-14 : IRIS redemande la liaison à chaque reconnexion (réveil du portable, redémarrage
        # du relais). Chaque relance après 10 minutes renvoyait un courriel, REMPLAÇAIT l'attente (le lien du courriel
        # précédent donnait 410) et comptait dans LIAISONS_PAR_CLE : à la 6e, IRIS affichait « Trop de demandes »
        # alors qu'un lien valable attendait dans la boîte. Tant que l'attente de CETTE clé est valable, aucune relance
        # n'envoie de courriel, ne remplace le lien, ni ne compte dans les limites.
        _toucher_attente(courriel, empreinte, maintenant, _empreinte_ip(courriel, ip))
        premiere = maintenant - float(deja.get("envoye_a") or 0) < RENVOI_CONFIRMATION_S and deja.get("jeton")
        return JSONResponse({"etat": "en_attente", "empreinte": empreinte,
                             "message": message_attente if premiere else _message_deja_envoye(deja, empreinte, maintenant)},
                            status_code=202)
    delai = limiter([f"liaison-ip:{ip}"], LIAISONS_PAR_IP, 3600.0) \
        or limiter([f"liaison-cle:{courriel}|{empreinte}"], LIAISONS_PAR_CLE, 24 * 3600.0) \
        or limiter([f"liaison-courriel-ip:{courriel}|{ip}"], LIAISONS_PAR_COURRIEL_IP, 24 * 3600.0)
    if delai:
        return JSONResponse({"etat": "trop_de_demandes", "empreinte": empreinte,
                             "message": "Trop de demandes de liaison depuis cet ordinateur. Réessayez plus tard."},
                            status_code=429, headers={"Retry-After": str(int(delai) + 1)})
    if not smtp_configure():
        return JSONResponse({"etat": "confirmation_indisponible",
                             "message": ("Le relais VELA ne peut pas envoyer de courriel de confirmation pour le moment : cet "
                                         "ordinateur ne peut pas encore être lié au verrouillage à distance.")},
                            status_code=503)
    trop_plein = _place_pour_attente(fiche, _empreinte_ip(courriel, ip), empreinte, maintenant)
    if trop_plein:
        return JSONResponse({"etat": "trop_de_demandes", "empreinte": empreinte, "message": trop_plein},
                            status_code=429, headers={"Retry-After": "3600"})
    ident = secrets.token_hex(8)
    jeton_confirmation = secrets.token_urlsafe(32)
    nouvelle = {"id": ident, "cle": _b64(_xor(cle, _cle_emballage(courriel, ident))), "machine": machine,
                "jeton": hashlib.sha256(jeton_confirmation.encode()).hexdigest(), "cree": maintenant,
                "envoye_a": maintenant, "vu_a": maintenant, "echecs": 0, "ip": _empreinte_ip(courriel, ip)}
    # Anti-pourriel : au plus COURRIELS_LIAISON_PAR_JOUR courriels par adresse. Au-delà, l'attente est quand même
    # gardée : la page de n'importe quel lien encore valable (reçu dans les 24 h) accepte le code de CET ordinateur.
    if not limiter([f"liaison-courriel:{courriel}"], COURRIELS_LIAISON_PAR_JOUR, 24 * 3600.0):
        lien = f"{_base_publique(request)}/appareil/confirmer/{jeton_confirmation}"
        remplace = (" Si vous confirmez, il remplacera l'ordinateur lié jusqu'ici à votre compte." if fiche.get("confirme_le") else "")
        corps_courriel = (
            "Bonjour,\n\n"
            f"Un ordinateur nommé « {machine} » demande à être lié à votre compte VELA pour recevoir les commandes de "
            f"verrouillage et d'effacement à distance d'IRIS.{remplace}\n\n"
            "Si c'est bien vous, ouvrez ce lien dans les 24 heures. La page vous demandera de recopier le code de "
            "6 caractères affiché dans IRIS, sur votre ordinateur (Profil › Verrouillage à distance) :\n"
            f"{lien}\n\n"
            "Le nom de l'ordinateur ci-dessus vient de la demande elle-même : ne vous y fiez pas. Seul le code "
            "affiché dans IRIS désigne votre ordinateur. Si IRIS ne vous en montre aucun, ne confirmez rien.\n\n"
            "Si vous n'avez rien demandé, ignorez ce courriel : rien ne sera lié.\n\nVELA"
        )
        envoye = await asyncio.to_thread(envoyer_courriel, courriel, "VELA : confirmer l'ordinateur lié à votre compte",
                                         corps_courriel)
        if not envoye:
            return JSONResponse({"etat": "courriel_non_envoye",
                                 "message": "Le courriel de confirmation n'a pas pu partir. Réessayez dans quelques minutes."},
                                status_code=502)
    else:
        nouvelle["jeton"] = ""  # aucun lien propre : on confirme par un lien déjà reçu
        message_attente = (
            "Plusieurs courriels de confirmation ont déjà été envoyés aujourd'hui à l'adresse de votre compte VELA. "
            f"Ouvrez le plus récent (valable 24 heures) et recopiez le code {empreinte} affiché ici."
        )
    with _LIAISONS_VERROU:
        liaisons = _lire_liaisons()
        actuelle = liaisons.get(courriel) if isinstance(liaisons.get(courriel), dict) else {}
        en_cours = _attentes_valides(actuelle, maintenant)
        precedente = en_cours.get(empreinte)
        if precedente and not nouvelle["jeton"]:
            nouvelle["jeton"] = precedente.get("jeton") or ""
        # Relu sous le verrou : une demande concurrente a pu remplir la table entre-temps. On n'évince jamais
        # l'attente seule de son adresse (voir ATTENTES_PAR_ADRESSE).
        refus = _place_pour_attente(actuelle, nouvelle["ip"], empreinte, maintenant, evincer=en_cours)
        if refus:
            return JSONResponse({"etat": "trop_de_demandes", "empreinte": empreinte, "message": refus},
                                status_code=429, headers={"Retry-After": "3600"})
        en_cours[empreinte] = nouvelle
        actuelle.pop("attente", None)
        actuelle["attentes"] = en_cours
        liaisons[courriel] = actuelle
        _ecrire(FICHIER_LIAISONS, liaisons)
    return JSONResponse({"etat": "en_attente", "empreinte": empreinte, "message": message_attente}, status_code=202)


def empreinte_cle(cle: bytes) -> str:
    """Code court de la clé d'un ordinateur (6 caractères base32 de SHA-256), affiché par IRIS et recopié sur
    la page de confirmation. Même calcul dans backend/iris/telecommande.py (empreinte_cle)."""
    return base64.b32encode(hashlib.sha256(cle).digest()).decode("ascii")[:6]


def _normaliser_empreinte(texte: Any) -> str:
    """Base32 : ni 0, ni 1, ni 8 ; une saisie « O/0 », « I/1 » ou « B/8 » confondue est ramenée à la bonne lettre."""
    brut = str(texte or "").upper().replace("0", "O").replace("1", "I").replace("8", "B")
    return re.sub(r"[^A-Z2-7]", "", brut)[:6]


def _attentes_valides(fiche: dict, maintenant: float) -> dict:
    """Les attentes de confirmation d'un courriel, par empreinte, sans les expirées. Reprend l'ancien format
    (une seule « attente »)."""
    brutes = dict(fiche.get("attentes") or {}) if isinstance(fiche.get("attentes"), dict) else {}
    ancienne = fiche.get("attente")
    if isinstance(ancienne, dict) and ancienne.get("id"):
        brutes.setdefault("ancienne-" + str(ancienne["id"]), ancienne)
    return {e: a for e, a in brutes.items()
            if isinstance(a, dict) and maintenant - float(a.get("cree") or 0) <= DUREE_CONFIRMATION_S}


def _cle_attente(courriel: str, attente: dict) -> bytes | None:
    try:
        return _xor(_debase64(str(attente.get("cle"))), _cle_emballage(courriel, str(attente.get("id"))))
    except Exception:
        return None


def _toucher_attente(courriel: str, empreinte: str, maintenant: float, ip: str | None = None) -> None:
    with _LIAISONS_VERROU:
        liaisons = _lire_liaisons()
        fiche = liaisons.get(courriel)
        attentes = fiche.get("attentes") if isinstance(fiche, dict) else None
        attente = attentes.get(empreinte) if isinstance(attentes, dict) else None
        if isinstance(attente, dict):
            attente["vu_a"] = maintenant
            if ip:
                attente["ip"] = ip  # un portable change d'adresse : l'attente suit son ordinateur
            _ecrire(FICHIER_LIAISONS, liaisons)


MESSAGE_TROP_D_ATTENTES = (
    "Trop d'ordinateurs attendent déjà une confirmation pour ce compte VELA. Les demandes non confirmées expirent "
    "24 heures après leur envoi ; si un courriel de confirmation vous est déjà parvenu, ouvrez-le et recopiez le "
    "code affiché ici.")
MESSAGE_TROP_D_ATTENTES_ADRESSE = (
    "Trop d'ordinateurs attendent déjà une confirmation depuis cette connexion Internet pour ce compte VELA. Les "
    "demandes non confirmées expirent 24 heures après leur envoi.")


def _empreinte_ip(courriel: str, ip: str) -> str:
    """L'adresse IP n'est pas écrite en clair dans le fichier des liaisons : seulement une empreinte liée au courriel."""
    return hmac.new(SECRET_JETON, f"liaison-ip|{courriel}|{ip}".encode("utf-8"), hashlib.sha256).hexdigest()[:24]


def _place_pour_attente(fiche: dict, ip: str, empreinte: str, maintenant: float,
                        evincer: dict | None = None) -> str | None:
    """None s'il y a place pour une nouvelle attente de cette adresse, sinon le message de refus. Quand la table est
    pleine, l'attente la moins récemment vue d'une adresse qui en garde PLUSIEURS cède sa place (retirée de `evincer`
    s'il est donné ; sans lui, simple lecture). L'attente seule de son adresse ne cède jamais."""
    en_cours = evincer if evincer is not None else _attentes_valides(fiche, maintenant)
    autres = {e: a for e, a in en_cours.items() if e != empreinte}
    if sum(1 for a in autres.values() if a.get("ip") == ip) >= ATTENTES_PAR_ADRESSE:
        return MESSAGE_TROP_D_ATTENTES_ADRESSE
    if len(autres) < ATTENTES_PAR_COURRIEL:
        return None
    par_adresse: dict[str, int] = {}
    for a in autres.values():
        cle_adresse = str(a.get("ip") or "")
        par_adresse[cle_adresse] = par_adresse.get(cle_adresse, 0) + 1
    # Une attente sans adresse connue (ancien format) compte comme seule : on ne l'évince pas.
    cedables = [e for e, a in autres.items() if a.get("ip") and par_adresse.get(str(a.get("ip")), 0) > 1]
    if not cedables:
        return MESSAGE_TROP_D_ATTENTES
    if evincer is not None:
        evincer.pop(min(cedables, key=lambda e: float(autres[e].get("vu_a") or 0)), None)
    return None


def _message_deja_envoye(attente: dict, empreinte: str, maintenant: float) -> str:
    """Relance d'une attente encore valable : aucun nouveau courriel. Le message dit où chercher et quand un nouveau
    courriel pourra partir, au lieu d'un « Trop de demandes » alors qu'un lien valable attend."""
    heures = max(1, round((DUREE_CONFIRMATION_S - (maintenant - float(attente.get("cree") or 0))) / 3600))
    ouvrir = "Ouvrez son lien" if attente.get("jeton") else "Ouvrez le plus récent des courriels de confirmation reçus"
    return (
        "Un courriel de confirmation a déjà été envoyé à l'adresse de votre compte VELA pour cet ordinateur. "
        f"{ouvrir} et recopiez le code {empreinte} affiché ici. Pas reçu ? Regardez dans les courriels indésirables : "
        f"aucun nouveau courriel ne part tant que ce lien reste valable (encore environ {heures} h)."
    )


def _attente_du_jeton(jeton: str) -> tuple[str, dict, dict] | tuple[None, None, None]:
    """(courriel, fiche, attente) du lien reçu par courriel, s'il est encore valable."""
    empreinte_jeton = hashlib.sha256(str(jeton or "").encode()).hexdigest()
    maintenant = time.time()
    for courriel, fiche in _lire_liaisons().items():
        if not isinstance(fiche, dict):
            continue
        for attente in _attentes_valides(fiche, maintenant).values():
            if attente.get("jeton") and hmac.compare_digest(str(attente.get("jeton")), empreinte_jeton):
                return courriel, fiche, attente
    return None, None, None


@app.get("/appareil/confirmer/{jeton}", response_class=HTMLResponse)
def page_confirmer_liaison(jeton: str):
    """Page du lien reçu par courriel. Elle NE confirme rien d'elle-même (un logiciel qui ouvre les liens d'un
    courriel pour les analyser ne doit pas lier un ordinateur) : il faut recopier le code affiché dans IRIS et
    appuyer sur le bouton. Elle ne montre ni ce code ni le nom de l'ordinateur : ce nom vient de la demande."""
    courriel, fiche, attente = _attente_du_jeton(jeton)
    if not attente:
        return HTMLResponse(PAGE_LIAISON.replace("{{CONTENU}}", "<p>Ce lien n'est plus valable (déjà utilisé, ou plus "
                                                 "de 24 heures). Relancez la liaison depuis IRIS.</p>"),
                            status_code=410, headers=ENTETES_PAGES_SENSIBLES)
    remplace = ("<p><strong>Attention :</strong> un ordinateur est déjà lié à votre compte ; celui dont vous recopiez "
                "le code le remplacera.</p>") if fiche.get("confirme_le") else ""
    contenu = (
        "<p>Un ordinateur demande à recevoir les commandes de verrouillage et d'effacement à distance de votre "
        f"compte VELA.</p>{remplace}"
        "<p>Sur <strong>votre</strong> ordinateur, ouvrez IRIS › Profil › Verrouillage à distance : un code de "
        "6 caractères y est affiché. Recopiez-le ici. Si IRIS ne vous montre aucun code, ne confirmez rien : "
        "la demande ne vient pas de vous.</p>"
        '<label for="empreinte">Code affiché dans IRIS</label>'
        '<input id="empreinte" name="empreinte" autocomplete="off" autocapitalize="characters" spellcheck="false" '
        'maxlength="12">'
        '<button id="confirmer" type="button">Confirmer cet ordinateur</button>'
        '<p id="statut" role="status" aria-live="polite"></p>'
    )
    return HTMLResponse(PAGE_LIAISON.replace("{{CONTENU}}", contenu), headers=ENTETES_PAGES_SENSIBLES)


@app.post("/api/appareil/confirmer")
async def confirmer_liaison(request: Request):
    """{jeton, empreinte} : le lien reçu par courriel ET le code recopié depuis IRIS. Le code désigne l'ordinateur
    à lier parmi ceux en attente pour ce courriel ; un code qui ne correspond à rien est refusé (403) et compté :
    au 5e, le lien ne sert plus."""
    delai = limiter([f"confirmation-ip:{adresse_ip(request.headers, request.client)}"], CONFIRMATIONS_PAR_IP, 900.0)
    if delai:
        return JSONResponse({"ok": False, "message": "Trop de tentatives. Réessayez dans quelques minutes."},
                            status_code=429)
    corps = await _corps_json(request)
    jeton = str(corps.get("jeton") or "")
    code = _normaliser_empreinte(corps.get("empreinte"))
    maintenant = time.time()
    with _LIAISONS_VERROU:
        courriel, _, attente = _attente_du_jeton(jeton)
        if not attente:
            return JSONResponse({"ok": False, "message": "Ce lien n'est plus valable. Relancez la liaison depuis IRIS."},
                                status_code=410)
        liaisons = _lire_liaisons()
        actuelle = liaisons.get(courriel) if isinstance(liaisons.get(courriel), dict) else {}
        en_cours = _attentes_valides(actuelle, maintenant)
        choisie = en_cours.get(code) if len(code) == 6 else None
        if choisie is None:
            for a in en_cours.values():
                if a.get("jeton") and hmac.compare_digest(str(a.get("jeton")), str(attente.get("jeton"))):
                    a["echecs"] = int(a.get("echecs") or 0) + 1
                    if a["echecs"] >= ECHECS_CONFIRMATION_MAX:
                        a["jeton"] = ""  # lien épuisé : plus aucun essai par lui
            actuelle.pop("attente", None)
            actuelle["attentes"] = en_cours
            liaisons[courriel] = actuelle
            _ecrire(FICHIER_LIAISONS, liaisons)
            return JSONResponse({"ok": False, "message": (
                "Ce code ne correspond à aucun ordinateur en attente pour votre compte. Recopiez exactement le code "
                "affiché dans IRIS, sur votre ordinateur. Si IRIS n'en affiche aucun, ne confirmez rien.")},
                status_code=403)
        liaisons[courriel] = {"id": choisie["id"], "cle": choisie["cle"], "machine": choisie.get("machine"),
                              "confirme_le": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                              "sel": None, "iterations": None}
        _ecrire(FICHIER_LIAISONS, liaisons)
    # L'ordinateur connecté jusqu'ici (lié à l'ancienne clé, ou pas lié du tout) est déconnecté : le nouvel
    # ordinateur lié se reconnecte et prouve sa clé.
    pc = _pc_par_courriel.pop(courriel, None)
    if pc is not None:
        try:
            await pc["ws"].close(code=4003)
        except Exception:
            pass
    log.info("liaison : ordinateur lié confirmé")
    return {"ok": True, "message": "C'est confirmé : cet ordinateur est lié à votre compte pour le verrouillage à distance."}


PAGE_LIAISON = """<!doctype html>
<html lang="fr-CA">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex">
<title>Lier un ordinateur · VELA</title>
<style>
:root { --fond:#f6f7f9; --carte:#ffffff; --texte:#14161a; --accent:#1f4fd1; --focus:#ffb300; }
@media (prefers-color-scheme: dark) { :root { --fond:#0f1115; --carte:#181b21; --texte:#eef0f3; --accent:#8fb0ff; } }
body { margin:0; background:var(--fond); color:var(--texte); font:18px/1.5 system-ui, -apple-system, "Segoe UI", Roboto, sans-serif; }
main { max-width:36rem; margin:0 auto; padding:1.5rem 1rem 3rem; }
.carte { background:var(--carte); border-radius:14px; padding:1.25rem; }
label { display:block; font-weight:600; margin:1rem 0 .35rem; }
input { width:100%; box-sizing:border-box; font-size:1.3rem; letter-spacing:.2em; padding:.7rem; border-radius:10px;
  border:2px solid #8a919c; background:var(--fond); color:var(--texte); text-transform:uppercase; }
button { width:100%; min-height:3.2rem; font-size:1.15rem; font-weight:700; border:none; border-radius:12px;
  background:var(--accent); color:#fff; margin-top:1rem; cursor:pointer; }
:focus-visible { outline:3px solid var(--focus); outline-offset:2px; }
#statut { font-weight:600; min-height:1.5rem; }
</style>
</head>
<body>
<main>
<h1>Lier un ordinateur à votre compte VELA</h1>
<div class="carte">{{CONTENU}}</div>
</main>
<script>
(function () {
  var bouton = document.getElementById('confirmer');
  if (!bouton) return;
  var jeton = location.pathname.split('/').pop();
  var champ = document.getElementById('empreinte');
  bouton.addEventListener('click', function () {
    var statut = document.getElementById('statut');
    var code = ((champ && champ.value) || '').replace(/[^A-Za-z0-9]/g, '').toUpperCase();
    if (code.length !== 6) { statut.textContent = 'Recopiez les 6 caractères du code affiché dans IRIS.'; if (champ) champ.focus(); return; }
    bouton.disabled = true;
    statut.textContent = 'Confirmation en cours…';
    fetch('../../api/appareil/confirmer', { method: 'POST', headers: { 'Content-Type': 'application/json' },
      cache: 'no-store', body: JSON.stringify({ jeton: jeton, empreinte: code }) })
      .then(function (r) { return r.json().then(function (j) { return { ok: r.ok, j: j || {} }; }); })
      .then(function (res) { statut.textContent = res.j.message || 'Réponse inattendue.'; if (!res.ok) bouton.disabled = false; })
      .catch(function () { statut.textContent = 'Le relais est injoignable. Réessayez.'; bouton.disabled = false; });
  });
})();
</script>
</body>
</html>
"""


# --------------------------------------------------------------------------- télécommande (canal inverse)
# Le relais devient un COURTIER. L'ordinateur d'un abonné ouvre un WebSocket SORTANT et s'y annonce ;
# le téléphone du MÊME courriel envoie des commandes, routées vers cet ordinateur, exécutées CHEZ LUI
# (toute la boucle d'IRIS : périmètre + confirmation), et dont le résultat — et les demandes d'accord —
# reviennent au téléphone. Aucun port ouvert, aucune machine jamais joignable de l'extérieur.
# Cloisonné par courriel : un téléphone n'atteint QUE l'ordinateur de son propre compte.

_pc_par_courriel: dict[str, dict] = {}   # courriel -> {"ws": WebSocket, "pairing": str}
_req_en_cours: dict[str, dict] = {}       # req_id -> {"tel": WebSocket, "courriel": str}


async def _hello_complet(ws: WebSocket) -> tuple[str | None, str, dict]:
    """Attend {type:'hello', jeton, pairing, preuve?}. Renvoie (courriel, pairing, message), ou (None, '', {})."""
    try:
        premier = await asyncio.wait_for(ws.receive_json(), timeout=15)
    except Exception:
        return None, "", {}
    if not isinstance(premier, dict) or premier.get("type") != "hello":
        return None, "", {}
    info = lire_jeton(str(premier.get("jeton") or ""))
    if not info or not info.get("courriel"):
        return None, "", {}
    return normaliser(info["courriel"]), str(premier.get("pairing") or ""), premier


async def _hello(ws: WebSocket) -> tuple[str | None, str]:
    """Attend {type:'hello', jeton, pairing}. Renvoie (courriel, pairing), ou (None, '') si refusé.

    Le jeton d'appareil (émis sans mot de passe par /api/appareil) suffit pour l'IA, mais PAS pour
    piloter un ordinateur : connaître un courriel ne doit pas donner la main sur une machine. Le
    CODE D'APPAIRAGE — affiché par l'ordinateur, saisi dans le téléphone — est le second facteur."""
    courriel, pairing, _ = await _hello_complet(ws)
    return courriel, pairing


async def _defi_ordinateur(ws: WebSocket, courriel: str) -> bool:
    """Défi-réponse de l'ordinateur qui l'annonce ({preuve: 1} dans son hello). Vrai seulement si la réponse
    est faite avec la clé de l'ordinateur LIÉ à ce courriel ; il publie alors aussi le sel de son code de secours."""
    nonce = _b64(secrets.token_bytes(32))
    await ws.send_json({"type": "defi", "nonce": nonce})
    try:
        reponse = await asyncio.wait_for(ws.receive_json(), timeout=15)
    except Exception:
        return False
    if not isinstance(reponse, dict) or reponse.get("type") != "preuve":
        return False
    if not verifier_preuve_pc(courriel, f"vela-appareil-ws|v1|{courriel}|{nonce}", str(reponse.get("preuve") or "")):
        return False
    publier_infos_verrou(courriel, reponse.get("verrou"))
    return True


def _pc_pour(courriel: str, pairing: str) -> dict | None:
    """L'ordinateur d'un courriel, SEULEMENT si le code d'appairage correspond (comparaison constante)."""
    pc = _pc_par_courriel.get(courriel)
    if not pc or not pairing:
        return None
    return pc if hmac.compare_digest(pc.get("pairing", ""), pairing) else None


@app.websocket("/appareil/ws")
async def appareil_ws(ws: WebSocket):
    """L'ORDINATEUR d'un abonné se branche ici (connexion sortante) pour recevoir des commandes.

    Il ne reçoit QUE les commandes des téléphones de son propre courriel, et ne renvoie un message
    qu'au téléphone qui a lancé la requête concernée (routage par req_id vérifié côté courriel)."""
    await ws.accept()
    courriel, pairing, hello = await _hello_complet(ws)
    if not courriel or not pairing:  # jeton invalide OU aucun code d'appairage : on refuse
        await ws.close(code=4001)
        return
    # Constat bloquant du 2026-09-14 : quand un ordinateur est LIÉ à ce courriel (confirmé par courriel), seul
    # celui qui prouve sa clé est accepté ; il remplace alors l'ancienne connexion. Sans liaison, l'ancien
    # fonctionnement demeure (télécommande seulement : aucun message « verrou » n'est jamais envoyé).
    annonce_preuve = bool(hello.get("preuve"))
    prouve = await _defi_ordinateur(ws, courriel) if annonce_preuve else False
    lie = liaison_confirmee(courriel) is not None
    if lie and not prouve:
        try:
            await ws.send_json({"type": "refus", "raison": "liaison", "message": MESSAGE_PC_NON_LIE})
            await ws.close(code=4003)
        except Exception:
            pass
        return
    ancien = _pc_par_courriel.get(courriel)
    if ancien is not None and ancien.get("ws") is not ws:
        try:
            await ancien["ws"].close(code=4000)  # un seul ordinateur par courriel : le neuf remplace l'ancien
        except Exception:
            pass
    _pc_par_courriel[courriel] = {"ws": ws, "pairing": pairing, "prouve": prouve}
    await ws.send_json({"type": "pret", "prouve": prouve, "liaison": "confirmee" if lie else "absente"}
                       if annonce_preuve else {"type": "pret"})
    log.info("telecommande : ordinateur connecte%s", " (lié)" if prouve else "")
    try:
        while True:
            msg = await ws.receive_json()
            if not isinstance(msg, dict):
                continue
            if msg.get("type") == "verrou_info":
                if prouve:  # code de secours changé sur l'ordinateur lié : nouveau sel
                    publier_infos_verrou(courriel, msg.get("verrou"))
                continue
            req_id = str(msg.get("req_id") or "")
            entree = _req_en_cours.get(req_id)
            if entree and entree.get("verrou") and not prouve:
                continue  # la réponse à un verrouillage ne vient que de l'ordinateur lié
            # ne router que vers le téléphone qui a lancé CETTE requête, et seulement s'il est du bon courriel
            if entree and entree["courriel"] == courriel:
                try:
                    await entree["tel"].send_json(msg)
                except Exception:
                    pass
                if msg.get("type") == "resultat":
                    _req_en_cours.pop(req_id, None)
    except WebSocketDisconnect:
        pass
    except Exception as exc:  # pragma: no cover - défense
        log.info("telecommande ordinateur %s : %s", courriel, exc)
    finally:
        if _pc_par_courriel.get(courriel, {}).get("ws") is ws:
            _pc_par_courriel.pop(courriel, None)
        log.info("telecommande : ordinateur deconnecte (%s)", courriel)


@app.websocket("/telecommande/ws")
async def telecommande_ws(ws: WebSocket):
    """Le TÉLÉPHONE de l'abonné se branche ici pour piloter SON ordinateur, à distance."""
    await ws.accept()
    courriel, pairing = await _hello(ws)
    if not courriel or not pairing:
        await ws.close(code=4001)
        return
    await ws.send_json({"type": "pret", "ordinateur": _pc_pour(courriel, pairing) is not None})
    mes_reqs: set[str] = set()
    try:
        while True:
            msg = await ws.receive_json()
            if not isinstance(msg, dict):
                continue
            t = msg.get("type")
            pc = _pc_pour(courriel, pairing)  # None si l'ordi est absent OU si le code d'appairage ne correspond pas
            if t == "commande":
                req_id = str(msg.get("req_id") or uuid.uuid4().hex)
                if pc is None:
                    await ws.send_json({"type": "resultat", "req_id": req_id, "erreur": "ordinateur_absent",
                                        "message": "Ton ordinateur n'est pas connecté, ou le code d'appairage ne correspond pas."})
                    continue
                if len(mes_reqs) >= 4:  # anti-abus : pas plus de 4 commandes en vol par téléphone
                    await ws.send_json({"type": "resultat", "req_id": req_id, "erreur": "trop_de_commandes",
                                        "message": "Trop de commandes en attente. Réessaie dans un instant."})
                    continue
                _req_en_cours[req_id] = {"tel": ws, "courriel": courriel}
                mes_reqs.add(req_id)
                try:
                    await pc["ws"].send_json({"type": "commande", "req_id": req_id, "texte": str(msg.get("texte") or "")})
                except Exception:
                    _req_en_cours.pop(req_id, None)
                    mes_reqs.discard(req_id)
                    await ws.send_json({"type": "resultat", "req_id": req_id, "erreur": "ordinateur_injoignable",
                                        "message": "Ton ordinateur ne répond pas."})
            elif t == "confirm_reponse":
                req_id = str(msg.get("req_id") or "")
                entree = _req_en_cours.get(req_id)
                if entree and entree["tel"] is ws and pc is not None:
                    try:
                        await pc["ws"].send_json(msg)  # l'accord (oui/non) redescend vers l'ordinateur
                    except Exception:
                        pass
    except WebSocketDisconnect:
        pass
    except Exception as exc:  # pragma: no cover - défense
        log.info("telecommande telephone %s : %s", courriel, exc)
    finally:
        for r in list(mes_reqs):
            if _req_en_cours.get(r, {}).get("tel") is ws:
                _req_en_cours.pop(r, None)


# --------------------------------------------------------------------------- modules du 2026-09-13
# Vision partagée en direct (partage_vision.py) et verrouillage à distance (verrou_distant.py),
# chacun dans son fichier. Import protégé : le relais doit démarrer même si un module manque.
# Chaque module expose une fabrique qui reçoit CE module (accès à l'état du relais).
def _brancher_modules_relais() -> None:
    import importlib
    import sys

    for _module, _fabrique in (("partage_vision", "creer_routeur_partage"), ("verrou_distant", "creer_routeur_verrou")):
        try:
            _mod = importlib.import_module(_module)
            app.include_router(getattr(_mod, _fabrique)(sys.modules[__name__]))
        except Exception as _exc:  # pragma: no cover - module absent
            log.info("module %s indisponible : %s", _module, _exc)


_brancher_modules_relais()
