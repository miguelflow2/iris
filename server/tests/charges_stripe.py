"""Charges utiles Stripe réalistes, reconstruites à partir de la forme réelle des webhooks.

Elles servent à prouver le service sans compte Stripe. Les identifiants sont FACTICES mais
respectent le format de Stripe (evt_… pour les événements, cs_…/in_…/sub_… pour les objets,
price_… pour les prix). Les montants sont en CENTIMES et la devise en minuscules, comme Stripe.
"""
from __future__ import annotations

import itertools

_compteur = itertools.count(1)


def _identifiant_evenement() -> str:
    return f"evt_FACTICE_{next(_compteur):08d}"


def checkout_complete(courriel: str = "client@exemple.com", prix: str = "price_FACTICE_pro",
                      montant_cents: int = 1999, devise: str = "cad", payment_status: str = "paid",
                      abonnement: str = "sub_FACTICE_001", evenement_id: str | None = None,
                      avec_line_items: bool = True, courriel_dans_metadata: bool = False) -> dict:
    """checkout.session.completed — une session d'abonnement payée.

    `avec_line_items=False` simule le cas (fréquent) où Stripe ne développe pas line_items :
    le service doit alors se rabattre sur le montant.
    """
    objet: dict = {
        "id": "cs_test_FACTICE_001",
        "object": "checkout.session",
        "mode": "subscription",
        "payment_status": payment_status,
        "status": "complete",
        "currency": devise,
        "amount_total": montant_cents,
        "subscription": abonnement,
    }
    if courriel_dans_metadata:
        objet["metadata"] = {"courriel": courriel}
    else:
        objet["customer_details"] = {"email": courriel, "name": "Jean Tremblay"}
        objet["metadata"] = {"courriel": courriel}
    if avec_line_items:
        objet["line_items"] = {
            "object": "list",
            "data": [{"id": "li_FACTICE", "object": "item", "quantity": 1,
                      "price": {"id": prix, "object": "price", "currency": devise}}],
        }
    return {
        "id": evenement_id or _identifiant_evenement(),
        "object": "event",
        "api_version": "2024-06-20",
        "type": "checkout.session.completed",
        "data": {"object": objet},
    }


def facture_payee(courriel: str = "abonne@exemple.com", prix: str = "price_FACTICE_premium",
                  montant_cents: int = 2999, devise: str = "cad", abonnement: str = "sub_FACTICE_001",
                  type_evenement: str = "invoice.paid", evenement_id: str | None = None,
                  avec_lignes: bool = True) -> dict:
    """invoice.paid / invoice.payment_succeeded — un renouvellement d'abonnement."""
    objet: dict = {
        "id": "in_FACTICE_001",
        "object": "invoice",
        "currency": devise,
        "amount_paid": montant_cents,
        "amount_due": montant_cents,
        "total": montant_cents,
        "customer_email": courriel,
        "subscription": abonnement,
        "billing_reason": "subscription_cycle",
    }
    if avec_lignes:
        objet["lines"] = {
            "object": "list",
            "data": [{"id": "il_FACTICE", "object": "line_item",
                      "price": {"id": prix, "object": "price", "currency": devise}}],
        }
    return {
        "id": evenement_id or _identifiant_evenement(),
        "object": "event",
        "type": type_evenement,
        "data": {"object": objet},
    }


def abonnement_supprime(abonnement: str = "sub_FACTICE_001", courriel: str | None = None,
                        evenement_id: str | None = None) -> dict:
    """customer.subscription.deleted — l'abonnement est annulé chez Stripe."""
    objet: dict = {"id": abonnement, "object": "subscription", "status": "canceled"}
    if courriel:
        objet["metadata"] = {"courriel": courriel}
    return {
        "id": evenement_id or _identifiant_evenement(),
        "object": "event",
        "type": "customer.subscription.deleted",
        "data": {"object": objet},
    }


def paiement_echoue(courriel: str = "abonne@exemple.com", abonnement: str = "sub_FACTICE_001",
                    montant_cents: int = 2999, devise: str = "cad", evenement_id: str | None = None) -> dict:
    """invoice.payment_failed — un prélèvement a échoué."""
    return {
        "id": evenement_id or _identifiant_evenement(),
        "object": "event",
        "type": "invoice.payment_failed",
        "data": {"object": {
            "id": "in_FACTICE_ECHEC",
            "object": "invoice",
            "currency": devise,
            "amount_due": montant_cents,
            "customer_email": courriel,
            "subscription": abonnement,
            "billing_reason": "subscription_cycle",
        }},
    }


def evenement_non_traite(evenement_id: str | None = None) -> dict:
    """Un type que le service ne traite pas : il doit être journalisé puis ignoré."""
    return {
        "id": evenement_id or _identifiant_evenement(),
        "object": "event",
        "type": "payment_intent.created",
        "data": {"object": {"id": "pi_FACTICE", "object": "payment_intent", "amount": 1999,
                            "currency": "cad"}},
    }
