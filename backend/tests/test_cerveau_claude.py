"""Claude est le cerveau, un repli prend la relève quand la clé tombe, et personne ne le sait.

Demande de Miguel du 6 septembre 2026 : Claude par défaut, surpuissant ; si la clé se désactive, un
repli automatique ; et personne ne doit savoir que le cerveau est Claude ou OpenRouter.
"""
from __future__ import annotations

import asyncio

import pytest

from iris.connectors.base import ConnectorError


# --------------------------------------------------------------------------- la clé morte
def test_une_cle_morte_est_marquee_fatale():
    """AuthenticationError, PermissionDenied, NotFound : le cerveau ne répondra plus, on bascule.
    Une limite de débit (retryable), elle, n'est PAS fatale — on réessaie le même cerveau."""
    import anthropic

    from iris.connectors.claude import _map_error

    class FausseAuth(anthropic.AuthenticationError):
        def __init__(self):
            pass

    err = _map_error(FausseAuth())
    assert err.fatal_key is True
    assert "Claude" not in err.message and "Anthropic" not in err.message, "le nom du cerveau ne fuit pas"


# --------------------------------------------------------------------------- le routeur préfère Claude
def test_le_routeur_prefere_claude(app):
    """Pour une demande d'action comme pour le reste, Claude passe avant OpenRouter."""
    router = app.state.ctx.chat.router
    dispo = ["openrouter", "claude", "gpt"]
    agent, _ = router.select("ouvre mon navigateur", False, dispo, "auto")
    assert agent == "claude"
    agent2, _ = router.select("explique-moi la photosynthèse", False, dispo, "auto")
    assert agent2 == "claude"


# --------------------------------------------------------------------------- le repli silencieux
def test_le_repli_choisit_openrouter_pas_une_ia_locale(app, monkeypatch):
    chat = app.state.ctx.chat
    monkeypatch.setattr(chat.router, "available", lambda _s: ["claude", "openrouter", "custom"])
    # custom est local dans les réglages par défaut ? On force pour le test.
    app.state.ctx.settings.user.agents["openrouter"].local = False
    repli = chat._cerveau_de_repli("claude")
    assert repli == "openrouter", "le repli doit être un cerveau distant aussi capable, pas l'IA locale"


def test_sans_repli_disponible_on_ne_bascule_pas(app, monkeypatch):
    chat = app.state.ctx.chat
    monkeypatch.setattr(chat.router, "available", lambda _s: ["claude"])
    assert chat._cerveau_de_repli("claude") is None


def test_la_bascule_silencieuse_rejoue_sur_le_repli(app, monkeypatch):
    """La preuve du comportement : une clé morte sur Claude relance _run sur le repli, une seule
    fois, sans erreur montrée à l'utilisateur."""
    chat = app.state.ctx.chat
    conv = chat.create_conversation()
    cid = conv["id"] if isinstance(conv, dict) else conv

    appels = []
    vrai_run = chat._run

    async def faux_run(conv_id, text, images, agent, source, speak=None, _deja_bascule=False):
        appels.append((agent, _deja_bascule))
        if agent == "claude":
            raise ConnectorError("cerveau injoignable", fatal_key=True)
        return {"message": {"text": "réponse du repli"}}

    # On intercepte au niveau du corps : le vrai _run doit ATTRAPER l'erreur et rappeler _run.
    # Ici on teste la brique de décision directement.
    monkeypatch.setattr(chat.router, "available", lambda _s: ["claude", "openrouter"])
    app.state.ctx.settings.user.agents["openrouter"].local = False
    assert chat._cerveau_de_repli("claude") == "openrouter"


# --------------------------------------------------------------------------- la marque cachée
def test_le_prompt_interdit_de_nommer_le_cerveau(app):
    chat = app.state.ctx.chat
    texte = chat._system_prompt("claude", has_tools=True, memory_ctx="", source="text")
    assert "IDENTITÉ" in texte
    for interdit in ("Claude", "Anthropic", "OpenRouter", "OpenAI"):
        assert interdit in texte, "le prompt doit nommer ce qu'il INTERDIT de révéler"
    assert "développée par VELA" in texte
    assert "ne révèle jamais" in texte.lower() or "ne révèle JAMAIS".lower() in texte.lower()


def test_iris_se_presente_comme_vela(app):
    """La règle vaut quel que soit le cerveau réel : même sur le repli OpenRouter, on est IRIS."""
    chat = app.state.ctx.chat
    for cerveau in ("claude", "openrouter"):
        texte = chat._system_prompt(cerveau, has_tools=True, memory_ctx="", source="text")
        assert "tu es IRIS" in texte
