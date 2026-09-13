"""Le canal inverse (télécommande) : le relais courtier route les commandes du téléphone vers
l'ordinateur du MÊME courriel ET du MÊME code d'appairage, relaie les demandes de confirmation, et
refuse tout le reste.

Ce que ces tests protègent : (1) un jeton invalide ou un hello sans code d'appairage n'ouvre rien ;
(2) un aller-retour complet marche, confirmation comprise ; (3) un téléphone d'un autre compte
n'atteint jamais l'ordinateur d'autrui ; (4) le BON courriel mais un MAUVAIS code d'appairage
n'atteint pas l'ordinateur non plus (connaître le courriel ne suffit pas). Aucun réseau réel.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from starlette.websockets import WebSocketDisconnect

RACINE = Path(__file__).resolve().parents[1]
for chemin in (str(Path(__file__).parent), str(RACINE / "backend")):
    if chemin not in sys.path:
        sys.path.insert(0, chemin)

CODE = "code-appairage-secret"  # affiché par l'ordinateur, saisi dans le téléphone


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


def _jeton(relais, courriel):
    return relais.emettre_jeton(courriel, "machine-test")


def _hello(jeton, pairing=CODE):
    return {"type": "hello", "jeton": jeton, "pairing": pairing}


def test_refuse_un_jeton_invalide(client):
    with client.websocket_connect("/appareil/ws") as ws:
        ws.send_json(_hello("pas-un-vrai-jeton"))
        with pytest.raises(WebSocketDisconnect):
            ws.receive_json()  # fermée (4001), aucun {pret}


def test_ordinateur_refuse_sans_code_dappairage(client, relais):
    with client.websocket_connect("/appareil/ws") as ws:
        ws.send_json({"type": "hello", "jeton": _jeton(relais, "a@vela.app")})  # pairing manquant
        with pytest.raises(WebSocketDisconnect):
            ws.receive_json()


def test_ordinateur_valide_est_pret(client, relais):
    with client.websocket_connect("/appareil/ws") as ws:
        ws.send_json(_hello(_jeton(relais, "a@vela.app")))
        assert ws.receive_json() == {"type": "pret"}


def test_sans_ordinateur_le_dit(client, relais):
    with client.websocket_connect("/telecommande/ws") as tel:
        tel.send_json(_hello(_jeton(relais, "seul@vela.app")))
        assert tel.receive_json()["ordinateur"] is False
        tel.send_json({"type": "commande", "req_id": "x", "texte": "ouvre une application"})
        assert tel.receive_json()["erreur"] == "ordinateur_absent"


def test_aller_retour_complet(client, relais):
    tok = _jeton(relais, "duo@vela.app")  # même compte, même code des deux côtés
    with client.websocket_connect("/appareil/ws") as pc:
        pc.send_json(_hello(tok))
        assert pc.receive_json() == {"type": "pret"}
        with client.websocket_connect("/telecommande/ws") as tel:
            tel.send_json(_hello(tok))
            pret = tel.receive_json()
            assert pret["type"] == "pret" and pret["ordinateur"] is True
            tel.send_json({"type": "commande", "req_id": "r1", "texte": "ouvre le bloc-notes"})
            assert pc.receive_json() == {"type": "commande", "req_id": "r1", "texte": "ouvre le bloc-notes"}
            pc.send_json({"type": "confirm", "req_id": "r1", "confirm_id": "c1", "title": "Ouvrir ?", "detail": "Bloc-notes"})
            conf = tel.receive_json()
            assert conf["type"] == "confirm" and conf["confirm_id"] == "c1"
            tel.send_json({"type": "confirm_reponse", "req_id": "r1", "confirm_id": "c1", "approved": True})
            assert pc.receive_json()["approved"] is True
            pc.send_json({"type": "resultat", "req_id": "r1", "reponse": "C'est fait."})
            assert tel.receive_json() == {"type": "resultat", "req_id": "r1", "reponse": "C'est fait."}


def test_cloisonnee_par_compte(client, relais):
    """Un téléphone d'un AUTRE courriel n'atteint pas l'ordinateur de quelqu'un d'autre."""
    with client.websocket_connect("/appareil/ws") as pc:
        pc.send_json(_hello(_jeton(relais, "proprietaire@vela.app")))
        assert pc.receive_json() == {"type": "pret"}
        with client.websocket_connect("/telecommande/ws") as tel:
            tel.send_json(_hello(_jeton(relais, "voisin@vela.app")))  # autre compte
            assert tel.receive_json()["ordinateur"] is False
            tel.send_json({"type": "commande", "req_id": "z", "texte": "ouvre une application"})
            assert tel.receive_json()["erreur"] == "ordinateur_absent"


def test_bon_courriel_mais_mauvais_code_est_refuse(client, relais):
    """Connaître le courriel ne suffit pas : sans le bon code d'appairage, l'ordinateur reste hors d'atteinte."""
    tok = _jeton(relais, "cible@vela.app")
    with client.websocket_connect("/appareil/ws") as pc:
        pc.send_json(_hello(tok, pairing="le-vrai-code"))
        assert pc.receive_json() == {"type": "pret"}
        with client.websocket_connect("/telecommande/ws") as tel:
            tel.send_json(_hello(tok, pairing="mauvais-code"))  # même courriel, code faux
            assert tel.receive_json()["ordinateur"] is False
            tel.send_json({"type": "commande", "req_id": "z", "texte": "ouvre une application"})
            assert tel.receive_json()["erreur"] == "ordinateur_absent"
