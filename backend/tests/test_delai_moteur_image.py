"""Délai maximal de ChatService.demander_image_detail (contre-vérification du 2026-09-14).

Le délai était posé chez un seul appelant (vision d'accessibilité) : les reçus, le pas à pas et le résumé du
jour, eux aussi interceptés à la voix, attendaient un moteur muet sans limite. L'écoute gelait alors 90 s,
puis envoyait la même phrase au modèle pendant que le premier traitement tournait encore. Le délai vit
maintenant dans ChatService : tout appelant, présent ou futur, en profite.

Faux moteur (connecteur simulé qui dort) ; aucun réseau.
"""
from __future__ import annotations

import asyncio
import time

import pytest

import iris.chat as chat_module
from iris.connectors.base import BaseConnector, Chunk, ConnectorError, MoteurTropLent


class MoteurMuet(BaseConnector):
    name = "claude"
    supports_tools = True
    supports_images = True
    attente = 5.0

    def __init__(self):
        super().__init__("cle", "faux-modele")

    async def stream(self, messages, system, tools=None, run_tool=None, options=None):
        await asyncio.sleep(MoteurMuet.attente)
        yield Chunk("text", text="trop tard")
        yield Chunk("done")

    async def test(self):  # pragma: no cover
        return {"ok": True}


@pytest.fixture()
def chat(app, client, monkeypatch):
    monkeypatch.setattr(chat_module, "build_connector", lambda name, settings, secrets: MoteurMuet())
    client.put("/api/agents/claude", json={"active": True, "api_key": "sk-test-delai"})
    assert client.put("/api/consent/transcript", json={"granted": True}).status_code == 200
    MoteurMuet.attente = 5.0
    return app.state.ctx.chat


def test_un_moteur_muet_leve_moteur_trop_lent_dans_le_delai_par_defaut(chat, monkeypatch):
    monkeypatch.setattr(chat_module, "DELAI_MOTEUR_IMAGE_S", 0.3)
    debut = time.monotonic()
    with pytest.raises(MoteurTropLent) as exc:
        asyncio.run(chat.demander_image_detail("systeme", "question", [], consentement=("transcript",)))
    assert time.monotonic() - debut < 2.5
    # Sous-classe de ConnectorError : les appelants existants la traitent comme une panne (message neutre).
    assert isinstance(exc.value, ConnectorError)
    assert "VELA" in str(exc.value) and "claude" not in str(exc.value).lower()


def test_le_delai_explicite_prime(chat):
    debut = time.monotonic()
    with pytest.raises(MoteurTropLent):
        asyncio.run(chat.demander_image_detail("systeme", "question", [], consentement=("transcript",), delai_s=0.2))
    assert time.monotonic() - debut < 2.0


def test_un_moteur_dans_les_temps_repond_normalement(chat, monkeypatch):
    MoteurMuet.attente = 0.01
    monkeypatch.setattr(chat_module, "DELAI_MOTEUR_IMAGE_S", 2.0)
    r = asyncio.run(chat.demander_image_detail("systeme", "question", [], consentement=("transcript",)))
    assert r["texte"] == "trop tard" and r["local"] is False


def test_le_delai_par_defaut_reste_sous_celui_des_interceptions_vocales():
    """L'écoute n'attend une interception que 90 s : le moteur doit abandonner avant, avec une marge pour la
    photo et la lecture locale qui le précèdent."""
    assert 0 < chat_module.DELAI_MOTEUR_IMAGE_S <= 60
