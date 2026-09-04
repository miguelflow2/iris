"""Charges utiles PayPal réalistes, reconstruites à partir de la forme réelle des webhooks.

Elles servent à prouver le service sans compte PayPal. Les identifiants sont fictifs mais
respectent le format de PayPal (WH-… pour les événements, I-… pour les abonnements).
"""
from __future__ import annotations

import itertools

_compteur = itertools.count(1)


def _identifiant_evenement() -> str:
    return f"WH-{next(_compteur):017d}-8HN650336L201105X"


def capture_completee(courriel: str = "client@exemple.com", montant: str = "29.99",
                      devise: str = "CAD", capture_id: str | None = None,
                      evenement_id: str | None = None, courriel_dans_custom: bool = False) -> dict:
    """PAYMENT.CAPTURE.COMPLETED — un versement unique (le cas du paiement par lien PayPal).

    `courriel_dans_custom` reproduit le cas réel où PayPal ne transmet pas l'adresse du payeur
    dans la capture : le site VELA la place alors dans `custom_id` au moment de la commande.
    """
    capture_id = capture_id or "3C679366HH908993F"
    ressource = {
        "id": capture_id,
        "status": "COMPLETED",
        "amount": {"currency_code": devise, "value": montant},
        "final_capture": True,
        "seller_protection": {"status": "ELIGIBLE", "dispute_categories": ["ITEM_NOT_RECEIVED"]},
        "seller_receivable_breakdown": {
            "gross_amount": {"currency_code": devise, "value": montant},
            "paypal_fee": {"currency_code": devise, "value": "1.17"},
            "net_amount": {"currency_code": devise, "value": "28.82"},
        },
        "supplementary_data": {"related_ids": {"order_id": "5O190127TN364715T"}},
        "create_time": "2026-09-03T14:22:11Z",
        "update_time": "2026-09-03T14:22:11Z",
        "links": [{"href": f"https://api-m.paypal.com/v2/payments/captures/{capture_id}",
                   "rel": "self", "method": "GET"}],
    }
    if courriel_dans_custom:
        ressource["custom_id"] = courriel
    else:
        ressource["payer"] = {
            "email_address": courriel,
            "payer_id": "QYR5Z8XDVJNXQ",
            "name": {"given_name": "Jean", "surname": "Tremblay"},
            "address": {"country_code": "CA"},
        }
    return {
        "id": evenement_id or _identifiant_evenement(),
        "event_version": "1.0",
        "create_time": "2026-09-03T14:22:13.000Z",
        "resource_type": "capture",
        "resource_version": "2.0",
        "event_type": "PAYMENT.CAPTURE.COMPLETED",
        "summary": f"Payment completed for {devise} {montant} {devise}",
        "resource": ressource,
        "links": [],
    }


def abonnement_active(courriel: str = "abonne@exemple.com", montant: str = "29.99",
                      devise: str = "CAD", abonnement_id: str = "I-BW452GLLEP1G",
                      evenement_id: str | None = None, heure_paiement: str = "2026-09-03T14:30:00Z") -> dict:
    """BILLING.SUBSCRIPTION.ACTIVATED — abonnement récurrent démarré ou reconduit."""
    return {
        "id": evenement_id or _identifiant_evenement(),
        "event_version": "1.0",
        "create_time": "2026-09-03T14:30:05.000Z",
        "resource_type": "subscription",
        "resource_version": "2.0",
        "event_type": "BILLING.SUBSCRIPTION.ACTIVATED",
        "summary": "Subscription activated",
        "resource": {
            "id": abonnement_id,
            "plan_id": "P-5ML4271244454362WXNWU5NQ",
            "status": "ACTIVE",
            "status_update_time": heure_paiement,
            "start_time": "2026-09-03T14:30:00Z",
            "quantity": "1",
            "subscriber": {
                "email_address": courriel,
                "payer_id": "2J6XKMPR4TYUL",
                "name": {"given_name": "Marie", "surname": "Gagnon"},
                "shipping_address": {"address": {"country_code": "CA"}},
            },
            "billing_info": {
                "outstanding_balance": {"currency_code": devise, "value": "0.00"},
                "cycle_executions": [
                    {"tenure_type": "REGULAR", "sequence": 1, "cycles_completed": 1,
                     "cycles_remaining": 0, "total_cycles": 0}
                ],
                "last_payment": {"amount": {"currency_code": devise, "value": montant}, "time": heure_paiement},
                "next_billing_time": "2026-10-03T14:30:00Z",
                "failed_payments_count": 0,
            },
            "create_time": "2026-09-03T14:29:55Z",
            "update_time": heure_paiement,
            "links": [],
        },
        "links": [],
    }


def _evenement_abonnement(type_evenement: str, courriel: str, abonnement_id: str,
                          statut: str, evenement_id: str | None = None) -> dict:
    return {
        "id": evenement_id or _identifiant_evenement(),
        "event_version": "1.0",
        "create_time": "2026-10-03T09:00:00.000Z",
        "resource_type": "subscription",
        "resource_version": "2.0",
        "event_type": type_evenement,
        "summary": type_evenement.replace(".", " ").lower(),
        "resource": {
            "id": abonnement_id,
            "plan_id": "P-5ML4271244454362WXNWU5NQ",
            "status": statut,
            "status_update_time": "2026-10-03T09:00:00Z",
            "subscriber": {"email_address": courriel, "payer_id": "2J6XKMPR4TYUL"},
            "billing_info": {"failed_payments_count": 1 if statut == "ACTIVE" else 0},
            "update_time": "2026-10-03T09:00:00Z",
            "links": [],
        },
        "links": [],
    }


def abonnement_annule(courriel: str = "abonne@exemple.com", abonnement_id: str = "I-BW452GLLEP1G",
                      evenement_id: str | None = None) -> dict:
    return _evenement_abonnement("BILLING.SUBSCRIPTION.CANCELLED", courriel, abonnement_id, "CANCELLED", evenement_id)


def abonnement_expire(courriel: str = "abonne@exemple.com", abonnement_id: str = "I-BW452GLLEP1G",
                      evenement_id: str | None = None) -> dict:
    return _evenement_abonnement("BILLING.SUBSCRIPTION.EXPIRED", courriel, abonnement_id, "EXPIRED", evenement_id)


def paiement_echoue(courriel: str = "abonne@exemple.com", abonnement_id: str = "I-BW452GLLEP1G",
                    evenement_id: str | None = None) -> dict:
    return _evenement_abonnement("BILLING.SUBSCRIPTION.PAYMENT.FAILED", courriel, abonnement_id, "ACTIVE", evenement_id)


def evenement_non_traite(evenement_id: str | None = None) -> dict:
    """Un type que le service ne traite pas : il doit être journalisé puis ignoré."""
    return {
        "id": evenement_id or _identifiant_evenement(),
        "event_type": "CHECKOUT.ORDER.APPROVED",
        "resource_type": "checkout-order",
        "create_time": "2026-09-03T14:22:00.000Z",
        "resource": {"id": "5O190127TN364715T", "status": "APPROVED",
                     "payer": {"email_address": "client@exemple.com"}},
        "links": [],
    }
