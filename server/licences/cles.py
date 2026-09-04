"""Génération et vérification des clés d'abonnement IRIS.

Le format est repris **à l'identique** de backend/iris/plans.py :

    IRIS-<charge>-<signature>
    charge    = base64url(json{"p": plan, "e": expiration, "u": courriel}) sans le remplissage « = »
    signature = HMAC-SHA256(secret, charge) en hexadécimal, tronqué à 20 caractères

Toute divergence ici rendrait les clés inutilisables dans l'application. La seule différence
volontaire : le secret est un paramètre au lieu d'être en dur.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
from datetime import date, timedelta

log = logging.getLogger("licences.cles")

# Plans vendables. « gratuit » existe dans l'application mais ne se vend pas.
PLANS = ("gratuit", "essentiel", "pro", "ultra")
PLANS_PAYANTS = ("essentiel", "pro", "ultra")

ETIQUETTES = {
    "gratuit": "Gratuit",
    "essentiel": "Essentiel",
    "pro": "Pro",
    "ultra": "Ultra",
}


def faire_cle(plan: str, expiration: str, courriel: str, secret: bytes) -> str:
    """Équivalent exact de plans.make_key(), avec le secret en paramètre."""
    if plan not in PLANS:
        raise ValueError("plan inconnu")
    charge = (
        base64.urlsafe_b64encode(
            json.dumps({"p": plan, "e": expiration, "u": courriel}, separators=(",", ":")).encode()
        )
        .decode()
        .rstrip("=")
    )
    signature = hmac.new(secret, charge.encode(), hashlib.sha256).hexdigest()[:20]
    return f"IRIS-{charge}-{signature}"


def verifier_cle(cle: str, secret: bytes) -> dict | None:
    """Équivalent exact de plans.verify_key(), y compris son découpage `split("-", 2)`.

    Ce découpage est reproduit volontairement : c'est le code qui tournera chez le client.
    Si l'application le corrige un jour en `rsplit("-", 1)`, cette copie devra suivre.
    Voir `cle_utilisable()` : le serveur ne livre jamais une clé que ce code rejetterait.
    """
    try:
        cle = (cle or "").strip()
        if not cle.startswith("IRIS-"):
            return None
        _, charge, signature = cle.split("-", 2)
        attendue = hmac.new(secret, charge.encode(), hashlib.sha256).hexdigest()[:20]
        if not hmac.compare_digest(attendue, signature):
            return None
        donnees = json.loads(base64.urlsafe_b64decode(charge + "=" * (-len(charge) % 4)).decode())
        plan, expiration = donnees.get("p"), donnees.get("e") or ""
        if plan not in PLANS:
            return None
        if expiration and date.fromisoformat(expiration) < date.today():
            return {"plan": plan, "expiration": expiration, "expiree": True, "courriel": donnees.get("u", "")}
        return {"plan": plan, "expiration": expiration, "expiree": False, "courriel": donnees.get("u", "")}
    except Exception:
        return None


def cle_utilisable(cle: str, secret: bytes) -> bool:
    """Vrai si l'application acceptera cette clé (elle passe par notre copie de verify_key)."""
    return verifier_cle(cle, secret) is not None


def emettre(plan: str, expiration: str, courriel: str, secret: bytes) -> tuple[str, str]:
    """Émet une clé en garantissant qu'elle sera acceptée par l'application.

    La charge utile est du base64 *url-safe* : elle peut contenir un « - », et le découpage
    `split("-", 2)` de l'application casserait alors la clé. Le cas est rare (il demande des
    octets élevés, comme « ~ », dans le courriel) mais silencieux, donc on le teste avant l'envoi.

    Renvoie (clé, note) ; `note` est vide quand tout va bien, sinon elle explique le repli.
    """
    cle = faire_cle(plan, expiration, courriel, secret)
    if cle_utilisable(cle, secret):
        return cle, ""

    # Repli : la même clé sans le courriel. L'application n'utilise « u » que pour l'affichage.
    log.warning("Clé rejetée par la vérification pour %s : nouvel essai sans le courriel.", courriel)
    cle_sans_courriel = faire_cle(plan, expiration, "", secret)
    if cle_utilisable(cle_sans_courriel, secret):
        return cle_sans_courriel, (
            "Clé émise sans le courriel : la charge utile contenait un « - » que "
            "verify_key() de l'application ne sait pas découper."
        )

    raise ValueError(
        "Impossible d'émettre une clé que l'application accepterait "
        f"(plan={plan}, expiration={expiration}). À traiter à la main."
    )


def prolonger(expiration_actuelle: str | None, mois: int = 1, aujourdhui: date | None = None) -> str:
    """Nouvelle date d'expiration : on ajoute `mois` à la date existante si elle est encore valide,
    sinon à aujourd'hui. C'est ce qui permet à un client qui paie en avance de cumuler ses mois.
    """
    base = aujourdhui or date.today()
    if expiration_actuelle:
        try:
            actuelle = date.fromisoformat(expiration_actuelle)
            if actuelle > base:
                base = actuelle
        except ValueError:
            pass
    return _ajouter_mois(base, mois).isoformat()


def _ajouter_mois(depart: date, mois: int) -> date:
    """Ajoute des mois calendaires (le 31 janvier + 1 mois donne le 28/29 février)."""
    total = depart.month - 1 + mois
    annee = depart.year + total // 12
    mois_final = total % 12 + 1
    # Dernier jour du mois d'arrivée
    jour_max = (date(annee + (mois_final == 12), (mois_final % 12) + 1, 1) - timedelta(days=1)).day
    return date(annee, mois_final, min(depart.day, jour_max))
