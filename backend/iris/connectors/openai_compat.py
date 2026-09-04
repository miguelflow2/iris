"""Connecteur OpenAI-compatible : OpenRouter (IA de base d'IRIS), GPT, et tout serveur compatible
(Ollama, LM Studio, vLLM, agents perso). Streaming + appel d'outils (function calling)."""
from __future__ import annotations

import json
import logging
import time
from typing import AsyncIterator

import openai
from openai import AsyncOpenAI

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

log = logging.getLogger("iris.openai")

MAX_TOOL_ROUNDS = 12

GPT_MODELS = [
    {"id": "gpt-5", "label": "GPT-5"},
    {"id": "gpt-5-mini", "label": "GPT-5 mini"},
    {"id": "gpt-4.1", "label": "GPT-4.1"},
    {"id": "gpt-4o", "label": "GPT-4o"},
]

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
OPENROUTER_MODELS = [
    {"id": "minimax/minimax-m3:free", "label": "MiniMax M3 — gratuit, rapide (recommandé)"},
    {"id": "google/gemma-4-31b-it:free", "label": "Gemma 4 31B — gratuit"},
    {"id": "nvidia/nemotron-3.5-lightning:free", "label": "Nemotron 3.5 Lightning — gratuit"},
    {"id": "nvidia/nemotron-3-ultra-550b-a55b:free", "label": "Nemotron 3 Ultra 550B — gratuit, lent"},
    {"id": "z-ai/glm-5.2:free", "label": "GLM 5.2 — gratuit (souvent saturé)"},
    {"id": "openrouter/auto", "label": "Auto (OpenRouter choisit) — payant"},
    {"id": "anthropic/claude-sonnet-5", "label": "Claude Sonnet 5 via OpenRouter — payant"},
    {"id": "openai/gpt-5-mini", "label": "GPT-5 mini via OpenRouter — payant"},
    {"id": "google/gemini-2.5-flash", "label": "Gemini 2.5 Flash via OpenRouter — payant"},
]
# ordre de bascule automatique quand un modèle gratuit est saturé (429) ou indisponible
OPENROUTER_FREE_FALLBACKS = [m["id"] for m in OPENROUTER_MODELS if m["id"].endswith(":free")]


def _to_openai_messages(messages: list[dict]) -> list[dict]:
    out = []
    for m in messages:
        content = m["content"]
        if isinstance(content, str):
            if content.strip():
                out.append({"role": m["role"], "content": content})
            continue
        parts = []
        for b in content:
            if b.get("type") == "text" and b.get("text"):
                parts.append({"type": "text", "text": b["text"]})
            elif b.get("type") == "image":
                parts.append(
                    {"type": "image_url", "image_url": {"url": f"data:{b['media_type']};base64,{b['data']}"}}
                )
        if parts:
            out.append({"role": m["role"], "content": parts})
    return out


def _tool_to_openai(spec: ToolSpec) -> dict:
    return {
        "type": "function",
        "function": {"name": spec.name, "description": spec.description, "parameters": spec.input_schema},
    }


def _map_error(exc: Exception, label: str) -> ConnectorError:
    text = str(getattr(exc, "message", "") or exc)
    if isinstance(exc, openai.AuthenticationError):
        return ConnectorError(f"Clé API {label} invalide ou révoquée.")
    if isinstance(exc, openai.PermissionDeniedError):
        return ConnectorError(f"Cette clé {label} n'a pas accès au modèle demandé.")
    if isinstance(exc, openai.NotFoundError):
        return ConnectorError(f"Modèle {label} introuvable. Vérifiez le nom du modèle.")
    if isinstance(exc, openai.RateLimitError):
        if "insufficient_quota" in text.lower() or "quota" in text.lower() or "credit" in text.lower():
            return ConnectorError(f"Quota {label} épuisé : ajoutez des crédits sur le compte du fournisseur ou choisissez un modèle gratuit.")
        return ConnectorError(f"Limite de débit {label} atteinte (modèle très sollicité). Réessayez dans un instant ou changez de modèle.", retryable=True)
    if isinstance(exc, openai.BadRequestError):
        if "credit" in text.lower() or "insufficient" in text.lower():
            return ConnectorError(f"Crédits {label} insuffisants pour ce modèle : choisissez un modèle gratuit ou rechargez le compte.")
        if "provider returned error" in text.lower() or "provider" in text.lower():
            return ConnectorError(f"{label} : le fournisseur du modèle a renvoyé une erreur passagère.", retryable=True)
        return ConnectorError(f"Requête refusée par {label} : {text}")
    if isinstance(exc, openai.APIStatusError):
        return ConnectorError(f"Erreur de l'API {label} ({exc.status_code}).", retryable=exc.status_code >= 500 or exc.status_code in (408, 409, 425))
    if isinstance(exc, openai.APIConnectionError):
        return ConnectorError(f"Impossible de joindre {label}. Le serveur est-il démarré / le réseau disponible ?", retryable=True)
    return ConnectorError(f"Erreur {label} : {exc}")


class OpenAICompatibleConnector(BaseConnector):
    def __init__(
        self,
        api_key: str | None,
        model: str,
        base_url: str | None = None,
        name: str = "gpt",
        label: str = "GPT",
        supports_tools: bool = True,
        extra_headers: dict | None = None,
        include_usage: bool = True,
    ):
        super().__init__(api_key, model, base_url)
        self.name = name
        self.label = label
        self.supports_tools = supports_tools
        self.extra_headers = extra_headers or {}
        self.include_usage = include_usage

    def _client(self) -> AsyncOpenAI:
        return AsyncOpenAI(
            api_key=self.api_key or "not-needed",
            base_url=self.base_url,
            max_retries=2,
            timeout=600.0,
            default_headers=self.extra_headers or None,
        )

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
        model = opts.model_override or self.model
        payload: list[dict] = [{"role": "system", "content": system}] + _to_openai_messages(messages)
        tool_defs = [_tool_to_openai(t) for t in tools] if (tools and self.supports_tools) else None

        force_first = bool(opts.force_tools and tool_defs and run_tool is not None)
        # Anti-boucle : sans mémoire des appels précédents, un modèle bloqué refait indéfiniment la même action
        # (trace réelle : capture d'écran, clic, alt+tab, répétés jusqu'à l'arrêt de sécurité au 12e tour).
        vus: dict[str, int] = {}
        erreurs_suite = 0
        bloque = False
        for _round in range(max(1, int(opts.max_rounds or MAX_TOOL_ROUNDS))):
            params: dict = {"model": model, "messages": payload, "stream": True}
            if tool_defs:
                params["tools"] = tool_defs
                if _round == 0 and force_first:
                    params["tool_choice"] = "required"
            if self.include_usage:
                params["stream_options"] = {"include_usage": True}
            text_parts: list[str] = []
            calls: dict[int, dict] = {}
            finish = None
            try:
                response = None
                for attempt in range(3):
                    try:
                        response = await client.chat.completions.create(**params)
                        break
                    except (openai.RateLimitError, openai.InternalServerError, openai.APIConnectionError, openai.BadRequestError) as exc:
                        transient = not isinstance(exc, openai.BadRequestError) or "provider" in str(exc).lower()
                        if attempt == 2 or not transient:
                            raise
                        log.info("%s : erreur passagère (%s), nouvel essai dans %.1fs", self.label, type(exc).__name__, 1.5 * (attempt + 1))
                        import asyncio as _asyncio

                        await _asyncio.sleep(1.5 * (attempt + 1))
                async for chunk in response:
                    usage = getattr(chunk, "usage", None)
                    if usage and getattr(usage, "completion_tokens", None) is not None:
                        yield Chunk(
                            "usage",
                            data={
                                "input_tokens": getattr(usage, "prompt_tokens", 0) or 0,
                                "output_tokens": getattr(usage, "completion_tokens", 0) or 0,
                                "model": model,
                            },
                        )
                    if not getattr(chunk, "choices", None):
                        continue
                    choice = chunk.choices[0]
                    delta = choice.delta
                    if delta and delta.content:
                        text_parts.append(delta.content)
                        yield Chunk("text", text=delta.content)
                    reasoning = getattr(delta, "reasoning", None) if delta else None
                    if reasoning:
                        yield Chunk("thinking", text=str(reasoning))
                    for tc in (delta.tool_calls or []) if delta else []:
                        idx = getattr(tc, "index", 0) or 0
                        slot = calls.setdefault(idx, {"id": "", "name": "", "arguments": ""})
                        if tc.id:
                            slot["id"] = tc.id
                        if tc.function:
                            if tc.function.name:
                                slot["name"] += tc.function.name
                            if tc.function.arguments:
                                slot["arguments"] += tc.function.arguments
                    if choice.finish_reason:
                        finish = choice.finish_reason
            except openai.BadRequestError as exc:
                if params.get("tool_choice") == "required":
                    log.info("%s refuse tool_choice=required, nouvel essai en mode auto", self.label)
                    force_first = False
                    continue
                raise _map_error(exc, self.label) from exc
            except openai.APIError as exc:
                raise _map_error(exc, self.label) from exc

            if calls and run_tool is not None:
                assistant_msg: dict = {
                    "role": "assistant",
                    "content": "".join(text_parts) or None,
                    "tool_calls": [
                        {"id": c["id"] or f"call_{i}", "type": "function", "function": {"name": c["name"], "arguments": c["arguments"] or "{}"}}
                        for i, c in sorted(calls.items())
                    ],
                }
                payload.append(assistant_msg)
                image_followups: list[dict] = []
                for i, c in sorted(calls.items()):
                    call_id = c["id"] or f"call_{i}"
                    try:
                        args = json.loads(c["arguments"] or "{}")
                        if not isinstance(args, dict):
                            args = {}
                    except json.JSONDecodeError:
                        args = {}
                    yield Chunk("tool_use", data={"id": call_id, "name": c["name"], "input": args})
                    cle = c["name"] + json.dumps(args, sort_keys=True, ensure_ascii=False)
                    vus[cle] = vus.get(cle, 0) + 1
                    if vus[cle] >= 2:
                        # même outil, mêmes arguments : on ne rejoue pas, on le dit au modèle
                        content = (
                            f"Tu viens de refaire exactement la même action ({c['name']}) sans nouveau résultat. "
                            "Ne la répète pas : change de méthode, ou explique à l'utilisateur ce qui bloque."
                        )
                        is_error = True
                        log.info("appel d'outil répété ignoré : %s", c["name"])
                        if vus[cle] >= 3:
                            bloque = True
                    else:
                        try:
                            raw = await run_tool(c["name"], args)
                            content, is_error = normalize_tool_result(raw)
                        except Exception as exc:
                            log.exception("outil %s en erreur", c["name"])
                            content, is_error = f"Erreur pendant l'exécution de l'outil : {exc}", True
                    erreurs_suite = erreurs_suite + 1 if is_error else 0
                    if erreurs_suite >= 3:
                        bloque = True
                    yield Chunk("tool_result", data={"id": call_id, "name": c["name"], "result": preview_text(content), "is_error": is_error})
                    text_result = content if isinstance(content, str) else preview_text(content, limit=100000)
                    if isinstance(content, list):
                        for block in content:
                            if isinstance(block, dict) and block.get("type") == "image":
                                src = block.get("source", {})
                                image_followups.append(
                                    {"type": "image_url", "image_url": {"url": f"data:{src.get('media_type')};base64,{src.get('data')}"}}
                                )
                    payload.append({"role": "tool", "tool_call_id": call_id, "content": ("ERREUR : " if is_error else "") + str(text_result)})
                if image_followups:
                    payload.append({"role": "user", "content": [{"type": "text", "text": "Voici l'image renvoyée par l'outil :"}, *image_followups]})
                if bloque:
                    yield Chunk("error", text="Je n'arrive pas à aller plus loin : la même action échoue en boucle. Dis-moi autrement ce que tu veux faire.")
                    return
                continue

            if finish == "length":
                yield Chunk("info", text="Réponse tronquée : limite de tokens atteinte.")
            yield Chunk("done")
            return

        yield Chunk("error", text="J'ai enchaîné trop d'actions sans y arriver. Reformule ta demande, ou dis-moi l'étape précise à faire.")

    async def test(self) -> dict:
        client = self._client()
        started = time.time()
        try:
            await client.models.retrieve(self.model)
            return {
                "ok": True,
                "message": f"Connecté à {self.label} — modèle {self.model}.",
                "model": self.model,
                "latency_ms": int((time.time() - started) * 1000),
            }
        except openai.NotFoundError:
            try:
                listing = await client.models.list()
                ids = [m.id for m in listing.data]
                if self.model in ids:
                    return {"ok": True, "message": f"Connecté à {self.label} — modèle {self.model}.", "model": self.model, "latency_ms": int((time.time() - started) * 1000)}
                hint = ", ".join(ids[:8]) if ids else "aucun modèle listé"
                return {"ok": False, "message": f"Modèle {self.model} introuvable. Disponibles : {hint}", "model": self.model, "latency_ms": 0}
            except openai.APIError as exc:
                return {"ok": False, "message": _map_error(exc, self.label).message, "model": self.model, "latency_ms": 0}
        except openai.APIError as exc:
            return {"ok": False, "message": _map_error(exc, self.label).message, "model": self.model, "latency_ms": 0}
        except Exception as exc:
            return {"ok": False, "message": f"Erreur : {exc}", "model": self.model, "latency_ms": 0}


class OpenRouterConnector(OpenAICompatibleConnector):
    """OpenRouter : IA de base d'IRIS (modèles gratuits par défaut), appel d'outils, en-têtes d'attribution."""

    name = "openrouter"

    def __init__(self, api_key: str | None, model: str):
        super().__init__(
            api_key,
            model,
            base_url=OPENROUTER_BASE_URL,
            name="openrouter",
            label="OpenRouter",
            supports_tools=True,
            extra_headers={"HTTP-Referer": "https://vela.app/iris", "X-Title": "IRIS (VELA)"},
            include_usage=True,
        )

    async def stream(self, messages, system, tools=None, run_tool=None, options=None):  # type: ignore[override]
        """Comme le connecteur générique, mais bascule sur le modèle gratuit suivant si le premier est saturé."""
        opts = options or ChatOptions()
        wanted = opts.model_override or self.model
        candidates = [wanted] + [m for m in OPENROUTER_FREE_FALLBACKS if m != wanted] if wanted.endswith(":free") else [wanted]
        for i, model in enumerate(candidates):
            started_output = False
            try:
                local_opts = ChatOptions(**{**opts.__dict__, "model_override": model})
                async for chunk in super().stream(messages, system, tools, run_tool, local_opts):
                    if chunk.kind in ("text", "tool_use", "thinking"):
                        started_output = True
                    yield chunk
                return
            except ConnectorError as exc:
                is_last = i == len(candidates) - 1
                if started_output or not exc.retryable or is_last:
                    raise
                yield Chunk("info", text=f"{model} saturé, bascule sur {candidates[i + 1]}.")

    async def test(self) -> dict:
        """Vérifie la clé (GET /key) puis le modèle ; signale le solde si le modèle est payant."""
        started = time.time()
        try:
            import requests

            resp = await __import__("asyncio").to_thread(
                requests.get, f"{OPENROUTER_BASE_URL}/key", headers={"Authorization": f"Bearer {self.api_key}"}, timeout=20
            )
            if resp.status_code == 401:
                return {"ok": False, "message": "Clé OpenRouter invalide.", "model": self.model, "latency_ms": 0}
            resp.raise_for_status()
            data = resp.json().get("data", {})
            free_tier = bool(data.get("is_free_tier"))
            base = await super().test()
            if base["ok"] and free_tier and not self.model.endswith(":free"):
                base["message"] += " Attention : compte sans crédits, ce modèle est payant — choisissez un modèle « gratuit »."
            elif base["ok"]:
                base["message"] += " (modèle gratuit)" if self.model.endswith(":free") else ""
            base["latency_ms"] = int((time.time() - started) * 1000)
            return base
        except Exception as exc:
            return {"ok": False, "message": f"OpenRouter injoignable : {exc}", "model": self.model, "latency_ms": 0}
