"""Les points d'entrée qu'IRIS et Miguel utilisent : /api/licence, /api/licence/verifier,
/sante et la page d'administration."""
from __future__ import annotations

from datetime import date, timedelta

import charges_paypal as charges
from conftest import JETON_ADMIN, poster_webhook

from licences import cles
from licences.config import SECRET_HISTORIQUE


# ============================================================ /sante
def test_sante(client):
    donnees = client.get("/sante").json()
    assert donnees["etat"] == "ok"
    assert donnees["paypal"]["verification_signature"] is True
    assert donnees["abonnements_actifs"] == 0
    # Aucun secret ne doit fuir par cette route publique.
    assert "secret" not in client.get("/sante").text.lower()


# ============================================================ /api/licence
def test_licence_dun_courriel_inconnu_est_neutre(client):
    reponse = client.get("/api/licence", params={"email": "personne@nulle-part.com"})
    assert reponse.status_code == 200
    assert reponse.json() == {"actif": False, "plan": "gratuit", "expire_le": None, "cle": None}


def test_licence_inconnue_indiscernable_dune_licence_expiree(client, base):
    """Anti-énumération : la réponse doit être strictement identique dans les deux cas."""
    hier = (date.today() - timedelta(days=1)).isoformat()
    base.enregistrer_abonnement("expire@exemple.com", "pro", hier, "actif",
                                derniere_cle=cles.faire_cle("pro", hier, "expire@exemple.com", SECRET_HISTORIQUE))
    inconnue = client.get("/api/licence", params={"email": "jamais-vu@exemple.com"}).json()
    expiree = client.get("/api/licence", params={"email": "expire@exemple.com"}).json()
    assert inconnue == expiree == {"actif": False, "plan": "gratuit", "expire_le": None, "cle": None}


def test_licence_active_renvoie_le_plan_et_la_cle(client, base):
    poster_webhook(client, charges.capture_completee("actif@exemple.com", "99.99", capture_id="CAP-ACTIF"))
    donnees = client.get("/api/licence", params={"email": "actif@exemple.com"}).json()
    assert donnees["actif"] is True
    assert donnees["plan"] == "entreprise"
    assert donnees["cle"].startswith("IRIS-")
    assert cles.verifier_cle(donnees["cle"], SECRET_HISTORIQUE)["plan"] == "entreprise"
    # Rien de plus que le nécessaire : ni identifiant PayPal, ni montant, ni historique.
    assert set(donnees) == {"actif", "plan", "expire_le", "cle"}


def test_licence_insensible_a_la_casse_et_aux_espaces(client, base):
    poster_webhook(client, charges.capture_completee("Casse@Exemple.com", "29.99", capture_id="CAP-CASSE"))
    donnees = client.get("/api/licence", params={"email": "  CASSE@exemple.COM "}).json()
    assert donnees["actif"] is True and donnees["plan"] == "premium"


def test_licence_sans_parametre_reste_neutre(client):
    assert client.get("/api/licence").json()["actif"] is False
    assert client.get("/api/licence", params={"email": "pas-une-adresse"}).json()["actif"] is False


def test_limitation_de_debit_sur_la_licence(fabrique_client):
    """La limite est ce qui rend l'énumération des adresses courriel impraticable."""
    client = fabrique_client(limite_licence_requetes=5, limite_fenetre=60)
    codes = [client.get("/api/licence", params={"email": f"essai{n}@exemple.com"}).status_code
             for n in range(8)]
    assert codes[:5] == [200] * 5
    assert codes[5:] == [429] * 3
    refus = client.get("/api/licence", params={"email": "encore@exemple.com"})
    assert refus.headers.get("Retry-After") == "60"
    assert "Trop de requêtes" in refus.json()["message"]


# ============================================================ /api/licence/verifier
def test_verification_dune_cle_valide(client):
    cle = cles.faire_cle("pro", "2029-01-01", "client@exemple.com", SECRET_HISTORIQUE)
    donnees = client.post("/api/licence/verifier", json={"cle": cle}).json()
    assert donnees == {"valide": True, "plan": "pro", "expire_le": "2029-01-01"}


def test_verification_dune_cle_falsifiee(client):
    donnees = client.post("/api/licence/verifier", json={"cle": "IRIS-nimportequoi-0123456789abcdef0123"}).json()
    assert donnees["valide"] is False
    assert "invalide" in donnees["raison"].lower()


def test_verification_dune_cle_expiree(client):
    hier = (date.today() - timedelta(days=1)).isoformat()
    cle = cles.faire_cle("pro", hier, "client@exemple.com", SECRET_HISTORIQUE)
    donnees = client.post("/api/licence/verifier", json={"cle": cle}).json()
    assert donnees["valide"] is False
    assert hier in donnees["raison"]


def test_verification_accepte_aussi_la_forme_anglaise(client):
    cle = cles.faire_cle("pro", "2029-01-01", "", SECRET_HISTORIQUE)
    assert client.post("/api/licence/verifier", json={"key": cle}).json()["valide"] is True
    assert client.post("/api/licence/verifier", json={}).json()["valide"] is False


# ============================================================ administration
def test_administration_refusee_sans_jeton(client):
    assert client.get("/admin").status_code == 401
    assert client.get("/admin", params={"jeton": "mauvais"}).status_code == 401
    assert client.post("/admin/emettre", data={"courriel": "x@y.com", "plan": "pro"}).status_code == 401


def test_administration_affiche_les_abonnements(client, base):
    poster_webhook(client, charges.capture_completee("liste@exemple.com", "29.99", capture_id="CAP-LISTE"))
    page = client.get("/admin", params={"jeton": JETON_ADMIN})
    assert page.status_code == 200
    assert "liste@exemple.com" in page.text
    assert "Pro" in page.text or "pro" in page.text


def test_emission_manuelle_dune_cle(client, base, config):
    """Le filet de sécurité : virement, comptant, clé perdue."""
    reponse = client.post("/admin/emettre", data={
        "courriel": "Virement@Exemple.com", "plan": "entreprise", "mois": "3",
        "raison": "virement Interac", "jeton": JETON_ADMIN,
    })
    assert reponse.status_code == 200
    donnees = reponse.json()
    assert donnees["ok"] is True
    assert donnees["courriel"] == "virement@exemple.com"
    assert donnees["expire_le"] == cles.prolonger(None, 3)
    assert cles.verifier_cle(donnees["cle"], SECRET_HISTORIQUE)["plan"] == "entreprise"

    ligne = base.abonnement("virement@exemple.com")
    assert ligne["statut"] == "actif" and ligne["plan"] == "entreprise"
    # La clé est aussi partie au client.
    assert any("virement@exemple.com" in f.read_text(encoding="utf-8")
               for f in config.dossier_sortie.glob("*.eml"))


def test_emission_manuelle_refuse_les_donnees_invalides(client):
    mauvais = client.post("/admin/emettre", data={"courriel": "pas-une-adresse", "plan": "pro",
                                                  "jeton": JETON_ADMIN})
    assert mauvais.status_code == 400
    plan_inconnu = client.post("/admin/emettre", data={"courriel": "x@y.com", "plan": "platine",
                                                       "jeton": JETON_ADMIN})
    assert plan_inconnu.status_code == 400


def test_administration_desactivee_sans_jeton_configure(config, base):
    from fastapi.testclient import TestClient
    from licences.app import creer_app
    config.jeton_admin = ""
    with TestClient(creer_app(cfg=config, base=base, client_paypal=None)) as client:
        assert client.get("/admin").status_code == 404
        assert client.get("/sante").json()["administration"] is False


def test_dossier_manuel_marque_comme_resolu(client, base):
    poster_webhook(client, charges.capture_completee("adossier@exemple.com", "3.00", capture_id="CAP-3"))
    dossiers = base.manuels()
    assert len(dossiers) == 1
    reponse = client.post("/admin/resoudre", data={"identifiant": dossiers[0]["id"], "jeton": JETON_ADMIN})
    assert reponse.status_code == 200
    assert base.manuels() == []
