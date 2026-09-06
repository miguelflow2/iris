"""« Montre-moi » : le navigateur pilote peut s'ouvrir visible sur demande.

Limite qu'IRIS a elle-meme nommee le 6 septembre 2026 : « mes recherches web ne t'ouvrent pas de
fenetre ». L'invisible reste le defaut ; `visible=True` doit remonter jusqu'au lancement.
"""
from __future__ import annotations

import pytest


def _capture(app, monkeypatch):
    web = app.state.ctx.web
    vus = []

    def faux_browser(visible=False):
        vus.append(visible)
        raise RuntimeError("stop ici : on ne lance pas de navigateur en test")

    monkeypatch.setattr(web, "_browser", faux_browser)
    return web, vus


def test_search_reste_invisible_par_defaut(app, monkeypatch):
    web, vus = _capture(app, monkeypatch)
    with pytest.raises(RuntimeError):  # le faux navigateur coupe court, APRES avoir note le drapeau
        web.search("vela lunettes")
    assert vus == [False]


def test_search_peut_etre_visible(app, monkeypatch):
    web, vus = _capture(app, monkeypatch)
    with pytest.raises(RuntimeError):  # le faux navigateur coupe court, APRES avoir note le drapeau
        web.search("vela lunettes", visible=True)
    assert vus == [True]


def test_open_peut_etre_visible(app, monkeypatch):
    web, vus = _capture(app, monkeypatch)
    with pytest.raises(RuntimeError):  # le faux navigateur coupe court, APRES avoir note le drapeau
        web.open("https://exemple.com", visible=True)
    assert vus == [True]
