"""API locale IRIS (FastAPI) : REST + WebSocket, protégée par un jeton de session."""
from __future__ import annotations

import asyncio
import base64
import logging
import os
import platform
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, Response
from pydantic import BaseModel, Field

from . import __version__
from .capture import CaptureIndicator
from .chat import ChatService
from .config import AGENT_NAMES, Settings, write_env_value
from .connectors import ConnectorError, agent_catalog, build_connector
from .consent import DATA_TYPES, ConsentGate
from .db import Database
from .events import EventHub
from .glasses import GlassesService
from .memory import MemoryService
from .plans import PLANS, PlanService
from .licence import LicenceSync
from .comptes import Comptes
from .mobile import AGENT_SERVICE, MANIFESTE, PAGE as PAGE_MOBILE, urls_locales
from .presence import Presence
from .watch import WatchService
from .reminders import ReminderService
from .routines import RoutineService
from .pc import actions
from .router import AgentRouter
from .security.crypto import Crypto, load_master_key
from .security.secrets import SecretStore
from .tasks import TaskService
from .web import WebAgent
from .voice import stt
from .voice.listener import VoiceListener
from .voice.tts import TextToSpeech

log = logging.getLogger("iris.api")


def session_reelle() -> bool:
    """L'application a-t-elle lancé ce backend pour une vraie session ?

    Deux préparatifs partent sur le réseau au démarrage : le modèle vocal (41 Mo) et le jeton
    d'accès VELA. Ils ont leur place quand un utilisateur ouvre IRIS, nulle part ailleurs. Sans
    ce garde-fou, la suite de tests téléchargeait le modèle une fois par client et remplissait
    le disque — c'est arrivé. Le drapeau est posé par electron/main/backend.ts, et par lui seul."""
    return os.environ.get("IRIS_AUTO_SETUP", "") == "1"


def courriel_du_jeton(jeton: str) -> str | None:
    """Le courriel encodé dans un jeton d'appareil VELA. Sert à savoir s'il faut en redemander un
    après que l'utilisateur a renseigné son courriel d'achat."""
    try:
        tete = (jeton or "").split(".", 1)[0]
        return base64.urlsafe_b64decode(tete + "=" * (-len(tete) % 4)).decode(errors="replace").lower()
    except Exception:
        return None


class AppContext:
    def __init__(self, data_dir: Path | None, use_keyring: bool = True, enable_tts: bool = True):
        self.settings = Settings(data_dir)
        self.db = Database(self.settings.db_path)
        key, self.key_source = load_master_key(self.settings.data_dir, use_keyring=use_keyring)
        self.crypto = Crypto(key)
        self.secrets = SecretStore(self.crypto, self.settings.data_dir, use_keyring=use_keyring)
        self.hub = EventHub()
        self.consent = ConsentGate(self.db, self.settings, self.hub)
        self.capture = CaptureIndicator(self.hub)
        self.memory = MemoryService(self.db, self.crypto, self.settings)
        self.router = AgentRouter(self.settings)
        self.tts = TextToSpeech(self.settings, self.hub, enabled=enable_tts)
        self.chat = ChatService(
            self.db, self.crypto, self.settings, self.secrets, self.consent, self.hub, self.memory, self.router, self.capture
        )
        self.tasks = TaskService(self.db, self.crypto, self.hub, self.chat, announce=self._announce)
        self.voice = VoiceListener(self.settings, self.hub, self.consent, self.capture, self.tts, self._voice_command)
        self.glasses = GlassesService(self.settings, self.hub, self.capture)
        self.routines = RoutineService(self.db, self.hub)
        self.reminders = ReminderService(self.db, self.hub, announce=self._announce)
        self.chat.routines = self.routines
        self.chat.reminders = self.reminders
        self.web = WebAgent(self.settings, self.hub, self.secrets)
        self.chat.web = self.web
        self.plans = PlanService(self.db, self.settings, self.hub, secrets=self.secrets)
        self.chat.plans = self.plans
        self.tts.plans = self.plans
        # Présence : IRIS vit sur cet appareil et se souvient de sa propre continuité entre deux lancements.
        self.comptes = Comptes(self.settings.data_dir)
        self.presence = Presence(self.db)
        self.chat.presence = self.presence
        # Abonnement : activation et renouvellement automatiques, sans que le client copie une clé.
        self.licence = LicenceSync(self.settings, self.plans, self.hub)
        # Veille : surveille une conversation ou une page dans la durée, analyse, et prépare la décision.
        self.watch = WatchService(
            self.db, self.crypto, self.hub, web=self.web,
            analyse=self.chat.analyse_veille, announce=self._announce,
        )
        self.chat.watches = self.watch
        self._summary_done_for: str | None = None
        self._voice_conv_id: str | None = None
        self._purge_task: asyncio.Task | None = None

    def _announce(self, text: str) -> None:
        self.tts.speak(text)

    def voice_conversation(self) -> dict:
        if self._voice_conv_id:
            conv = self.chat.get_conversation(self._voice_conv_id)
            if conv:
                return conv
        rows = self.db.query("SELECT * FROM conversations WHERE kind='voice' ORDER BY updated_at DESC LIMIT 1")
        if rows:
            self._voice_conv_id = rows[0]["id"]
            return self.chat.get_conversation(self._voice_conv_id)  # type: ignore[return-value]
        conv = self.chat.create_conversation(title="Voix", agent="auto", kind="voice")
        self._voice_conv_id = conv["id"]
        return conv

    async def _voice_command(self, text: str) -> dict:
        """Traite une commande vocale : réponse lue phrase par phrase pendant le streaming."""
        conv = self.voice_conversation()
        speak = (lambda s: self.tts.speak(s, force=True)) if self.tts.available else None
        result = await self.chat.run_and_wait(conv["id"], text, agent="auto", source="voice", speak=speak)
        if result.get("consent_required"):
            msg = "Je ne peux pas envoyer cette demande : le consentement n'est pas accordé. Ouvrez Confidentialité dans IRIS."
            return {"text": msg, "spoken": False}
        message_text = (result.get("message") or {}).get("text") or ""
        if result.get("error") and not message_text:
            return {"text": result["error"], "spoken": bool(speak)}
        return {"text": message_text, "spoken": bool(result.get("spoken"))}

    async def _watch_loop(self) -> None:
        """Fait tourner les veilles arrivées à échéance. Une veille qui échoue n'arrête pas les autres."""
        await asyncio.sleep(45)  # laisser le démarrage et le navigateur se mettre en place
        while True:
            try:
                if not self.settings.user.privacy_mode:
                    for w in self.watch.due():
                        try:
                            await self.watch.check(w["id"])
                        except Exception as exc:
                            log.info("veille « %s » en erreur : %s", w["name"], exc)
                        await asyncio.sleep(2)  # on n'enchaîne pas les pages à la file
            except Exception as exc:  # pragma: no cover
                log.debug("boucle de veille : %s", exc)
            await asyncio.sleep(60)

    async def _licence_loop(self) -> None:
        """Vérifie l'abonnement au démarrage puis une fois par jour : activation, renouvellement, expiration.
        Tout échec est sans conséquence, le plan déjà activé reste en place."""
        await asyncio.sleep(20)  # laisser le démarrage se terminer
        while True:
            try:
                self.licence.check_expiry()
                await asyncio.to_thread(self.assurer_acces_vela)
                if self.licence.configured:
                    await asyncio.to_thread(self.licence.sync)
            except Exception as exc:  # pragma: no cover
                log.debug("vérification d'abonnement : %s", exc)
            await asyncio.sleep(24 * 3600)

    async def _presence_heartbeat(self) -> None:
        """Marque régulièrement qu'IRIS est vivante : au prochain démarrage, elle saura depuis quand elle
        était absente et pourra le dire à l'utilisateur."""
        while True:
            await asyncio.sleep(60)
            try:
                self.presence.heartbeat()
            except Exception as exc:  # pragma: no cover
                log.debug("battement de présence : %s", exc)

    async def _voice_watchdog(self) -> None:
        """Relance l'écoute si elle s'est arrêtée toute seule (auto-démarrage actif, pas d'arrêt volontaire)."""
        while True:
            await asyncio.sleep(20)
            try:
                u = self.settings.user
                if self.tts.eleven.configured and not self.tts.eleven.available:
                    await asyncio.to_thread(self.tts.eleven.retry_if_disabled)
                if u.privacy_mode:
                    continue
                pause_over = self.voice.paused_until and time.time() > self.voice.paused_until
                if u.voice_autostart and not self.voice.running and not self.voice.muted and (not self.voice.stopped_by_user or pause_over):
                    if self.voice.model_ready() or self.consent.is_granted("audio_raw"):
                        log.info("chien de garde : redémarrage de l'écoute vocale")
                        self.voice.start()
            except Exception as exc:  # pragma: no cover
                log.warning("chien de garde vocal: %s", exc)

    def assurer_acces_vela(self) -> None:
        """Obtient auprès du relais VELA le jeton qui donne accès à l'IA.

        C'est ce qui remplace la demande de clé OpenRouter à l'accueil. L'accès fait partie de ce
        qu'on vend : il est fourni, pas apporté par le client. Le jeton ne vaut que pour cet
        appareil, et c'est le relais qui décide quel modèle répond, selon l'abonnement rattaché
        au courriel. Un échec ne casse rien : IRIS retombe sur les moteurs déjà configurés."""
        if not session_reelle():
            return
        base = (self.settings.user.relay_server or "").strip().rstrip("/")
        if not base or self.settings.user.local_only:
            return
        courriel = (self.settings.user.licence_email or "").strip().lower()
        actuel = self.secrets.get_api_key("vela")
        if actuel and courriel_du_jeton(actuel) == courriel:
            return  # déjà obtenu, et pour le bon courriel
        try:
            import uuid

            import httpx

            with httpx.Client(timeout=15) as client:
                resp = client.post(f"{base}/api/appareil", json={"machine": f"{uuid.getnode():x}", "email": courriel})
            resp.raise_for_status()
            jeton = (resp.json().get("jeton") or "").strip()
            if not jeton:
                raise ValueError("le relais n'a pas renvoyé de jeton")
            self.secrets.set_api_key("vela", jeton)
            log.info("accès IA VELA obtenu (plan %s)", resp.json().get("plan", "?"))
        except Exception as exc:
            log.info("relais VELA injoignable (%s) : IRIS utilisera les moteurs déjà configurés", exc)

    def assurer_modele_vocal(self) -> None:
        """Télécharge le modèle de reconnaissance vocale s'il manque. Sans rien demander.

        Constat réel sur une installation neuve : le modèle n'arrivait que si l'utilisateur
        cliquait « Télécharger » dans la dernière étape de l'accueil. Sans lui, le moteur refuse
        de démarrer — le micro s'ouvre, plus rien n'est entendu, et aucun message ne l'explique.
        Une assistante vocale qui n'entend pas n'est pas un réglage avancé, c'est une panne.

        Aucune donnée ne part : on récupère un fichier de modèle, et c'est justement lui qui
        permet ensuite de tout reconnaître sur l'appareil, sans réseau."""
        if not session_reelle():
            return
        langue = self.settings.user.language
        if stt.model_dir(self.settings.models_dir, langue) is not None:
            return
        try:
            log.info("modèle vocal absent : téléchargement automatique (%s)", langue)
            self.hub.publish("voice.model_progress", done=0, total=0, language=langue)

            def progress(done: int, total: int) -> None:
                self.hub.publish("voice.model_progress", done=done, total=total, language=langue)

            stt.download_model(self.settings.models_dir, langue, progress)
            self.voice.error = None
            self.hub.publish("voice.model_ready", language=langue, ready=True)
            if self.settings.user.voice_autostart and not self.voice.running:
                self.voice.start()
            self.hub.publish("voice.state", **self.voice.status())
            log.info("modèle vocal installé : IRIS entend")
        except Exception as exc:
            log.warning("téléchargement automatique du modèle vocal impossible : %s", exc)
            self.hub.publish("voice.model_ready", language=langue, ready=False, error=str(exc))

    async def _daily_summary_loop(self) -> None:
        from datetime import date, datetime

        while True:
            await asyncio.sleep(60)
            try:
                u = self.settings.user
                if not u.daily_summary_enabled:
                    continue
                now = datetime.now()
                today = date.today().isoformat()
                if now.strftime("%H:%M") >= (u.daily_summary_time or "21:00") and self._summary_done_for != today:
                    self._summary_done_for = today
                    result = await self.chat.summarize_day(today)
                    if result.get("stored"):
                        self.tts.speak("Le résumé de ta journée est prêt dans ta mémoire.")
            except Exception as exc:
                log.warning("résumé quotidien: %s", exc)

    async def _periodic_purge(self) -> None:
        while True:
            try:
                purged = await asyncio.to_thread(self.memory.purge_expired)
                if any(purged.values()):
                    self.hub.publish("privacy.purged", **purged)
            except Exception as exc:  # pragma: no cover
                log.warning("purge en erreur: %s", exc)
            await asyncio.sleep(3600)

    def status(self) -> dict:
        u = self.settings.user
        return {
            "name": u.assistant_name,
            "version": __version__,
            "data_dir": str(self.settings.data_dir),
            "key_source": self.key_source,
            "secrets_backend": self.secrets.backend,
            "platform": f"{platform.system()} {platform.release()}",
            "local_only": u.local_only,
            "onboarded": u.onboarded,
            "agents_available": self.router.available(self.secrets),
            "consent": self.consent.status(),
            "capture": self.capture.snapshot(),
            "voice": self.voice.status(),
            "glasses": {k: self.glasses.status()[k] for k in ("connected", "device", "battery", "remembered")},
            "memory_count": self.memory.count(),
            "plan": {"plan": self.plans.plan, "label": PLANS[self.plans.plan]["label"], "usage": self.plans.usage()},
            "presence": self.presence.info(),
            "ws_clients": self.hub.client_count,
        }

    def close(self) -> None:
        try:
            self.web.close()
        except Exception:
            pass
        try:
            self.voice.stop()
        except Exception:
            pass
        try:
            self.tts.shutdown()
        except Exception:
            pass
        self.db.close()


# ---------------------------------------------------------------------- modèles d'entrée
class MotDePasse(BaseModel):
    mot_de_passe: str = ""
    nouveau: str = ""
    nom: str = ""


class WatchBody(BaseModel):
    name: str
    url: str
    criteria: str
    interval_min: int = 15
    site: str = ""


class SettingsPatch(BaseModel):
    model_config = {"extra": "allow"}


class AgentUpdate(BaseModel):
    active: bool | None = None
    model: str | None = None
    base_url: str | None = None
    label: str | None = None
    api_key: str | None = None


class ConversationCreate(BaseModel):
    title: str | None = None
    agent: str = "auto"


class ConversationPatch(BaseModel):
    title: str | None = None
    agent: str | None = None
    archived: bool | None = None


class ImageIn(BaseModel):
    media_type: str
    data: str


class MessageIn(BaseModel):
    text: str = ""
    images: list[ImageIn] = Field(default_factory=list)
    agent: str = "auto"


class ConfirmIn(BaseModel):
    confirm_id: str
    approved: bool


class MemoryIn(BaseModel):
    text: str


class ConsentIn(BaseModel):
    granted: bool


class TaskIn(BaseModel):
    title: str
    instructions: str
    agent: str = "auto"


class SayIn(BaseModel):
    text: str


class ModelDownloadIn(BaseModel):
    language: str | None = None


class ElevenKeyIn(BaseModel):
    api_key: str


class LicenseIn(BaseModel):
    key: str


class DemoPlanIn(BaseModel):
    plan: str


class SiteIn(BaseModel):
    url: str
    username: str = ""
    password: str | None = None
    label: str | None = None


class RoutineIn(BaseModel):
    name: str
    trigger: str | None = None
    steps: list[dict] = Field(default_factory=list)


class RecordIn(BaseModel):
    name: str
    trigger: str | None = None


class ReminderIn(BaseModel):
    text: str
    minutes: float | None = None
    at: str | None = None


class CalibrateIn(BaseModel):
    count: int = 3


class SummaryIn(BaseModel):
    day: str | None = None


class GlassesScanIn(BaseModel):
    seconds: float = 6.0


class GlassesConnectIn(BaseModel):
    address: str
    name: str | None = None
    attempts: int = 3


class GlassesPrefsIn(BaseModel):
    auto_connect: bool | None = None
    audio_input_device: str | None = None
    audio_output_device: str | None = None


# ---------------------------------------------------------------------- application
def create_app(
    data_dir: Path | None = None, token: str | None = None, use_keyring: bool = True, enable_tts: bool = True
) -> FastAPI:
    ctx = AppContext(data_dir, use_keyring=use_keyring, enable_tts=enable_tts)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        loop = asyncio.get_running_loop()
        ctx.hub.bind_loop(loop)
        ctx.voice.loop = loop
        ctx._purge_task = loop.create_task(ctx._periodic_purge())
        ctx.presence.start_session()
        heartbeat_task = loop.create_task(ctx._presence_heartbeat())
        licence_task = loop.create_task(ctx._licence_loop())
        watch_task = loop.create_task(ctx._watch_loop())
        watchdog_task = loop.create_task(ctx._voice_watchdog())
        reminders_task = loop.create_task(ctx.reminders.loop())
        summary_task = loop.create_task(ctx._daily_summary_loop())
        threading.Thread(target=ctx.tts.eleven.prewarm, name="iris-eleven-prewarm", daemon=True).start()
        from .pc.apps import index as app_index

        threading.Thread(target=app_index.build, name="iris-apps-index", daemon=True).start()
        threading.Thread(target=ctx.assurer_modele_vocal, name="iris-modele-vocal", daemon=True).start()
        threading.Thread(target=ctx.assurer_acces_vela, name="iris-acces-vela", daemon=True).start()
        if ctx.settings.user.voice_autostart and not ctx.settings.user.privacy_mode:
            loop.call_later(1.0, ctx.voice.start)
        glasses_task = loop.create_task(ctx.glasses.auto_connect_on_start())
        try:
            yield
        finally:
            reminders_task.cancel()
            summary_task.cancel()
            watchdog_task.cancel()
            glasses_task.cancel()
            if ctx._purge_task:
                ctx._purge_task.cancel()
            try:
                await ctx.glasses.close()
            except Exception:
                pass
            ctx.close()

    app = FastAPI(title="IRIS Backend", version=__version__, lifespan=lifespan, docs_url=None, redoc_url=None)
    app.state.ctx = ctx
    app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

    def require_token(request: Request) -> None:
        if token is None:
            return
        header = request.headers.get("authorization", "")
        supplied = header[7:] if header.lower().startswith("bearer ") else request.query_params.get("token", "")
        # Un jeton de session ouvert avec le mot de passe donne les mêmes droits : c'est par là
        # que passe le téléphone, pour que l'adresse seule ne suffise jamais.
        if supplied and supplied != token and ctx.comptes.session_valide(supplied):
            return
        if supplied != token:
            raise HTTPException(status_code=401, detail="jeton de session invalide")

    auth = [Depends(require_token)]

    @app.exception_handler(ConnectorError)
    async def _connector_error(_req: Request, exc: ConnectorError):
        return JSONResponse(status_code=400, content={"detail": exc.message, "retryable": exc.retryable})

    @app.exception_handler(ValueError)
    async def _value_error(_req: Request, exc: ValueError):
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    # ------------------------------------------------------------------ santé / statut
    @app.get("/api/health")
    def health():
        return {"ok": True, "name": "IRIS", "version": __version__}

    @app.get("/api/status", dependencies=auth)
    def status():
        return ctx.status()

    # ------------------------------------------------------------------ réglages
    @app.get("/api/settings", dependencies=auth)
    def get_settings():
        return ctx.settings.user.model_dump()

    @app.patch("/api/settings", dependencies=auth)
    def patch_settings(patch: SettingsPatch):
        data = patch.model_dump()
        before = ctx.settings.user
        restart_voice = ctx.voice.running and any(
            k in data and data[k] != getattr(before, k) for k in ("wake_word", "language", "stt_engine", "local_only")
        )
        user = ctx.settings.update(data)
        ctx.hub.publish("settings.updated", settings=user.model_dump())
        if restart_voice:
            ctx.voice.stop(by_user=False)
            ctx.voice.start()
        if "local_only" in data:
            ctx.consent.log("local_only_enabled" if user.local_only else "local_only_disabled")
        if "privacy_mode" in data:
            apply_privacy_mode(user.privacy_mode)
        return user.model_dump()

    def apply_privacy_mode(enabled: bool) -> None:
        """Mode confidentiel : coupe le micro (et empêche toute relance) tant qu'il est actif."""
        if enabled:
            ctx.voice.stop(by_user=True)
            ctx.tts.stop()
            ctx.capture.set(mic=False, listening=False, screen=False, camera=False)
            ctx.consent.log("privacy_mode_enabled")
        else:
            ctx.consent.log("privacy_mode_disabled")
            if ctx.settings.user.voice_autostart:
                ctx.voice.start()
        ctx.hub.publish("privacy.mode", enabled=enabled)

    # ------------------------------------------------------------------ agents
    def agent_view(name: str) -> dict:
        meta = agent_catalog()[name]
        cfg = ctx.settings.user.agent(name)
        key = ctx.secrets.get_api_key(name)
        return {
            "name": name,
            **meta,
            "label": cfg.label or meta["label"],
            "active": cfg.active,
            "model": cfg.model,
            "base_url": cfg.base_url,
            "local": cfg.local,
            "has_key": bool(key),
            "key_masked": SecretStore.mask(key),
            "ready": name in ctx.router.available(ctx.secrets),
        }

    @app.get("/api/agents", dependencies=auth)
    def list_agents():
        return {"agents": [agent_view(n) for n in AGENT_NAMES], "default_agent": ctx.settings.user.default_agent}

    @app.put("/api/agents/{name}", dependencies=auth)
    def update_agent(name: str, body: AgentUpdate):
        if name not in AGENT_NAMES:
            raise HTTPException(404, "moteur IA inconnu")
        patch = {k: v for k, v in body.model_dump().items() if v is not None and k != "api_key"}
        if body.api_key is not None:
            ctx.secrets.set_api_key(name, body.api_key)
            ctx.consent.log("api_key_updated" if body.api_key else "api_key_removed", agent=name)
        if patch:
            ctx.settings.update({"agents": {name: patch}})
        view = agent_view(name)
        ctx.hub.publish("agent.updated", agent=view)
        return view

    @app.delete("/api/agents/{name}/key", dependencies=auth)
    def delete_agent_key(name: str):
        if name not in AGENT_NAMES:
            raise HTTPException(404, "moteur IA inconnu")
        ctx.secrets.delete_api_key(name)
        ctx.consent.log("api_key_removed", agent=name)
        view = agent_view(name)
        ctx.hub.publish("agent.updated", agent=view)
        return view

    @app.post("/api/agents/{name}/test", dependencies=auth)
    async def test_agent(name: str):
        if name not in AGENT_NAMES:
            raise HTTPException(404, "moteur IA inconnu")
        cfg = ctx.settings.user.agent(name)
        was_active = cfg.active
        if not was_active:
            ctx.settings.update({"agents": {name: {"active": True}}})
        try:
            connector = build_connector(name, ctx.settings, ctx.secrets)
            result = await connector.test()
        except ConnectorError as exc:
            result = {"ok": False, "message": exc.message, "model": cfg.model, "latency_ms": 0}
        finally:
            if not was_active:
                ctx.settings.update({"agents": {name: {"active": False}}})
        ctx.consent.log("agent_test", agent=name, detail=result["message"])
        return result

    # ------------------------------------------------------------------ conversations
    @app.get("/api/conversations", dependencies=auth)
    def list_conversations(kind: str = "chat", archived: bool = False):
        return {
            "conversations": ctx.chat.list_conversations(kind=kind, archived=archived),
            "archived_count": ctx.chat.count_conversations(kind=kind, archived=True),
        }

    @app.post("/api/conversations", dependencies=auth)
    def create_conversation(body: ConversationCreate):
        return ctx.chat.create_conversation(title=body.title, agent=body.agent)

    @app.get("/api/conversations/voice", dependencies=auth)
    def voice_conversation():
        conv = ctx.voice_conversation()
        return {**conv, "messages": ctx.chat.messages(conv["id"])}

    @app.get("/api/conversations/{conv_id}", dependencies=auth)
    def get_conversation(conv_id: str):
        conv = ctx.chat.get_conversation(conv_id)
        if not conv:
            raise HTTPException(404, "conversation introuvable")
        return {**conv, "messages": ctx.chat.messages(conv_id)}

    @app.patch("/api/conversations/{conv_id}", dependencies=auth)
    def patch_conversation(conv_id: str, body: ConversationPatch):
        conv = ctx.chat.update_conversation(conv_id, title=body.title, agent=body.agent, archived=body.archived)
        if not conv:
            raise HTTPException(404, "conversation introuvable")
        return conv

    @app.delete("/api/conversations/{conv_id}", dependencies=auth)
    def delete_conversation(conv_id: str):
        if not ctx.chat.delete_conversation(conv_id):
            raise HTTPException(404, "conversation introuvable")
        return {"deleted": True}

    @app.post("/api/conversations/{conv_id}/messages", dependencies=auth)
    async def send_message(conv_id: str, body: MessageIn):
        try:
            return ctx.chat.send(conv_id, body.text, [i.model_dump() for i in body.images], agent=body.agent)
        except KeyError:
            raise HTTPException(404, "conversation introuvable")
        except RuntimeError as exc:
            raise HTTPException(409, str(exc))

    @app.post("/api/conversations/{conv_id}/cancel", dependencies=auth)
    def cancel_message(conv_id: str):
        return {"cancelled": ctx.chat.cancel(conv_id)}

    @app.post("/api/chat/confirm", dependencies=auth)
    def confirm(body: ConfirmIn):
        return {"resolved": ctx.chat.resolve_confirm(body.confirm_id, body.approved)}

    # ------------------------------------------------------------------ mémoire
    @app.get("/api/memory", dependencies=auth)
    def list_memory(q: str | None = Query(default=None), limit: int = 200):
        if q:
            return {"items": ctx.memory.search(q, limit=min(limit, 50)), "query": q}
        return {"items": ctx.memory.list(limit=limit), "count": ctx.memory.count()}

    @app.post("/api/memory", dependencies=auth)
    def add_memory(body: MemoryIn):
        item = ctx.memory.add(body.text, source="user")
        ctx.hub.publish("memory.updated", count=ctx.memory.count())
        return item

    @app.delete("/api/memory/{memory_id}", dependencies=auth)
    def delete_memory(memory_id: str):
        ok = ctx.memory.delete(memory_id)
        ctx.hub.publish("memory.updated", count=ctx.memory.count())
        return {"deleted": ok}

    @app.delete("/api/memory", dependencies=auth)
    def clear_memory():
        n = ctx.memory.clear()
        ctx.consent.log("memory_cleared", detail=f"{n} souvenirs")
        ctx.hub.publish("memory.updated", count=0)
        return {"deleted": n}

    @app.get("/api/memory/export", dependencies=auth)
    def export_memory():
        return Response(
            content=ctx.memory.export(),
            media_type="application/json",
            headers={"Content-Disposition": "attachment; filename=iris-memoire.json"},
        )

    # ------------------------------------------------------------------ confidentialité
    @app.get("/api/consent", dependencies=auth)
    def get_consent():
        return {"consent": ctx.consent.status(), "local_only": ctx.settings.user.local_only, "types": DATA_TYPES}

    @app.put("/api/consent/{data_type}", dependencies=auth)
    def set_consent(data_type: str, body: ConsentIn):
        if data_type not in DATA_TYPES:
            raise HTTPException(404, "type de donnée inconnu")
        ctx.consent.set(data_type, body.granted)
        return {"consent": ctx.consent.status()}

    @app.get("/api/privacy/events", dependencies=auth)
    def privacy_events(limit: int = 200):
        return {"events": ctx.consent.events(limit=limit)}

    @app.delete("/api/privacy/events", dependencies=auth)
    def clear_privacy_events():
        ctx.consent.clear_events()
        return {"cleared": True}

    @app.post("/api/privacy/purge", dependencies=auth)
    async def purge_now():
        purged = await asyncio.to_thread(ctx.memory.purge_expired)
        ctx.consent.log("purge_manual", detail=str(purged))
        return purged

    # ------------------------------------------------------------------ tâches
    @app.get("/api/tasks", dependencies=auth)
    def list_tasks():
        return {"tasks": ctx.tasks.list()}

    @app.post("/api/tasks", dependencies=auth)
    async def create_task(body: TaskIn):
        return await ctx.tasks.create(body.title, body.instructions, body.agent)

    @app.get("/api/tasks/{task_id}", dependencies=auth)
    def get_task(task_id: str):
        task = ctx.tasks.get(task_id)
        if not task:
            raise HTTPException(404, "tâche introuvable")
        return task

    @app.post("/api/tasks/{task_id}/cancel", dependencies=auth)
    def cancel_task(task_id: str):
        return {"cancelled": ctx.tasks.cancel(task_id)}

    @app.delete("/api/tasks/{task_id}", dependencies=auth)
    def delete_task(task_id: str):
        return {"deleted": ctx.tasks.delete(task_id)}

    # ------------------------------------------------------------------ voix
    @app.get("/api/voice/status", dependencies=auth)
    def voice_status():
        return {**ctx.voice.status(), "capture": ctx.capture.snapshot(), "tts_speaking": ctx.tts.is_speaking, "tts_engine": ctx.tts.engine}

    @app.post("/api/voice/start", dependencies=auth)
    def voice_start():
        return ctx.voice.start()

    @app.post("/api/voice/stop", dependencies=auth)
    def voice_stop(minutes: float = 10.0):
        return ctx.voice.pause(minutes)

    @app.post("/api/voice/mute", dependencies=auth)
    def voice_mute():
        ctx.consent.log("mic_muted")
        return ctx.voice.mute(announce=False)

    @app.post("/api/voice/unmute", dependencies=auth)
    def voice_unmute():
        ctx.consent.log("mic_unmuted")
        return ctx.voice.unmute()

    @app.post("/api/voice/interrupt", dependencies=auth)
    def voice_interrupt():
        ctx.voice.interrupt()
        return {"interrupted": True}

    @app.post("/api/voice/push_to_talk", dependencies=auth)
    def voice_ptt():
        return ctx.voice.push_to_talk()

    @app.post("/api/voice/say", dependencies=auth)
    def voice_say(body: SayIn):
        return {"queued": ctx.tts.speak(body.text, force=True)}

    @app.post("/api/voice/stop_speaking", dependencies=auth)
    def voice_stop_speaking():
        ctx.tts.stop()
        return {"stopped": True}

    @app.get("/api/voice/voices", dependencies=auth)
    def voice_voices():
        return {"voices": ctx.tts.voices(), "available": ctx.tts.available, "error": ctx.tts.error}

    @app.get("/api/voice/elevenlabs", dependencies=auth)
    async def elevenlabs_status(refresh: bool = False):
        el = ctx.tts.eleven
        voices = await asyncio.to_thread(el.voices, refresh) if el.configured else []
        sub = await asyncio.to_thread(el.subscription) if el.configured else {}
        return {**el.status(), "voices": voices, "subscription": sub, "engine_in_use": ctx.tts.engine,
                "env_file": str(ctx.settings.data_dir / ".env")}

    @app.post("/api/voice/elevenlabs/key", dependencies=auth)
    async def elevenlabs_key(body: ElevenKeyIn):
        path = write_env_value(ctx.settings.data_dir, "ELEVENLABS_API_KEY", body.api_key.strip())
        el = ctx.tts.eleven
        el._disabled_until = 0.0
        el.error = None
        el._voices_cache = []
        ctx.consent.log("api_key_updated" if body.api_key.strip() else "api_key_removed", agent="elevenlabs", detail=f"stockée dans {path.name}")
        return {"configured": el.configured, "env_file": str(path)}

    @app.post("/api/voice/elevenlabs/test", dependencies=auth)
    def elevenlabs_test():
        el = ctx.tts.eleven
        if not el.configured:
            raise HTTPException(400, "Aucune clé ElevenLabs dans le fichier .env")
        el._disabled_until = 0.0
        name = ctx.settings.user.assistant_name or "IRIS"
        ok = el.speak(f"Bonjour, je suis {name}. Voici ma voix ElevenLabs en français. Dites {ctx.settings.user.wake_word} pour me parler.")
        return {"queued": ok, "error": el.error}

    @app.get("/api/voice/devices", dependencies=auth)
    def voice_devices():
        outputs: list[str] = []
        try:
            import sounddevice as sd

            seen = set()
            for d in sd.query_devices():
                if d.get("max_output_channels", 0) > 0 and d["name"] not in seen:
                    seen.add(d["name"])
                    outputs.append(d["name"])
        except Exception:
            pass
        return {"devices": ctx.voice.mic_devices(), "outputs": outputs}

    _download_lock = threading.Lock()

    @app.post("/api/voice/model/download", dependencies=auth)
    def download_model(body: ModelDownloadIn):
        language = body.language or ctx.settings.user.language
        if not _download_lock.acquire(blocking=False):
            raise HTTPException(409, "téléchargement déjà en cours")

        def work():
            try:
                def progress(done: int, total: int):
                    ctx.hub.publish("voice.model_progress", done=done, total=total, language=language)

                stt.download_model(ctx.settings.models_dir, language, progress)
                ctx.voice.error = None
                ctx.hub.publish("voice.model_ready", language=language, ready=True)
                if ctx.settings.user.voice_autostart and not ctx.voice.running:
                    ctx.voice.start()  # l'écoute démarre dès que la reconnaissance hors-ligne est disponible
                ctx.hub.publish("voice.state", **ctx.voice.status())
            except Exception as exc:
                ctx.hub.publish("voice.model_ready", language=language, ready=False, error=str(exc))
            finally:
                _download_lock.release()

        threading.Thread(target=work, name="iris-model-download", daemon=True).start()
        return {"started": True, "model": stt.VOSK_MODELS[stt.lang_key(language)]}

    # ------------------------------------------------------------------ système
    @app.get("/api/system/status", dependencies=auth)
    async def system_status():
        return await asyncio.to_thread(actions.system_status)

    @app.post("/api/system/screenshot", dependencies=auth)
    async def system_screenshot():
        shot = await asyncio.to_thread(actions.take_screenshot)
        ctx.capture.pulse_screen()
        ctx.consent.log("screen_captured", data_type="screen", detail="capture locale (aperçu avant envoi)")
        return shot

    # ------------------------------------------------------------------ abonnement
    @app.get("/api/plan", dependencies=auth)
    def get_plan():
        return ctx.plans.info()

    @app.post("/api/plan/activate", dependencies=auth)
    def activate_plan(body: LicenseIn):
        try:
            info = ctx.plans.activate(body.key)
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        ctx.consent.log("plan_activated", detail=info["plan"])
        ctx.hub.publish("settings.updated", settings=ctx.settings.user.model_dump())
        return info

    @app.get("/api/plan/licence", dependencies=auth)
    def licence_status():
        """État de l'activation automatique (serveur, courriel, dernière vérification)."""
        return ctx.licence.status()

    @app.post("/api/plan/sync", dependencies=auth)
    async def licence_sync():
        """Demande maintenant au serveur de licences si un abonnement est actif pour ce courriel."""
        result = await asyncio.to_thread(ctx.licence.sync, True)
        return {**result, "plan": ctx.plans.info()}

    @app.post("/api/plan/demo", dependencies=auth)
    def demo_plan(body: DemoPlanIn):
        try:
            info = ctx.plans.set_demo(body.plan)
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        ctx.consent.log("plan_demo", detail=body.plan)
        ctx.hub.publish("settings.updated", settings=ctx.settings.user.model_dump())
        return info

    # ------------------------------------------------------------------ comptes web
    def site_view(name: str) -> dict:
        site = ctx.settings.user.sites.get(name)
        creds = ctx.secrets.get_site(name)
        return {
            "name": name,
            "url": site.url if site else "",
            "username": site.username if site else "",
            "label": site.label if site else name,
            "has_password": bool(creds and creds.get("password")),
            "profile": next((k for k, p in __import__("iris.web", fromlist=["SITE_PROFILES"]).SITE_PROFILES.items() if site and (p["match"] in (site.url or "").lower() or p["match"] in name.lower())), None),
        }

    @app.get("/api/sites", dependencies=auth)
    def list_sites():
        return {"sites": [site_view(n) for n in ctx.settings.user.sites]}

    @app.put("/api/sites/{name}", dependencies=auth)
    def put_site(name: str, body: SiteIn):
        name = name.strip().lower()
        if not name or not body.url.strip():
            raise HTTPException(400, "nom et adresse requis")
        sites = {k: v.model_dump() for k, v in ctx.settings.user.sites.items()}
        sites[name] = {"url": body.url.strip(), "username": body.username.strip(), "label": (body.label or name).strip()}
        user = ctx.settings.update({"sites": sites})
        if body.password:
            ctx.secrets.set_site(name, body.username.strip(), body.password)
            ctx.consent.log("site_credentials_updated", detail=name)
        elif body.username:
            existing = ctx.secrets.get_site(name) or {}
            if existing.get("password"):
                ctx.secrets.set_site(name, body.username.strip(), existing["password"])
        ctx.hub.publish("settings.updated", settings=user.model_dump())
        return site_view(name)

    @app.delete("/api/sites/{name}", dependencies=auth)
    def delete_site(name: str):
        sites = {k: v.model_dump() for k, v in ctx.settings.user.sites.items() if k != name}
        user = ctx.settings.update({"sites": sites})
        ctx.secrets.delete_site(name)
        ctx.consent.log("site_credentials_removed", detail=name)
        ctx.hub.publish("settings.updated", settings=user.model_dump())
        return {"deleted": True}

    @app.post("/api/sites/{name}/login", dependencies=auth)
    async def site_login(name: str):
        try:
            result = await asyncio.to_thread(ctx.web.login, name)
        except Exception as exc:
            raise HTTPException(400, str(exc))
        ctx.consent.log("web_login", detail=f"{name} → {result['status']}")
        return result

    @app.post("/api/web/close", dependencies=auth)
    async def web_close():
        await asyncio.to_thread(ctx.web.close)
        return {"closed": True}

    # ------------------------------------------------------------------ routines
    @app.get("/api/routines", dependencies=auth)
    def list_routines():
        return {"routines": ctx.routines.list(), "recording": ctx.routines.recording}

    @app.post("/api/routines", dependencies=auth)
    def create_routine(body: RoutineIn):
        return ctx.routines.create(body.name, body.trigger or body.name, body.steps)

    @app.delete("/api/routines/{routine_id}", dependencies=auth)
    def delete_routine(routine_id: str):
        return {"deleted": ctx.routines.delete(routine_id)}

    @app.post("/api/routines/{routine_id}/run", dependencies=auth)
    async def run_routine(routine_id: str):
        routine = ctx.routines.get(routine_id)
        if not routine:
            raise HTTPException(404, "routine introuvable")
        conv = ctx.voice_conversation()
        return await ctx.chat._run_routine(conv["id"], routine, "text")

    @app.post("/api/routines/record/start", dependencies=auth)
    def record_start(body: RecordIn):
        return ctx.routines.start_recording(body.name, body.trigger)

    @app.post("/api/routines/record/stop", dependencies=auth)
    def record_stop():
        routine = ctx.routines.stop_recording()
        return {"routine": routine}

    # ------------------------------------------------------------------ rappels
    @app.get("/api/reminders", dependencies=auth)
    def list_reminders(include_done: bool = False):
        return {"reminders": ctx.reminders.list(include_done)}

    @app.post("/api/reminders", dependencies=auth)
    def create_reminder(body: ReminderIn):
        return ctx.reminders.create(body.text, body.minutes, body.at)

    @app.delete("/api/reminders/{reminder_id}", dependencies=auth)
    def delete_reminder(reminder_id: str):
        return {"deleted": ctx.reminders.delete(reminder_id)}

    # ------------------------------------------------------------------ mémoire : résumé de journée
    @app.post("/api/memory/summarize-day", dependencies=auth)
    async def summarize_day(body: SummaryIn):
        try:
            return await ctx.chat.summarize_day(body.day)
        except Exception as exc:
            raise HTTPException(400, str(exc))

    # ------------------------------------------------------------------ registre de transparence
    @app.get("/api/privacy/export", dependencies=auth)
    def privacy_export(format: str = "json"):
        fmt = "csv" if format == "csv" else "json"
        content = ctx.consent.export(fmt)
        ctx.consent.log("register_exported", detail=fmt)
        return Response(
            content=content,
            media_type="text/csv" if fmt == "csv" else "application/json",
            headers={"Content-Disposition": f"attachment; filename=iris-registre.{fmt}"},
        )

    @app.get("/api/privacy/verify", dependencies=auth)
    def privacy_verify():
        return ctx.consent.verify()

    # ------------------------------------------------------------------ applications installées
    # ------------------------------------------------------------------ veilles
    @app.get("/api/watches", dependencies=auth)
    def watches_list():
        return {"items": ctx.watch.list(), "events": ctx.watch.events(limit=30)}

    @app.post("/api/watches", dependencies=auth)
    def watch_create(body: WatchBody):
        try:
            return ctx.watch.create(body.name, body.url, body.criteria, body.interval_min, body.site)
        except ValueError as exc:
            raise HTTPException(400, str(exc))

    @app.post("/api/watches/{watch_id}/check", dependencies=auth)
    async def watch_check(watch_id: str):
        try:
            return await ctx.watch.check(watch_id)
        except ValueError as exc:
            raise HTTPException(404, str(exc))

    @app.post("/api/watches/{watch_id}/stop", dependencies=auth)
    def watch_stop(watch_id: str):
        return {"ok": ctx.watch.stop(watch_id)}

    @app.post("/api/watches/{watch_id}/resume", dependencies=auth)
    def watch_resume(watch_id: str):
        return {"ok": ctx.watch.resume(watch_id)}

    @app.delete("/api/watches/{watch_id}", dependencies=auth)
    def watch_delete(watch_id: str):
        return {"ok": ctx.watch.delete(watch_id)}

    # ------------------------------------------------------------------ accès mobile
    @app.get("/manifest.webmanifest")
    def manifeste():
        """Décrit l'application au téléphone : nom, icônes, plein écran."""
        return JSONResponse(MANIFESTE, media_type="application/manifest+json")

    @app.get("/sw.js")
    def agent_service():
        """Agent de service : Android l'exige pour proposer l'installation."""
        return Response(AGENT_SERVICE, media_type="application/javascript")

    @app.get("/icone-{taille}.png")
    def icone(taille: int):
        fichier = Path(__file__).parent / "assets" / f"icone-{taille}.png"
        if taille not in (192, 512) or not fichier.exists():
            raise HTTPException(404, "icône introuvable")
        return Response(fichier.read_bytes(), media_type="image/png",
                        headers={"Cache-Control": "public, max-age=86400"})

    @app.get("/m", response_class=HTMLResponse)
    def page_mobile():
        """Coquille de l'interface téléphone. Volontairement publique : elle ne contient aucune
        donnée, seulement le formulaire de connexion. Tout ce qui suit exige une session."""
        return HTMLResponse(PAGE_MOBILE)

    @app.get("/api/compte")
    def compte_info():
        """État du compte. Public : le téléphone doit savoir s'il faut créer ou se connecter."""
        return ctx.comptes.info()

    @app.post("/api/compte")
    def compte_creer(body: MotDePasse, request: Request):
        """Premier mot de passe. Exige le jeton de l'application : c'est le propriétaire qui le pose."""
        require_token(request)
        try:
            return ctx.comptes.creer(body.nouveau or body.mot_de_passe, body.nom)
        except ValueError as exc:
            raise HTTPException(400, str(exc))

    @app.patch("/api/compte", dependencies=auth)
    def compte_changer(body: MotDePasse):
        try:
            return ctx.comptes.changer(body.mot_de_passe, body.nouveau)
        except ValueError as exc:
            raise HTTPException(400, str(exc))

    @app.post("/api/compte/connexion")
    def compte_connexion(body: MotDePasse):
        """Échange un mot de passe contre une session. Public par nécessité, protégé par le
        ralentissement après plusieurs échecs."""
        if not ctx.comptes.verifier(body.mot_de_passe):
            raise HTTPException(401, "Mot de passe incorrect.")
        return {"session": ctx.comptes.ouvrir_session(), "nom": ctx.comptes.info().get("nom", "")}

    @app.post("/api/compte/deconnexion", dependencies=auth)
    def compte_deconnexion():
        ctx.comptes.revoquer_tout()
        return {"ok": True}

    @app.get("/api/remote", dependencies=auth)
    def remote_info(request: Request):
        """Adresses à ouvrir sur le téléphone, et état de l'accès réseau."""
        actif = bool(ctx.settings.user.remote_access)
        port = request.url.port or 0
        return {
            "enabled": actif,
            "port": port,
            "urls": urls_locales(port, token or "") if actif else [],
            "note": (
                "Le téléphone doit être sur le même réseau WiFi que cet ordinateur. "
                "Pour y accéder depuis l'extérieur, utilisez un tunnel privé (Tailscale) : "
                "n'ouvrez jamais de port sur votre routeur."
            ),
        }

    @app.get("/api/presence", dependencies=auth)
    def presence_info():
        """Ce qu'IRIS sait de sa propre vie sur cet appareil : depuis quand, combien de démarrages, dernier échange."""
        return ctx.presence.info()

    @app.get("/api/apps", dependencies=auth)
    async def list_apps(q: str = ""):
        from .pc.apps import index as app_index

        if q:
            return {"apps": await asyncio.to_thread(app_index.search, q, 20)}
        await asyncio.to_thread(app_index.ensure)
        return {"apps": app_index.apps[:500], "count": len(app_index.apps)}

    @app.post("/api/apps/refresh", dependencies=auth)
    async def refresh_apps():
        from .pc.apps import index as app_index

        apps = await asyncio.to_thread(app_index.build)
        return {"count": len(apps)}

    @app.post("/api/voice/calibrate", dependencies=auth)
    def voice_calibrate(body: CalibrateIn):
        return ctx.voice.calibrate(body.count)

    # ------------------------------------------------------------------ lunettes
    @app.get("/api/glasses/status", dependencies=auth)
    def glasses_status():
        return ctx.glasses.status()

    @app.post("/api/glasses/scan", dependencies=auth)
    async def glasses_scan(body: GlassesScanIn):
        devices = await ctx.glasses.scan(min(max(body.seconds, 2.0), 20.0))
        return {"devices": devices, "error": ctx.glasses.error}

    @app.post("/api/glasses/connect", dependencies=auth)
    async def glasses_connect(body: GlassesConnectIn):
        status = await ctx.glasses.connect(body.address, body.name, attempts=max(1, min(body.attempts, 5)))
        if not status["connected"]:
            raise HTTPException(400, status.get("error") or "connexion impossible")
        ctx.consent.log("glasses_connected", detail=f"{body.name or ''} {body.address}")
        return status

    @app.post("/api/glasses/disconnect", dependencies=auth)
    async def glasses_disconnect():
        return await ctx.glasses.disconnect()

    @app.post("/api/glasses/forget", dependencies=auth)
    async def glasses_forget():
        await ctx.glasses.disconnect()
        ctx.glasses.forget()
        return ctx.glasses.status()

    @app.post("/api/glasses/battery", dependencies=auth)
    async def glasses_battery():
        return {"battery": await ctx.glasses.refresh_battery()}

    @app.patch("/api/glasses/prefs", dependencies=auth)
    def glasses_prefs(body: GlassesPrefsIn):
        patch: dict = {}
        if body.auto_connect is not None:
            g = ctx.settings.user.glasses
            patch["glasses"] = {"address": g.address, "name": g.name, "auto_connect": body.auto_connect}
        if body.audio_input_device is not None:
            patch["audio_input_device"] = body.audio_input_device
            # micro mains libres des lunettes → la sortie doit passer par le même profil (Windows coupe la stéréo)
            if "hands-free" in body.audio_input_device.lower() and not ctx.settings.user.audio_output_device:
                patch["audio_output_device"] = body.audio_input_device.split(" Hands-Free")[0] + " Hands-Free"
        if body.audio_output_device is not None:
            patch["audio_output_device"] = body.audio_output_device
        if patch:
            user = ctx.settings.update(patch)
            ctx.hub.publish("settings.updated", settings=user.model_dump())
            if body.audio_input_device is not None and ctx.voice.running:
                ctx.voice.stop(by_user=False)
                ctx.voice.start()
        return ctx.glasses.status()

    # ------------------------------------------------------------------ WebSocket
    @app.websocket("/ws")
    async def websocket(ws: WebSocket):
        supplied = ws.query_params.get("token", "")
        if token is not None and supplied != token:
            await ws.close(code=4401)
            return
        await ws.accept()
        q = ctx.hub.subscribe()
        await ws.send_text(EventHub.encode({"type": "hello", "status": ctx.status()}))

        async def reader():
            while True:
                raw = await ws.receive_json()
                await handle_client_message(raw)

        async def handle_client_message(msg: dict[str, Any]) -> None:
            kind = msg.get("type")
            if kind and (kind.startswith("voice.") or kind.startswith("privacy.") or kind == "tts.stop"):
                log.info("diagnostic message client %s depuis %s : %s", kind, ws.headers.get("user-agent", "?")[:60], {k: v for k, v in msg.items() if k != "images"})
            try:
                if kind == "chat.send":
                    ctx.chat.send(
                        msg["conversation_id"], msg.get("text", ""), msg.get("images") or [], agent=msg.get("agent", "auto")
                    )
                elif kind == "chat.cancel":
                    ctx.chat.cancel(msg["conversation_id"])
                elif kind == "chat.confirm_reply":
                    ctx.chat.resolve_confirm(msg["confirm_id"], bool(msg.get("approved")))
                elif kind == "voice.push_to_talk":
                    ctx.voice.push_to_talk()
                elif kind == "voice.start":
                    ctx.voice.start()
                elif kind == "voice.stop" or kind == "voice.pause":
                    ctx.voice.pause(float(msg.get("minutes") or 10))
                elif kind == "tts.stop":
                    ctx.voice.interrupt()
                elif kind == "voice.mute":
                    ctx.consent.log("mic_muted")
                    ctx.voice.mute(announce=False)
                elif kind == "voice.unmute":
                    ctx.consent.log("mic_unmuted")
                    ctx.voice.unmute()
                elif kind == "voice.toggle_mute":
                    if ctx.voice.muted:
                        ctx.consent.log("mic_unmuted")
                        ctx.voice.unmute()
                    else:
                        ctx.consent.log("mic_muted")
                        ctx.voice.mute(announce=False)
                elif kind == "privacy.toggle":
                    enabled = not ctx.settings.user.privacy_mode if msg.get("enabled") is None else bool(msg.get("enabled"))
                    user = ctx.settings.update({"privacy_mode": enabled})
                    ctx.hub.publish("settings.updated", settings=user.model_dump())
                    apply_privacy_mode(enabled)
                elif kind == "ping":
                    await ws.send_text(EventHub.encode({"type": "pong"}))
            except (KeyError, RuntimeError) as exc:
                await ws.send_text(
                    EventHub.encode({"type": "chat.error", "conversation_id": msg.get("conversation_id"), "message": str(exc)})
                )

        reader_task = asyncio.create_task(reader())
        try:
            while True:
                event = await q.get()
                await ws.send_text(EventHub.encode(event))
        except (WebSocketDisconnect, RuntimeError):
            pass
        finally:
            reader_task.cancel()
            ctx.hub.unsubscribe(q)

    return app
