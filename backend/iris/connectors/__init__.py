"""Fabrique de connecteurs : construit le bon client à partir des réglages et du coffre de clés."""
from __future__ import annotations

from ..config import Settings
from ..security.secrets import SecretStore
from .base import BaseConnector, ChatOptions, Chunk, ConnectorError, ToolSpec
from .claude import CLAUDE_MODELS, ClaudeConnector
from .gemini import GEMINI_MODELS, modele_gratuit, GeminiConnector
from .openai_compat import GPT_MODELS, OPENROUTER_MODELS, OpenAICompatibleConnector, OpenRouterConnector, VelaConnector

__all__ = [
    "BaseConnector",
    "ChatOptions",
    "Chunk",
    "ConnectorError",
    "ToolSpec",
    "build_connector",
    "agent_catalog",
]

AGENT_META = {
    "vela": {
        "label": "VELA",
        "vendor": "VELA — inclus dans votre abonnement",
        "key_hint": "",
        "key_url": "",
        "needs_key": False,
        "supports_tools": True,
        "models": [],
        "description": "L'accès IA livré avec IRIS. Aucune clé à coller : le modèle est choisi automatiquement selon votre abonnement.",
    },
    "openrouter": {
        "label": "OpenRouter",
        "vendor": "OpenRouter — IA de base d'IRIS",
        "key_hint": "sk-or-v1-…",
        "key_url": "https://openrouter.ai/keys",
        "needs_key": True,
        "supports_tools": True,
        "models": OPENROUTER_MODELS,
        "description": "Accès à des centaines de modèles avec une seule clé. Modèles gratuits par défaut ; contrôle de l'ordinateur via outils ; bascule automatique si un modèle gratuit est saturé.",
    },
    "claude": {
        "label": "Claude",
        "vendor": "Anthropic",
        "key_hint": "sk-ant-…",
        "key_url": "https://console.anthropic.com/settings/keys",
        "needs_key": True,
        "supports_tools": True,
        "models": CLAUDE_MODELS,
        "description": "Moteur principal d'IRIS : raisonnement, code, et contrôle de l'ordinateur via outils.",
    },
    "gpt": {
        "label": "GPT",
        "vendor": "OpenAI",
        "key_hint": "sk-…",
        "key_url": "https://platform.openai.com/api-keys",
        "needs_key": True,
        "supports_tools": False,
        "models": GPT_MODELS,
        "description": "Conversation et analyse d'images.",
    },
    "gemini": {
        "label": "Gemini",
        "vendor": "Google",
        "key_hint": "AIza… ou AQ.…",
        "key_url": "https://aistudio.google.com/app/apikey",
        "needs_key": True,
        "supports_tools": False,
        "models": GEMINI_MODELS,
        "description": "Recherche d'informations récentes, conversation.",
    },
    "custom": {
        "label": "IA locale / perso",
        "vendor": "Serveur local compatible (Ollama, LM Studio, vLLM…)",
        "key_hint": "(optionnelle)",
        "key_url": "",
        "needs_key": False,
        "supports_tools": False,
        "models": [],
        "description": "Un serveur compatible OpenAI. Marqué « local » : utilisable même en mode 100 % local.",
    },
}


def agent_catalog() -> dict:
    return AGENT_META


# Replis du relais : la MÊME infrastructure VELA, atteinte par une autre entrée. Le domaine
# principal (relais.velaglass.ca) peut être détourné au niveau DNS par un réseau filtré — constaté
# sur le wifi d'un cégep, qui renvoyait le domaine vers une impasse interne (10.1.255.32) alors que
# le relais répondait parfaitement par l'entrée ci-dessous. Aucun fournisseur d'IA n'est nommé ici :
# c'est l'adresse d'hébergement de VELA, neutre. Vider VELA_RELAIS_REPLIS (env) désactive le repli.
import logging as _logging
import os as _os

_log_relais = _logging.getLogger("iris.connectors")

REPLIS_RELAIS_DEFAUT = ["https://vela-relais.onrender.com"]


def _replis_relais() -> list[str]:
    surcharge = (_os.environ.get("VELA_RELAIS_REPLIS") or "").strip()
    if surcharge:
        return [b.strip().rstrip("/") for b in surcharge.split(",") if b.strip()]
    return list(REPLIS_RELAIS_DEFAUT)


def _base_relais_sure(base: str) -> bool:
    """Le canal du relais porte le jeton VELA ET le courriel d'achat : il doit être chiffré.
    On accepte https partout, et http UNIQUEMENT en boucle locale (relais lancé sur le PC même,
    ex. http://127.0.0.1:8100). Un http DISTANT est refusé — sinon un repli injecté détournerait
    ces secrets en clair vers un tiers, sans le moindre avertissement de rétrogradation."""
    from urllib.parse import urlsplit

    try:
        parts = urlsplit(base)
    except Exception:
        return False
    if parts.scheme == "https":
        return True
    if parts.scheme == "http":
        return (parts.hostname or "").lower() in ("127.0.0.1", "::1", "localhost")
    return False


def bases_relais(settings: Settings) -> list[str]:
    """Le relais principal (réglages de l'utilisateur) puis ses replis, dédoublonnés et filtrés :
    une base http distante (jeton/courriel en clair) est écartée avec un avertissement."""
    vus: list[str] = []
    for brut in [settings.user.relay_server, *_replis_relais()]:
        base = (brut or "").strip().rstrip("/")
        if not base or base in vus:
            continue
        if not _base_relais_sure(base):
            _log_relais.warning("base de relais ignorée (http distant : jeton en clair refusé) : %s", base)
            continue
        vus.append(base)
    return vus


def resoudre_relais(settings: Settings, timeout: float = 4.0) -> str:
    """Trouve la première base de relais dont /sante répond, et la mémorise dans settings si c'est
    un repli (le principal reste la valeur de référence). Purement additif : si le principal répond,
    l'override reste vide et le comportement est identique à avant. Rend la base retenue.

    Appelé au démarrage. Un échec réseau total ne casse rien : on garde le principal, et IRIS
    retombe de toute façon sur les moteurs déjà configurés (voir AppContext.assurer_acces_vela)."""
    import httpx

    bases = bases_relais(settings)
    if not bases:
        return ""
    principal = bases[0]
    for base in bases:
        try:
            r = httpx.get(f"{base}/sante", timeout=timeout)
            if r.status_code == 200 and bool(r.json().get("ok")):
                settings.relay_base_override = "" if base == principal else base
                if base != principal:
                    _log_relais.info(
                        "relais principal injoignable sur ce réseau ; repli actif sur %s "
                        "(le domaine principal reprend dès qu'il résout).", base,
                    )
                return base
        except Exception:
            continue
    # Aucune base ne répond (hors ligne, ou tout est filtré) : on ne fixe pas d'override, on garde
    # le principal. Ce n'est pas une panne d'IRIS — juste l'absence de réseau à cet instant.
    settings.relay_base_override = ""
    return principal


def base_relais_effective(settings: Settings) -> str:
    """La base de relais à utiliser MAINTENANT : le repli résolu s'il existe, sinon le principal.
    Le principal est soumis au même contrôle de sûreté (pas de http distant portant le jeton)."""
    override = (getattr(settings, "relay_base_override", "") or "").strip().rstrip("/")
    if override:
        return override  # déjà validé par bases_relais lors de la résolution
    principal = (settings.user.relay_server or "").strip().rstrip("/")
    if principal and not _base_relais_sure(principal):
        _log_relais.warning("relais principal http distant ignoré (jeton en clair refusé) : %s", principal)
        return ""
    return principal


def build_connector(name: str, settings: Settings, secrets: SecretStore) -> BaseConnector:
    cfg = settings.user.agent(name)
    meta = AGENT_META.get(name)
    if meta is None:
        raise ConnectorError(f"Moteur IA inconnu : {name}")
    if not cfg.active:
        raise ConnectorError(f"Le moteur IA {cfg.label or meta['label']} n'est pas activé. Activez-le dans Réglages › Moteurs IA.")
    key = secrets.get_api_key(name)
    if meta["needs_key"] and not key:
        raise ConnectorError(f"Aucune clé API configurée pour {meta['label']}. Ajoutez-la dans Réglages › Moteurs IA.")
    if name == "vela":
        # Base effective : le repli résolu au démarrage si le domaine principal était détourné sur
        # ce réseau, sinon le domaine principal. Transparent pour l'utilisateur.
        base = base_relais_effective(settings)
        if not base:
            raise ConnectorError("Aucun relais VELA n'est configuré. Ajoutez votre propre clé dans Réglages › Moteurs IA.")
        if not key:
            raise ConnectorError("IRIS n'a pas encore obtenu son accès VELA. Vérifiez la connexion Internet, puis relancez-la.")
        return VelaConnector(key, cfg.model, base_url=base + "/v1")
    if name == "openrouter":
        return OpenRouterConnector(key, cfg.model or "minimax/minimax-m3:free")
    if name == "claude":
        return ClaudeConnector(key, cfg.model or "claude-opus-5")
    if name == "gpt":
        return OpenAICompatibleConnector(key, cfg.model or "gpt-5", name="gpt", label="GPT", supports_tools=True)
    if name == "gemini":
        return GeminiConnector(key, modele_gratuit(cfg.model))
    if name == "custom":
        if not cfg.base_url:
            raise ConnectorError("Indiquez l'URL du serveur de votre IA perso (ex. http://127.0.0.1:11434/v1).")
        return OpenAICompatibleConnector(key, cfg.model, base_url=cfg.base_url, name="custom", label=cfg.label or "IA perso", supports_tools=False, include_usage=False)
    raise ConnectorError(f"Moteur IA non pris en charge : {name}")
