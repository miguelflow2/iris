"""Recherche web par une API OFFICIELLE (accès sanctionné, prévu pour ça, aucun CAPTCHA).

Pourquoi ce module existe
-------------------------
`web.py` `WebAgent.search()` OUVRAIT une page de moteur (DuckDuckGo, Google, Bing) dans le
navigateur piloté et grattait le HTML. Les moteurs répondent à ça par un contrôle anti-robot :
Google et DuckDuckGo bloquent, Bing renvoie du hors-sujet. Résultat, la recherche d'IRIS n'était
pas fiable — et c'est une fonctionnalité clé pour les clients pros.

La solution N'EST PAS de mieux tromper les moteurs. IRIS ne résout JAMAIS de CAPTCHA et ne
contourne JAMAIS une détection de robot. La solution est d'appeler une API de recherche prévue
pour l'usage automatisé, qui rend des résultats propres sans jamais afficher de mur de vérification.

Fournisseurs pris en charge (choisis selon la clé présente)
-----------------------------------------------------------
- Tavily  (POST JSON sur https://api.tavily.com/search, clé TAVILY_API_KEY) — optimisé pour l'IA,
  renvoie des extraits déjà résumés et parfois une réponse directe. PRIVILÉGIÉ s'il est configuré.
- Brave Search (GET https://api.search.brave.com/res/v1/web/search, en-tête X-Subscription-Token,
  clé BRAVE_SEARCH_API_KEY).

D'où viennent les clés
----------------------
1. L'environnement (fichier backend/.env, chargé par config.py) : TAVILY_API_KEY / BRAVE_SEARCH_API_KEY.
2. À défaut, le coffre : SecretStore.get_api_key("recherche"). Le coffre ne connaît qu'UNE entrée
   « recherche » ; pour dire de quel fournisseur elle relève, on accepte un préfixe explicite
   « tavily:… » ou « brave:… ». Sans préfixe, une clé commençant par « tvly- » est reconnue comme
   Tavily ; sinon on suppose Tavily (le fournisseur privilégié).

Aucun secret n'est jamais journalisé. Aucun réseau dans les tests : la requête HTTP passe par un
point d'injection (`requete=`), simulé par les tests.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping

log = logging.getLogger("iris.recherche")

# Noms des variables d'environnement — une seule source de vérité pour le README et le .env.
ENV_TAVILY = "TAVILY_API_KEY"
ENV_BRAVE = "BRAVE_SEARCH_API_KEY"
# Nom de l'entrée dans le coffre (SecretStore.get_api_key).
COFFRE_CLE = "recherche"

URL_TAVILY = "https://api.tavily.com/search"
URL_BRAVE = "https://api.search.brave.com/res/v1/web/search"

DELAI_HTTP = 12.0  # secondes ; au-delà, c'est une coupure réseau, pas une API lente
MAX_RESULTATS = 6


# ------------------------------------------------------------------ erreurs typées
class RechercheError(RuntimeError):
    """Base : tout ce qui empêche une recherche par API d'aboutir."""


class RechercheNonConfiguree(RechercheError):
    """Aucune clé d'API de recherche (ni environnement ni coffre)."""


class RechercheReseau(RechercheError):
    """L'API n'a pas pu être jointe (coupure, DNS, délai dépassé)."""


class RechercheRefusee(RechercheError):
    """L'API a répondu par un refus : clé invalide, quota épuisé, requête rejetée."""


# ------------------------------------------------------------------ résultat
@dataclass
class ResultatRecherche:
    query: str
    url: str  # URL du 1er résultat (ou page de recherche du fournisseur si aucun)
    text: str  # résultats formatés, prêts pour un LLM
    fournisseur: str
    resultats: list[dict] = field(default_factory=list)  # [{titre, url, extrait}]


# (méthode, url, en-têtes, params, corps JSON, délai) -> réponse façon httpx. Injecté dans les
# tests : aucun test de ce module ne touche le réseau.
Requete = Callable[..., Any]


def _executer_requete(methode: str, url: str, *, headers: dict | None = None,
                      params: dict | None = None, json: dict | None = None,
                      timeout: float = DELAI_HTTP) -> Any:
    """Requête HTTP réelle (httpx), importée paresseusement comme partout dans le dépôt."""
    import httpx

    with httpx.Client(timeout=timeout) as client:
        return client.request(methode, url, headers=headers, params=params, json=json)


def resoudre_cle(secrets: Any | None = None, environ: Mapping[str, str] | None = None
                 ) -> tuple[str, str] | None:
    """Rend (fournisseur, clé) selon la clé présente, ou None si rien n'est configuré.

    Priorité : Tavily (env) → Brave (env) → coffre « recherche ». Tavily est privilégié : optimisé
    pour l'IA, il rend des extraits déjà résumés."""
    env = environ if environ is not None else os.environ
    tav = (env.get(ENV_TAVILY) or "").strip()
    if tav:
        return "tavily", tav
    brave = (env.get(ENV_BRAVE) or "").strip()
    if brave:
        return "brave", brave
    if secrets is not None:
        try:
            brut = (secrets.get_api_key(COFFRE_CLE) or "").strip()
        except Exception:  # coffre indisponible : on se comporte comme « non configuré »
            brut = ""
        if brut:
            return _depuis_coffre(brut)
    return None


def _depuis_coffre(valeur: str) -> tuple[str, str]:
    """Interprète l'entrée « recherche » du coffre : préfixe explicite, sinon détection, sinon Tavily."""
    bas = valeur.lower()
    if bas.startswith("tavily:"):
        return "tavily", valeur.split(":", 1)[1].strip()
    if bas.startswith("brave:"):
        return "brave", valeur.split(":", 1)[1].strip()
    if valeur.startswith("tvly-"):
        return "tavily", valeur
    return "tavily", valeur  # à défaut, le fournisseur privilégié


class ClientRecherche:
    """Client de recherche agnostique du fournisseur.

    `requete` permet d'injecter la couche HTTP dans les tests ; en production elle vaut None et
    l'on passe par httpx."""

    def __init__(self, secrets: Any | None = None, *, requete: Requete | None = None,
                 environ: Mapping[str, str] | None = None):
        self.secrets = secrets
        self._requete = requete or _executer_requete
        self._environ = environ

    def fournisseur_actif(self) -> tuple[str, str] | None:
        """(fournisseur, clé) ou None. Sert à décider API vs repli navigateur sans lever."""
        return resoudre_cle(self.secrets, self._environ)

    @property
    def configure(self) -> bool:
        return self.fournisseur_actif() is not None

    def rechercher(self, query: str, max_chars: int = 4000,
                   max_results: int = MAX_RESULTATS) -> ResultatRecherche:
        """Cherche via l'API configurée. Lève une RechercheError typée en cas de problème."""
        query = (query or "").strip()
        if not query:
            raise RechercheRefusee("Aucune requête de recherche fournie.")
        actif = self.fournisseur_actif()
        if actif is None:
            raise RechercheNonConfiguree(
                "Aucune clé d'API de recherche configurée (TAVILY_API_KEY, BRAVE_SEARCH_API_KEY ou coffre)."
            )
        fournisseur, cle = actif
        if fournisseur == "brave":
            resultats, url = self._brave(query, cle, max_results)
        else:
            resultats, url = self._tavily(query, cle, max_results)
        texte = _formater(query, resultats, max_chars)
        return ResultatRecherche(query=query, url=url, text=texte,
                                 fournisseur=fournisseur, resultats=resultats)

    # ------------------------------------------------------------------ fournisseurs
    def _tavily(self, query: str, cle: str, n: int) -> tuple[list[dict], str]:
        corps = {
            "api_key": cle,  # forme classique de Tavily (clé dans le corps)
            "query": query,
            "max_results": max(1, min(n, 10)),
            "search_depth": "basic",
            "include_answer": True,
        }
        # L'en-tête Bearer couvre la variante récente de l'API ; les deux ensemble ne gênent pas.
        entetes = {"Authorization": f"Bearer {cle}", "Content-Type": "application/json"}
        data = self._appeler("POST", URL_TAVILY, headers=entetes, json=corps, fournisseur="Tavily")
        resultats: list[dict] = []
        reponse_directe = (data.get("answer") or "").strip() if isinstance(data, dict) else ""
        if reponse_directe:
            # La réponse résumée de Tavily : posée en tête, c'est souvent la réponse tout court.
            resultats.append({"titre": "Réponse directe", "url": "", "extrait": reponse_directe})
        for item in (data.get("results") or []) if isinstance(data, dict) else []:
            if not isinstance(item, dict):
                continue
            resultats.append({
                "titre": (item.get("title") or "").strip(),
                "url": (item.get("url") or "").strip(),
                "extrait": (item.get("content") or "").strip(),
            })
        url = _premiere_url(resultats) or "https://tavily.com"
        return resultats, url

    def _brave(self, query: str, cle: str, n: int) -> tuple[list[dict], str]:
        params = {"q": query, "count": max(1, min(n, 20))}
        entetes = {"Accept": "application/json", "X-Subscription-Token": cle}
        data = self._appeler("GET", URL_BRAVE, headers=entetes, params=params, fournisseur="Brave")
        resultats: list[dict] = []
        web = (data.get("web") or {}) if isinstance(data, dict) else {}
        for item in (web.get("results") or []):
            if not isinstance(item, dict):
                continue
            resultats.append({
                "titre": (item.get("title") or "").strip(),
                "url": (item.get("url") or "").strip(),
                "extrait": (item.get("description") or "").strip(),
            })
        from urllib.parse import quote_plus
        url = _premiere_url(resultats) or ("https://search.brave.com/search?q=" + quote_plus(query))
        return resultats, url

    # ------------------------------------------------------------------ HTTP + erreurs
    def _appeler(self, methode: str, url: str, *, fournisseur: str, headers: dict,
                 params: dict | None = None, json: dict | None = None) -> dict:
        try:
            resp = self._requete(methode, url, headers=headers, params=params, json=json,
                                  timeout=DELAI_HTTP)
        except RechercheError:
            raise
        except Exception as exc:  # httpx.ConnectError, TimeoutException, DNS… : réseau
            raise RechercheReseau(
                f"{fournisseur} injoignable ({type(exc).__name__}). Vérifie la connexion réseau."
            ) from exc
        code = getattr(resp, "status_code", 0)
        if code in (401, 403):
            raise RechercheRefusee(f"{fournisseur} a refusé la clé d'API (HTTP {code}) : clé invalide ou non autorisée.")
        if code == 429:
            raise RechercheRefusee(f"{fournisseur} a atteint sa limite de requêtes (HTTP 429) : quota épuisé.")
        if code >= 400:
            detail = _extrait_message(resp)
            raise RechercheRefusee(f"{fournisseur} a rejeté la requête (HTTP {code}){detail}.")
        try:
            data = resp.json()
        except Exception as exc:
            raise RechercheRefusee(f"Réponse de {fournisseur} illisible (JSON attendu).") from exc
        if not isinstance(data, dict):
            raise RechercheRefusee(f"Réponse de {fournisseur} inattendue.")
        return data


# ------------------------------------------------------------------ mise en forme
def _premiere_url(resultats: list[dict]) -> str:
    for r in resultats:
        if r.get("url"):
            return r["url"]
    return ""


def _extrait_message(resp: Any) -> str:
    """Petit complément de message d'erreur, sans jamais faire échouer l'appelant."""
    try:
        data = resp.json()
        msg = ""
        if isinstance(data, dict):
            msg = str(data.get("message") or data.get("error") or data.get("detail") or "")
        msg = msg.strip()
        return f" : {msg[:200]}" if msg else ""
    except Exception:
        texte = (getattr(resp, "text", "") or "").strip()
        return f" : {texte[:200]}" if texte else ""


def _formater(query: str, resultats: list[dict], max_chars: int) -> str:
    """Concatène titre + URL + extrait de chaque résultat, prêt à être lu par un LLM."""
    if not resultats:
        return f"Aucun résultat pour « {query} »."
    lignes: list[str] = [f"Résultats de recherche pour « {query} » :", ""]
    n = 0
    for r in resultats:
        titre = r.get("titre") or "(sans titre)"
        url = r.get("url") or ""
        extrait = r.get("extrait") or ""
        n += 1
        lignes.append(f"{n}. {titre}")
        if url:
            lignes.append(f"   {url}")
        if extrait:
            lignes.append(f"   {extrait}")
        lignes.append("")
    texte = "\n".join(lignes).strip()
    if len(texte) > max_chars:
        texte = texte[:max_chars].rstrip() + "…"
    return texte
