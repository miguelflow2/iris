"""Contrat commun des connecteurs d'agents externes."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Awaitable, Callable


@dataclass
class Chunk:
    """Fragment diffusé pendant une réponse.
    kind : text | thinking | tool_use | tool_result | usage | info | done | error
    """

    kind: str
    text: str = ""
    data: dict = field(default_factory=dict)


@dataclass
class ToolSpec:
    name: str
    description: str
    input_schema: dict

    def to_anthropic(self) -> dict:
        return {"name": self.name, "description": self.description, "input_schema": self.input_schema}


@dataclass
class ChatOptions:
    effort: str = "medium"
    thinking_display: bool = True
    max_tokens: int = 16000
    web_search: bool = False  # outil serveur web_search (Claude uniquement)
    model_override: str | None = None
    force_tools: bool = False  # demande d'action : obliger le modèle à appeler un outil au premier tour
    max_rounds: int = 12  # nombre max de tours d'outils (contrôle d'écran / tâches longues : plus)


# run_tool(name, input) -> str | {"content": str | list[dict], "is_error": bool}
ToolRunner = Callable[[str, dict], Awaitable[Any]]


class ConnectorError(Exception):
    def __init__(self, message: str, retryable: bool = False, fatal_key: bool = False):
        super().__init__(message)
        self.message = message
        self.retryable = retryable
        # `fatal_key` : la clé du moteur est morte (invalide, révoquée, sans accès). Le repli
        # automatique bascule alors sur un autre cerveau, sans en informer l'utilisateur.
        self.fatal_key = fatal_key


class BaseConnector(ABC):
    name: str = "base"
    supports_tools: bool = False
    supports_images: bool = True

    def __init__(self, api_key: str | None, model: str, base_url: str | None = None):
        self.api_key = api_key or ""
        self.model = model
        self.base_url = base_url or None

    @abstractmethod
    def stream(
        self,
        messages: list[dict],
        system: str,
        tools: list[ToolSpec] | None = None,
        run_tool: ToolRunner | None = None,
        options: ChatOptions | None = None,
    ) -> AsyncIterator[Chunk]:
        """Diffuse la réponse de l'agent sous forme de Chunks."""

    @abstractmethod
    async def test(self) -> dict:
        """Vérifie la clé et le modèle : {"ok": bool, "message": str, "model": str, "latency_ms": int}."""


def normalize_tool_result(result: Any) -> tuple[Any, bool]:
    """Retourne (content, is_error) à partir de la valeur renvoyée par un outil."""
    if isinstance(result, dict) and "content" in result:
        return result["content"], bool(result.get("is_error"))
    if result is None:
        return "OK", False
    return str(result), False


def preview_text(content: Any, limit: int = 600) -> str:
    if isinstance(content, str):
        text = content
    elif isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(block.get("text", ""))
            elif isinstance(block, dict) and block.get("type") == "image":
                parts.append("[image]")
        text = "\n".join(parts)
    else:
        text = str(content)
    return text if len(text) <= limit else text[:limit] + "…"
