"""Outils du modèle pour les modules du chantier du 2026-09-13 (tools.py : rappel_contexte, pas_a_pas,
entrainement, comparer_prix, resume_journee).

Sans ces outils, « la prochaine fois que je vois Marc, rappelle-moi de… » tapé dans le chat restait sans
effet : les services existaient, le modèle ne pouvait pas les appeler. Chaque outil relaie son service,
respecte « lunettes d'abord » comme les routes, et rend les refus en clair au lieu de planter.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from iris.lunettes_presence import MESSAGE_REQUISES
from iris.tools import OUTILS_QUOTIDIEN, TOOL_SPECS, ToolContext, make_tool_runner

NOMS_INTERDITS = ("claude", "anthropic", "openai", "gpt", "gemini", "google", "elevenlabs", "vosk", "piper", "twilio")


@pytest.fixture()
def service(data_dir):
    from iris.main import create_app

    app = create_app(data_dir=data_dir, token="test-token", use_keyring=False, enable_tts=False)
    app.state.ctx.settings.update({"voice_autostart": False})
    with TestClient(app, headers={"Authorization": "Bearer test-token"}) as client:
        yield client
    app.state.ctx.close()


def _outil(client, nom, args, app_ctx="defaut"):
    ctx = client.app.state.ctx
    outils = ToolContext(
        settings=ctx.settings, consent=ctx.consent, capture=ctx.capture, memory=ctx.memory, agent="test",
        confirm=lambda titre, detail: True, app=ctx if app_ctx == "defaut" else app_ctx,
    )
    runner = make_tool_runner(outils)
    return client.portal.call(runner, nom, args)


def test_les_cinq_outils_sont_declares_et_decrits_sans_promesse_ni_fournisseur():
    noms = {s.name for s in TOOL_SPECS}
    for nom in OUTILS_QUOTIDIEN:
        assert nom in noms
    for spec in TOOL_SPECS:
        if spec.name in OUTILS_QUOTIDIEN:
            texte = spec.description.lower()
            assert not any(n in texte for n in NOMS_INTERDITS), spec.name
            assert "toujours" not in texte and "instantan" not in texte, spec.name


def test_le_chat_passe_le_contexte_de_lapplication_aux_outils(service):
    assert service.app.state.ctx.chat.contexte_app is service.app.state.ctx


def test_rappel_contexte_cree_un_vrai_rappel(service, lunettes_presentes):
    r = _outil(service, "rappel_contexte", {"personne": "Marc", "texte": "lui rendre son livre"})
    assert isinstance(r, str) and "Marc" in r and "visage" in r
    rappels = service.app.state.ctx.rappels_contexte.liste()
    assert [x["personne"] for x in rappels] == ["Marc"]


def test_rappel_contexte_refuse_proprement_un_champ_vide(service, lunettes_presentes):
    r = _outil(service, "rappel_contexte", {"personne": "", "texte": "x"})
    assert isinstance(r, dict) and r["is_error"] and "personne" in r["content"].lower()
    assert service.app.state.ctx.rappels_contexte.liste() == []


def test_pas_a_pas_et_entrainement_ouvrent_une_vraie_session(service, lunettes_presentes):
    r = _outil(service, "pas_a_pas", {"sujet": "crêpes", "type": "recette", "etapes": ["Mélanger", "Cuire"]})
    assert isinstance(r, str) and r
    etat = service.app.state.ctx.pas_a_pas.etat()
    assert etat["actif"] is True and len(etat["etapes"]) == 2

    r = _outil(service, "entrainement", {"exercice": "squats", "series_cibles": 3, "repos_s": 60})
    assert isinstance(r, str) and "répétitions" in r  # la limite « ne compte pas les répétitions » est rendue
    seance = service.app.state.ctx.entrainement.etat()
    assert seance["actif"] is True and seance["series_cibles"] == 3
    service.portal.call(service.app.state.ctx.entrainement.commande, "terminer")
    service.portal.call(service.app.state.ctx.pas_a_pas.commande, "terminer")


def test_comparer_prix_sans_cle_de_recherche_le_dit(service, lunettes_presentes, monkeypatch):
    for nom in ("TAVILY_API_KEY", "BRAVE_SEARCH_API_KEY"):
        monkeypatch.delenv(nom, raising=False)
    r = _outil(service, "comparer_prix", {"requete": "cafetière Bodum 8 tasses"})
    # Sans clé (ou sans consentement) : un refus expliqué, jamais une exception ni des prix inventés.
    assert isinstance(r, (dict, str))
    if isinstance(r, dict):
        assert r["is_error"] and r["content"]


def test_resume_journee_rend_le_texte_et_sa_limite(service, lunettes_presentes):
    r = _outil(service, "resume_journee", {})
    assert isinstance(r, str) and "Limite" in r


def test_sans_lunettes_les_outils_refusent_et_ne_creent_rien(service):
    ctx = service.app.state.ctx
    assert ctx.presence_lunettes.presentes() is False
    for nom, args in (
        ("rappel_contexte", {"personne": "Marc", "texte": "livre"}),
        ("pas_a_pas", {"sujet": "crêpes", "etapes": ["a"]}),
        ("entrainement", {}),
        ("comparer_prix", {"requete": "cafetière"}),
        ("resume_journee", {}),
    ):
        r = _outil(service, nom, args)
        assert isinstance(r, dict) and r["is_error"] and r["content"] == MESSAGE_REQUISES, (nom, r)
    assert ctx.rappels_contexte.liste() == []
    assert ctx.pas_a_pas.etat().get("actif") is False
    assert ctx.entrainement.etat().get("actif") is False


def test_sans_module_branche_loutil_le_dit(service):
    r = _outil(service, "rappel_contexte", {"personne": "Marc", "texte": "livre"}, app_ctx=None)
    assert r["is_error"] and "pas disponible" in r["content"]


def test_cle_de_recherche_enregistree_masquee_puis_effacee(service, monkeypatch):
    """La comparaison de prix exige une clé de recherche (coffre « recherche ») : elle se saisit par
    /api/recherche/cle, et la clé ne revient jamais en clair."""
    for nom in ("TAVILY_API_KEY", "BRAVE_SEARCH_API_KEY"):
        monkeypatch.delenv(nom, raising=False)
    etat = service.get("/api/recherche/cle").json()
    assert etat["configuree"] is False and etat["source"] is None and etat["cle_masquee"] is None

    cle = "tvly-abcdefghijklmnop1234"
    r = service.post("/api/recherche/cle", json={"cle": cle})
    assert r.status_code == 200
    etat = r.json()
    assert etat["configuree"] is True and etat["source"] == "coffre" and etat["fournisseur"] == "tavily"
    assert cle not in r.text and etat["cle_masquee"] == "tvly…1234"
    assert cle not in service.get("/api/recherche/cle").text

    assert service.post("/api/recherche/cle", json={"cle": "court"}).status_code == 422
    assert service.post("/api/recherche/cle", json={"cle": cle, "fournisseur": "autre"}).status_code == 422

    etat = service.delete("/api/recherche/cle").json()
    assert etat["configuree"] is False and etat["coffre_defini"] is False


def test_la_cle_de_lenvironnement_passe_avant_le_coffre_et_cest_dit(service, monkeypatch):
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    monkeypatch.setenv("BRAVE_SEARCH_API_KEY", "BSA-cle-de-test-0000")
    service.post("/api/recherche/cle", json={"cle": "tvly-abcdefghijklmnop1234"})
    etat = service.get("/api/recherche/cle").json()
    assert etat["source"] == "environnement" and etat["fournisseur"] == "brave" and etat["coffre_defini"] is True
