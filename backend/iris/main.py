"""API locale IRIS (FastAPI) : REST + WebSocket, protégée par un jeton de session."""
from __future__ import annotations

import asyncio
import base64
import importlib
import inspect
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
from starlette.requests import HTTPConnection

from . import __version__
from .capture import CaptureIndicator
from .chat import ChatService
from .config import AGENT_NAMES, Settings, write_env_value
from .connectors import ConnectorError, agent_catalog, build_connector
from .consent import DATA_TYPES, ConsentGate
from .courriel import Postier
from .personas import PERSONAS, liste_publique as personas_publics
from .traduction import NOMS_LANGUES, ServiceTraduction
from .db import Database
from .telephonie import Telephoniste
from .telecommande import Telecommande
from .events import EventHub
from .glasses import GlassesService
from .memory import MemoryService
from .lunettes_presence import PresenceLunettes, exiger_lunettes, exiger_lunettes_pc, raison_capture_pc
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


def construire_opencode(settings, registre, hub) -> Any:
    """Crée le service de délégation à OpenCode, s'il est là.

    Deux prudences, et elles ont chacune une raison précise.

    D'abord `iris/opencode.py` est chargé par import paresseux : il a été écrit en parallèle de ce
    câblage, et une IRIS qui refuse de démarrer parce qu'un module optionnel manque est un désastre
    bien plus grand que l'absence de la délégation. Miguel présente mardi.

    Ensuite la construction s'adapte à la signature réelle du service au lieu de la supposer :
    on ne passe que les paramètres qu'il déclare. Le 5 septembre 2026, DEUX modules entiers, écrits
    et testés, sont restés inutilisables toute une journée faute d'être branchés — un TypeError
    silencieux ici produirait exactement le même résultat, et personne ne s'en apercevrait avant
    d'avoir demandé à IRIS de corriger un bogue."""
    try:
        from . import opencode as module
    except Exception as exc:
        log.info("délégation OpenCode indisponible (module absent) : %s", exc)
        return None
    classe = next(
        (c for c in (getattr(module, n, None)
                     for n in ("Contremaitre", "ServiceOpenCode", "OpenCode", "Opencode", "ServiceDelegation"))
         if isinstance(c, type)),
        None,
    )
    if classe is None:
        log.warning("iris/opencode.py est présent mais n'expose aucune classe de service connue")
        return None
    import inspect

    try:
        parametres = inspect.signature(classe).parameters
    except (TypeError, ValueError):
        parametres = {}
    nommes = {
        nom: valeur
        for nom, valeur in (("settings", settings), ("reglages", settings), ("registre", registre),
                            ("consent", registre), ("hub", hub))
        if nom in parametres
    }
    try:
        if not parametres:
            return classe()
        if nommes.get("settings") is not None or nommes.get("reglages") is not None:
            return classe(**nommes)
        return classe(settings, **nommes)  # premier paramètre positionnel : les réglages, comme partout ailleurs
    except Exception as exc:
        log.warning("service OpenCode non construit : %s", exc)
        return None


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
        # Crochets de cycle de vie des modules branchés par routeur (voir _brancher_modules).
        self.demarrages: list = []
        self.arrets: list = []
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
        # Courriel et téléphonie : construits ici, offerts au modèle par tools.py. Ils étaient
        # écrits et testés depuis le 5 septembre, mais rien ne les appelait — IRIS ne pouvait
        # donc ni écrire ni texter, alors que le code était là.
        # Le mode traduction. Constat du 5 septembre 2026, deux fois dans la même journée : un
        # module écrit et testé que PERSONNE n'appelle ne sert à rien. On le branche donc ici même,
        # dans le même geste que sa création — l'écoute, le chat et les outils, les trois.
        self.traduction = ServiceTraduction(
            lambda systeme, message: self.chat.demander_court(systeme, message),
            settings=self.settings, registre=self.consent, hub=self.hub,
        )
        self.voice.traduction = self.traduction
        self.courriel = Postier(self.settings, self.secrets)
        self.telephonie = Telephoniste(self.settings, self.secrets, registre=self.consent, hub=self.hub)
        # Déléguer la programmation à OpenCode. Construit ICI, dans le même geste que le reste,
        # et injecté dans le chat trois lignes plus bas : c'est la seule façon de ne pas répéter le
        # 5 septembre 2026, où deux modules finis sont restés muets faute de câblage. Tant
        # qu'OpenCode n'est pas installé, le service le dit et l'outil n'est même pas offert au
        # modèle — IRIS se comporte exactement comme si rien n'avait été ajouté.
        self.opencode = construire_opencode(self.settings, self.consent, self.hub)
        # Le verrou du pilotage vocal a besoin de savoir si les lunettes sont là.
        self.voice.glasses_connected = lambda: self.glasses.connected
        # LUNETTES D'ABORD (2026-09-13) : une seule règle de présence pour la voix, le chat et toutes
        # les fonctions qui captent ou agissent (voir lunettes_presence.py).
        self.presence_lunettes = PresenceLunettes(
            self.settings, self.settings.data_dir, voice=self.voice, glasses=self.glasses, hub=self.hub
        )
        self.voice.presence_lunettes = self.presence_lunettes
        self.presence_lunettes.journal = self.consent.log
        self.chat.presence_lunettes = self.presence_lunettes
        # Les outils du chat (rappel contextuel, pas à pas, prix…) trouvent les modules branchés par ici.
        self.chat.contexte_app = self
        self.routines = RoutineService(self.db, self.hub)
        self.reminders = ReminderService(self.db, self.hub, announce=self._announce)
        self.chat.routines = self.routines
        self.chat.reminders = self.reminders
        self.web = WebAgent(self.settings, self.hub, self.secrets)
        self.chat.web = self.web
        self.chat.glasses = self.glasses
        self.chat.courriel = self.courriel
        self.chat.telephonie = self.telephonie
        self.chat.traduction = self.traduction
        self.chat.voice = self.voice
        self.chat.opencode = self.opencode
        # Accord vocal, dans les deux sens : le chat dépose sa demande de confirmation dans le fil
        # vocal, et le fil vocal résout le futur du chat quand Miguel a répondu « oui » ou « non ».
        # Sans ce pont, une confirmation ne pouvait venir que d'un clic — inutilisable à la voix.
        self.voice._resoudre_confirmation = self.chat.resolve_confirm
        self.chat.set_sink_confirm_vocal(self.voice.file_confirmation_vocale)
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
        # Télécommande : le téléphone pilote CET ordinateur à distance, via le relais (opt-in, coupé
        # par défaut). Réutilise le jeton d'appareil déjà obtenu pour le cerveau VELA.
        self.telecommande = Telecommande(
            self.chat, self.settings, obtenir_jeton=lambda: self.secrets.get_api_key("vela") or "",
        )
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
            # Cadence : une fois par jour en régime normal. MAIS tant que l'accès IA VELA n'est pas
            # encore obtenu (relais en réveil à froid ou momentanément lent au tout premier lancement),
            # on réessaie toutes les 2 minutes : sinon une install neuve resterait SANS aucune IA
            # jusqu'au prochain démarrage. Dès que le jeton est là, on repasse à la cadence quotidienne.
            besoin_acces = (
                not self.settings.user.local_only
                and bool((self.settings.user.relay_server or "").strip())
                and not self.secrets.get_api_key("vela")
            )
            await asyncio.sleep(120 if besoin_acces else 24 * 3600)

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
                if u.voice_autostart and not self.voice.running and raison_capture_pc(self) is not None:
                    # Lunettes absentes, ou attestées par le téléphone seulement (leur porteur est dehors) :
                    # le micro de cet ordinateur reste fermé. start() refuserait aussi ; on ne le sollicite pas.
                    continue
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
        if self.settings.user.local_only or not (self.settings.user.relay_server or "").strip():
            return
        # Résoudre la base réellement joignable AVANT tout le reste : sur un réseau filtré, le
        # domaine principal peut être détourné par DNS (constaté sur le wifi d'un cégep), et c'est
        # le repli — la même infrastructure VELA par une autre entrée — qui répond. On le fait même
        # quand le jeton est déjà en cache, car c'est cette base que le connecteur utilisera ensuite.
        from .connectors import base_relais_effective, resoudre_relais

        resoudre_relais(self.settings)
        base = base_relais_effective(self.settings)
        if not base:
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
                    resume_quotidien = getattr(self, "resume_quotidien", None)
                    if resume_quotidien is not None:
                        # Résumé vocal de fin de journée (quotidien.py) : il garde la mémorisation.
                        await resume_quotidien(today)
                        continue
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
            try:
                # Le journal technique suit la même rétention (constat du 2026-09-14 : il n'est pas chiffré).
                from .verrou import purger_journal_technique

                jours = int(getattr(self.settings.user, "retention_days", 0) or 0)
                if jours > 0:
                    await asyncio.to_thread(purger_journal_technique, jours)
            except Exception as exc:  # pragma: no cover
                log.warning("purge du journal technique en erreur : %s", exc)
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
    # Confirmation seulement (jamais gardée) : exigée pour retirer ou remplacer le jeton d'appareil « vela »
    # quand le verrouillage à distance est actif — c'est ce jeton qui garde le canal du verrou ouvert.
    mot_de_passe: str | None = None


class ConfirmationIn(BaseModel):
    mot_de_passe: str | None = None


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


class CommandeVocaleIn(BaseModel):
    texte: str = Field(default="", max_length=2000)
    source: str = Field(default="iphone", max_length=20)
    conversation_id: str | None = Field(default=None, max_length=64)


# Dehors, une phrase qui ouvrirait le micro de l'ordinateur resté à la maison (mode traduction, interprète).
PHRASE_MICRO_MAISON = ("Dehors, je n'ouvre pas le micro de l'ordinateur resté à la maison : "
                       "utilise l'interprète de l'application du téléphone.")

# Session refusée parce qu'IRIS a été effacée à distance (comptes.motif_revocation). Le code permet à l'app
# iPhone, en arrière-plan au moment de l'effacement, de retirer à sa réouverture les copies gardées sur elle.
CODE_EFFACE_A_DISTANCE = "efface_a_distance"
PHRASE_EFFACE_A_DISTANCE = ("IRIS a été effacée à distance et est verrouillée. "
                            "Reconnectez-vous avec le mot de passe du propriétaire.")
# Même cause, une fois l'ordinateur déverrouillé par son propriétaire : dire « est verrouillée » serait faux.
PHRASE_EFFACE_A_DISTANCE_DEVERROUILLEE = ("IRIS a été effacée à distance. "
                                          "Reconnectez-vous avec le mot de passe du propriétaire.")
PHRASES_EFFACE_A_DISTANCE = (PHRASE_EFFACE_A_DISTANCE, PHRASE_EFFACE_A_DISTANCE_DEVERROUILLEE)


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


class TraductionIn(BaseModel):
    langue: str = "en"  # code court (en, es, pt, it, de) ou nom dit (« espagnol ») ; voir traduction.NOMS_LANGUES


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


class AttestationLunettesIn(BaseModel):
    nom: str
    identifiant: str = ""
    batterie: int | None = None
    source: str = "telephone"


class AssociationLunettesIn(BaseModel):
    nom: str
    identifiant: str = ""
    mot_de_passe: str | None = None


class DemoIn(BaseModel):
    mot_de_passe: str


# Réglages qui ouvriraient IRIS sans lunettes : jamais modifiables par PATCH /api/settings (un écran
# client, ou un appel direct, suffirait sinon à contourner la règle « lunettes d'abord »). Le mode
# démonstration passe par POST /api/demo/activer, avec le mot de passe du propriétaire.
# « glasses » (constat du 2026-09-14) : un nom de lunettes posé à la main (« Micro ») faisait passer
# n'importe quel micro pour les lunettes. Le nom et l'adresse ne changent que par une vraie connexion
# Bluetooth (POST /api/glasses/connect) ou par l'oubli (POST /api/glasses/forget).
REGLAGES_PROTEGES = ("require_glasses", "demo_sans_lunettes", "glasses")
# Constat du 2026-09-14 : sur l'ordinateur, l'application utilise le jeton local et ne demande aucun mot
# de passe. Le voleur d'un portable resté ouvert couperait le verrouillage à distance en changeant l'un de
# ces réglages avant que le propriétaire n'arrive sur la page /verrou. Quand le verrouillage à distance
# est actif (et qu'un mot de passe existe), les modifier exige le mot de passe du propriétaire.
MESSAGE_ASSOCIATION_SANS_COMPTE = (
    "Crée d'abord le mot de passe du propriétaire sur l'ordinateur (Profil › Compte et sécurité) : c'est lui qui autorise "
    "un appareil de plus à dire que les lunettes sont connectées."
)
MESSAGE_REGLAGE_VERROU = (
    "Le verrouillage à distance est actif : ce réglage le couperait. Désactivez d'abord le verrouillage à "
    "distance (Profil › Verrouillage à distance) avec le mot de passe du propriétaire, puis réessayez."
)


class GlassesPhotoIn(BaseModel):
    # reconnaissance : charge utile 01 07 00 (image « à analyser ») plutôt que 01 04 00. L'analyse
    # reste locale dans les deux cas ; ce drapeau ne change que la charge utile envoyée aux lunettes.
    reconnaissance: bool = False


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
        telecommande_task = loop.create_task(ctx.telecommande.run())
        threading.Thread(target=ctx.tts.eleven.prewarm, name="iris-eleven-prewarm", daemon=True).start()
        # Et le canal Windows : ouvrir le profil mains libres coute jusqu'a huit secondes la
        # premiere fois. Sans ce prechauffage, ces huit secondes tombent sur le tout premier
        # << Dis-moi Iris >>, celui qu'on fait devant une salle.
        ctx.tts.prechauffer()
        from .pc.apps import index as app_index

        threading.Thread(target=app_index.build, name="iris-apps-index", daemon=True).start()
        threading.Thread(target=ctx.assurer_modele_vocal, name="iris-modele-vocal", daemon=True).start()
        threading.Thread(target=ctx.assurer_acces_vela, name="iris-acces-vela", daemon=True).start()
        verrouillee_au_demarrage = bool(getattr(getattr(ctx, "verrou", None), "verrouille", False))
        if ctx.settings.user.voice_autostart and not ctx.settings.user.privacy_mode and not verrouillee_au_demarrage:
            loop.call_later(1.0, ctx.voice.start)
        glasses_task = None if verrouillee_au_demarrage else loop.create_task(ctx.glasses.auto_connect_on_start())
        for demarrer in list(ctx.demarrages):
            try:
                resultat = demarrer()
                if inspect.isawaitable(resultat):
                    await resultat
            except Exception as exc:
                log.warning("démarrage d'un module en erreur : %s", exc)
        try:
            yield
        finally:
            for arreter in list(ctx.arrets):
                try:
                    resultat = arreter()
                    if inspect.isawaitable(resultat):
                        await resultat
                except Exception as exc:
                    log.warning("arrêt d'un module en erreur : %s", exc)
            reminders_task.cancel()
            summary_task.cancel()
            watchdog_task.cancel()
            if glasses_task is not None:
                glasses_task.cancel()
            ctx.telecommande.arreter()
            telecommande_task.cancel()
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

    def _vient_de_cet_ordinateur(connexion: HTTPConnection) -> bool:
        """La requête part-elle bien de cette machine, sans intermédiaire ?

        Un mandataire ou un tunnel se signale par l'un de ces en-têtes. On les traite comme
        « pas local » même quand la connexion arrive par la boucle locale : derrière un tunnel,
        TOUT semble venir de 127.0.0.1, et s'y fier reviendrait à ne rien vérifier.

        `HTTPConnection` est l'ancêtre commun de `Request` et de `WebSocket` : la même question se
        pose aux deux, et elle doit recevoir la même réponse."""
        import ipaddress

        for entete in ("x-forwarded-for", "x-real-ip", "cf-connecting-ip", "forwarded", "x-forwarded-host"):
            if connexion.headers.get(entete):
                return False
        hote = (connexion.client.host if connexion.client else "") or ""
        try:
            return ipaddress.ip_address(hote).is_loopback
        except ValueError:
            # Pas une adresse IP : la requête n'a pas traversé le réseau du tout. C'est le cas d'un
            # client interne, en mémoire. Une vraie connexion distante porte toujours une adresse.
            return True

    def _jeton_presente(connexion: HTTPConnection) -> str:
        """Le jeton que porte la connexion : l'en-tête Authorization d'abord, sinon « ?token= »."""
        header = connexion.headers.get("authorization", "")
        return header[7:] if header.lower().startswith("bearer ") else connexion.query_params.get("token", "")

    # Chemins encore joignables quand IRIS est verrouillée à distance (verrou.py) : de quoi
    # afficher l'écran de verrouillage et déverrouiller avec le mot de passe du propriétaire.
    CHEMINS_PERMIS_VERROUILLEE = (
        "/api/health", "/api/compte", "/api/confiance/verrou", "/api/confiance/deverrouiller",
        "/m", "/manifest.webmanifest", "/sw.js", "/icone-",
    )

    def raison_de_refus(connexion: HTTPConnection) -> str | None:
        raison = _raison_jeton(connexion)
        if raison is not None:
            return raison
        verrou = getattr(ctx, "verrou", None)
        if verrou is not None and getattr(verrou, "verrouille", False):
            if not connexion.url.path.startswith(CHEMINS_PERMIS_VERROUILLEE):
                if getattr(verrou, "raison", None) == "distance":
                    return "IRIS est verrouillée à distance. Déverrouillez-la avec le mot de passe du propriétaire."
                return "IRIS est verrouillée. Déverrouillez-la avec le mot de passe du propriétaire."
        return None

    def _raison_jeton(connexion: HTTPConnection) -> str | None:
        """LA règle d'accès, la même pour le HTTP et pour le WebSocket. Rend la phrase de refus,
        ou None si la connexion est admise.

        Une seule fonction, pas deux : jusqu'au 6 septembre 2026, /ws avait sa propre règle,
        réduite au jeton maître. Elle ignorait les deux garde-fous posés ici sur le HTTP — la
        session par mot de passe et l'origine locale — alors que /ws porte « chat.send », qui
        pilote l'ordinateur. Quiconque avait vu l'adresse « /m?token=… » pouvait donc, à travers un
        tunnel, ouvrir le WebSocket et commander le PC sans mot de passe, pendant que le HTTP le
        refusait. Deux règles pour la même porte, c'est une règle de trop."""
        if token is None:
            return None
        supplied = _jeton_presente(connexion)
        # Une session ouverte avec le mot de passe donne les mêmes droits : c'est par là que passe
        # le téléphone.
        if supplied and supplied != token and ctx.comptes.session_valide(supplied):
            return None
        if supplied != token:
            motif = getattr(ctx.comptes, "motif_revocation", None)
            if supplied and callable(motif) and motif(supplied) == "effacement":
                verrou = getattr(ctx, "verrou", None)
                if verrou is not None and getattr(verrou, "verrouille", False):
                    return PHRASE_EFFACE_A_DISTANCE
                return PHRASE_EFFACE_A_DISTANCE_DEVERROUILLEE
            return "jeton de session invalide"
        # Jeton maître accepté — mais IRIS écrit elle-même ce jeton dans l'adresse qu'elle donne au
        # téléphone (« /m?token=… »). Une adresse finit dans un historique, une capture d'écran, un
        # message qu'on s'envoie à soi-même. Tant qu'aucun mot de passe n'existe, c'est le seul
        # secret dont on dispose et il faut bien s'en contenter. Dès qu'il en existe un, ce jeton
        # cesse de valoir depuis l'extérieur : sinon le mot de passe ne protégerait rien du tout,
        # et la promesse écrite dans docs/ACCES-DISTANT.md serait fausse.
        if ctx.comptes.configure and not _vient_de_cet_ordinateur(connexion):
            return "Depuis un autre appareil, connectez-vous avec votre mot de passe."
        return None

    def require_token(request: Request) -> None:
        raison = raison_de_refus(request)
        if raison in PHRASES_EFFACE_A_DISTANCE:
            raise HTTPException(status_code=401, detail={"code": CODE_EFFACE_A_DISTANCE, "message": raison})
        if raison is not None:
            raise HTTPException(status_code=401, detail=raison)

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
        # Le mot de passe n'est jamais un réglage : il ne sert qu'à confirmer, et n'est ni gardé ni renvoyé.
        mot_de_passe = data.pop("mot_de_passe", None)
        proteges = [cle for cle in REGLAGES_PROTEGES if cle in data]
        if proteges:
            raise HTTPException(403, "Réglage protégé : il ne se modifie pas depuis l'application.")
        if "persona" in data and data["persona"] not in PERSONAS:
            raise HTTPException(400, "rôle inconnu")
        before = ctx.settings.user
        _verifier_reglages_du_verrou(data, before, mot_de_passe)
        if data.get("verrou_vocal_actif") is True:
            from .verrou_vocal import NON_OFFERTE, fonction_offerte

            if not fonction_offerte():
                raise HTTPException(409, NON_OFFERTE)
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

    def _verifier_reglages_du_verrou(data: dict, before: Any, mot_de_passe: Any) -> None:
        """Refuse (403) ce qui couperait le verrouillage à distance actif sans le mot de passe du propriétaire :
        l'éteindre (`verrou_distant_actif` à faux), changer ou vider l'adresse du relais ou le courriel du compte.

        `verrou_distant_actif` éteint : la décision passe par VerrouIRIS.definir_distant (l'état réel vit dans
        verrou.json). Sans mot de passe, 403 dit tel quel : rendre 200 puis rétablir le réglage en silence
        laissait l'écran annoncer « désactivé » à tort. Le mode 100 % local, lui, reste permis : il garde le
        canal « verrouillage seulement » ouvert tant que le verrouillage à distance est actif
        (telecommande.Telecommande.actif)."""
        verrou = getattr(ctx, "verrou", None)
        actif = bool(getattr(verrou, "distant_actif", None)) if verrou is not None else bool(
            getattr(before, "verrou_distant_actif", False))
        if not actif or not ctx.comptes.configure:
            return
        definir_distant = getattr(verrou, "definir_distant", None) if verrou is not None else None
        if data.get("verrou_distant_actif") is False and callable(definir_distant):
            from .verrou import RefusVerrou

            try:
                definir_distant(False, mot_de_passe if isinstance(mot_de_passe, str) else None)
            except RefusVerrou as exc:
                raise HTTPException(exc.code, exc.message)

        def _propre(valeur: Any) -> str:
            return str(valeur or "").strip().rstrip("/").lower()

        touches = []
        for cle in ("relay_server", "licence_email"):
            if cle in data and _propre(data[cle]) != _propre(getattr(before, cle, "")):
                touches.append(cle)
        if not touches:
            return
        _exiger_mot_de_passe_du_verrou(mot_de_passe, ", ".join(touches))

    def _verrou_distant_protege() -> bool:
        """Vrai quand couper le canal du verrouillage à distance doit exiger le mot de passe du propriétaire."""
        verrou = getattr(ctx, "verrou", None)
        actif = bool(getattr(verrou, "distant_actif", None)) if verrou is not None else bool(
            getattr(ctx.settings.user, "verrou_distant_actif", False))
        return actif and bool(ctx.comptes.configure)

    def _exiger_mot_de_passe_du_verrou(mot_de_passe: Any, detail: str) -> None:
        """429 pendant la limitation des essais ; 403 MESSAGE_REGLAGE_VERROU (journalisé) sans le bon mot de passe."""
        trop = getattr(ctx.comptes, "_trop_d_essais", None)
        if callable(trop) and trop():
            raise HTTPException(429, "Trop de tentatives : réessayez dans quelques minutes.")
        if isinstance(mot_de_passe, str) and mot_de_passe and ctx.comptes.verifier(mot_de_passe):
            return
        ctx.consent.log("reglage_protege_refuse", detail=detail)
        raise HTTPException(403, MESSAGE_REGLAGE_VERROU)

    def _proteger_jeton_vela(name: str, nouvelle_cle: str | None, mot_de_passe: Any) -> None:
        """Constat du 2026-09-14 : retirer le jeton d'appareil « vela » (DELETE …/key ou PUT api_key vide) éteignait
        le canal du verrouillage à distance (Telecommande.actif exige un jeton), sans mot de passe ; avec le mode
        100 % local, assurer_acces_vela ne le réobtenait jamais. Le retirer ou le remplacer par une autre valeur
        exige donc le mot de passe du propriétaire tant que le verrouillage à distance est actif.
        nouvelle_cle None = suppression."""
        if name != "vela" or not _verrou_distant_protege():
            return
        actuel = (ctx.secrets.get_api_key("vela") or "").strip()
        propose = (nouvelle_cle or "").strip()
        if not actuel or propose == actuel:
            return  # rien à couper : aucun jeton en place, ou la même valeur réécrite
        _exiger_mot_de_passe_du_verrou(mot_de_passe, "jeton vela")

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

    # ------------------------------------------------------------------ rôles (personas)
    @app.get("/api/personas", dependencies=auth)
    def get_personas():
        """Les rôles proposés par l'interface et celui en vigueur. Le choix se fait par
        PATCH /api/settings {"persona": "<id>"} — un identifiant inconnu est refusé (400)."""
        return {"personas": personas_publics(), "courant": ctx.settings.user.persona}

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
        patch = {k: v for k, v in body.model_dump().items() if v is not None and k not in ("api_key", "mot_de_passe")}
        if body.api_key is not None:
            _proteger_jeton_vela(name, body.api_key, body.mot_de_passe)
            ctx.secrets.set_api_key(name, body.api_key)
            ctx.consent.log("api_key_updated" if body.api_key else "api_key_removed", agent=name)
        if patch:
            ctx.settings.update({"agents": {name: patch}})
        view = agent_view(name)
        ctx.hub.publish("agent.updated", agent=view)
        return view

    @app.delete("/api/agents/{name}/key", dependencies=auth)
    def delete_agent_key(name: str, body: ConfirmationIn | None = None):
        if name not in AGENT_NAMES:
            raise HTTPException(404, "moteur IA inconnu")
        _proteger_jeton_vela(name, None, body.mot_de_passe if body is not None else None)
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
    def get_conversation(conv_id: str, depuis: str | None = Query(default=None, max_length=64),
                         limit: int | None = Query(default=None, ge=1, le=500)):
        """Sans paramètre : toute la conversation (500 messages au plus), comme avant. `depuis` : seulement les
        messages après celui-là ; `limit` : les N derniers. `depuis_trouve` faux = recharger tout."""
        conv = ctx.chat.get_conversation(conv_id)
        if not conv:
            raise HTTPException(404, "conversation introuvable")
        # issue_non_gardee : dernière demande finie SANS message (consentement requis, erreur publiée seulement),
        # lue par le téléphone qui a perdu l'événement pendant une coupure de sa liaison.
        issue = ctx.chat.issue_non_gardee(conv_id)
        if depuis is None and limit is None:
            return {**conv, "messages": ctx.chat.messages(conv_id), "issue_non_gardee": issue}
        messages, trouve = ctx.chat.messages_depuis(conv_id, depuis, limit)
        return {**conv, "messages": messages, "depuis_trouve": trouve, "issue_non_gardee": issue}

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

    @app.post("/api/voix/commande", dependencies=auth)
    async def voix_commande(body: CommandeVocaleIn):
        """Une phrase dite dans les lunettes reliées à l'app du téléphone, déjà transcrite par le téléphone.

        Même chemin qu'une commande dite au micro de l'ordinateur (demande de l'équipe iOS, 2026-09-14) :
        les interceptions d'abord (mode invité, pas à pas, vision, résumé…), puis le chat avec la règle de
        la voix (lunettes exigées, pas d'aperçu écrit, réponse orale courte). La réponse est rendue au
        téléphone, qui la lit : l'ordinateur resté à la maison ne parle pas.
        Ce qui ouvrirait le micro de l'ordinateur (mode traduction, interprète) est refusé avec la phrase à dire."""
        texte = (body.texte or "").strip()
        if not texte:
            raise HTTPException(422, "Phrase vide.")
        exiger_lunettes(ctx, "voix")
        if ctx.settings.user.privacy_mode:
            raise HTTPException(409, "Mode confidentiel actif : IRIS ne traite aucune commande vocale.")
        debut = time.monotonic()

        def reponse(phrase: str, intercepte: bool, **extra: Any) -> dict:
            return {"texte": phrase, "intercepte": intercepte,
                    "duree_ms": int((time.monotonic() - debut) * 1000), **extra}

        voix = ctx.voice
        try:
            from .traduction import est_phrase_interprete

            ouvre_micro = est_phrase_interprete(texte) == "demarrer"
        except Exception:  # pragma: no cover - module voisin absent
            ouvre_micro = False
        est_traduction = getattr(voix, "_est_demande_traduction", None)
        if ouvre_micro or (callable(est_traduction) and est_traduction(texte)):
            return reponse(PHRASE_MICRO_MAISON, True, refus="micro_de_la_maison")
        mode_invite = getattr(ctx, "mode_invite", None)
        if bool(getattr(mode_invite, "actif", False)):
            # Filet (constat du 2026-09-14) : cette phrase a été transcrite par le téléphone, sans audio ; aucun
            # verrou vocal ne l'a admise. Elle ne sort jamais du mode invité, même si l'interception manquait.
            try:
                from .mode_invite import _DESACTIVER, SORTIE_VOCALE_REFUSEE, _normaliser, heure_locale

                if _DESACTIVER.match(_normaliser(texte)):
                    ctx.consent.log("mode_invite_sortie_vocale_refusee",
                                    detail="commande transcrite par le téléphone, voix non vérifiée")
                    return reponse(SORTIE_VOCALE_REFUSEE.format(heure=heure_locale(mode_invite.jusqua)), True,
                                   refus="voix_non_verifiee")
            except ImportError:  # pragma: no cover - module voisin absent
                pass
        if getattr(voix, "_interceptions", None):
            # Dans un fil : _intercepter attend les interceptions asynchrones sur la boucle du service, qui
            # doit rester libre (un appel direct ici l'attendrait sur elle-même). L'origine dit aux interceptions
            # que cette phrase n'est pas passée par le verrou vocal du micro de l'ordinateur.
            from .voice.listener import ORIGINE_VOIX_TELEPHONE

            phrase = await asyncio.to_thread(voix._intercepter, texte, ORIGINE_VOIX_TELEPHONE)
            if phrase is not None:
                return reponse(phrase, True)
        if body.conversation_id:
            conv = ctx.chat.get_conversation(body.conversation_id)
            if conv is None:
                raise HTTPException(404, "conversation introuvable")
        else:
            conv = ctx.voice_conversation()
        try:
            resultat = await ctx.chat.run_and_wait(conv["id"], texte, agent="auto", source="voix_telephone")
        except RuntimeError:
            raise HTTPException(409, "Une réponse est déjà en cours dans cette conversation.")
        message = resultat.get("message") or {}
        extra: dict[str, Any] = {"conversation_id": conv["id"], "message_id": message.get("id")}
        if resultat.get("glasses_required"):
            extra["lunettes_requises"] = True
        if resultat.get("consent_required"):
            extra["consentement_requis"] = resultat["consent_required"]
            return reponse("Je ne peux pas envoyer cette demande : le consentement n'est pas accordé. "
                           "Ouvre Confidentialité dans IRIS.", False, **extra)
        return reponse(message.get("text") or resultat.get("error") or "", False, **extra)

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
        from .memory import MemoireSuspendue

        try:
            item = ctx.memory.add(body.text, source="user")
        except MemoireSuspendue as exc:
            raise HTTPException(409, str(exc))
        ctx.hub.publish("memory.updated", count=ctx.memory.count())
        return item

    # Déclarée AVANT /api/memory/{memory_id} : sinon « plage » y est pris pour un identifiant, et la
    # route répond « rien supprimé » sans le dire (constat de l'équipe écoute, 2026-09-13).
    @app.delete("/api/memory/plage", dependencies=auth)
    def delete_memory_plage(debut: str | None = Query(default=None), fin: str | None = Query(default=None)):
        try:
            n = ctx.memory.supprimer_plage(debut, fin)
        except ValueError as exc:
            raise HTTPException(422, str(exc))
        ctx.consent.log("memory_range_deleted", detail=f"{n} souvenir(s) ; debut={debut or '-'} fin={fin or '-'}")
        ctx.hub.publish("memory.updated", count=ctx.memory.count())
        return {"supprimes": n}

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
        return {"deleted": n, "journal_technique": _vider_journal_technique()}

    def _vider_journal_technique() -> int:
        """Tout effacer, c'est aussi le journal technique (backend.log) : ses lignes ne portent plus de texte
        dicté, mais celles d'une version antérieure au 2026-09-14 en portaient, et il n'est pas chiffré."""
        try:
            from .verrou import purger_journal_technique

            return purger_journal_technique(None)
        except Exception as exc:  # pragma: no cover - l'effacement demandé a déjà eu lieu
            log.warning("journal technique non vidé : %s", exc)
            return 0

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
        exiger_lunettes(ctx, "taches")
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

    # ------------------------------------------------------------------ mode traduction
    # Le mode a trois entrées : la voix (« Iris, traduis ce qu'il dit »), l'outil du modèle, et
    # l'interface — celle-ci. Toutes passent par le même service ; c'est le fil audio de l'écoute
    # (VoiceListener._boucle_traduction) qui écoute réellement l'interlocuteur.
    @app.get("/api/traduction/etat", dependencies=auth)
    def traduction_etat():
        return {
            **ctx.traduction.etat(),
            "langues": [{"code": c, "nom": n} for c, n in NOMS_LANGUES.items()],
            "empechement": ctx.traduction.pourquoi_impossible(),
            "ecoute": ctx.voice.running,
        }

    @app.post("/api/traduction/demarrer", dependencies=auth)
    def traduction_demarrer(body: TraductionIn):
        """Ouvre le mode depuis l'interface, et fait en sorte qu'IRIS écoute VRAIMENT.

        Armer le service (`ctx.traduction.demarrer`) ne suffit pas : l'écoute route la parole vers la
        traduction sur son propre fil audio, et ce fil doit tourner. Donc :
        1. si l'écoute est arrêtée, on la démarre par `ctx.voice.start()`, qui applique lui-même
           TOUS les verrous (micro coupé, mode confidentiel, lunettes exigées) et refuse sinon ;
        2. on ouvre le mode par `ctx.voice.demander_traduction`, qui ajoute au service la seule
           condition qu'il ignore — le consentement « audio brut » — et qui dit honnêtement quand
           le micro n'écoute pas ;
        3. le fil audio, lui, voit le mode armé au bloc suivant et entre dans la boucle de
           traduction sans attendre un mot d'activation (VoiceListener._wake_cycle).
        La phrase rendue est toujours vraie : elle annonce la traduction, ou dit pourquoi il n'y en a pas."""
        exiger_lunettes_pc(ctx, "traduction")  # micro de l'ordinateur
        empeche = ctx.traduction.pourquoi_impossible()
        if not empeche and ctx.consent.is_granted("audio_raw") and not ctx.voice.running:
            ctx.voice.start()  # les verrous sont dans start() ; s'il refuse, `running` reste faux et il dit pourquoi
        reponse = ctx.voice.demander_traduction(body.langue)
        phrase = (reponse.get("phrase") or "").strip()
        if reponse.get("ouvert") and not ctx.voice.running and ctx.voice.error:
            phrase = f"{phrase} {ctx.voice.error}".strip()
        return {"phrase": phrase, "ecoute": ctx.voice.running, **ctx.traduction.etat()}

    @app.post("/api/traduction/arreter", dependencies=auth)
    def traduction_arreter():
        """Ferme le mode. La boucle d'écoute le voit au bloc suivant (0,25 s) et revient au mot d'activation."""
        return {"phrase": ctx.traduction.arreter("demande"), "ecoute": ctx.voice.running, **ctx.traduction.etat()}

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
        exiger_lunettes(ctx, "routines")
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
        exiger_lunettes(ctx, "resume_journee")
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
        exiger_lunettes(ctx, "surveillances")
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
    # En-têtes de sécurité de la page téléphone (CSP avec frame-ancestors, Permissions-Policy, nosniff) :
    # fabriqués par routes_mobile, posés ICI parce que ces trois routes masquent celles des modules.
    # Import protégé : si routes_mobile ne se charge pas, la page reste servie comme avant (sa balise
    # meta et la garde anti-cadre de coeur.js restent en place) plutôt que de disparaître.
    try:
        from .routes_mobile import reponse_agent_service, reponse_manifeste, reponse_page
    except Exception as exc:  # pragma: no cover - dépend d'un module voisin
        log.warning("page téléphone : en-têtes de sécurité indisponibles (%s)", exc)
        reponse_agent_service = reponse_manifeste = reponse_page = None

    @app.get("/manifest.webmanifest")
    def manifeste():
        """Décrit l'application au téléphone : nom, icônes, plein écran."""
        if reponse_manifeste is not None:
            return reponse_manifeste(MANIFESTE)
        return JSONResponse(MANIFESTE, media_type="application/manifest+json")

    @app.get("/sw.js")
    def agent_service():
        """Agent de service : Android l'exige pour proposer l'installation."""
        if reponse_agent_service is not None:
            return reponse_agent_service(AGENT_SERVICE)
        return Response(AGENT_SERVICE, media_type="application/javascript")

    @app.get("/icone-{taille}.png")
    def icone(taille: int):
        fichier = Path(__file__).parent / "assets" / f"icone-{taille}.png"
        if taille not in (192, 512) or not fichier.exists():
            raise HTTPException(404, "icône introuvable")
        return Response(fichier.read_bytes(), media_type="image/png",
                        headers={"Cache-Control": "public, max-age=86400"})

    @app.get("/m", response_class=HTMLResponse)
    def page_mobile(request: Request):
        """Coquille de l'interface téléphone. Volontairement publique : elle ne contient aucune
        donnée, seulement le formulaire de connexion. Tout ce qui suit exige une session."""
        if reponse_page is not None:
            return reponse_page(ctx, request, PAGE_MOBILE)
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

    # ------------------------------------------------------------------ délégation à OpenCode
    @app.get("/api/opencode/etat", dependencies=auth)
    def opencode_etat():
        """Dit proprement pourquoi la délégation dort, au lieu de la faire disparaître en silence.

        L'outil n'est pas offert au modèle tant qu'OpenCode n'est pas utilisable — c'est voulu, une
        porte qui ne s'ouvre pas ne doit pas être montrée. Mais l'absence doit rester lisible
        quelque part, sinon personne ne saura jamais qu'il suffit d'installer OpenCode."""
        from .tools import opencode_raison, opencode_utilisable

        service = getattr(ctx, "opencode", None)
        utilisable = opencode_utilisable(service)
        return {
            "branche": service is not None,
            "utilisable": utilisable,
            "raison": "" if utilisable else opencode_raison(service),
        }

    # ------------------------------------------------------------------ lunettes
    # ------------------------------------------------------------------ présence des lunettes
    @app.get("/api/lunettes/presence", dependencies=auth)
    def lunettes_presence():
        return ctx.presence_lunettes.etat()

    @app.post("/api/lunettes/attestation", dependencies=auth)
    def lunettes_attestation(body: AttestationLunettesIn):
        return ctx.presence_lunettes.attester(body.nom, body.identifiant, body.batterie, body.source)

    @app.delete("/api/lunettes/attestation", dependencies=auth)
    def lunettes_attestation_retirer(identifiant: str | None = Query(default=None, max_length=120)):
        return ctx.presence_lunettes.retirer_attestation(identifiant)

    @app.post("/api/lunettes/association", dependencies=auth)
    def lunettes_association(body: AssociationLunettesIn):
        """Associe un appareil de plus (second téléphone, app iPhone après la page Android) aux lunettes connues
        de cet ordinateur. Le premier appareil est associé à sa première attestation ; les suivants exigent le
        mot de passe du propriétaire. Contre-vérification du 2026-09-14 : sans mot de passe défini, la route
        associait n'importe quel identifiant inventé (valide=True) ; elle répond maintenant 409."""
        if not ctx.comptes.configure:
            raise HTTPException(409, MESSAGE_ASSOCIATION_SANS_COMPTE)
        trop = getattr(ctx.comptes, "_trop_d_essais", None)
        if callable(trop) and trop():
            raise HTTPException(429, "Trop de tentatives : réessayez dans quelques minutes.")
        valide = bool(body.mot_de_passe) and ctx.comptes.verifier(body.mot_de_passe or "")
        return ctx.presence_lunettes.associer(body.nom, body.identifiant, valide)

    # Mode démonstration : accès propriétaire CACHÉ (décision de Miguel, 2026-09-13). Jamais affiché
    # dans un écran client ; exige le mot de passe du propriétaire.
    @app.post("/api/demo/activer", dependencies=auth)
    def demo_activer(body: DemoIn):
        if not ctx.comptes.configure:
            raise HTTPException(409, "Crée d'abord le mot de passe du propriétaire.")
        if not ctx.comptes.verifier(body.mot_de_passe):
            raise HTTPException(403, "Mot de passe incorrect.")
        user = ctx.settings.update({"demo_sans_lunettes": True})
        # Nom neutre dans le registre : il est visible par quiconque ouvre Confidentialité et part dans
        # l'export ; l'accès propriétaire caché ne s'y nomme pas.
        ctx.consent.log("acces_proprietaire", detail="mot de passe vérifié")
        ctx.hub.publish("settings.updated", settings=user.model_dump())
        return ctx.presence_lunettes.etat()

    @app.post("/api/demo/desactiver", dependencies=auth)
    def demo_desactiver():
        user = ctx.settings.update({"demo_sans_lunettes": False})
        ctx.consent.log("acces_proprietaire_fin")
        ctx.hub.publish("settings.updated", settings=user.model_dump())
        return ctx.presence_lunettes.etat()

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
        # Le nom journalisé est celui annoncé par l'appareil (glasses.connect), pas celui fourni par l'appelant.
        ctx.consent.log("glasses_connected", detail=f"{(status.get('device') or {}).get('name') or ''} {body.address}")
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

    @app.post("/api/glasses/photo", dependencies=auth)
    async def glasses_photo(body: GlassesPhotoIn):
        exiger_lunettes_pc(ctx, "photo_lunettes")  # caméra reliée à l'ordinateur
        # Caméra des lunettes VELA : déclenche une prise de vue et rapatrie le JPEG EN LOCAL.
        # Le module est honnête par construction — il lève CameraIndisponible sur la paire audio
        # (pas de service ae00) et ProtocoleNonConfirme tant que l'en-tête de trame n'est pas prouvé
        # (sauf mode « lunettes_exploration »). On renvoie 409 avec le message tel quel dans ces cas :
        # ce n'est pas une panne, c'est une limite assumée qu'on affiche honnêtement à l'utilisateur.
        from .lunettes_camera import (
            CameraLunettes, CameraIndisponible, ProtocoleNonConfirme, refus_camera_client,
        )

        cam = CameraLunettes(ctx.glasses)
        try:
            res = await cam.prendre_photo(reconnaissance=bool(body.reconnaissance))
        except (CameraIndisponible, ProtocoleNonConfirme) as exc:
            # {code, message} : la phrase client ; le texte technique du module reste au journal.
            raise HTTPException(409, refus_camera_client(exc))
        except Exception:
            # Détail (chemins locaux, erreur BLE) au journal, pas dans la réponse HTTP.
            log.exception("échec de la prise de photo des lunettes")
            raise HTTPException(500, "La prise de photo a échoué.")
        if res.ok and res.chemin:
            ctx.consent.log("lunettes_photo", detail=Path(str(res.chemin)).name)  # le nom seul, pas le chemin
            ctx.hub.publish("glasses.photo", chemin=res.chemin, octets=res.octets)
        return {
            "ok": res.ok,
            "chemin": res.chemin,
            "octets": res.octets,
            "constat": res.constat,
            "paquets": len(res.paquets_recus),
        }

    @app.get("/api/glasses/captures", dependencies=auth)
    def glasses_captures():
        # Liste les photos déjà rapatriées localement (dossier data_dir/captures). Tri du plus récent
        # au plus ancien. Rien ici ne quitte l'ordinateur : ce sont des fichiers locaux.
        from datetime import datetime, timezone

        dossier = ctx.settings.data_dir / "captures"
        items: list[dict] = []
        if dossier.is_dir():
            for f in sorted(dossier.glob("*.jpg"), key=lambda p: p.stat().st_mtime, reverse=True):
                st = f.stat()
                items.append({
                    "nom": f.name,
                    "octets": st.st_size,
                    "modifie": datetime.fromtimestamp(st.st_mtime, timezone.utc).isoformat(timespec="seconds"),
                })
        return {"captures": items}

    @app.get("/api/glasses/captures/{nom}", dependencies=auth)
    def glasses_capture_fichier(nom: str):
        # Sert une photo locale. On refuse tout nom qui tenterait de sortir du dossier des captures
        # (pas de séparateur, pas de « .. ») : un chemin ne doit jamais permettre de lire ailleurs.
        if "/" in nom or "\\" in nom or ".." in nom or not nom.lower().endswith(".jpg"):
            raise HTTPException(400, "nom de fichier invalide")
        chemin = (ctx.settings.data_dir / "captures" / nom).resolve()
        base = (ctx.settings.data_dir / "captures").resolve()
        if base not in chemin.parents or not chemin.is_file():
            raise HTTPException(404, "capture introuvable")
        return Response(chemin.read_bytes(), media_type="image/jpeg")

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
        # Même règle que le HTTP, par la même fonction (voir raison_de_refus). On ferme AVANT
        # d'accepter : la poignée de main n'aboutit pas, le serveur répond 403, et le code 4401
        # avec sa phrase restent lisibles par le client qui sait les lire.
        raison = raison_de_refus(ws)
        if raison is not None:
            await ws.close(code=4401, reason=raison)
            return
        await ws.accept()
        q = ctx.hub.subscribe()
        await ws.send_text(EventHub.encode({"type": "hello", "status": ctx.status()}))

        async def reader():
            while True:
                raw = await ws.receive_json()
                await handle_client_message(raw)

        def verrouillee() -> bool:
            verrou = getattr(ctx, "verrou", None)
            return bool(verrou is not None and getattr(verrou, "verrouille", False))

        async def handle_client_message(msg: dict[str, Any]) -> None:
            # Un WebSocket ouvert AVANT le verrouillage ne doit pas continuer à piloter l'ordinateur.
            if verrouillee():
                await ws.close(code=4401, reason="IRIS est verrouillée.")
                return
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
                if event.get("type") == "verrou.etat" and event.get("verrouille"):
                    await ws.close(code=4401, reason="IRIS est verrouillée.")
                    break
        except (WebSocketDisconnect, RuntimeError):
            pass
        finally:
            reader_task.cancel()
            ctx.hub.unsubscribe(q)

    # ------------------------------------------------------------------ courriel et téléphonie
    # Le routeur du chantier D (routes_communications.py) : c'est lui qui donne enfin au téléphone
    # le moyen de LIRE le brouillon de SMS que telephonie.py déposait — jusqu'ici, IRIS annonçait
    # « c'est prêt sur ton téléphone » et rien n'y apparaissait. Import protégé, comme
    # construire_opencode : le module a été écrit en parallèle de ce câblage, et une IRIS qui
    # refuse de démarrer parce qu'un module manque est pire que l'absence de ses routes. Il
    # s'inclut avec `auth`, la même garde que /api/status : session ou jeton maître local.
    try:
        from .routes_communications import creer_routeur
    except Exception as exc:
        log.info("routes de communication indisponibles (module absent) : %s", exc)
    else:
        try:
            app.include_router(creer_routeur(ctx), dependencies=auth)
        except Exception as exc:
            log.warning("routeur de communication non branché : %s", exc)

    # Webhooks ENTRANTS de la ligne Twilio d'IRIS (SMS et appels reçus). SANS `auth` à dessein :
    # Twilio ne présente pas de jeton de session, c'est un tiers qui appelle de l'extérieur. Chaque
    # route exige à la place une signature Twilio valide (routes_twilio.py) et échoue fermé sans
    # elle. Il faut une URL publique (tunnel Cloudflare) déclarée à Twilio et à TWILIO_PUBLIC_BASE.
    try:
        from .routes_twilio import creer_routeur_twilio
    except Exception as exc:
        log.info("routes Twilio entrantes indisponibles (module absent) : %s", exc)
    else:
        try:
            app.include_router(creer_routeur_twilio(ctx))
        except Exception as exc:
            log.warning("routeur Twilio entrant non branché : %s", exc)

    _brancher_modules(app, ctx, auth)
    return app


# Modules du chantier du 2026-09-13, chacun dans son propre fichier : routes_<nom>.py expose
# creer_routeur(ctx) -> APIRouter. Import protégé (un module absent ou cassé ne doit JAMAIS
# empêcher IRIS de démarrer). Crochets facultatifs sur le routeur : iris_demarrage et iris_arret.
MODULES_ROUTEURS: tuple[tuple[str, bool], ...] = (
    ("routes_accessibilite", True),
    ("routes_ecoute", True),
    ("routes_alertes", True),
    ("routes_album", True),
    ("routes_interprete", True),
    ("routes_quotidien", True),
    ("routes_assistants", True),
    ("routes_confiance", True),
    ("routes_partage", True),
    ("routes_mobile", False),  # fichiers statiques de la page téléphone : publics, comme /m
)


def _brancher_modules(app: FastAPI, ctx: AppContext, auth: list) -> None:
    for module, protege in MODULES_ROUTEURS:
        try:
            mod = importlib.import_module(f".{module}", __package__)
        except Exception as exc:
            log.info("module %s indisponible : %s", module, exc)
            continue
        try:
            routeur = mod.creer_routeur(ctx)
            if protege:
                app.include_router(routeur, dependencies=auth)
            else:
                app.include_router(routeur)
        except Exception as exc:
            log.warning("module %s non branché : %s", module, exc)
            continue
        for attribut, liste in (("iris_demarrage", ctx.demarrages), ("iris_arret", ctx.arrets)):
            crochet = getattr(routeur, attribut, None)
            if callable(crochet):
                liste.append(crochet)
