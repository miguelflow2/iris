"""Connecteur Gemini (SDK google-genai officiel)."""
from __future__ import annotations

import base64
import logging
import time
from typing import AsyncIterator

from .base import BaseConnector, ChatOptions, Chunk, ConnectorError, ToolRunner, ToolSpec

log = logging.getLogger("iris.gemini")

# Modèles GRATUITS seulement (décision de Miguel, 2026-09-14). Vérifiés le 2026-09-14 sur la clé
# de VELA, projet sans facturation : ces modèles répondent ; les modèles « Pro » sont refusés
# (quota 0 sans facturation) et Gemini 2.5 n'est plus ouvert aux nouveaux comptes (404). Un modèle
# hors de cette liste n'est JAMAIS utilisé : `modele_gratuit` retombe sur le défaut.
# Limite à connaître : sur l'offre gratuite, Google peut utiliser les contenus envoyés pour améliorer
# ses produits (conditions de l'API Gemini pour les services non payants).
GEMINI_MODELS = [
    {"id": "gemini-3.8-flash", "label": "Gemini 3.8 Flash (gratuit)"},
    {"id": "gemini-3.6-flash", "label": "Gemini 3.6 Flash (gratuit)"},
    {"id": "gemini-3.5-flash", "label": "Gemini 3.5 Flash (gratuit)"},
    {"id": "gemini-3.5-flash-lite", "label": "Gemini 3.5 Flash-Lite (gratuit, le plus rapide)"},
    {"id": "gemini-3.1-flash-lite", "label": "Gemini 3.1 Flash-Lite (gratuit)"},
]
GEMINI_MODELE_DEFAUT = "gemini-3.5-flash"
GEMINI_GRATUITS = frozenset(m["id"] for m in GEMINI_MODELS)


def modele_gratuit(modele: str | None) -> str:
    """Le modèle demandé s'il est gratuit, sinon le modèle gratuit par défaut."""
    choisi = (modele or "").strip().removeprefix("models/")
    if choisi in GEMINI_GRATUITS:
        return choisi
    if choisi:
        log.warning("modèle Gemini « %s » hors de la liste gratuite : %s utilisé à la place", choisi, GEMINI_MODELE_DEFAUT)
    return GEMINI_MODELE_DEFAUT


def _map_error(exc: Exception) -> ConnectorError:
    code = getattr(exc, "code", None) or getattr(exc, "status_code", None)
    message = getattr(exc, "message", None) or str(exc)
    if code in (401, 403) or "API key not valid" in message or "PERMISSION_DENIED" in message:
        return ConnectorError("Clé API Gemini invalide ou sans accès au modèle.")
    if code == 404 or "NOT_FOUND" in message:
        return ConnectorError("Modèle Gemini introuvable. Vérifiez le nom du modèle.")
    if code == 429 or "RESOURCE_EXHAUSTED" in message:
        return ConnectorError("Limite de débit Gemini atteinte. Réessayez dans un instant.", retryable=True)
    if isinstance(code, int) and code >= 500:
        return ConnectorError(f"Erreur de l'API Gemini ({code}).", retryable=True)
    if "Connect" in message or "timed out" in message.lower():
        return ConnectorError("Impossible de joindre l'API Gemini. Vérifiez la connexion réseau.", retryable=True)
    return ConnectorError(f"Erreur Gemini : {message}")


class GeminiConnector(BaseConnector):
    name = "gemini"
    supports_tools = False

    def _client(self):
        from google import genai

        return genai.Client(api_key=self.api_key)

    @staticmethod
    def _to_contents(messages: list[dict]):
        from google.genai import types

        contents = []
        for m in messages:
            role = "user" if m["role"] == "user" else "model"
            parts = []
            content = m["content"]
            if isinstance(content, str):
                if content.strip():
                    parts.append(types.Part.from_text(text=content))
            else:
                for b in content:
                    if b.get("type") == "text" and b.get("text"):
                        parts.append(types.Part.from_text(text=b["text"]))
                    elif b.get("type") == "image":
                        parts.append(
                            types.Part.from_bytes(data=base64.b64decode(b["data"]), mime_type=b["media_type"])
                        )
            if parts:
                contents.append(types.Content(role=role, parts=parts))
        return contents

    async def stream(
        self,
        messages: list[dict],
        system: str,
        tools: list[ToolSpec] | None = None,
        run_tool: ToolRunner | None = None,
        options: ChatOptions | None = None,
    ) -> AsyncIterator[Chunk]:
        from google.genai import types

        client = self._client()
        contents = self._to_contents(messages)
        config = types.GenerateContentConfig(system_instruction=system)
        try:
            response = await client.aio.models.generate_content_stream(
                model=self.model, contents=contents, config=config
            )
            async for chunk in response:
                text = getattr(chunk, "text", None)
                if text:
                    yield Chunk("text", text=text)
                meta = getattr(chunk, "usage_metadata", None)
                if meta and getattr(meta, "candidates_token_count", None):
                    yield Chunk(
                        "usage",
                        data={
                            "input_tokens": getattr(meta, "prompt_token_count", 0) or 0,
                            "output_tokens": getattr(meta, "candidates_token_count", 0) or 0,
                            "model": self.model,
                        },
                    )
            yield Chunk("done")
        except Exception as exc:
            raise _map_error(exc) from exc

    async def test(self) -> dict:
        started = time.time()
        try:
            client = self._client()
            info = await client.aio.models.get(model=self.model)
            label = getattr(info, "display_name", None) or self.model
            return {
                "ok": True,
                "message": f"Connecté à Gemini — modèle {label}.",
                "model": self.model,
                "latency_ms": int((time.time() - started) * 1000),
            }
        except Exception as exc:
            return {"ok": False, "message": _map_error(exc).message, "model": self.model, "latency_ms": 0}
