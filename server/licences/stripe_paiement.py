"""Dialogue avec Stripe : vérification de la signature des webhooks et création de session Checkout.

Le miroir exact de paypal.py, mais pour Stripe. Deux différences de fond tenant à Stripe lui-même :

  1. La signature se vérifie **localement**, sans aucun appel réseau. Stripe envoie un en-tête
     `Stripe-Signature` de la forme `t=<horodatage>,v1=<signature hexadécimale>`. On recalcule
     HMAC-SHA256 de `"{t}.{corps brut}"` avec le secret du webhook (STRIPE_WEBHOOK_SECRET), et on
     compare en temps constant. Le corps utilisé DOIT être le corps brut exact reçu (bytes),
     jamais du JSON re-sérialisé : un seul octet de différence et la signature ne correspond plus.

  2. Les montants arrivent en **centimes** (amount_total, amount_paid…) et la devise en minuscules.
     On convertit en dollars et on met la devise en majuscules pour parler le même langage que
     montants.reconnaitre().

Aucune clé réelle n'apparaît ici : le secret du webhook et la clé secrète viennent de la
configuration (donc de variables d'environnement). Rien n'est jamais journalisé.

Documentation : https://stripe.com/docs/webhooks/signatures
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import time

import httpx

log = logging.getLogger("licences.stripe")

# Types d'événements Stripe que le service sait traiter, et leur vocabulaire interne.
#   « crediter »        : un paiement est arrivé, on active ou on prolonge l'abonnement ;
#   « annule »          : l'abonnement est supprimé chez Stripe ;
#   « paiement_echoue » : un prélèvement a échoué (on n'coupe pas tout de suite).
# Tout type absent de ce tableau est journalisé puis ignoré.
TYPE_VERS_INTERNE = {
    "checkout.session.completed": "crediter",
    "invoice.paid": "crediter",
    "invoice.payment_succeeded": "crediter",
    "customer.subscription.deleted": "annule",
    "invoice.payment_failed": "paiement_echoue",
}


class ErreurStripe(RuntimeError):
    """Impossible de joindre Stripe (création de session Checkout)."""


# ---------------------------------------------------------------------- signature
def verifier_signature(entete_stripe_signature: str, corps_brut: bytes, secret_webhook: str,
                       tolerance: int = 300) -> bool:
    """Vrai si l'en-tête `Stripe-Signature` correspond bien au corps brut et au secret.

    Schéma Stripe, vérifié **sans aucun appel réseau** :
      - l'en-tête a la forme `t=1690000000,v1=abc...,v1=def...` (plusieurs v1 possibles lors
        d'une rotation de secret) ;
      - la charge signée est exactement `f"{t}.{corps_brut décodé en UTF-8}"` ;
      - la signature attendue est HMAC-SHA256(secret_webhook, charge signée) en hexadécimal ;
      - la comparaison est en temps constant (hmac.compare_digest) ;
      - si `tolerance` > 0, un horodatage qui s'écarte de plus de `tolerance` secondes de l'heure
        actuelle est refusé (protection contre le rejeu d'un ancien appel).

    Le secret du webhook (whsec_...) est utilisé TEL QUEL comme clé HMAC, sans décodage :
    c'est ce que fait la bibliothèque officielle de Stripe.
    """
    if not entete_stripe_signature or not secret_webhook:
        return False
    if isinstance(corps_brut, str):
        corps_brut = corps_brut.encode("utf-8")
    try:
        corps_texte = corps_brut.decode("utf-8")
    except (UnicodeDecodeError, AttributeError):
        log.warning("Corps de webhook Stripe non décodable en UTF-8 : signature refusée.")
        return False

    horodatage: str | None = None
    signatures: list[str] = []
    for partie in entete_stripe_signature.split(","):
        cle, _, valeur = partie.partition("=")
        cle, valeur = cle.strip(), valeur.strip()
        if cle == "t":
            horodatage = valeur
        elif cle == "v1":
            signatures.append(valeur)

    if horodatage is None or not signatures:
        log.warning("En-tête Stripe-Signature incomplet (t ou v1 manquant).")
        return False
    try:
        t = int(horodatage)
    except ValueError:
        log.warning("Horodatage Stripe non numérique dans la signature.")
        return False

    if tolerance and tolerance > 0 and abs(time.time() - t) > tolerance:
        log.warning("Horodatage de webhook Stripe hors tolérance (%s s) : rejeu probable, refusé.", tolerance)
        return False

    charge_signee = f"{horodatage}.{corps_texte}".encode("utf-8")
    attendue = hmac.new(secret_webhook.encode("utf-8"), charge_signee, hashlib.sha256).hexdigest()
    for signature in signatures:
        if hmac.compare_digest(attendue, signature):
            return True
    log.warning("Aucune signature v1 ne correspond : webhook Stripe refusé.")
    return False


# ---------------------------------------------------------------------- lecture des événements
def objet(evenement: dict) -> dict:
    """L'objet métier de l'événement.

    Stripe l'imbrique sous `data.object`. On accepte aussi `resource` par prudence (certains
    outils de rejeu l'aplatissent), pour coller au vocabulaire de paypal.py.
    """
    evenement = evenement or {}
    donnees = evenement.get("data")
    if isinstance(donnees, dict) and isinstance(donnees.get("object"), dict):
        return donnees["object"]
    ressource = evenement.get("resource")
    if isinstance(ressource, dict):
        return ressource
    return {}


def courriel_du_payeur(evenement: dict) -> str:
    """Extrait le courriel du payeur, quel que soit le type d'événement Stripe.

    On cherche du plus fiable au moins fiable : les détails client d'une session Checkout,
    le courriel direct d'une facture, puis les métadonnées (le site VELA y place `courriel`).
    """
    obj = objet(evenement)
    chemins = (
        ("customer_details", "email"),  # checkout.session
        ("customer_email",),            # checkout.session, invoice
        ("receipt_email",),             # payment_intent / charge
        ("metadata", "email"),
        ("metadata", "courriel"),       # ce que VELA place lui-même
    )
    for chemin in chemins:
        valeur = obj
        for cle in chemin:
            if not isinstance(valeur, dict):
                valeur = None
                break
            valeur = valeur.get(cle)
        if isinstance(valeur, str) and "@" in valeur:
            return valeur.strip().lower()
    return ""


def montant_de(evenement: dict) -> tuple[float | None, str | None]:
    """Extrait (montant en dollars, devise en majuscules) de l'objet.

    Stripe donne des **centimes** (amount_total, amount_paid, amount_due…) : on divise par 100.
    La devise arrive en minuscules (« cad ») : on la met en majuscules pour montants.reconnaitre.
    """
    obj = objet(evenement)
    devise_brute = obj.get("currency")
    devise = devise_brute.upper() if isinstance(devise_brute, str) and devise_brute else None
    for cle in ("amount_total", "amount_paid", "amount_due", "total", "amount"):
        valeur = obj.get(cle)
        if valeur is None:
            continue
        try:
            return round(int(valeur) / 100.0, 2), devise
        except (TypeError, ValueError):
            continue
    return None, devise


def identifiant_transaction(evenement: dict) -> str:
    """Clé d'idempotence : l'identifiant de l'événement Stripe (evt_...), unique par événement.

    Stripe renvoie le même `id` d'événement quand il relance une livraison : c'est exactement ce
    qu'il faut pour dédupliquer. Inutile d'aller chercher l'identifiant de la ressource.
    """
    return str((evenement or {}).get("id") or "")


def abonnement_externe(evenement: dict) -> str:
    """Identifiant d'abonnement Stripe (sub_...), pour retrouver l'abonnement lors d'une annulation.

    - Sur un événement d'abonnement (customer.subscription.*), c'est l'identifiant de l'objet ;
    - sur une session Checkout ou une facture, c'est le champ `subscription`.
    """
    obj = objet(evenement)
    type_ev = (evenement or {}).get("type") or ""
    if type_ev.startswith("customer.subscription"):
        return str(obj.get("id") or "")
    sous = obj.get("subscription")
    if isinstance(sous, dict):
        return str(sous.get("id") or "")
    if isinstance(sous, str):
        return sous
    return ""


def _prix_de_ligne(ligne: dict) -> str:
    """Identifiant de prix d'une ligne (line_item, ligne de facture, item d'abonnement)."""
    if not isinstance(ligne, dict):
        return ""
    prix = ligne.get("price")
    if isinstance(prix, dict) and prix.get("id"):
        return str(prix["id"])
    if isinstance(prix, str):
        return prix
    plan = ligne.get("plan")  # ancienne forme (abonnements historiques)
    if isinstance(plan, dict) and plan.get("id"):
        return str(plan["id"])
    pricing = ligne.get("pricing")  # forme récente des factures
    if isinstance(pricing, dict):
        details = pricing.get("price_details")
        if isinstance(details, dict) and details.get("price"):
            return str(details["price"])
    return ""


def id_prix(evenement: dict) -> str:
    """Identifiant de prix Stripe (price_...) trouvé dans l'événement, ou chaîne vide.

    On regarde, dans l'ordre : les line_items d'une session Checkout, les lignes d'une facture,
    les items d'un abonnement, puis un éventuel prix/plan posé directement sur l'objet.
    Le price id n'est pas toujours présent (Stripe ne développe pas line_items par défaut) :
    dans ce cas la chaîne vide invite à se rabattre sur le montant.
    """
    obj = objet(evenement)
    for conteneur in ("line_items", "lines", "items"):
        bloc = obj.get(conteneur)
        if isinstance(bloc, dict):
            data = bloc.get("data")
            if isinstance(data, list) and data:
                prix = _prix_de_ligne(data[0])
                if prix:
                    return prix
    # Un prix/plan directement sur l'objet (certains événements d'abonnement).
    prix = obj.get("price")
    if isinstance(prix, dict) and prix.get("id"):
        return str(prix["id"])
    if isinstance(prix, str):
        return prix
    plan = obj.get("plan")
    if isinstance(plan, dict) and plan.get("id"):
        return str(plan["id"])
    return ""


def plan_depuis_prix(identifiant_prix: str, correspondance: dict[str, str]) -> str | None:
    """Plan interne correspondant à un identifiant de prix Stripe, via la table de config.

    `correspondance` : {price_id: plan}. Renvoie None si le prix est absent ou inconnu —
    l'appelant se rabat alors sur le montant (montants.reconnaitre).
    """
    if not identifiant_prix:
        return None
    return correspondance.get(identifiant_prix)


def statut_paiement(evenement: dict) -> str:
    """Valeur de `payment_status` de l'objet (utile pour checkout.session.completed)."""
    return str(objet(evenement).get("payment_status") or "")


# ---------------------------------------------------------------------- création de session Checkout
def creer_session_checkout(*, secret_key: str, prix: str, courriel: str,
                           success_url: str, cancel_url: str, locale: str = "fr-CA",
                           delai: float = 10.0,
                           transport: httpx.BaseTransport | None = None) -> str:
    """Crée une session Stripe Checkout (abonnement) et renvoie son URL.

    Appel REST direct à l'API Stripe (pas de paquet `stripe`) : POST form-encodé vers
    /v1/checkout/sessions, authentifié par `Authorization: Bearer {secret_key}`.
    `locale=fr-CA` respecte la Loi 96 (Québec). `transport` est injecté par les tests ;
    en production il reste None (vrai réseau). La clé secrète n'est jamais journalisée.
    """
    if not secret_key:
        raise ErreurStripe("STRIPE_SECRET_KEY absente : impossible de créer une session Checkout.")
    if not prix:
        raise ErreurStripe("Aucun identifiant de prix Stripe pour ce plan.")

    donnees = {
        "mode": "subscription",
        "locale": locale,
        "line_items[0][price]": prix,
        "line_items[0][quantity]": "1",
        "customer_email": courriel,
        "metadata[courriel]": courriel,
        "subscription_data[metadata][courriel]": courriel,  # pour retrouver le courriel aux renouvellements
        "success_url": success_url,
        "cancel_url": cancel_url,
    }
    try:
        with httpx.Client(timeout=delai, transport=transport) as client:
            reponse = client.post(
                "https://api.stripe.com/v1/checkout/sessions",
                data=donnees,
                headers={"Authorization": f"Bearer {secret_key}"},
            )
    except httpx.HTTPError as erreur:
        raise ErreurStripe(f"Stripe injoignable pour la session Checkout : {erreur}") from erreur

    if reponse.status_code != 200:
        # On ne journalise ni le corps (il peut contenir des détails) ni la clé : juste le code.
        raise ErreurStripe(f"Stripe a refusé la création de session (HTTP {reponse.status_code}).")
    url = (reponse.json() or {}).get("url")
    if not url:
        raise ErreurStripe("Stripe n'a pas renvoyé d'URL de session.")
    return str(url)
