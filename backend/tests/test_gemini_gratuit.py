"""Gemini : IRIS n'utilise QUE des modèles gratuits (décision de Miguel, 2026-09-14)."""
from __future__ import annotations

from iris.connectors.gemini import GEMINI_GRATUITS, GEMINI_MODELE_DEFAUT, GEMINI_MODELS, modele_gratuit


def test_la_liste_ne_contient_que_des_modeles_gratuits():
    assert GEMINI_MODELE_DEFAUT in GEMINI_GRATUITS
    for m in GEMINI_MODELS:
        assert "pro" not in m["id"], f"modèle payant dans la liste : {m['id']}"
        assert "gratuit" in m["label"]


def test_un_modele_payant_ou_retire_retombe_sur_le_gratuit():
    for payant in ("gemini-2.5-pro", "gemini-3.1-pro-preview", "gemini-pro-latest", "gemini-2.5-flash", "", None):
        assert modele_gratuit(payant) == GEMINI_MODELE_DEFAUT, payant
    assert modele_gratuit("models/gemini-3.5-flash-lite") == "gemini-3.5-flash-lite"


def test_le_connecteur_construit_nutilise_que_du_gratuit(app):
    from iris.connectors import build_connector

    ctx = app.state.ctx
    ctx.secrets.set_api_key("gemini", "cle-de-test")
    ctx.settings.update({"agents": {"gemini": {"active": True, "model": "gemini-2.5-pro"}}})
    connecteur = build_connector("gemini", ctx.settings, ctx.secrets)
    assert connecteur.model in GEMINI_GRATUITS
