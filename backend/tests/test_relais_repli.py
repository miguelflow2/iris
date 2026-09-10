"""Repli du relais VELA — résilience sur réseau filtré (DNS détourné).

Contexte réel : sur le wifi d'un cégep, le serveur DNS renvoyait `relais.velaglass.ca` vers une
impasse interne (10.1.255.32 / ::1), alors que le relais répondait parfaitement par son entrée
Render. Ces tests garantissent que la résolution :
  - bascule sur le repli quand le domaine principal ne répond pas, mais
  - laisse tout inchangé quand le principal répond (additif, zéro régression), et
  - ne fixe aucun repli quand on est simplement hors ligne (ce n'est pas une panne d'IRIS).
Aucun réseau réel n'est touché : httpx.get est simulé.
"""
from __future__ import annotations

import types

import httpx

from iris import connectors


def _settings(relay: str = "https://relais.velaglass.ca"):
    s = types.SimpleNamespace()
    s.user = types.SimpleNamespace(relay_server=relay)
    s.relay_base_override = ""
    return s


def _reponse_ok():
    return types.SimpleNamespace(status_code=200, json=lambda: {"ok": True})


def test_bases_relais_principal_puis_repli_dedup():
    s = _settings()
    bases = connectors.bases_relais(s)
    assert bases[0] == "https://relais.velaglass.ca"
    assert "https://vela-relais.onrender.com" in bases
    # Si le principal EST déjà le repli, pas de doublon.
    s2 = _settings("https://vela-relais.onrender.com")
    assert connectors.bases_relais(s2) == ["https://vela-relais.onrender.com"]


def test_repli_depuis_env(monkeypatch):
    monkeypatch.setenv("VELA_RELAIS_REPLIS", "https://a.example/, https://b.example")
    s = _settings()
    assert connectors.bases_relais(s) == [
        "https://relais.velaglass.ca",
        "https://a.example",
        "https://b.example",
    ]


def test_resoudre_bascule_sur_repli_si_principal_injoignable(monkeypatch):
    def fake_get(url, timeout=None):
        if url.startswith("https://relais.velaglass.ca"):
            raise httpx.ConnectError("détourné")
        return _reponse_ok()

    monkeypatch.setattr(httpx, "get", fake_get)
    s = _settings()
    base = connectors.resoudre_relais(s, timeout=0.1)
    assert base == "https://vela-relais.onrender.com"
    assert s.relay_base_override == "https://vela-relais.onrender.com"
    assert connectors.base_relais_effective(s) == "https://vela-relais.onrender.com"


def test_resoudre_garde_principal_quand_il_repond(monkeypatch):
    monkeypatch.setattr(httpx, "get", lambda url, timeout=None: _reponse_ok())
    s = _settings()
    base = connectors.resoudre_relais(s, timeout=0.1)
    assert base == "https://relais.velaglass.ca"
    assert s.relay_base_override == ""  # additif : rien ne change quand le principal marche


def test_resoudre_hors_ligne_conserve_le_principal(monkeypatch):
    def fake_get(url, timeout=None):
        raise httpx.ConnectError("hors ligne")

    monkeypatch.setattr(httpx, "get", fake_get)
    s = _settings()
    base = connectors.resoudre_relais(s, timeout=0.1)
    assert base == "https://relais.velaglass.ca"
    assert s.relay_base_override == ""


def test_base_effective_prefere_loverride():
    s = _settings()
    s.relay_base_override = "https://vela-relais.onrender.com"
    assert connectors.base_relais_effective(s) == "https://vela-relais.onrender.com"
