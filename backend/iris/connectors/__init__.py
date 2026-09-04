"""Fabrique de connecteurs : construit le bon client à partir des réglages et du coffre de clés."""
from __future__ import annotations

from ..config import Settings
from ..security.secrets import SecretStore
from .base import BaseConnector, ChatOptions, Chunk, ConnectorError, ToolSpec
from .claude import CLAUDE_MODELS, ClaudeConnector
from .gemini import GEMINI_MODELS, GeminiConnector
from .openai_compat import GPT_MODELS, OPENROUTER_MODELS, OpenAICompatibleConnector, OpenRouterConnector

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
        "key_hint": "AIza…",
        "key_url": "https://aistudio.google.com/app/apikey",
        "needs_key": True,
        "supports_tools": False,
        "models": GEMINI_MODELS,
        "description": "Recherche d'informations récentes, conversation.",
    },
    "custom": {
        "label": "IA locale / perso",
        "vendor": "OpenAI-compatible (Ollama, LM Studio, vLLM…)",
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
    if name == "openrouter":
        return OpenRouterConnector(key, cfg.model or "minimax/minimax-m3:free")
    if name == "claude":
        return ClaudeConnector(key, cfg.model or "claude-opus-5")
    if name == "gpt":
        return OpenAICompatibleConnector(key, cfg.model or "gpt-5", name="gpt", label="GPT", supports_tools=True)
    if name == "gemini":
        return GeminiConnector(key, cfg.model or "gemini-2.5-pro")
    if name == "custom":
        if not cfg.base_url:
            raise ConnectorError("Indiquez l'URL du serveur de votre IA perso (ex. http://127.0.0.1:11434/v1).")
        return OpenAICompatibleConnector(key, cfg.model, base_url=cfg.base_url, name="custom", label=cfg.label or "IA perso", supports_tools=False, include_usage=False)
    raise ConnectorError(f"Moteur IA non pris en charge : {name}")
