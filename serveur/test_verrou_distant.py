"""Verrouillage à distance côté relais (serveur/verrou_distant.py, 2026-09-13).

Ce que ces tests protègent : (1) la page /verrou est autonome, en français, sans ressource externe ;
(2) 5 tentatives par 15 minutes, par courriel ET par adresse IP ; (3) la commande est relayée à
l'ordinateur factice du BON courriel, sa réponse revient au navigateur sans le code ni l'identifiant
interne ; (4) sans réponse en 15 s, le relais le dit ; (5) ordinateur hors ligne : la commande attend
en mémoire et part à la reconnexion, le code quitte alors la mémoire du relais ; (6) le code n'apparaît
dans aucun journal. Aucun réseau réel : faux ordinateur sur le WebSocket /appareil/ws.
"""
from __future__ import annotations

import logging
import sys
import threading
import time
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[1]
for chemin in (str(Path(__file__).parent), str(RACINE / "backend")):
    if chemin not in sys.path:
        sys.path.insert(0, chemin)

CODE = "secours-2468-code"
PAIRING = "code-appairage"


@pytest.fixture()
def relais(tmp_path, monkeypatch):
    monkeypatch.setenv("VELA_DONNEES", str(tmp_path))
    monkeypatch.setenv("VELA_OPENROUTER_KEY", "sk-or-factice")
    import verrou_distant

    monkeypatch.setattr(verrou_distant, "INTERVALLE_LIVRAISON_S", 0.05)
    for module in [m for m in list(sys.modules) if m == "relais"]:
        del sys.modules[module]
    import relais as module

    return module


@pytest.fixture()
def client(relais):
    from fastapi.testclient import TestClient

    with TestClient(relais.app) as c:  # une seule boucle : la livraison en attente y tourne
        yield c


def _etat(relais) -> dict:
    import verrou_distant

    return verrou_distant.etat_memoire(relais)


def _corps(courriel="proprio@vela.ca", code=CODE, action="verrouiller") -> dict:
    return {"courriel": courriel, "code": code, "action": action}


def _ordinateur(client, relais, courriel="proprio@vela.ca"):
    ws = client.websocket_connect("/appareil/ws")
    pc = ws.__enter__()
    pc.send_json({"type": "hello", "jeton": relais.emettre_jeton(courriel, "machine-test"), "pairing": PAIRING})
    assert pc.receive_json() == {"type": "pret"}
    return ws, pc


def _poster_en_fond(client, corps: dict, ip: str = "203.0.113.7") -> tuple[threading.Thread, dict]:
    resultat: dict = {}

    def poster() -> None:
        r = client.post("/api/verrou", json=corps, headers={"X-Forwarded-For": ip})
        resultat["statut"], resultat["json"] = r.status_code, r.json()

    fil = threading.Thread(target=poster, daemon=True)
    fil.start()
    return fil, resultat


# --------------------------------------------------------------------------- page
def test_la_page_est_autonome_en_francais_et_accessible(client):
    r = client.get("/verrou")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/html")
    page = r.text
    assert '<html lang="fr-CA">' in page and "Verrouiller IRIS à distance" in page
    assert "src=\"http" not in page and "href=\"http" not in page and "@import" not in page, "aucune ressource externe"
    assert 'role="status"' in page and 'aria-live="polite"' in page and '<label for="code">' in page
    assert "perdue" in page, "la limite de la mise en attente est dite"
    for fournisseur in ("Claude", "Anthropic", "OpenAI", "Google", "Render", "OpenRouter"):
        assert fournisseur not in page
    assert r.headers.get("cache-control") == "no-store"


# --------------------------------------------------------------------------- limitation
def test_cinq_tentatives_par_courriel_toutes_adresses_confondues(client):
    statuts = [client.post("/api/verrou", json=_corps(code=f"mauvais-{i}"),
                           headers={"X-Forwarded-For": f"198.51.100.{i}"}).status_code for i in range(6)]
    assert statuts[:5] == [202] * 5 and statuts[5] == 429
    refus = client.post("/api/verrou", json=_corps(), headers={"X-Forwarded-For": "198.51.100.99"})
    assert refus.status_code == 429 and "Réessayez dans" in refus.json()["message"] and refus.headers["retry-after"]


def test_cinq_tentatives_par_adresse_ip_tous_courriels_confondus(client):
    statuts = [client.post("/api/verrou", json=_corps(courriel=f"cible{i}@vela.ca"),
                           headers={"X-Forwarded-For": "6.6.6.6, 192.0.2.10"}).status_code for i in range(6)]
    assert statuts[5] == 429
    # la première entrée de X-Forwarded-For est forgeable : changer celle-là ne contourne pas la limite
    forge = client.post("/api/verrou", json=_corps(courriel="autre@vela.ca"), headers={"X-Forwarded-For": "1.1.1.1, 192.0.2.10"})
    assert forge.status_code == 429


def test_entrees_invalides_sans_echo_du_code(client):
    r = client.post("/api/verrou", json={"courriel": "pas-un-courriel", "code": CODE, "action": "verrouiller"})
    assert r.status_code == 422 and CODE not in r.text
    assert client.post("/api/verrou", json=_corps(code="123")).status_code == 422
    assert client.post("/api/verrou", json=_corps(action="formater")).status_code == 422
    assert client.post("/api/verrou", content=b"pas du json", headers={"content-type": "application/json"}).status_code == 422


# --------------------------------------------------------------------------- relai à l'ordinateur
def test_la_commande_est_relayee_au_pc_du_courriel_et_la_reponse_revient(client, relais, caplog):
    caplog.set_level(logging.DEBUG)
    ws, pc = _ordinateur(client, relais)
    try:
        fil, resultat = _poster_en_fond(client, _corps())
        recu = pc.receive_json()
        assert recu["type"] == "verrou" and recu["action"] == "verrouiller" and recu["code"] == CODE
        assert recu["req_id"] in relais._req_en_cours
        pc.send_json({"type": "resultat", "req_id": recu["req_id"], "verrou": True, "ok": True,
                      "etat": "verrouille", "message": "L'ordinateur est verrouillé."})
        fil.join(timeout=10)
        assert resultat["statut"] == 200
        assert resultat["json"] == {"ok": True, "etat": "verrouille", "message": "L'ordinateur est verrouillé."}
        assert recu["req_id"] not in relais._req_en_cours
    finally:
        ws.__exit__(None, None, None)
    assert CODE not in caplog.text, "le relais ne journalise jamais le code"


def test_code_refuse_par_le_pc_rend_403(client, relais):
    ws, pc = _ordinateur(client, relais)
    try:
        fil, resultat = _poster_en_fond(client, _corps(code="mauvais-code"))
        recu = pc.receive_json()
        pc.send_json({"type": "resultat", "req_id": recu["req_id"], "ok": False, "etat": "code_refuse",
                      "message": "Code de secours incorrect."})
        fil.join(timeout=10)
        assert resultat["statut"] == 403 and resultat["json"]["etat"] == "code_refuse"
    finally:
        ws.__exit__(None, None, None)


def test_sans_reponse_du_pc_le_relais_le_dit(client, relais, monkeypatch):
    import verrou_distant

    monkeypatch.setattr(verrou_distant, "DELAI_REPONSE_S", 0.3)
    ws, pc = _ordinateur(client, relais)
    try:
        fil, resultat = _poster_en_fond(client, _corps())
        assert pc.receive_json()["type"] == "verrou"  # reçu, mais l'ordinateur ne répond pas
        fil.join(timeout=10)
        assert resultat["statut"] == 504 and "impossible de confirmer" in resultat["json"]["message"]
        assert not relais._req_en_cours
    finally:
        ws.__exit__(None, None, None)


def test_un_autre_courriel_natteint_pas_cet_ordinateur(client, relais):
    ws, pc = _ordinateur(client, relais, courriel="proprio@vela.ca")
    try:
        r = client.post("/api/verrou", json=_corps(courriel="voisin@vela.ca"))
        assert r.status_code == 202, "pas d'ordinateur pour ce courriel : en attente, jamais relayée ailleurs"
        time.sleep(0.3)
        assert "voisin@vela.ca" in _etat(relais)["attentes"]
    finally:
        ws.__exit__(None, None, None)


# --------------------------------------------------------------------------- mise en attente
def test_ordinateur_hors_ligne_commande_en_attente_puis_livree_a_la_reconnexion(client, relais):
    r = client.post("/api/verrou", json=_corps(action="effacer"))
    assert r.status_code == 202
    corps = r.json()
    assert corps["etat"] == "en_attente" and "perdue" in corps["message"] and CODE not in r.text
    suivi = corps["suivi"]
    assert client.get(f"/api/verrou/suivi/{suivi}").json()["etat"] == "en_attente"
    assert _etat(relais)["attentes"]["proprio@vela.ca"][0]["code"] == CODE  # en mémoire seulement

    ws, pc = _ordinateur(client, relais)  # l'ordinateur se reconnecte
    try:
        recu = pc.receive_json()
        assert recu["type"] == "verrou" and recu["action"] == "effacer" and recu["code"] == CODE
        pc.send_json({"type": "resultat", "req_id": recu["req_id"], "ok": True, "etat": "efface",
                      "message": "Les données d'IRIS ont été effacées sur l'ordinateur et il est verrouillé."})
        limite = time.monotonic() + 5
        while client.get(f"/api/verrou/suivi/{suivi}").json()["etat"] == "en_attente" and time.monotonic() < limite:
            time.sleep(0.05)
        final = client.get(f"/api/verrou/suivi/{suivi}").json()
        assert final["etat"] == "efface" and "effacées" in final["message"]
        assert _etat(relais)["attentes"] == {}, "le code a quitté la mémoire du relais"
    finally:
        ws.__exit__(None, None, None)
    assert client.get("/api/verrou/suivi/inexistant").status_code == 404


def test_au_plus_trois_commandes_en_attente_par_courriel(client, relais):
    suivis = [client.post("/api/verrou", json=_corps(), headers={"X-Forwarded-For": f"192.0.2.{i}"}).json()["suivi"]
              for i in range(4)]
    assert len(_etat(relais)["attentes"]["proprio@vela.ca"]) == 3
    assert client.get(f"/api/verrou/suivi/{suivis[0]}").json()["etat"] == "remplacee"
