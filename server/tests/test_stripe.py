"""Le webhook Stripe : signature locale, idempotence, montants/prix, cycle de vie, et Checkout.

Aucune vraie clé, aucun appel réseau. La signature est calculée localement ; la création de session
Checkout passe par un transport httpx simulé.
"""
from __future__ import annotations

import json
from datetime import date

import charges_stripe as charges
from conftest import (STRIPE_WEBHOOK_SECRET, poster_webhook_stripe, signer_stripe,
                      transport_stripe)

from licences import cles, stripe_paiement
from licences.config import SECRET_HISTORIQUE


# ============================================================ signature (unité, sans réseau)
def test_signature_valide_acceptee():
    corps = json.dumps({"id": "evt_FACTICE", "type": "checkout.session.completed"}).encode("utf-8")
    entete = signer_stripe(corps, STRIPE_WEBHOOK_SECRET)
    assert stripe_paiement.verifier_signature(entete, corps, STRIPE_WEBHOOK_SECRET) is True


def test_signature_refuse_un_corps_altere():
    corps = json.dumps({"id": "evt_FACTICE", "montant": 1999}).encode("utf-8")
    entete = signer_stripe(corps, STRIPE_WEBHOOK_SECRET)
    corps_altere = json.dumps({"id": "evt_FACTICE", "montant": 999999}).encode("utf-8")
    assert stripe_paiement.verifier_signature(entete, corps_altere, STRIPE_WEBHOOK_SECRET) is False


def test_signature_refuse_un_mauvais_secret():
    corps = b'{"id":"evt_FACTICE"}'
    entete = signer_stripe(corps, STRIPE_WEBHOOK_SECRET)
    assert stripe_paiement.verifier_signature(entete, corps, "whsec_un_autre_secret") is False


def test_signature_refuse_un_horodatage_perime():
    corps = b'{"id":"evt_FACTICE"}'
    vieux = signer_stripe(corps, STRIPE_WEBHOOK_SECRET, horodatage=1_600_000_000)  # 2020
    assert stripe_paiement.verifier_signature(vieux, corps, STRIPE_WEBHOOK_SECRET, tolerance=300) is False
    # Mais sans tolérance, la seule cryptographie suffit : la même signature est acceptée.
    assert stripe_paiement.verifier_signature(vieux, corps, STRIPE_WEBHOOK_SECRET, tolerance=0) is True


def test_signature_refuse_un_entete_incomplet():
    corps = b'{"id":"evt_FACTICE"}'
    assert stripe_paiement.verifier_signature("", corps, STRIPE_WEBHOOK_SECRET) is False
    assert stripe_paiement.verifier_signature("t=123", corps, STRIPE_WEBHOOK_SECRET) is False
    assert stripe_paiement.verifier_signature("v1=abc", corps, STRIPE_WEBHOOK_SECRET) is False


# ============================================================ webhook : authentification
def test_webhook_signature_invalide_refuse_et_rien_en_base(client, base):
    reponse = poster_webhook_stripe(client, charges.checkout_complete("pirate@exemple.com"),
                                    signature_override="t=9999999999,v1=fausse_signature")
    assert reponse.status_code == 400
    assert base.abonnement("pirate@exemple.com") is None
    assert base.un("SELECT COUNT(*) n FROM evenements")["n"] == 0


def test_webhook_sans_secret_configure_refuse(config, base):
    from fastapi.testclient import TestClient
    from licences.app import creer_app
    config.stripe_webhook_secret = ""
    with TestClient(creer_app(cfg=config, base=base, client_paypal=None)) as client:
        reponse = poster_webhook_stripe(client, charges.checkout_complete("nul@exemple.com"))
    assert reponse.status_code == 400
    assert base.abonnement("nul@exemple.com") is None


def test_mode_developpement_saute_la_verification_stripe(fabrique_client, base):
    client = fabrique_client(mode_dev_sans_verification=True)
    reponse = poster_webhook_stripe(client, charges.checkout_complete("dev@exemple.com"),
                                    signature_override="t=1,v1=peu_importe")
    assert reponse.status_code == 200
    assert base.abonnement("dev@exemple.com")["plan"] == "pro"


# ============================================================ checkout.session.completed → crédit
def test_checkout_complete_avec_prix_connu_active_le_plan(client, base):
    # Montant qui, seul, pointerait vers « entreprise » ; mais l'ID de prix dit « pro ».
    # L'ID de prix doit l'emporter : c'est la source de vérité.
    reponse = poster_webhook_stripe(client, charges.checkout_complete(
        "nouveau@exemple.com", prix="price_FACTICE_pro", montant_cents=9999))
    assert reponse.status_code == 200
    assert reponse.json()["resultat"] == "active"

    ligne = base.abonnement("nouveau@exemple.com")
    assert ligne is not None
    assert ligne["plan"] == "pro", "l'ID de prix Stripe doit primer sur le montant"
    assert ligne["statut"] == "actif"
    assert ligne["abonnement_paypal"] == "sub_FACTICE_001"  # colonne « abonnement externe »
    assert date.fromisoformat(ligne["expire_le"]) > date.today()

    # La clé stockée doit être acceptée par le VRAI verify_key de l'application.
    from conftest import plans_application
    verifiee = plans_application().verify_key(ligne["derniere_cle"])
    assert verifiee is not None and verifiee["plan"] == "pro" and verifiee["expired"] is False


def test_checkout_sans_line_items_se_rabat_sur_le_montant(client, base):
    """Sans ID de prix développé, le montant (en centimes) doit suffire à reconnaître le plan."""
    poster_webhook_stripe(client, charges.checkout_complete(
        "parmontant@exemple.com", montant_cents=2999, avec_line_items=False))
    ligne = base.abonnement("parmontant@exemple.com")
    assert ligne is not None and ligne["plan"] == "premium"


def test_checkout_non_payee_ne_credite_rien(client, base):
    reponse = poster_webhook_stripe(client, charges.checkout_complete(
        "enattente@exemple.com", payment_status="unpaid"))
    assert reponse.status_code == 200
    assert reponse.json()["resultat"] == "ignore"
    assert base.abonnement("enattente@exemple.com") is None


def test_la_cle_part_par_courriel(client, config):
    poster_webhook_stripe(client, charges.checkout_complete("recoit@exemple.com", prix="price_FACTICE_pro"))
    fichiers = list(config.dossier_sortie.glob("*.eml"))
    assert fichiers, "aucun courriel déposé alors que SMTP n'est pas configuré"
    contenu = fichiers[0].read_text(encoding="utf-8")
    assert "recoit@exemple.com" in contenu and "IRIS-" in contenu


def test_le_webhook_ne_renvoie_jamais_la_cle_a_stripe(client):
    reponse = poster_webhook_stripe(client, charges.checkout_complete("discret@exemple.com"))
    assert "cle" not in reponse.json()
    assert "IRIS-" not in reponse.text


def test_courriel_dans_metadata_reconnu(client, base):
    poster_webhook_stripe(client, charges.checkout_complete(
        "via-metadata@exemple.com", prix="price_FACTICE_entreprise", courriel_dans_metadata=True))
    ligne = base.abonnement("via-metadata@exemple.com")
    assert ligne is not None and ligne["plan"] == "entreprise"


# ============================================================ renouvellement
def test_invoice_paid_prolonge_labonnement(client, base):
    poster_webhook_stripe(client, charges.checkout_complete(
        "fidele@exemple.com", prix="price_FACTICE_premium", montant_cents=2999))
    premiere_fin = base.abonnement("fidele@exemple.com")["expire_le"]

    poster_webhook_stripe(client, charges.facture_payee(
        "fidele@exemple.com", prix="price_FACTICE_premium", type_evenement="invoice.paid"))
    seconde_fin = base.abonnement("fidele@exemple.com")["expire_le"]
    assert seconde_fin > premiere_fin
    assert seconde_fin == cles.prolonger(premiere_fin, 1)


def test_invoice_payment_succeeded_credite_aussi(client, base):
    poster_webhook_stripe(client, charges.facture_payee(
        "renouvelle@exemple.com", prix="price_FACTICE_pro", montant_cents=1999,
        type_evenement="invoice.payment_succeeded"))
    assert base.abonnement("renouvelle@exemple.com")["plan"] == "pro"


# ============================================================ cycle de vie
def test_subscription_deleted_annule_le_statut(client, base):
    poster_webhook_stripe(client, charges.checkout_complete(
        "annule@exemple.com", prix="price_FACTICE_premium", abonnement="sub_ANNULE"))
    expiration = base.abonnement("annule@exemple.com")["expire_le"]

    reponse = poster_webhook_stripe(client, charges.abonnement_supprime(abonnement="sub_ANNULE"))
    assert reponse.json()["resultat"] == "annule"
    ligne = base.abonnement("annule@exemple.com")
    assert ligne["statut"] == "annule"
    assert ligne["expire_le"] == expiration, "le client garde ce qu'il a payé"
    # L'accès reste ouvert jusqu'à l'échéance.
    assert client.get("/api/licence", params={"email": "annule@exemple.com"}).json()["actif"] is True


def test_payment_failed_signale_sans_couper_immediatement(client, base):
    poster_webhook_stripe(client, charges.checkout_complete(
        "impaye@exemple.com", prix="price_FACTICE_premium", abonnement="sub_IMPAYE"))
    reponse = poster_webhook_stripe(client, charges.paiement_echoue("impaye@exemple.com", "sub_IMPAYE"))
    assert reponse.json()["resultat"] == "paiement_echoue"
    assert base.abonnement("impaye@exemple.com")["statut"] == "paiement_echoue"
    assert client.get("/api/licence", params={"email": "impaye@exemple.com"}).json()["actif"] is True


def test_annulation_dun_abonnement_inconnu_est_ignoree(client, base):
    reponse = poster_webhook_stripe(client, charges.abonnement_supprime(abonnement="sub_FANTOME"))
    assert reponse.status_code == 200
    assert reponse.json()["resultat"] == "inconnu"


def test_evenement_non_traite_est_journalise_puis_ignore(client, base):
    reponse = poster_webhook_stripe(client, charges.evenement_non_traite())
    assert reponse.status_code == 200
    assert reponse.json()["resultat"] == "ignore"
    assert base.un("SELECT COUNT(*) n FROM abonnements")["n"] == 0
    assert base.un("SELECT resultat FROM evenements ORDER BY id DESC")["resultat"] == "ignore"


# ============================================================ idempotence
def test_meme_evenement_rejoue_ne_credite_pas_deux_fois(client, base):
    charge = charges.checkout_complete("rejeu@exemple.com", prix="price_FACTICE_pro",
                                       evenement_id="evt_FACTICE_REJEU")
    premiere = poster_webhook_stripe(client, charge)
    assert premiere.json()["resultat"] == "active"
    expiration = base.abonnement("rejeu@exemple.com")["expire_le"]

    seconde = poster_webhook_stripe(client, charge)
    assert seconde.status_code == 200
    assert seconde.json()["resultat"] == "deja_traite"
    assert base.abonnement("rejeu@exemple.com")["expire_le"] == expiration
    assert base.un("SELECT COUNT(*) n FROM evenements WHERE courriel='rejeu@exemple.com'")["n"] == 1


def test_un_echec_inattendu_libere_la_reservation(service, base, monkeypatch):
    charge = charges.checkout_complete("panne@exemple.com", prix="price_FACTICE_pro",
                                       evenement_id="evt_FACTICE_PANNE")

    def exploser(*args, **kwargs):
        raise RuntimeError("panne simulée")

    monkeypatch.setattr(service.base, "enregistrer_abonnement", exploser)
    try:
        service.traiter_stripe(charge)
    except RuntimeError:
        pass
    assert base.un("SELECT COUNT(*) n FROM evenements")["n"] == 0, "la réservation aurait dû être libérée"

    monkeypatch.undo()
    assert service.traiter_stripe(charge)["resultat"] == "active"
    assert base.abonnement("panne@exemple.com")["plan"] == "pro"


# ============================================================ montants non reconnus
def test_montant_et_prix_inconnus_partent_en_manuel(client, base):
    """Ni ID de prix connu, ni montant reconnu : aucun plan activé, dossier manuel."""
    reponse = poster_webhook_stripe(client, charges.checkout_complete(
        "bizarre@exemple.com", prix="price_INCONNU", montant_cents=4200, avec_line_items=True))
    assert reponse.status_code == 200
    assert reponse.json()["resultat"] == "manuel"
    assert base.abonnement("bizarre@exemple.com") is None
    manuels = base.manuels()
    assert len(manuels) == 1 and "42.0" in manuels[0]["raison"]


def test_devise_non_prevue_part_en_manuel(client, base):
    """19,99 USD (sans ID de prix connu) n'est pas 19,99 CAD : on ne devine pas."""
    poster_webhook_stripe(client, charges.checkout_complete(
        "usd@exemple.com", prix="price_INCONNU", montant_cents=1999, devise="usd"))
    assert base.abonnement("usd@exemple.com") is None
    assert len(base.manuels()) == 1


def test_paiement_sans_courriel_part_en_manuel(client, base):
    charge = charges.checkout_complete("client@exemple.com", prix="price_FACTICE_pro")
    charge["data"]["object"].pop("customer_details", None)
    charge["data"]["object"].pop("metadata", None)
    reponse = poster_webhook_stripe(client, charge)
    assert reponse.json()["resultat"] == "manuel"
    assert base.un("SELECT COUNT(*) n FROM abonnements")["n"] == 0


# ============================================================ montant : conversion centimes -> dollars
def test_conversion_centimes_vers_dollars():
    montant, devise = stripe_paiement.montant_de(charges.checkout_complete(montant_cents=2999, devise="cad"))
    assert montant == 29.99
    assert devise == "CAD"


# ============================================================ création de session Checkout
def test_creation_session_checkout_renvoie_une_url(fabrique_client):
    client = fabrique_client(transport_stripe=transport_stripe())
    reponse = client.post("/stripe/checkout", json={"plan": "pro", "courriel": "Client@Exemple.com"})
    assert reponse.status_code == 200
    assert reponse.json()["url"].startswith("https://checkout.stripe.com")


def test_checkout_refuse_un_plan_inconnu(fabrique_client):
    client = fabrique_client(transport_stripe=transport_stripe())
    assert client.post("/stripe/checkout", json={"plan": "platine", "courriel": "a@b.com"}).status_code == 400
    assert client.post("/stripe/checkout", json={"plan": "pro", "courriel": "pas-une-adresse"}).status_code == 400


def test_checkout_remonte_une_panne_stripe_en_502(fabrique_client):
    client = fabrique_client(transport_stripe=transport_stripe(erreur_reseau=True))
    reponse = client.post("/stripe/checkout", json={"plan": "premium", "courriel": "a@b.com"})
    assert reponse.status_code == 502


# ============================================================ santé
def test_sante_expose_letat_stripe_sans_secret(client):
    donnees = client.get("/sante").json()
    assert donnees["stripe"]["configure"] is True
    assert donnees["stripe"]["verification_signature"] is True
    assert set(donnees["stripe"]["prix_configures"]) == {"pro", "premium", "entreprise"}
    # Aucun secret ne doit fuir par cette route publique.
    assert "secret" not in client.get("/sante").text.lower()
    assert "sk_test" not in client.get("/sante").text.lower()
