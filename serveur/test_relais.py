"""Le relais tient la clé IA de VELA. Ces tests portent sur ce qui coûterait cher s'il cédait.

Trois choses doivent tenir : un plan Gratuit ne doit jamais atteindre un modèle payant, un jeton
forgé ne doit rien ouvrir, et une clé d'abonnement émise ici doit être acceptée par IRIS — sinon
le client paie et n'obtient rien.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[1]
for chemin in (str(Path(__file__).parent), str(RACINE / "backend")):
    if chemin not in sys.path:
        sys.path.insert(0, chemin)


@pytest.fixture()
def relais(tmp_path, monkeypatch):
    monkeypatch.setenv("VELA_DONNEES", str(tmp_path))
    monkeypatch.setenv("VELA_OPENROUTER_KEY", "sk-or-factice")
    for module in [m for m in list(sys.modules) if m == "relais"]:
        del sys.modules[module]
    import relais as module

    return module


@pytest.fixture()
def client(relais):
    from fastapi.testclient import TestClient

    return TestClient(relais.app)


def abonne(relais, courriel: str, plan: str, expires: str = "2099-01-01") -> None:
    (Path(relais.DONNEES)).mkdir(parents=True, exist_ok=True)
    (Path(relais.DONNEES) / "abonnes.json").write_text(
        json.dumps({courriel: {"plan": plan, "expires": expires}}), encoding="utf-8"
    )


# --------------------------------------------------------------------------- l'argent
def test_un_plan_gratuit_natteint_jamais_un_modele_payant(relais):
    for demande in ("anthropic/claude-opus-5", "openai/gpt-5-mini", "n'importe quoi"):
        choisi = relais.modele_autorise(demande, "gratuit")
        assert choisi.endswith(":free"), f"{demande} a donné {choisi}"


def test_chaque_plan_recoit_ce_quil_a_paye(relais):
    assert relais.modele_autorise("anthropic/claude-sonnet-5", "premium") == "anthropic/claude-sonnet-5"
    assert relais.modele_autorise("anthropic/claude-opus-5", "entreprise") == "anthropic/claude-opus-5"
    # Opus est réservé au dernier palier : un abonné Premium qui le demande obtient son propre modèle.
    assert relais.modele_autorise("anthropic/claude-opus-5", "premium") != "anthropic/claude-opus-5"


def test_un_abonnement_expire_retombe_au_gratuit(relais):
    abonne(relais, "ancien@exemple.com", "entreprise", expires="2020-01-01")
    etat = relais.abonnement("ancien@exemple.com")
    assert etat["plan"] == "gratuit" and etat.get("expire") is True


def test_le_quota_du_plan_est_applique(relais):
    from fastapi import HTTPException

    relais.QUOTAS["gratuit"] = 2
    relais.consommer("qui@exemple.com", "gratuit")
    relais.consommer("qui@exemple.com", "gratuit")
    with pytest.raises(HTTPException) as leve:
        relais.consommer("qui@exemple.com", "gratuit")
    assert leve.value.status_code == 429


# --------------------------------------------------------------------------- les jetons
def test_un_jeton_forge_est_refuse(relais):
    vrai = relais.emettre_jeton("client@exemple.com", "machine-1")
    assert relais.lire_jeton(vrai)["courriel"] == "client@exemple.com"
    corps, signature = vrai.rsplit(".", 1)
    assert relais.lire_jeton(corps + ".XXXX") is None, "signature modifiée"
    assert relais.lire_jeton("") is None
    assert relais.lire_jeton("n'importe.quoi.du.tout") is None


def test_un_jeton_perime_ne_vaut_plus_rien(relais, monkeypatch):
    monkeypatch.setattr(relais, "DUREE_JETON", -10)
    assert relais.lire_jeton(relais.emettre_jeton("client@exemple.com", "m")) is None


def test_changer_de_courriel_ne_donne_pas_le_plan_dun_autre(relais):
    """Le courriel est dans le corps signé : le modifier casse la signature."""
    jeton = relais.emettre_jeton("gratuit@exemple.com", "m")
    tete, reste = jeton.split(".", 1)
    autre = relais._b64(b"entreprise@exemple.com")
    assert relais.lire_jeton(autre + "." + reste) is None


def test_lia_est_fermee_sans_jeton(client):
    assert client.get("/v1/models").status_code == 401
    assert client.post("/v1/chat/completions", json={"messages": [{"role": "user", "content": "salut"}]}).status_code == 401


def test_un_appareil_obtient_son_acces_et_voit_ses_modeles(client, relais):
    abonne(relais, "premium@exemple.com", "premium")
    reponse = client.post("/api/appareil", json={"machine": "abc", "email": "premium@exemple.com"}).json()
    assert reponse["plan"] == "premium"
    modeles = client.get("/v1/models", headers={"Authorization": "Bearer " + reponse["jeton"]}).json()
    assert "anthropic/claude-sonnet-5" in [m["id"] for m in modeles["data"]]


# --------------------------------------------------------------------------- l'abonnement
def test_une_cle_emise_ici_est_acceptee_par_iris(relais):
    """Le test qui compte vraiment : sinon le client paie, reçoit une clé, et IRIS la refuse."""
    from iris.plans import verify_key

    abonne(relais, "acheteur@exemple.com", "pro", expires="2099-06-30")
    cle = relais.cle_licence("pro", "2099-06-30", "acheteur@exemple.com")
    info = verify_key(cle)
    assert info is not None, "IRIS rejette la clé émise par le relais"
    assert info["plan"] == "pro" and info["expires"] == "2099-06-30" and not info["expired"]


def test_aucun_abonnement_pour_un_inconnu(client):
    assert client.get("/api/licence", params={"email": "personne@exemple.com"}).status_code == 404


def test_la_licence_dun_abonne_est_servie(client, relais):
    abonne(relais, "abonne@exemple.com", "entreprise", expires="2099-01-01")
    corps = client.get("/api/licence", params={"email": "Abonne@Exemple.com"}).json()
    assert corps["plan"] == "entreprise" and corps["key"].startswith("IRIS-")


def test_le_relais_ne_divulgue_jamais_sa_cle(client, relais):
    """Une clé d'API dans une réponse, et n'importe quel client peut vider le compte."""
    corps = json.dumps(client.get("/sante").json()) + json.dumps(
        client.post("/api/appareil", json={"machine": "m", "email": ""}).json()
    )
    assert relais.CLE_AMONT not in corps
