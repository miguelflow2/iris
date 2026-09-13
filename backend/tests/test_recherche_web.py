"""Recherche web par API officielle (Tavily / Brave) et repli navigateur.

Aucun test ne touche le réseau : la couche HTTP est injectée (`requete=`). On vérifie le chemin
API (Tavily et Brave), la sélection du fournisseur selon la clé, le repli navigateur quand aucune
clé n'est configurée, et qu'une erreur d'API remonte un message typé plutôt qu'une exception crue.
"""
from __future__ import annotations

import pytest

from iris import recherche_web
from iris.recherche_web import (
    ClientRecherche,
    RechercheNonConfiguree,
    RechercheRefusee,
    RechercheReseau,
    resoudre_cle,
)


# --------------------------------------------------------------------------- faux HTTP
class FauxReponse:
    def __init__(self, status_code=200, data=None, text=""):
        self.status_code = status_code
        self._data = data
        self.text = text

    def json(self):
        if self._data is None:
            raise ValueError("pas de JSON")
        return self._data


def faux_requete(reponse=None, capture=None, exc=None):
    """Fabrique un `requete=` injectable. `capture` reçoit les arguments de l'appel."""

    def _req(methode, url, *, headers=None, params=None, json=None, timeout=None):
        if capture is not None:
            capture.append({"methode": methode, "url": url, "headers": headers,
                            "params": params, "json": json})
        if exc is not None:
            raise exc
        return reponse

    return _req


REPONSE_TAVILY = {
    "query": "vela lunettes",
    "answer": "VELA fabrique des lunettes connectées avec l'assistante IRIS.",
    "results": [
        {"title": "VELA — site officiel", "url": "https://vela.app", "content": "Lunettes VELA et IRIS."},
        {"title": "IRIS assistante", "url": "https://vela.app/iris", "content": "IRIS vit dans les lunettes."},
    ],
}

REPONSE_BRAVE = {
    "web": {
        "results": [
            {"title": "VELA lunettes", "url": "https://vela.app", "description": "Les lunettes VELA."},
            {"title": "IRIS", "url": "https://vela.app/iris", "description": "L'assistante IRIS."},
        ]
    }
}


# --------------------------------------------------------------------------- sélection fournisseur
def test_selection_tavily_prioritaire():
    env = {"TAVILY_API_KEY": "tvly-abc", "BRAVE_SEARCH_API_KEY": "brv-xyz"}
    assert resoudre_cle(None, env) == ("tavily", "tvly-abc")


def test_selection_brave_si_seul():
    env = {"BRAVE_SEARCH_API_KEY": "brv-xyz"}
    assert resoudre_cle(None, env) == ("brave", "brv-xyz")


def test_aucune_cle_rend_none():
    assert resoudre_cle(None, {}) is None


def test_cle_depuis_coffre_avec_prefixe():
    class Coffre:
        def get_api_key(self, nom):
            assert nom == "recherche"
            return "brave:brv-123"

    assert resoudre_cle(Coffre(), {}) == ("brave", "brv-123")


def test_cle_depuis_coffre_detectee_tavily():
    class Coffre:
        def get_api_key(self, nom):
            return "tvly-sanscprefixe"

    assert resoudre_cle(Coffre(), {}) == ("tavily", "tvly-sanscprefixe")


# --------------------------------------------------------------------------- chemin Tavily
def test_tavily_texte_formate():
    capture: list = []
    client = ClientRecherche(environ={"TAVILY_API_KEY": "tvly-abc"},
                             requete=faux_requete(FauxReponse(200, REPONSE_TAVILY), capture))
    res = client.rechercher("vela lunettes")
    assert res.fournisseur == "tavily"
    # titres, URLs et extraits présents et prêts pour un LLM
    assert "VELA — site officiel" in res.text
    assert "https://vela.app" in res.text
    assert "Réponse directe" in res.text  # le résumé de Tavily posé en tête
    assert res.url == "https://vela.app"  # 1re URL réelle (la réponse directe n'a pas d'URL)
    # la clé part bien vers Tavily, en POST
    assert capture[0]["methode"] == "POST"
    assert capture[0]["url"] == recherche_web.URL_TAVILY
    assert capture[0]["json"]["api_key"] == "tvly-abc"


# --------------------------------------------------------------------------- chemin Brave
def test_brave_texte_formate():
    capture: list = []
    client = ClientRecherche(environ={"BRAVE_SEARCH_API_KEY": "brv-xyz"},
                             requete=faux_requete(FauxReponse(200, REPONSE_BRAVE), capture))
    res = client.rechercher("vela lunettes")
    assert res.fournisseur == "brave"
    assert "VELA lunettes" in res.text
    assert "https://vela.app/iris" in res.text
    assert res.url == "https://vela.app"
    assert capture[0]["methode"] == "GET"
    assert capture[0]["url"] == recherche_web.URL_BRAVE
    assert capture[0]["headers"]["X-Subscription-Token"] == "brv-xyz"
    assert capture[0]["params"]["q"] == "vela lunettes"


# --------------------------------------------------------------------------- erreurs typées
def test_erreur_cle_invalide():
    client = ClientRecherche(environ={"TAVILY_API_KEY": "tvly-mauvaise"},
                             requete=faux_requete(FauxReponse(401, {"message": "unauthorized"})))
    with pytest.raises(RechercheRefusee):
        client.rechercher("test")


def test_erreur_quota():
    client = ClientRecherche(environ={"BRAVE_SEARCH_API_KEY": "brv-xyz"},
                             requete=faux_requete(FauxReponse(429)))
    with pytest.raises(RechercheRefusee):
        client.rechercher("test")


def test_erreur_reseau():
    client = ClientRecherche(environ={"TAVILY_API_KEY": "tvly-abc"},
                             requete=faux_requete(exc=OSError("connexion refusée")))
    with pytest.raises(RechercheReseau):
        client.rechercher("test")


def test_non_configure_leve():
    client = ClientRecherche(environ={})
    assert client.configure is False
    with pytest.raises(RechercheNonConfiguree):
        client.rechercher("test")


def test_aucun_resultat_ne_leve_pas():
    client = ClientRecherche(environ={"BRAVE_SEARCH_API_KEY": "brv-xyz"},
                             requete=faux_requete(FauxReponse(200, {"web": {"results": []}})))
    res = client.rechercher("requête sans réponse")
    assert "Aucun résultat" in res.text


# --------------------------------------------------------------------------- intégration WebAgent
def _sans_cles(monkeypatch):
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    monkeypatch.delenv("BRAVE_SEARCH_API_KEY", raising=False)


def test_webagent_utilise_api_si_cle(app, monkeypatch):
    """Une clé configurée → chemin API, AUCUN navigateur ouvert (donc aucun anti-robot)."""
    web = app.state.ctx.web
    monkeypatch.setenv("TAVILY_API_KEY", "tvly-abc")

    def faux_browser(visible=False):
        raise AssertionError("le navigateur ne doit PAS s'ouvrir quand l'API répond")

    monkeypatch.setattr(web, "_browser", faux_browser)
    monkeypatch.setattr(recherche_web, "_executer_requete",
                        faux_requete(FauxReponse(200, REPONSE_TAVILY)))
    r = web.search("vela lunettes")
    assert r["query"] == "vela lunettes"
    assert "VELA — site officiel" in r["text"]
    assert r["url"] == "https://vela.app"


def test_webagent_repli_navigateur_sans_cle(app, monkeypatch):
    """Aucune clé → repli sur le navigateur (comportement historique)."""
    _sans_cles(monkeypatch)
    web = app.state.ctx.web
    vus = []

    def faux_browser(visible=False):
        vus.append(visible)
        raise RuntimeError("stop : pas de vrai navigateur en test")

    monkeypatch.setattr(web, "_browser", faux_browser)
    with pytest.raises(RuntimeError):
        web.search("vela lunettes")
    assert vus == [False]  # le repli a bien tenté d'ouvrir le navigateur


def test_webagent_erreur_api_message_typé(app, monkeypatch):
    """Erreur d'API → message clair, pas d'exception crue, pas de bascule silencieuse sur le grattage."""
    web = app.state.ctx.web
    monkeypatch.setenv("TAVILY_API_KEY", "tvly-abc")

    def faux_browser(visible=False):
        raise AssertionError("pas de repli navigateur sur erreur d'API")

    monkeypatch.setattr(web, "_browser", faux_browser)
    monkeypatch.setattr(recherche_web, "_executer_requete",
                        faux_requete(FauxReponse(401, {"message": "clé invalide"})))
    r = web.search("vela lunettes")
    assert "[Recherche indisponible]" in r["text"]
    assert r["url"] == ""
