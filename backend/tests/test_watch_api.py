"""Les veilles à travers l'API : c'est ce que fait réellement l'interface, et c'est là qu'une régression passe.

Ce fichier existe parce qu'un modèle de requête déclaré dans une fonction était pris par FastAPI pour un
paramètre d'URL : les tests du service passaient, mais la création échouait en 422 dans l'application.
"""
from __future__ import annotations


def _pret(client):
    """Assistant minimal : les veilles n'exigent ni clé d'agent ni consentement."""
    return client


def test_creation_et_liste_par_lapi(client):
    r = client.post(
        "/api/watches",
        json={
            "name": "fournisseur Alibaba",
            "url": "https://message.alibaba.com/fil/1",
            "criteria": "prix sous 2,50 $ l'unité pour 500 pièces",
            "interval_min": 20,
        },
    )
    assert r.status_code == 200, r.text
    cree = r.json()
    assert cree["name"] == "fournisseur Alibaba" and cree["interval_min"] == 20

    liste = client.get("/api/watches").json()
    assert [w["id"] for w in liste["items"]] == [cree["id"]]
    assert liste["items"][0]["criteria"].startswith("prix sous")


def test_valeurs_par_defaut(client):
    r = client.post("/api/watches", json={"name": "v", "url": "https://x.com/f", "criteria": "c"})
    assert r.status_code == 200 and r.json()["interval_min"] == 15


def test_entree_invalide_refusee_proprement(client):
    r = client.post("/api/watches", json={"name": "v", "url": "pas-une-adresse", "criteria": "c"})
    assert r.status_code == 400
    assert "adresse" in r.json()["detail"].lower()


def test_arret_reprise_et_suppression(client):
    w = client.post("/api/watches", json={"name": "v", "url": "https://x.com/f", "criteria": "c"}).json()

    assert client.post(f"/api/watches/{w['id']}/stop").json()["ok"]
    assert client.get("/api/watches").json()["items"][0]["active"] is False

    assert client.post(f"/api/watches/{w['id']}/resume").json()["ok"]
    assert client.get("/api/watches").json()["items"][0]["active"] is True

    assert client.delete(f"/api/watches/{w['id']}").json()["ok"]
    assert client.get("/api/watches").json()["items"] == []


def test_verification_dune_veille_inconnue(client):
    assert client.post("/api/watches/inexistante/check").status_code == 404
