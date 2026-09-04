"""Dialogue avec PayPal : jeton OAuth2 et vérification de la signature des webhooks.

Un webhook PayPal arrive avec cinq en-têtes de signature. On les renvoie à PayPal, accompagnés
du corps **exact** reçu, et PayPal répond SUCCESS ou FAILURE. C'est la seule façon fiable de
savoir que l'événement vient bien de PayPal : sans cette vérification, n'importe qui connaissant
l'adresse du service pourrait s'offrir un abonnement Ultra en envoyant un faux paiement.

Documentation : POST {api}/v1/notifications/verify-webhook-signature
"""
from __future__ import annotations

import logging
import time

import httpx

log = logging.getLogger("licences.paypal")

# Les cinq en-têtes que PayPal envoie avec chaque webhook.
ENTETES_SIGNATURE = (
    "paypal-auth-algo",
    "paypal-cert-url",
    "paypal-transmission-id",
    "paypal-transmission-sig",
    "paypal-transmission-time",
)


class ErreurPaypal(RuntimeError):
    """Impossible de joindre PayPal ou de valider la signature."""


class ClientPaypal:
    """Client minimal : un jeton OAuth2 mis en cache et la vérification de signature."""

    def __init__(self, base: str, client_id: str, secret: str, webhook_id: str,
                 delai: float = 10.0, transport: httpx.BaseTransport | None = None):
        self.base = base.rstrip("/")
        self.client_id = client_id
        self.secret = secret
        self.webhook_id = webhook_id
        self.delai = delai
        self._transport = transport  # injecté par les tests, jamais en production
        self._jeton = ""
        self._expire_a = 0.0

    # ------------------------------------------------------------------ jeton
    def jeton(self) -> str:
        """Jeton d'accès OAuth2, renouvelé une minute avant son expiration.

        Le jeton n'est jamais journalisé : seule sa durée de vie l'est.
        """
        if self._jeton and time.time() < self._expire_a:
            return self._jeton
        try:
            with httpx.Client(timeout=self.delai, transport=self._transport) as client:
                reponse = client.post(
                    f"{self.base}/v1/oauth2/token",
                    auth=(self.client_id, self.secret),
                    data={"grant_type": "client_credentials"},
                    headers={"Accept": "application/json"},
                )
        except httpx.HTTPError as erreur:
            raise ErreurPaypal(f"PayPal injoignable pour le jeton : {erreur}") from erreur
        if reponse.status_code != 200:
            raise ErreurPaypal(f"PayPal a refusé les identifiants (HTTP {reponse.status_code}).")
        donnees = reponse.json()
        self._jeton = donnees.get("access_token") or ""
        duree = int(donnees.get("expires_in") or 0)
        self._expire_a = time.time() + max(duree - 60, 30)
        if not self._jeton:
            raise ErreurPaypal("PayPal n'a pas renvoyé de jeton d'accès.")
        log.info("Jeton PayPal obtenu (valide %s s).", duree)
        return self._jeton

    # ------------------------------------------------------------------ signature
    def verifier_signature(self, entetes: dict, evenement: dict) -> bool:
        """Vrai si PayPal confirme la signature du webhook.

        `entetes` : les en-têtes HTTP de la requête reçue (insensibles à la casse).
        `evenement` : le corps du webhook déjà décodé en JSON.
        """
        entetes = {k.lower(): v for k, v in entetes.items()}
        manquants = [e for e in ENTETES_SIGNATURE if not entetes.get(e)]
        if manquants:
            log.warning("Webhook sans en-têtes de signature : %s", ", ".join(manquants))
            return False

        corps = {
            "auth_algo": entetes["paypal-auth-algo"],
            "cert_url": entetes["paypal-cert-url"],
            "transmission_id": entetes["paypal-transmission-id"],
            "transmission_sig": entetes["paypal-transmission-sig"],
            "transmission_time": entetes["paypal-transmission-time"],
            "webhook_id": self.webhook_id,
            "webhook_event": evenement,
        }
        try:
            with httpx.Client(timeout=self.delai, transport=self._transport) as client:
                reponse = client.post(
                    f"{self.base}/v1/notifications/verify-webhook-signature",
                    json=corps,
                    headers={"Authorization": f"Bearer {self.jeton()}", "Content-Type": "application/json"},
                )
        except httpx.HTTPError as erreur:
            raise ErreurPaypal(f"PayPal injoignable pour la vérification : {erreur}") from erreur

        if reponse.status_code != 200:
            log.warning("Vérification refusée par PayPal (HTTP %s).", reponse.status_code)
            return False
        statut = (reponse.json() or {}).get("verification_status")
        if statut != "SUCCESS":
            log.warning("Signature invalide : verification_status=%s", statut)
            return False
        return True


# ---------------------------------------------------------------------- lecture des événements
def courriel_du_payeur(evenement: dict) -> str:
    """Extrait le courriel du payeur, quel que soit le type d'événement.

    PayPal le place à des endroits différents selon qu'il s'agit d'une capture de paiement
    ou d'un abonnement. On cherche dans l'ordre du plus fiable au moins fiable.
    """
    ressource = (evenement or {}).get("resource") or {}
    chemins = (
        ("subscriber", "email_address"),
        ("payer", "email_address"),
        ("payer", "payer_info", "email"),
        ("payment_source", "paypal", "email_address"),
        ("supplementary_data", "related_ids", "payer_email"),
    )
    for chemin in chemins:
        valeur = ressource
        for cle in chemin:
            if not isinstance(valeur, dict):
                valeur = None
                break
            valeur = valeur.get(cle)
        if isinstance(valeur, str) and "@" in valeur:
            return valeur.strip().lower()

    # Repli : certains marchands mettent le courriel dans custom_id (c'est ce que fera le site VELA).
    for cle in ("custom_id", "custom"):
        valeur = ressource.get(cle)
        if isinstance(valeur, str) and "@" in valeur:
            return valeur.strip().lower()
    return ""


def montant_de(evenement: dict) -> tuple[float | None, str | None]:
    """Extrait (montant, devise) de la ressource, selon la forme de l'événement."""
    ressource = (evenement or {}).get("resource") or {}
    candidats = (
        ressource.get("amount"),                                   # PAYMENT.CAPTURE.*
        (ressource.get("billing_info") or {}).get("last_payment", {}).get("amount"),  # abonnement actif
        ressource.get("gross_amount"),
        (ressource.get("seller_receivable_breakdown") or {}).get("gross_amount"),
    )
    for bloc in candidats:
        if isinstance(bloc, dict):
            valeur = bloc.get("value") or bloc.get("total")
            devise = bloc.get("currency_code") or bloc.get("currency")
            if valeur is not None:
                try:
                    return float(valeur), (devise or "").upper() or None
                except (TypeError, ValueError):
                    continue
    return None, None


def identifiant_transaction(evenement: dict) -> str:
    """Identifiant qui sert de clé d'idempotence pour le crédit accordé.

    Pour une capture : l'identifiant de la capture (unique par paiement).
    Pour un abonnement : l'identifiant du dernier paiement s'il existe, sinon
    l'identifiant de l'abonnement suffixé par le type d'événement (un abonnement ne peut
    être activé, annulé ou expiré qu'une fois).
    """
    ressource = (evenement or {}).get("resource") or {}
    type_evenement = (evenement or {}).get("event_type") or ""
    if type_evenement.startswith("PAYMENT.CAPTURE"):
        return str(ressource.get("id") or "")
    abonnement = str(ressource.get("id") or "")
    if not abonnement:
        return ""
    if type_evenement == "BILLING.SUBSCRIPTION.ACTIVATED":
        dernier = ((ressource.get("billing_info") or {}).get("last_payment") or {}).get("time")
        return f"{abonnement}:{type_evenement}:{dernier}" if dernier else f"{abonnement}:{type_evenement}"
    return f"{abonnement}:{type_evenement}"
