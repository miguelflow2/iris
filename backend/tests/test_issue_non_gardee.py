"""Demande finie sans message : le téléphone doit pouvoir la lire en sondant la conversation.

Constat iOS du 2026-09-14 : un consentement manquant ne laisse AUCUN message (seulement l'événement
chat.consent_required). L'app iPhone dont la liaison d'événements était fermée (cas normal dehors, ou juste
après un retour d'arrière-plan) perdait l'événement, sondait GET /api/conversations/{id} sans rien trouver
et finissait 3 minutes plus tard sur un faux motif (« connexion perdue »). La conversation rend maintenant
`issue_non_gardee` {apres, message, consentement, ts} — sans ajouter de message à la conversation.
"""
from __future__ import annotations

import time

import pytest

import iris.chat as chat_module
from iris.connectors.base import BaseConnector, Chunk


class ConnecteurMuet(BaseConnector):
    name = "claude"
    supports_tools = False
    appels = 0

    def __init__(self, api_key=None, model="faux-modele", base_url=None):
        super().__init__(api_key, model, base_url)

    async def stream(self, messages, system, tools=None, run_tool=None, options=None):
        ConnecteurMuet.appels += 1
        yield Chunk("text", text="Réponse.")
        yield Chunk("done")

    async def test(self):
        return {"ok": True, "message": "ok", "model": self.model, "latency_ms": 1}


@pytest.fixture()
def connecteur(monkeypatch):
    ConnecteurMuet.appels = 0
    monkeypatch.setattr(chat_module, "build_connector", lambda name, settings, secrets: ConnecteurMuet())
    return ConnecteurMuet


def _attendre_issue(client, conv_id: str, secondes: float = 10.0) -> dict:
    fin = time.monotonic() + secondes
    while time.monotonic() < fin:
        corps = client.get(f"/api/conversations/{conv_id}").json()
        if corps.get("issue_non_gardee"):
            return corps
        time.sleep(0.1)
    return client.get(f"/api/conversations/{conv_id}").json()


def test_consentement_requis_lisible_sans_evenement(client, connecteur):
    client.put("/api/agents/claude", json={"active": True, "api_key": "cle-factice-test"})
    conv = client.post("/api/conversations", json={}).json()
    avant = client.get(f"/api/conversations/{conv['id']}").json()
    assert avant["issue_non_gardee"] is None

    # Envoi HTTP, AUCUN WebSocket ouvert : c'est le cas de l'iPhone dont la liaison est coupée.
    assert client.post(f"/api/conversations/{conv['id']}/messages",
                       json={"text": "salut", "agent": "auto", "images": []}).status_code == 200
    corps = _attendre_issue(client, conv["id"])
    issue = corps["issue_non_gardee"]
    assert issue, "la fin sans message doit être lisible en sondant la conversation"
    utilisateur = [m for m in corps["messages"] if m["role"] == "user"]
    assert issue["apres"] == utilisateur[-1]["id"], "l'issue nomme la demande qu'elle conclut"
    assert issue["consentement"]["data_type"] == "transcript"
    assert issue["consentement"]["label"]
    assert "consentement requis" in issue["message"]
    # Rien n'est ajouté à la conversation, et rien n'est parti vers le moteur.
    assert [m["role"] for m in corps["messages"]] == ["user"]
    assert connecteur.appels == 0
    # Même champ dans la lecture partielle (?limit=) qu'utilise un téléphone sur données mobiles.
    assert client.get(f"/api/conversations/{conv['id']}?limit=5").json()["issue_non_gardee"]["apres"] == issue["apres"]
