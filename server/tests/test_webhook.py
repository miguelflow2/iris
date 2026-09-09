"""Le webhook PayPal : authentification, idempotence, montants, cycle de vie de l'abonnement."""
from __future__ import annotations

from datetime import date

import charges_paypal as charges
from conftest import entetes_paypal, plans_application, poster_webhook

from licences import cles
from licences.config import SECRET_HISTORIQUE


# ============================================================ paiement reconnu
def test_paiement_valide_cree_labonnement_et_une_cle_utilisable(client, base):
    reponse = poster_webhook(client, charges.capture_completee("nouveau@exemple.com", "29.99"))
    assert reponse.status_code == 200
    assert reponse.json()["resultat"] == "active"

    ligne = base.abonnement("nouveau@exemple.com")
    assert ligne is not None
    assert ligne["plan"] == "premium"
    assert ligne["statut"] == "actif"
    assert date.fromisoformat(ligne["expire_le"]) > date.today()

    # La clé stockée doit être acceptée par le VRAI verify_key de l'application.
    plans = plans_application()
    verifiee = plans.verify_key(ligne["derniere_cle"])
    assert verifiee is not None and verifiee["plan"] == "premium" and verifiee["expired"] is False


def test_la_cle_part_par_courriel(client, config):
    poster_webhook(client, charges.capture_completee("recoit@exemple.com", "19.99"))
    fichiers = list(config.dossier_sortie.glob("*.eml"))
    assert fichiers, "aucun courriel déposé alors que SMTP n'est pas configuré"
    contenu = fichiers[0].read_text(encoding="utf-8")
    assert "recoit@exemple.com" in contenu
    assert "IRIS-" in contenu


def test_le_webhook_ne_renvoie_jamais_la_cle_a_paypal(client):
    reponse = poster_webhook(client, charges.capture_completee("discret@exemple.com", "29.99"))
    assert "cle" not in reponse.json()
    assert "IRIS-" not in reponse.text


def test_courriel_dans_custom_id_reconnu(client, base):
    """Cas réel : PayPal ne met pas toujours l'adresse du payeur dans la capture."""
    poster_webhook(client, charges.capture_completee("via-custom@exemple.com", "19.99", courriel_dans_custom=True))
    ligne = base.abonnement("via-custom@exemple.com")
    assert ligne is not None and ligne["plan"] == "pro"


def test_chaque_prix_active_le_bon_plan(client, base):
    for montant, plan, courriel in (("19.99", "pro", "e@exemple.com"),
                                    ("29.99", "premium", "p@exemple.com"),
                                    ("99.99", "entreprise", "u@exemple.com")):
        poster_webhook(client, charges.capture_completee(courriel, montant, capture_id=f"CAP-{plan}"))
        assert base.abonnement(courriel)["plan"] == plan


def test_lachat_des_lunettes_nactive_aucun_abonnement(client, base):
    """250 $, c'est du matériel. Le confondre avec un abonnement offrirait un mois à chaque client."""
    poster_webhook(client, charges.capture_completee("lunettes@exemple.com", "250.00", capture_id="CAP-LUNETTES"))
    assert base.abonnement("lunettes@exemple.com") is None


def test_ecart_de_quelques_cents_tolere(client, base):
    """Change, arrondis : 29,96 $ reste un Premium."""
    poster_webhook(client, charges.capture_completee("centimes@exemple.com", "29.96", capture_id="CAP-CENTS"))
    assert base.abonnement("centimes@exemple.com")["plan"] == "premium"


# ============================================================ idempotence
def test_meme_transaction_rejouee_ne_prolonge_rien(client, base):
    charge = charges.capture_completee("rejeu@exemple.com", "29.99", capture_id="CAP-REJEU")
    premiere = poster_webhook(client, charge)
    assert premiere.json()["resultat"] == "active"
    expiration = base.abonnement("rejeu@exemple.com")["expire_le"]

    # PayPal relance le même événement (c'est son comportement normal en cas de doute).
    seconde = poster_webhook(client, charge)
    assert seconde.status_code == 200
    assert seconde.json()["resultat"] == "deja_traite"
    assert base.abonnement("rejeu@exemple.com")["expire_le"] == expiration

    # Et même avec un nouvel identifiant d'événement, la transaction reste unique.
    rejeu = charges.capture_completee("rejeu@exemple.com", "29.99", capture_id="CAP-REJEU",
                                      evenement_id="WH-AUTRE-IDENTIFIANT")
    troisieme = poster_webhook(client, rejeu)
    assert troisieme.json()["resultat"] == "deja_traite"
    assert base.abonnement("rejeu@exemple.com")["expire_le"] == expiration
    assert base.un("SELECT COUNT(*) n FROM evenements WHERE courriel='rejeu@exemple.com'")["n"] == 1


def test_la_reservation_est_posee_avant_tout_credit(service, base):
    """La déduplication est une écriture atomique, pas un « SELECT puis INSERT ».

    On le prouve en réservant à la main : le traitement du même événement doit alors être
    refusé, donc aucun abonnement ne peut être créé une seconde fois.
    """
    charge = charges.capture_completee("atomique@exemple.com", "29.99", capture_id="CAP-ATOM")
    identifiant = base.reserver_evenement(charge["id"], "CAP-ATOM", charge["event_type"])
    assert identifiant is not None
    # Une deuxième réservation du même paiement échoue au niveau de la base elle-même.
    assert base.reserver_evenement(charge["id"], "CAP-ATOM", charge["event_type"]) is None
    assert service.traiter(charge)["resultat"] == "deja_traite"
    assert base.abonnement("atomique@exemple.com") is None


def test_un_echec_inattendu_libere_la_reservation(service, base, monkeypatch):
    """Si le traitement casse, PayPal doit pouvoir relancer l'événement utilement."""
    charge = charges.capture_completee("panne-interne@exemple.com", "29.99", capture_id="CAP-PANNE")

    def exploser(*args, **kwargs):
        raise RuntimeError("panne simulée")

    monkeypatch.setattr(service.base, "enregistrer_abonnement", exploser)
    try:
        service.traiter(charge)
    except RuntimeError:
        pass
    assert base.un("SELECT COUNT(*) n FROM evenements")["n"] == 0, "la réservation aurait dû être libérée"

    # La relance de PayPal aboutit maintenant que la panne est passée.
    monkeypatch.undo()
    assert service.traiter(charge)["resultat"] == "active"
    assert base.abonnement("panne-interne@exemple.com")["plan"] == "premium"


def test_deux_paiements_distincts_cumulent_bien(client, base):
    poster_webhook(client, charges.capture_completee("fidele@exemple.com", "29.99", capture_id="CAP-A"))
    premiere_fin = base.abonnement("fidele@exemple.com")["expire_le"]
    poster_webhook(client, charges.capture_completee("fidele@exemple.com", "29.99", capture_id="CAP-B"))
    seconde_fin = base.abonnement("fidele@exemple.com")["expire_le"]
    assert seconde_fin > premiere_fin
    assert seconde_fin == cles.prolonger(premiere_fin, 1)


# ============================================================ authentification
def test_signature_invalide_refusee_et_rien_en_base(client, base):
    reponse = poster_webhook(client, charges.capture_completee("pirate@exemple.com", "99.99"),
                             signature="signature-fabriquee")
    assert reponse.status_code == 400
    assert base.abonnement("pirate@exemple.com") is None
    assert base.un("SELECT COUNT(*) n FROM evenements")["n"] == 0


def test_entetes_de_signature_manquants_refuses(client, base):
    reponse = poster_webhook(client, charges.capture_completee("sansentetes@exemple.com", "99.99"),
                             entetes_complets=False)
    assert reponse.status_code == 400
    assert base.abonnement("sansentetes@exemple.com") is None


def test_paypal_injoignable_repond_503_pour_provoquer_une_relance(fabrique_client, base):
    """Une panne réseau n'est pas une signature invalide : PayPal doit pouvoir réessayer."""
    client = fabrique_client(erreur_reseau=True)
    reponse = poster_webhook(client, charges.capture_completee("panne@exemple.com", "29.99"))
    assert reponse.status_code == 503
    assert base.abonnement("panne@exemple.com") is None


def test_corps_illisible_refuse(client):
    reponse = client.post("/paypal/webhook", content=b"ceci n'est pas du JSON",
                          headers=entetes_paypal())
    assert reponse.status_code == 400


def test_sans_identifiants_paypal_le_webhook_est_refuse(config, base):
    """Un service mal configuré doit refuser, pas croire son appelant sur parole."""
    from fastapi.testclient import TestClient
    from licences.app import creer_app
    config.paypal_client_id = config.paypal_secret = config.paypal_webhook_id = ""
    with TestClient(creer_app(cfg=config, base=base, client_paypal=None)) as client:
        reponse = poster_webhook(client, charges.capture_completee("nul@exemple.com", "29.99"))
    assert reponse.status_code == 400
    assert base.abonnement("nul@exemple.com") is None


def test_mode_developpement_saute_la_verification(fabrique_client, base):
    """Le mode explicite de développement permet de tester sans compte PayPal."""
    client = fabrique_client(verification="echec", mode_dev_sans_verification=True)
    reponse = poster_webhook(client, charges.capture_completee("dev@exemple.com", "29.99"),
                             signature="peu-importe")
    assert reponse.status_code == 200
    assert base.abonnement("dev@exemple.com")["plan"] == "premium"


def test_mode_developpement_interdit_en_production():
    """Le garde-fou : impossible de démarrer en production sans vérifier les signatures."""
    import pytest
    from licences.config import Config, ConfigurationInvalide, valider
    cfg = Config(environnement="production", mode_dev_sans_verification=True,
                 paypal_client_id="a", paypal_secret="b", paypal_webhook_id="c")
    with pytest.raises(ConfigurationInvalide):
        valider(cfg)


def test_production_stripe_seul_demarre():
    """Nouvelle règle : en production, Stripe configuré suffit — le démarrage est autorisé sans PayPal."""
    from licences.config import Config, valider
    cfg = Config(environnement="production",
                 stripe_secret_key="sk_live_xxx", stripe_webhook_secret="whsec_xxx")
    # Ne doit lever aucune exception : un seul fournisseur (Stripe) est configuré.
    valider(cfg)


def test_production_paypal_seul_demarre():
    """Symétrique : PayPal seul configuré autorise toujours le démarrage, sans Stripe."""
    from licences.config import Config, valider
    cfg = Config(environnement="production",
                 paypal_client_id="a", paypal_secret="b", paypal_webhook_id="c")
    valider(cfg)


def test_production_sans_aucun_fournisseur_echoue():
    """En production, si NI PayPal NI Stripe n'est configuré, le service refuse de démarrer."""
    import pytest
    from licences.config import Config, ConfigurationInvalide, valider
    cfg = Config(environnement="production")
    with pytest.raises(ConfigurationInvalide):
        valider(cfg)


# ============================================================ montants non reconnus
def test_montant_inconnu_ne_active_rien_et_part_en_manuel(client, base):
    reponse = poster_webhook(client, charges.capture_completee("bizarre@exemple.com", "42.00",
                                                               capture_id="CAP-42"))
    assert reponse.status_code == 200
    assert reponse.json()["resultat"] == "manuel"
    assert base.abonnement("bizarre@exemple.com") is None, "aucun plan ne doit être offert"
    manuels = base.manuels()
    assert len(manuels) == 1
    assert "42.0" in manuels[0]["raison"]


def test_devise_non_prevue_part_en_manuel(client, base):
    """19,99 USD n'est pas 19,99 CAD : on ne devine pas."""
    poster_webhook(client, charges.capture_completee("usd@exemple.com", "19.99", devise="USD",
                                                     capture_id="CAP-USD"))
    assert base.abonnement("usd@exemple.com") is None
    assert len(base.manuels()) == 1


def test_paiement_sans_courriel_part_en_manuel(client, base):
    charge = charges.capture_completee("client@exemple.com", "29.99", capture_id="CAP-ANONYME")
    charge["resource"].pop("payer", None)  # PayPal ne transmet rien d'exploitable
    reponse = poster_webhook(client, charge)
    assert reponse.json()["resultat"] == "manuel"
    assert base.un("SELECT COUNT(*) n FROM abonnements")["n"] == 0


def test_alerte_envoyee_pour_un_paiement_a_traiter(client, config):
    poster_webhook(client, charges.capture_completee("alerte@exemple.com", "7.50", capture_id="CAP-750"))
    depots = [f.read_text(encoding="utf-8") for f in config.dossier_sortie.glob("*.eml")]
    assert any("traiter manuellement" in d for d in depots)


# ============================================================ abonnements récurrents
def test_abonnement_active(client, base):
    poster_webhook(client, charges.abonnement_active("abonne@exemple.com", "29.99"))
    ligne = base.abonnement("abonne@exemple.com")
    assert ligne["plan"] == "premium"
    assert ligne["statut"] == "actif"
    assert ligne["abonnement_paypal"] == "I-BW452GLLEP1G"


def test_annulation_change_le_statut_sans_couper_le_mois_paye(client, base):
    poster_webhook(client, charges.abonnement_active("annule@exemple.com", "29.99",
                                                     abonnement_id="I-ANNULE"))
    expiration = base.abonnement("annule@exemple.com")["expire_le"]

    reponse = poster_webhook(client, charges.abonnement_annule("annule@exemple.com", "I-ANNULE"))
    assert reponse.json()["resultat"] == "annule"
    ligne = base.abonnement("annule@exemple.com")
    assert ligne["statut"] == "annule"
    assert ligne["expire_le"] == expiration, "le client garde ce qu'il a payé"

    # L'accès reste ouvert jusqu'à l'échéance, mais rien ne sera renouvelé.
    licence = client.get("/api/licence", params={"email": "annule@exemple.com"}).json()
    assert licence["actif"] is True


def test_expiration_coupe_lacces(client, base):
    poster_webhook(client, charges.abonnement_active("fini@exemple.com", "29.99", abonnement_id="I-FINI"))
    poster_webhook(client, charges.abonnement_expire("fini@exemple.com", "I-FINI"))
    assert base.abonnement("fini@exemple.com")["statut"] == "expire"
    licence = client.get("/api/licence", params={"email": "fini@exemple.com"}).json()
    assert licence == {"actif": False, "plan": "gratuit", "expire_le": None, "cle": None}


def test_echec_de_paiement_signale_sans_couper_immediatement(client, base):
    poster_webhook(client, charges.abonnement_active("impaye@exemple.com", "29.99", abonnement_id="I-IMPAYE"))
    reponse = poster_webhook(client, charges.paiement_echoue("impaye@exemple.com", "I-IMPAYE"))
    assert reponse.json()["resultat"] == "paiement_echoue"
    ligne = base.abonnement("impaye@exemple.com")
    assert ligne["statut"] == "paiement_echoue"
    assert client.get("/api/licence", params={"email": "impaye@exemple.com"}).json()["actif"] is True


def test_annulation_dun_abonnement_inconnu_est_ignoree(client, base):
    reponse = poster_webhook(client, charges.abonnement_annule("fantome@exemple.com", "I-FANTOME"))
    assert reponse.status_code == 200
    assert reponse.json()["resultat"] == "inconnu"
    assert base.abonnement("fantome@exemple.com") is None


def test_evenement_non_traite_est_journalise_puis_ignore(client, base):
    reponse = poster_webhook(client, charges.evenement_non_traite())
    assert reponse.status_code == 200
    assert reponse.json()["resultat"] == "ignore"
    assert base.un("SELECT COUNT(*) n FROM abonnements")["n"] == 0
    assert base.un("SELECT resultat FROM evenements ORDER BY id DESC")["resultat"] == "ignore"


def test_changement_de_plan_repart_de_zero(client, base):
    """Un Essentiel qui passe Ultra ne doit pas hériter des mois de l'ancien plan."""
    poster_webhook(client, charges.capture_completee("montee@exemple.com", "19.99", capture_id="CAP-E"))
    poster_webhook(client, charges.capture_completee("montee@exemple.com", "99.99", capture_id="CAP-U"))
    ligne = base.abonnement("montee@exemple.com")
    assert ligne["plan"] == "entreprise"
    assert ligne["expire_le"] == cles.prolonger(None, 1)


def test_la_cle_est_bien_signee_avec_le_secret_configure(client, base):
    poster_webhook(client, charges.capture_completee("signee@exemple.com", "29.99", capture_id="CAP-SIG"))
    cle = base.abonnement("signee@exemple.com")["derniere_cle"]
    assert cles.verifier_cle(cle, SECRET_HISTORIQUE) is not None
    assert cles.verifier_cle(cle, b"secret-different") is None
