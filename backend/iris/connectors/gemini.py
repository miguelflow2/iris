"""Connecteur Gemini (SDK google-genai officiel)."""
from __future__ import annotations

import base64
import logging
import time
from typing import AsyncIterator

from .base import BaseConnector, ChatOptions, Chunk, ConnectorError, ToolRunner, ToolSpec

log = logging.getLogger("iris.gemini")

GEMINI_MODELS = [
    {"id": "gemini-2.5-pro", "label": "Gemini 2.5 Pro"},
    {"id": "gemini-2.5-flash", "label": "Gemini 2.5 Flash"},
]


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
