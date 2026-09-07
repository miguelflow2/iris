"""Connecteur Claude (SDK Anthropic officiel) : streaming, pensée adaptative, boucle d'outils,
repli serveur en cas de refus de sécurité."""
from __future__ import annotations

import json
import logging
import re
import time
from typing import AsyncIterator

import anthropic

from .base import (
    BaseConnector,
    ChatOptions,
    Chunk,
    ConnectorError,
    ToolRunner,
    ToolSpec,
    normalize_tool_result,
    preview_text,
)

log = logging.getLogger("iris.claude")

FALLBACK_BETA = "server-side-fallback-2026-07-01"
MAX_TOOL_ROUNDS = 12

# Modèles acceptant thinking={"type": "adaptive"} + output_config.effort
_ADAPTIVE = re.compile(r"^claude-(opus-5|opus-4-[678]|sonnet-5|sonnet-4-6|fable|mythos)")

CLAUDE_MODELS = [
    {"id": "claude-opus-5", "label": "Claude Opus 5 (recommandé)"},
    {"id": "claude-sonnet-5", "label": "Claude Sonnet 5 (rapide)"},
    {"id": "claude-fable-5-1", "label": "Claude Fable 5.1 (le plus capable)"},
    {"id": "claude-haiku-4-5", "label": "Claude Haiku 4.5 (léger)"},
]


def _to_anthropic_messages(messages: list[dict]) -> list[dict]:
    out: list[dict] = []
    for m in messages:
        content = m["content"]
        if isinstance(content, str):
            if content.strip():
                out.append({"role": m["role"], "content": content})
            continue
        blocks = []
        for b in content:
            if b.get("type") == "text" and b.get("text"):
                blocks.append({"type": "text", "text": b["text"]})
            elif b.get("type") == "image":
                blocks.append(
                    {
                        "type": "image",
                        "source": {"type": "base64", "media_type": b["media_type"], "data": b["data"]},
                    }
                )
        if blocks:
            out.append({"role": m["role"], "content": blocks})
    return out


def _map_error(exc: Exception) -> ConnectorError:
    if isinstance(exc, anthropic.AuthenticationError):
        return ConnectorError("Le cerveau d'IRIS n'est plus accessible : je bascule sur mon accès de secours.", fatal_key=True)
    if isinstance(exc, anthropic.PermissionDeniedError):
        return ConnectorError("Le cerveau d'IRIS n'a pas accès à ce modèle : je bascule sur mon accès de secours.", fatal_key=True)
    if isinstance(exc, anthropic.NotFoundError):
        return ConnectorError("Le modèle demandé est introuvable : je bascule sur mon accès de secours.", fatal_key=True)
    if isinstance(exc, anthropic.RateLimitError):
        return ConnectorError("Limite de débit Claude atteinte. Réessayez dans un instant.", retryable=True)
    if isinstance(exc, anthropic.BadRequestError):
        if "credit balance" in (exc.message or "").lower():
            return ConnectorError(
                "Votre compte Anthropic n'a plus de crédits API : la clé est valide mais le solde est épuisé. "
                "Ajoutez des crédits sur console.anthropic.com › Plans & Billing, puis réessayez."
            )
        return ConnectorError(f"Requête refusée par l'API Claude : {exc.message}")
    if isinstance(exc, anthropic.APIStatusError):
        return ConnectorError(f"Erreur de l'API Claude ({exc.status_code}).", retryable=exc.status_code >= 500)
    if isinstance(exc, anthropic.APIConnectionError):
        return ConnectorError("Impossible de joindre l'API Claude. Vérifiez la connexion réseau.", retryable=True)
    return ConnectorError(f"Erreur Claude : {exc}")


class ClaudeConnector(BaseConnector):
    name = "claude"
    supports_tools = True
    _use_fallbacks = True  # désactivé automatiquement si le SDK installé ne connaît pas le paramètre

    def _client(self) -> anthropic.AsyncAnthropic:
        return anthropic.AsyncAnthropic(api_key=self.api_key, max_retries=2, timeout=600.0)

    def _supports_adaptive(self) -> bool:
        return bool(_ADAPTIVE.match(self.model))

    async def stream(
        self,
        messages: list[dict],
        system: str,
        tools: list[ToolSpec] | None = None,
        run_tool: ToolRunner | None = None,
        options: ChatOptions | None = None,
    ) -> AsyncIterator[Chunk]:
        opts = options or ChatOptions()
        client = self._client()
        history = _to_anthropic_messages(messages)
        if not history or history[-1]["role"] != "user":
            raise ConnectorError("Le dernier message doit venir de l'utilisateur.")

        model = opts.model_override or self.model
        params: dict = {
            "model": model,
            "max_tokens": opts.max_tokens,
            "system": [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
            "messages": history,
        }
        if _ADAPTIVE.match(model):
            params["thinking"] = {
                "type": "adaptive",
                "display": "summarized" if opts.thinking_display else "omitted",
            }
            params["output_config"] = {"effort": opts.effort}
        tool_defs: list[dict] = []
        if opts.web_search:
            tool_defs.append({"type": "web_search_20260209", "name": "web_search", "max_uses": 5})
        if tools:
            tool_defs.extend(t.to_anthropic() for t in tools)
        if tool_defs:
            params["tools"] = tool_defs

        for _round in range(max(1, int(opts.max_rounds or MAX_TOOL_ROUNDS))):
            holder: dict = {}
            try:
                async for chunk in self._stream_once(client, params, holder):
                    yield chunk
            except TypeError as exc:
                if ClaudeConnector._use_fallbacks and "fallbacks" in str(exc):
                    log.warning("SDK Anthropic sans support 'fallbacks' — désactivation du repli serveur.")
                    ClaudeConnector._use_fallbacks = False
                    async for chunk in self._stream_once(client, params, holder):
                        yield chunk
                else:
                    raise
            except anthropic.APIError as exc:
                raise _map_error(exc) from exc

            final = holder.get("final")
            if final is None:
                raise ConnectorError("Réponse Claude incomplète.")

            usage = getattr(final, "usage", None)
            if usage is not None:
                yield Chunk(
                    "usage",
                    data={
                        "input_tokens": getattr(usage, "input_tokens", 0),
                        "output_tokens": getattr(usage, "output_tokens", 0),
                        "cache_read_input_tokens": getattr(usage, "cache_read_input_tokens", 0) or 0,
                        "cache_creation_input_tokens": getattr(usage, "cache_creation_input_tokens", 0) or 0,
                        "model": getattr(final, "model", self.model),
                    },
                )

            stop = getattr(final, "stop_reason", None)
            if stop == "refusal":
                details = getattr(final, "stop_details", None)
                category = getattr(details, "category", None) if details else None
                explanation = getattr(details, "explanation", None) if details else None
                msg = "Claude a décliné cette demande pour des raisons de sécurité."
                if category:
                    msg += f" (catégorie : {category})"
                if explanation:
                    msg += f" {explanation}"
                yield Chunk("error", text=msg, data={"refusal": True})
                return

            if stop == "pause_turn":
                # outil serveur (recherche web) interrompu : on renvoie le contenu tel quel pour continuer
                params["messages"] = params["messages"] + [{"role": "assistant", "content": final.content}]
                continue

            if stop == "tool_use" and run_tool is not None:
                tool_blocks = [b for b in final.content if getattr(b, "type", "") == "tool_use"]
                if not tool_blocks:
                    yield Chunk("done")
                    return
                params["messages"] = params["messages"] + [{"role": "assistant", "content": final.content}]
                results = []
                for block in tool_blocks:
                    tool_input = block.input if isinstance(block.input, dict) else {}
                    yield Chunk("tool_use", data={"id": block.id, "name": block.name, "input": tool_input})
                    try:
                        raw = await run_tool(block.name, tool_input)
                        content, is_error = normalize_tool_result(raw)
                    except Exception as exc:  # l'outil a planté : on le dit à Claude
                        log.exception("outil %s en erreur", block.name)
                        content, is_error = f"Erreur pendant l'exécution de l'outil : {exc}", True
                    yield Chunk(
                        "tool_result",
                        data={
                            "id": block.id,
                            "name": block.name,
                            "result": preview_text(content),
                            "is_error": is_error,
                        },
                    )
                    results.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": content,
                            "is_error": is_error,
                        }
                    )
                params["messages"] = params["messages"] + [{"role": "user", "content": results}]
                continue

            if stop == "max_tokens":
                yield Chunk("info", text="Réponse tronquée : limite de tokens atteinte.")
            yield Chunk("done")
            return

        yield Chunk("error", text="Trop d'appels d'outils successifs, arrêt de sécurité.")

    async def _stream_once(self, client: anthropic.AsyncAnthropic, params: dict, holder: dict) -> AsyncIterator[Chunk]:
        if ClaudeConnector._use_fallbacks:
            ctx = client.beta.messages.stream(betas=[FALLBACK_BETA], fallbacks="default", **params)
        else:
            ctx = client.messages.stream(**params)
        async with ctx as stream:
            async for event in stream:
                et = getattr(event, "type", "")
                if et == "content_block_start":
                    cb = event.content_block
                    cb_type = getattr(cb, "type", "")
                    if cb_type == "fallback":
                        src = getattr(getattr(cb, "from_", None), "model", "?")
                        dst = getattr(getattr(cb, "to", None), "model", "?")
                        yield Chunk("info", text=f"{src} a décliné ; {dst} prend le relais.")
                    elif cb_type == "server_tool_use":
                        yield Chunk("info", text="Recherche web en cours…", data={"server_tool": getattr(cb, "name", "")})
                    elif cb_type == "web_search_tool_result":
                        content = getattr(cb, "content", None)
                        count = len(content) if isinstance(content, list) else 0
                        yield Chunk("info", text=f"Résultats web reçus ({count}).", data={"server_tool_result": True})
                elif et == "content_block_delta":
                    d = event.delta
                    dt = getattr(d, "type", "")
                    if dt == "text_delta" and d.text:
                        yield Chunk("text", text=d.text)
                    elif dt == "thinking_delta" and getattr(d, "thinking", ""):
                        yield Chunk("thinking", text=d.thinking)
            holder["final"] = await stream.get_final_message()

    async def test(self) -> dict:
        client = self._client()
        started = time.time()
        try:
            info = await client.models.retrieve(self.model)
            label = getattr(info, "display_name", self.model)
            return {
                "ok": True,
                "message": f"Connecté à Claude — modèle {label}.",
                "model": self.model,
                "latency_ms": int((time.time() - started) * 1000),
            }
        except anthropic.APIError as exc:
            err = _map_error(exc)
            return {"ok": False, "message": err.message, "model": self.model, "latency_ms": int((time.time() - started) * 1000)}
        except Exception as exc:
            return {"ok": False, "message": f"Erreur : {exc}", "model": self.model, "latency_ms": 0}


def tool_input_to_json(value: dict) -> str:
    return json.dumps(value, ensure_ascii=False)
