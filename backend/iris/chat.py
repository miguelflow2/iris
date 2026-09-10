"""Service de conversation : historique chiffré, routage d'agent, streaming, outils, confirmations."""
from __future__ import annotations

import asyncio
import json
import logging
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable

from .capture import CaptureIndicator
from .config import Settings
from .connectors import ChatOptions, ConnectorError, build_connector
from .consent import DATA_TYPES, ConsentGate, ConsentRequired, LocalOnlyMode
from .db import Database
from .events import EventHub
from .memory import MemoryService
from .plans import QuotaExceeded
from .quick_commands import match as match_quick_command
from .router import AgentRouter, NoAgentAvailable, _has
from .security.crypto import Crypto
from .security.secrets import SecretStore
from .tools import ToolContext, make_tool_runner, opencode_utilisable, tool_specs

log = logging.getLogger("iris.chat")

DEFAULT_TITLE = "Nouvelle conversation"
TITLE_MAX = 42


def clean_title(text: str, limit: int = TITLE_MAX) -> str:
    """Titre de conversation lisible à partir de la première demande : une seule ligne, majuscule
    initiale, sans ponctuation de fin superflue, coupé sur une frontière de mot. Le texte brut de
    l'utilisateur fait un titre de banc d'essai (« t2 », « explique-moi en une phrase ce que f… »).
    Le « ? » et le « ! » sont conservés : « Quelle heure est-il ? » reste juste."""
    ligne = " ".join(text.split())
    if not ligne:
        return DEFAULT_TITLE
    if len(ligne) > limit:
        coupe = ligne[:limit]
        espace = coupe.rfind(" ")
        if espace > limit // 2:
            coupe = coupe[:espace]
        ligne = coupe.rstrip(" ,;:-–—.…") + "…"
    else:
        ligne = ligne.rstrip(" ,;:.…")
    if not ligne:
        return DEFAULT_TITLE
    return ligne[0].upper() + ligne[1:]

_SENTENCE_END = re.compile(r"(?<=[.!?…])\s+|\n+")
# réponses d'assistant qui prétendent avoir agi : retirées de l'historique des demandes d'action (le modèle les imite)
ACTION_CLAIM = re.compile(r"c'est fait|c'est ouvert|j'ouvre|je lance|je rouvre|est ouvert|est lanc|je mets|c'est lanc|voil[àa]", re.IGNORECASE)
# verbes d'action clairs : outil obligatoire + garde anti « c'est fait » (les demandes de rédaction/code n'en font pas partie)
STRICT_ACTION = [
    "ouvre", "ouvrir", "lance", "lancement", "démarre", "demarre", "ferme", "va sur", "vas sur", "mets ", "met de la",
    "mets de la", "joue", "affiche", "capture", "verrouille", "tape ", "clique", "appuie", "installe", "exécute", "execute",
    "youtube", "google", "spotify", "navigateur", "chrome", "musique", "vidéo", "video", "open ", "launch ", "play ",
    "connecte", "connecter", "omnivox", "navigue", "va dans", "vas dans", "mes notes", "mon horaire", "sur le site",
    # surveillance durable : « surveille la conversation », « préviens-moi si le prix baisse »…
    "surveille", "surveiller", "surveillance", "garde un œil", "garde un oeil", "préviens-moi", "previens-moi",
    "avertis-moi", "tiens-moi au courant", "en permanence", "guette",
]
WEB_KEYWORDS = ["omnivox", "connecte", "site", "navigue", "page", "portail", "mes notes", "mon horaire", "formulaire", "inscri"]
# demandes de création (jeu, site, application, script) : le modèle doit ÉCRIRE les fichiers avec write_file
STRICT_BUILD = [
    "crée", "cree", "créer", "creer", "développe", "developpe", "code-moi", "code moi", "programme-moi", "programme moi",
    "fais-moi", "fais moi", "fait-moi", "génère", "genere", "construis", "build me", "create ", "make me", "write me",
    "un jeu", "un site", "une app", "une application", "un script", "un programme", "une page web", "un bot",
]
# Lecture d'écran pour malvoyants : « lis-moi l'écran », « décris l'écran », « qu'y a-t-il à l'écran ? ».
# C'est souvent la PREMIÈRE phrase d'un utilisateur qui ne voit pas. Avant, aucun de ces mots n'était
# un déclencheur d'écran : tool_specs(screen=False) retirait take_screenshot, et IRIS « décrivait »
# de mémoire un écran qu'elle n'avait jamais regardé — un échec silencieux, impossible à vérifier par
# quelqu'un qui ne voit pas. On évite « lis » nu (présent dans « utilise », « réalise ») : seules les
# formes qui ne peuvent dire QUE la lecture d'écran.
SCREEN_READ_KEYWORDS = [
    "lis-moi", "lis moi", "lis-le-moi", "lis le moi", "lis-les", "lis tout", "lis ce qui", "lis ce qu'",
    "lis l'écran", "lis l'ecran", "lis la page", "lis cette", "lis mon écran", "lis mon ecran",
    "lire l'écran", "lire l'ecran", "lire mon écran", "lire mon ecran", "lire ce qui", "lire la page",
    "lecture d'écran", "lecture d'ecran", "lecture de l'écran", "lecture de l'ecran",
    "décris", "decris", "décris-moi", "decris-moi", "décris moi", "decris moi", "décrire", "decrire", "décrit",
    "qu'est-ce qu'il y a à l'écran", "qu'est-ce qu'il y a a l'ecran", "qu'y a-t-il à l'écran", "qu'y a-t-il a l'ecran",
    "qu'est-ce qui est affiché", "qu'est-ce qui est affiche", "que dit l'écran", "que dit l'ecran",
    "que vois-tu à l'écran", "que vois-tu a l'ecran", "contenu de l'écran", "contenu de l'ecran",
    "qu'est-ce qu'il y a d'écrit", "qu'est-ce qu'il y a d'ecrit", "qu'est-ce qui est écrit", "qu'est-ce qui est ecrit",
]
# demandes qui exigent de voir l'écran / la souris
SCREEN_KEYWORDS = [
    "clique", "click", "double-clique", "à l'écran", "a l'ecran", "sur l'écran", "sur l'ecran", "dans le jeu", "dans la fenêtre",
    "dans la fenetre", "bouton", "souris", "glisse", "fais défiler", "fais defiler", "scroll", "regarde l'écran", "regarde mon écran",
    "que vois-tu", "qu'est-ce que tu vois", "sélectionne", "selectionne", "menu", "onglet", "coche", "case",
] + SCREEN_READ_KEYWORDS
# Applications que l'on pilote en regardant l'écran : ouvrir ne suffit pas, il faut ensuite cliquer.
APPLICATIONS_PILOTABLES = (
    "spotify", "deezer", "apple music", "soundcloud", "tidal", "amazon music", "youtube music",
    "netflix", "disney", "prime video", "crave", "vlc", "plex", "itunes", "twitch", "audible",
    "word", "excel", "powerpoint", "outlook", "teams", "discord", "slack", "notion", "obsidian",
    "photoshop", "premiere", "capcut", "steam", "epic games", "explorateur", "parametres",
    "calculatrice", "bloc-notes", "bloc notes", "paint", "navigateur", "chrome", "edge", "firefox",
)
# Verbes qui demandent d'agir DANS l'application, une fois ouverte.
VERBES_DANS_APP = (
    "joue", "jouer", "lance", "lancer", "mets", "met", "ecoute", "écoute", "cherche", "trouve",
    "ouvre le", "ouvre la", "ouvre mon", "ouvre ma", "ouvre mes", "connecte", "envoie", "ecris",
    "écris", "tape", "supprime", "renomme", "telecharge", "télécharge", "partage", "modifie",
    "ajoute", "coche", "choisis", "selectionne", "sélectionne", "monte", "baisse", "passe",
)
# Ce qui appartient à l'utilisateur et ne se trouve que DANS son application.
DONNEES_PERSONNELLES = (
    "ma liste", "mes listes", "ma playlist", "mes playlists", "mes chansons", "mes musiques",
    "mes favoris", "mes titres", "mes morceaux", "ma bibliotheque", "ma bibliothèque",
    "mes aimes", "aimée", "aimees", "aimées", "mon historique", "mes fichiers", "mes documents",
    "mes photos", "mes courriels", "mes messages", "mon compte", "mon profil",
)


def besoin_de_piloter(texte: str) -> bool:
    """Faut-il donner à IRIS les yeux et les mains ?

    Oui dès qu'on lui demande d'agir DANS une application, et pas seulement de l'ouvrir. Sans
    cela elle ouvre Spotify et reste plantée devant, incapable de cliquer sur quoi que ce soit."""
    app_nommee = any(a in texte for a in APPLICATIONS_PILOTABLES)
    if not app_nommee:
        return any(d in texte for d in DONNEES_PERSONNELLES)
    # Une application est nommée : est-ce qu'on lui demande plus que de s'ouvrir ?
    if any(d in texte for d in DONNEES_PERSONNELLES):
        return True
    if " et " in texte or " puis " in texte or " ensuite " in texte:
        return True
    return sum(1 for v in VERBES_DANS_APP if v in texte) >= 2


CONSIGNE_PILOTAGE = """PILOTER UNE APPLICATION. Tu peux voir l'écran et t'en servir comme l'utilisateur le ferait.
La marche à suivre, dans cet ordre, sans la brûler :
1. Ouvre l'application avec open_application, puis attends qu'elle soit là.
2. take_screenshot pour VOIR où tu en es. Ne clique jamais sans avoir regardé.
3. find_on_screen ou click_text pour viser un élément par son texte. C'est plus sûr que des coordonnées.
4. press_keys pour ce qui a un raccourci : c'est plus fiable qu'un clic. Beaucoup d'applications
   ont une recherche interne (souvent Ctrl+L, Ctrl+F ou Ctrl+K) : sers-t'en plutôt que de fouiller.
5. Reprends une capture pour VÉRIFIER que ton action a fait ce que tu croyais.
6. Si deux tentatives échouent, arrête-toi et dis à l'utilisateur ce que tu vois et ce qui bloque.
   Ne clique jamais au hasard en espérant tomber juste.
Ce que l'utilisateur te demande dans SA bibliothèque (sa liste, ses favoris, ses fichiers) n'existe
que dans son application : ne le remplace jamais par une recherche sur le web."""

ACTION_FAILED_TEXT = "Je n'ai pas réussi à exécuter cette demande : aucune action n'a été faite sur l'ordinateur. Reformule-la, par exemple : « ouvre Google », « lance YouTube » ou « crée un jeu de morpion dans un fichier HTML »."


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


_EN_WORDS = {"the", "and", "is", "are", "you", "your", "with", "this", "that", "have", "has", "will", "can", "for", "it", "its",
             "here", "now", "done", "open", "opened", "opening", "file", "files", "folder", "browser", "playing", "please", "let",
             "me", "know", "want", "would", "should", "there", "what", "which", "how", "i've", "i'm", "it's", "here's", "sure", "okay"}
_FR_WORDS = {"le", "la", "les", "de", "des", "du", "et", "est", "vous", "votre", "vos", "avec", "ce", "cette", "que", "qui", "pour",
             "dans", "une", "un", "sur", "je", "tu", "c'est", "voici", "voilà", "fait", "ouvert", "fichier", "dossier", "navigateur",
             "pas", "ne", "en", "au", "aux", "ton", "ta", "tes", "veux", "veux-tu", "oui", "non", "il", "elle", "nous", "sont"}


def _looks_english(text: str) -> bool:
    """Vrai si la phrase est majoritairement en anglais (garde-fou avant la lecture à voix haute)."""
    words = re.findall(r"[a-zà-ÿ']+", text.lower())
    if len(words) < 3:
        return False
    en = sum(1 for w in words if w in _EN_WORDS)
    fr = sum(1 for w in words if w in _FR_WORDS)
    return en >= 2 and en > fr * 1.5


class SentenceSpeaker:
    """Lit la réponse à voix haute phrase par phrase pendant le streaming (latence perçue minimale)."""

    def __init__(self, speak: Callable[[str], Any]):
        self.speak = speak
        self.buffer = ""
        self.spoken: list[str] = []
        self.foreign: list[str] = []  # phrases retenues parce qu'elles ne sont pas en français (traduites avant lecture)

    def feed(self, text: str) -> None:
        self.buffer += text
        parts = _SENTENCE_END.split(self.buffer)
        if len(parts) <= 1:
            # premier fragment lu dès la première virgule (le reste suit) ; sinon phrase longue : on coupe à 220 caractères
            limit = 45 if not self.spoken else 220
            if len(self.buffer) > limit and "," in self.buffer:
                head, tail = self.buffer.rsplit(",", 1)
                self._say(head + ",")
                self.buffer = tail
            return
        for sentence in parts[:-1]:
            self._say(sentence)
        self.buffer = parts[-1]

    def flush(self) -> None:
        if self.buffer.strip():
            self._say(self.buffer)
        self.buffer = ""

    def _say(self, sentence: str) -> None:
        sentence = sentence.strip()
        if not sentence:
            return
        if _looks_english(sentence):
            self.foreign.append(sentence)
            return
        self.spoken.append(sentence)
        self.speak(sentence)


class ChatService:
    def __init__(
        self,
        db: Database,
        crypto: Crypto,
        settings: Settings,
        secrets: SecretStore,
        consent: ConsentGate,
        hub: EventHub,
        memory: MemoryService,
        router: AgentRouter,
        capture: CaptureIndicator,
    ):
        self.db = db
        self.crypto = crypto
        self.settings = settings
        self.secrets = secrets
        self.consent = consent
        self.hub = hub
        self.memory = memory
        self.presence = None  # Presence (injecté par AppContext) : IRIS sait depuis quand elle vit ici
        self.watches = None  # WatchService (injecté par AppContext) : surveillances durables
        self.router = router
        self.capture = capture
        self._running: dict[str, asyncio.Task] = {}
        self._confirms: dict[str, asyncio.Future] = {}
        # Par la voix, personne ne clique : ce puits laisse le fil vocal poser la question et
        # écouter la réponse. Trou trouvé le 5 septembre 2026 — un accord vocal était impossible,
        # ce qui rendait courriel, SMS et import d'identifiants inutilisables sans écran.
        self._sink_confirm_vocal = None
        # Même besoin pour une commande venue du téléphone (canal inverse, source="distant") : la
        # question d'accord doit remonter jusqu'au téléphone. La télécommande s'enregistre ici.
        self._sink_confirm_distant = None
        # injecté par TaskService : (titre, instructions, agent) -> dict tâche
        self.create_task_fn: Callable[[str, str, str], Awaitable[dict]] | None = None
        self.routines = None  # RoutineService (injecté)
        self.reminders = None  # ReminderService (injecté)
        self.web = None  # WebAgent (injecté)
        self.glasses = None  # GlassesService (injecté)
        self.courriel = None  # Postier (injecté)
        self.telephonie = None  # Telephoniste (injecté)
        self.traduction = None  # ServiceTraduction (injecté)
        self.voice = None  # VoiceListener (injecté) : lui seul sait si un micro écoute vraiment
        self.plans = None  # PlanService (injecté)
        # ServiceOpenCode (injecté) : déléguer la programmation. Reste None tant qu'OpenCode n'est
        # pas installé, et l'outil n'est alors même pas offert au modèle — IRIS ne change pas.
        self.opencode = None

    # ------------------------------------------------------------------ niveaux de modèles
    @staticmethod
    def _pick_model(u, is_voice: bool = False, is_build: bool = False, is_screen: bool = False, plan_models: dict | None = None) -> str | None:
        """Vision pour l'écran, raisonnement pour créer/planifier, modèle rapide pour la voix courante.
        Les modèles inclus dans le plan servent de défaut ; les réglages de l'utilisateur ont priorité."""
        pm = plan_models or {}
        if is_screen and (u.vision_model or pm.get("vision")):
            return u.vision_model or pm.get("vision")
        if is_build and (u.reasoning_model or pm.get("reasoning")):
            return u.reasoning_model or pm.get("reasoning")
        if is_voice and (u.voice_model or pm.get("fast")):
            return u.voice_model or pm.get("fast")
        return None

    async def _run_quick(self, conv_id: str, quick, source: str) -> dict:
        """Exécute une commande reconnue localement : une seule action, une réponse courte, aucun tour de modèle."""
        assistant_id = uuid.uuid4().hex
        self.hub.publish("chat.started", conversation_id=conv_id, message_id=assistant_id, agent="local", model="",
                         reason="commande reconnue localement")
        events: list[dict] = []
        text = quick.reply
        if quick.tool:
            ctx = ToolContext(
                settings=self.settings, consent=self.consent, capture=self.capture, memory=self.memory, agent="local",
                confirm=lambda title, detail: self._confirm(conv_id, title, detail, source), create_task=self.create_task_fn,
                routines=self.routines, reminders=self.reminders, watches=self.watches,
                glasses=self.glasses, courriel=self.courriel, telephonie=self.telephonie,
                traduction=self.traduction, voice=self.voice, web=self.web,
                opencode=self.opencode, source=source, hub=self.hub,
            )
            runner = make_tool_runner(ctx)
            try:
                raw = await runner(quick.tool, dict(quick.args))
                ok = not (isinstance(raw, dict) and raw.get("is_error"))
                content = raw["content"] if isinstance(raw, dict) else str(raw)
            except Exception as exc:
                ok, content = False, str(exc)
            ev = {"id": "local-0", "name": quick.tool, "input": dict(quick.args),
                  "status": "done" if ok else "error", "result": str(content)[:400]}
            events.append(ev)
            self.hub.publish("chat.tool", conversation_id=conv_id, message_id=assistant_id, tool=ev)
            if not ok:
                text = f"Je n'ai pas réussi : {str(content)[:200]}"
            elif not text and isinstance(content, str) and content.strip():
                # Certains outils rendent une phrase déjà écrite pour l'utilisateur — c'est le cas
                # du mode traduction, qui doit annoncer qu'il s'ouvre. Sans ceci, IRIS exécutait
                # l'outil et ne disait RIEN : le 5 septembre 2026, elle a ouvert le mode traduction
                # en silence, et personne n'aurait pu deviner qu'il était actif. Entrer dans un
                # mode sans le dire est le pire des ratés — on ne sait pas non plus quand en sortir.
                text = content.strip()[:400]
        self.hub.publish("chat.delta", conversation_id=conv_id, message_id=assistant_id, text=text)
        msg = self._add_message(conv_id, "assistant", text, agent="local", model="",
                                meta={"agent": "local", "tools": events, "source": source, "quick": quick.kind},
                                message_id=assistant_id)
        self.hub.publish("chat.done", conversation_id=conv_id, message=msg)
        return {"message": msg, "quick": quick.kind}

    async def _run_routine(self, conv_id: str, routine: dict, source: str) -> dict:
        assistant_id = uuid.uuid4().hex
        self.hub.publish("chat.started", conversation_id=conv_id, message_id=assistant_id, agent="routine", model="", reason=f"routine « {routine['name']} »")
        ctx = ToolContext(
            settings=self.settings, consent=self.consent, capture=self.capture, memory=self.memory, agent="routine",
            confirm=lambda title, detail: self._confirm(conv_id, title, detail, source), create_task=self.create_task_fn,
            routines=None, reminders=self.reminders, watches=self.watches,
            glasses=self.glasses, courriel=self.courriel, telephonie=self.telephonie,
            traduction=self.traduction, voice=self.voice, web=self.web,
            opencode=self.opencode, source=source, hub=self.hub,
        )
        runner = make_tool_runner(ctx)
        events: list[dict] = []
        results = await self.routines.run(routine, runner)
        for i, r in enumerate(results):
            ev = {"id": f"routine-{i}", "name": r["tool"], "input": r["args"], "status": "done" if r["ok"] else "error", "result": r["result"]}
            events.append(ev)
            self.hub.publish("chat.tool", conversation_id=conv_id, message_id=assistant_id, tool=ev)
        ok = sum(1 for r in results if r["ok"])
        text = f"Routine « {routine['name']} » exécutée : {ok} étape{'s' if ok > 1 else ''} sur {len(results)}."
        self.hub.publish("chat.delta", conversation_id=conv_id, message_id=assistant_id, text=text)
        msg = self._add_message(conv_id, "assistant", text, agent="routine", model="", meta={"agent": "routine", "tools": events, "source": source, "routine": routine["name"]}, message_id=assistant_id)
        self.hub.publish("chat.done", conversation_id=conv_id, message=msg)
        return {"message": msg, "routine": routine["name"]}

    async def summarize_day(self, day: str | None = None) -> dict:
        """Résumé de la journée (décisions, promesses, chiffres, idées) à partir de toutes les conversations."""
        from datetime import date

        target = day or date.today().isoformat()
        # les messages sont horodatés en UTC : on convertit la journée locale en intervalle UTC
        from datetime import datetime as _dt, time as _time, timedelta as _td

        local_start = _dt.combine(date.fromisoformat(target), _time.min).astimezone()
        start_utc = local_start.astimezone(timezone.utc).isoformat(timespec="seconds")
        end_utc = (local_start + _td(days=1)).astimezone(timezone.utc).isoformat(timespec="seconds")
        rows = self.db.query(
            "SELECT m.role, m.content_enc, c.kind FROM messages m JOIN conversations c ON c.id = m.conversation_id "
            "WHERE m.created_at >= ? AND m.created_at < ? ORDER BY m.created_at ASC LIMIT 400",
            (start_utc, end_utc),
        )
        lines = []
        for r in rows:
            try:
                content = json.loads(self.crypto.decrypt(r["content_enc"]))
            except Exception:
                continue
            t = (content.get("text") or "").strip()
            if t and r["role"] in ("user", "assistant"):
                lines.append(f"{'Utilisateur' if r['role'] == 'user' else 'IRIS'} : {t[:300]}")
        if not lines:
            return {"day": target, "summary": "", "stored": False}
        available = self.router.available(self.secrets)
        if not available:
            raise NoAgentAvailable("Aucune IA disponible pour résumer la journée.")
        agent_name = available[0]
        connector = build_connector(agent_name, self.settings, self.secrets)
        self.consent.check("transcript", agent=agent_name)
        transcript = "\n".join(lines)[-12000:]
        system = "Tu es IRIS. Résume la journée de l'utilisateur en français, en 3 à 6 puces courtes : décisions prises, promesses ou engagements, chiffres importants, idées à retenir, choses à faire. Rien d'autre."
        options = ChatOptions(effort="low", model_override=self.settings.user.reasoning_model or None)
        parts: list[str] = []
        async for chunk in connector.stream([{"role": "user", "content": f"Échanges du {target} :\n{transcript}"}], system, None, None, options):
            if chunk.kind == "text":
                parts.append(chunk.text)
            elif chunk.kind == "error":
                raise ConnectorError(chunk.text)
        summary = "".join(parts).strip()
        if not summary:
            return {"day": target, "summary": "", "stored": False}
        for old in self.memory.list(limit=1000):
            if old["kind"] == "daily_summary" and old["text"].startswith(f"Résumé du {target}"):
                self.memory.delete(old["id"])
        self.memory.add(f"Résumé du {target} :\n{summary}", source="iris", kind="daily_summary")
        self.consent.log("daily_summary", agent=agent_name, detail=target)
        self.hub.publish("memory.updated", count=self.memory.count())
        return {"day": target, "summary": summary, "stored": True}

    # ------------------------------------------------------------------ conversations
    def _conv_public(self, row: dict) -> dict:
        return {
            "id": row["id"],
            "title": row["title"],
            "agent": row["agent"],
            "kind": row["kind"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "archived": bool(row["archived"]),
            "busy": row["id"] in self._running,
        }

    def list_conversations(self, kind: str = "chat", limit: int = 200, archived: bool = False) -> list[dict]:
        rows = self.db.query(
            "SELECT * FROM conversations WHERE kind=? AND archived=? ORDER BY updated_at DESC LIMIT ?",
            (kind, 1 if archived else 0, limit),
        )
        return [self._conv_public(r) for r in rows]

    def count_conversations(self, kind: str = "chat", archived: bool = True) -> int:
        """Nombre de conversations rangées : sert à afficher « Archives (12) » sans second appel."""
        row = self.db.one(
            "SELECT COUNT(*) AS n FROM conversations WHERE kind=? AND archived=?", (kind, 1 if archived else 0)
        )
        return int(row["n"]) if row else 0

    def create_conversation(self, title: str | None = None, agent: str = "auto", kind: str = "chat") -> dict:
        conv_id = uuid.uuid4().hex
        ts = now_iso()
        self.db.execute(
            "INSERT INTO conversations(id, title, agent, kind, created_at, updated_at) VALUES(?,?,?,?,?,?)",
            (conv_id, title or DEFAULT_TITLE, agent or "auto", kind, ts, ts),
        )
        conv = self.get_conversation(conv_id)
        self.hub.publish("conversation.created", conversation=conv)
        return conv  # type: ignore[return-value]

    def get_conversation(self, conv_id: str) -> dict | None:
        row = self.db.one("SELECT * FROM conversations WHERE id=?", (conv_id,))
        return self._conv_public(row) if row else None

    def update_conversation(
        self, conv_id: str, title: str | None = None, agent: str | None = None, archived: bool | None = None
    ) -> dict | None:
        if title is not None:
            self.db.execute("UPDATE conversations SET title=? WHERE id=?", (title.strip()[:120] or DEFAULT_TITLE, conv_id))
        if agent is not None:
            self.db.execute("UPDATE conversations SET agent=? WHERE id=?", (agent or "auto", conv_id))
        if archived is not None:
            # ranger n'est pas détruire : updated_at n'est pas touché, la conversation garde sa place
            self.db.execute("UPDATE conversations SET archived=? WHERE id=?", (1 if archived else 0, conv_id))
        conv = self.get_conversation(conv_id)
        if conv:
            self.hub.publish("conversation.updated", conversation=conv)
        return conv

    def delete_conversation(self, conv_id: str) -> bool:
        self.cancel(conv_id)
        cur = self.db.execute("DELETE FROM conversations WHERE id=?", (conv_id,))
        if cur.rowcount:
            self.hub.publish("conversation.deleted", conversation_id=conv_id)
        return cur.rowcount > 0

    def _touch(self, conv_id: str) -> None:
        self.db.execute("UPDATE conversations SET updated_at=? WHERE id=?", (now_iso(), conv_id))

    # ------------------------------------------------------------------ messages
    def _decode_message(self, row: dict, include_images: bool = True) -> dict:
        try:
            content = json.loads(self.crypto.decrypt(row["content_enc"]))
        except Exception:
            content = {"text": "(message illisible)", "images": []}
        images = content.get("images") or []
        if not include_images:
            images = [{"media_type": i.get("media_type"), "data": ""} for i in images]
        return {
            "id": row["id"],
            "conversation_id": row["conversation_id"],
            "role": row["role"],
            "text": content.get("text", ""),
            "images": images,
            "agent": row["agent"],
            "model": row["model"],
            "meta": json.loads(row["meta"]) if row.get("meta") else {},
            "created_at": row["created_at"],
        }

    def messages(self, conv_id: str, limit: int = 500) -> list[dict]:
        rows = self.db.query(
            "SELECT * FROM messages WHERE conversation_id=? ORDER BY created_at ASC, rowid ASC LIMIT ?", (conv_id, limit)
        )
        return [self._decode_message(r) for r in rows]

    def _add_message(
        self,
        conv_id: str,
        role: str,
        text: str,
        images: list[dict] | None = None,
        agent: str | None = None,
        model: str | None = None,
        meta: dict | None = None,
        message_id: str | None = None,
    ) -> dict:
        message_id = message_id or uuid.uuid4().hex
        ts = now_iso()
        content = {"text": text, "images": images or []}
        self.db.execute(
            "INSERT INTO messages(id, conversation_id, role, content_enc, agent, model, meta, created_at) VALUES(?,?,?,?,?,?,?,?)",
            (
                message_id,
                conv_id,
                role,
                self.crypto.encrypt(json.dumps(content, ensure_ascii=False)),
                agent,
                model,
                json.dumps(meta or {}, ensure_ascii=False),
                ts,
            ),
        )
        self._touch(conv_id)
        return {
            "id": message_id,
            "conversation_id": conv_id,
            "role": role,
            "text": text,
            "images": images or [],
            "agent": agent,
            "model": model,
            "meta": meta or {},
            "created_at": ts,
        }

    def _history(self, conv_id: str, for_action: bool = False) -> list[dict]:
        window = max(2, int(self.settings.user.history_window or 40))
        if for_action:
            window = min(window, 8)
        items = self.messages(conv_id)[-window:]
        if for_action:
            items = [
                m for m in items
                if m["role"] == "user" or (m.get("meta") or {}).get("tools") or not ACTION_CLAIM.search(m["text"] or "")
            ]
        history: list[dict] = []
        for m in items:
            if m["role"] == "assistant":
                if m["text"].strip():
                    history.append({"role": "assistant", "content": m["text"]})
                continue
            if m["images"]:
                blocks: list[dict] = [
                    {"type": "image", "media_type": img["media_type"], "data": img["data"]}
                    for img in m["images"]
                    if img.get("data")
                ]
                if m["text"].strip():
                    blocks.append({"type": "text", "text": m["text"]})
                history.append({"role": "user", "content": blocks})
            elif m["text"].strip():
                history.append({"role": "user", "content": m["text"]})
        # le premier message doit venir de l'utilisateur
        while history and history[0]["role"] != "user":
            history.pop(0)
        return history

    # ------------------------------------------------------------------ prompt système
    async def demander_court(self, systeme: str, message: str) -> str:
        """Une question au modèle, sans outils ni historique. C'est le pont du mode traduction.

        Traduire est une tâche courte et sans mémoire : lui donner des outils lui ferait perdre du
        temps à chercher s'il doit en appeler un, et une traduction qui arrive après la réponse de
        l'interlocuteur ne sert à rien."""
        available = self.router.available(self.secrets)
        agent_name, _raison = self.router.select(message, False, available, "auto")
        connector = build_connector(agent_name, self.settings, self.secrets)
        options = ChatOptions(
            effort=self.settings.user.voice_effort,
            model_override=self._pick_model(self.settings.user, is_voice=True, is_build=False, is_screen=False,
                                            plan_models=self.plans.models() if (self.plans is not None and agent_name == "openrouter") else None),
            force_tools=False,
            max_rounds=1,
        )
        morceaux: list[str] = []
        async for chunk in connector.stream([{"role": "user", "content": message}], systeme, None, None, options):
            if chunk.kind == "text":
                morceaux.append(chunk.text)
        return "".join(morceaux).strip()

    async def analyse_veille(self, nom: str, criteres: str, nouveautes: str) -> dict:
        """Fait analyser les nouveautés d'une veille par un agent, et renvoie un verdict structuré.

        Le texte surveillé est écrit par une tierce personne : il est passé comme donnée encadrée, jamais
        comme consigne, et l'agent n'a AUCUN outil ici. Il ne peut donc rien exécuter, seulement juger."""
        from .watch import lire_verdict, prompt_analyse

        systeme, message = prompt_analyse(nom, criteres, nouveautes)
        try:
            available = self.router.available(self.secrets)
            agent_name, _raison = self.router.select(message, False, available, "auto")
            connector = build_connector(agent_name, self.settings, self.secrets)
            options = ChatOptions(
                effort=self.settings.user.voice_effort,
                model_override=self._pick_model(self.settings.user, is_voice=False, is_build=False, is_screen=False,
                                                plan_models=self.plans.models() if (self.plans is not None and agent_name == "openrouter") else None),
                force_tools=False,
                max_rounds=1,
            )
            morceaux: list[str] = []
            async for chunk in connector.stream([{"role": "user", "content": message}], systeme, None, None, options):
                if chunk.kind == "text":
                    morceaux.append(chunk.text)
            return lire_verdict("".join(morceaux))
        except Exception as exc:
            log.warning("analyse de veille impossible : %s", exc)
            return {"verdict": "rien", "resume": "", "action": ""}

    async def _translate_fr(self, connector, text: str, options) -> str:
        """Traduction rapide en français (garde-fou de langue), sans outils ni historique."""
        try:
            try:
                from dataclasses import replace as _dc_replace

                opts = _dc_replace(options, force_tools=False, max_rounds=1)
            except Exception:
                opts = options
            out: list[str] = []
            system = "Tu traduis en français du Québec naturel et parlé. Réponds uniquement par la traduction, sans commentaire."
            async for chunk in connector.stream([{"role": "user", "content": text}], system, None, None, opts):
                if chunk.kind == "text":
                    out.append(chunk.text)
            result = "".join(out).strip()
            return "" if _looks_english(result) else result
        except Exception as exc:
            log.warning("traduction impossible : %s", exc)
            return ""

    def _capacites_reelles(self) -> str:
        """Ce qu'IRIS sait VRAIMENT faire, généré depuis la liste réelle de ses outils.

        Bogue du 6 septembre 2026, et il était grave. Interrogée sur ses capacités, IRIS a répondu à
        Miguel qu'elle « dépendait de macOS » (elle tourne sur Windows), qu'elle « ne pouvait pas
        cliquer sur une coordonnée » (mouse_click existe), « ni faire défiler » (scroll existe), « ni
        connaître la batterie des lunettes » (lunettes_etat la lit). Rien dans son code ne lui disait
        ce qu'elle savait faire : elle INVENTAIT ses limites à partir de ses réflexes de modèle. Un
        client, ou un juge, aurait entendu une assistante se décrire faux.

        D'où cette liste, construite depuis TOOL_SPECS et l'état réel des services : elle ne peut
        plus dériver, parce qu'elle n'est pas écrite à la main."""
        import platform

        try:
            from .tools import TOOL_SPECS
        except Exception:  # pragma: no cover
            return ""

        lignes = []
        for spec in TOOL_SPECS:
            description = (spec.description or "").split(". ")[0].strip().rstrip(".")
            lignes.append(f"- {spec.name} : {description}")

        systeme = platform.system() or "Windows"
        etat = []

        def _prop(obj, *noms):
            for nom in noms:
                if obj is not None and hasattr(obj, nom):
                    valeur = getattr(obj, nom)
                    try:
                        return bool(valeur() if callable(valeur) else valeur)
                    except Exception:
                        return False
            return None

        courriel = _prop(self.courriel, "configure")
        telephonie = _prop(self.telephonie, "configure")
        lunettes = _prop(self.glasses, "connected")
        if courriel is not None:
            etat.append("courriel " + ("configuré : tu peux envoyer" if courriel else "NON configuré : dis-le et explique comment l'activer dans les réglages"))
        if telephonie is not None:
            etat.append("téléphonie " + ("configurée" if telephonie else "NON configurée : les SMS et appels passent par le téléphone de l'utilisateur, jamais tout seuls"))
        if lunettes is not None:
            etat.append("lunettes VELA " + ("connectées : lunettes_etat te donne leur charge" if lunettes else "non connectées en ce moment"))

        return (
            f"CE QUE TU SAIS FAIRE — LISTE EXACTE ET COMPLÈTE. Tu tournes sur {systeme}, jamais sur macOS. "
            "Voici tes outils réels ; il n'en existe aucun autre, et aucun de ceux-ci n'est fictif :\n"
            + "\n".join(lignes)
            + "\nÉtat en ce moment : " + ("; ".join(etat) if etat else "services en cours de chargement") + ". "
            "RÈGLE : quand on te demande ce que tu sais faire ou tes limites, réponds UNIQUEMENT à partir de cette "
            "liste. N'invente jamais une capacité que tu n'as pas, et n'invente jamais une limite qui n'y figure pas — "
            "tu PEUX cliquer à une coordonnée (mouse_click), faire défiler (scroll), taper, lire l'écran, lire la batterie "
            "des lunettes, traduire une conversation, retrouver un site dans l'historique et t'y connecter. "
            "Tes vraies règles, qui ne sont pas des faiblesses mais ta conception : tu n'envoies aucun courriel, SMS ou "
            "appel sans que l'utilisateur voie le contenu et l'approuve ; tu ne fais rien de destructeur sans son accord "
            "explicite ; les mots de passe vivent dans le coffre, jamais dans ta mémoire ; tu ne t'inventes pas de "
            "souvenirs."
        )

    def _system_prompt(self, agent: str, has_tools: bool, memory_ctx: str, source: str) -> str:
        u = self.settings.user
        name = u.assistant_name or "IRIS"
        who = f" Tu assistes {u.user_name}." if u.user_name else ""
        lang = "français" if u.language.lower().startswith("fr") else "la langue de l'utilisateur"
        parts = [
            f"Tu es {name}, l'assistante IA de VELA : une paire de lunettes connectées sans écran et une application de "
            f"bureau qui contrôle l'ordinateur à la voix, retient ce qui compte pour l'utilisateur, et garde ses "
            f"données chez lui.{who} Tu réponds en {lang}, de façon naturelle, directe et concise.",
            (
                "RÈGLE ABSOLUE DE LANGUE : tu écris uniquement en français (français du Québec, naturel), du premier au dernier mot. "
                "Jamais d'anglais, jamais de mélange des deux langues, même si les résultats d'outils, les pages web, les fichiers ou "
                "les noms de commandes sont en anglais : tu traduis. Emploie le mot français quand il existe (« fichier », « dossier », "
                "« navigateur », « c'est fait »). Seuls les noms propres et les noms de produits restent tels quels. "
                "UNE SEULE EXCEPTION : en mode traduction, quand tu rends à l'utilisateur la phrase à dire à son "
                "interlocuteur, tu l'écris dans la langue de cet interlocuteur — c'est tout l'objet de la traduction."
                if lang == "français" else ""
            ),
            "L'utilisateur peut t'écouter à la voix sans écran : pour une question simple, réponds en une ou deux phrases "
            "parlées ; développe seulement quand c'est nécessaire, et évite les tableaux ou la mise en forme lourde "
            "quand la demande vient de la voix.",
            f"Date du jour : {datetime.now().strftime('%A %d %B %Y')}.",
            # Demande de Miguel du 6 septembre 2026 : personne ne doit savoir quel est le cerveau.
            "IDENTITÉ : tu es IRIS, l'intelligence de VELA, et rien d'autre. Ne révèle JAMAIS quel "
            "modèle ou quelle entreprise te fait fonctionner (ni Claude, ni Anthropic, ni OpenRouter, "
            "ni OpenAI, ni Google, ni aucun autre) : c'est une information interne. Si on te demande "
            "quel modèle tu es, qui t'a créée, ou sur quelle technologie tu reposes, réponds "
            "simplement que tu es IRIS, développée par VELA, sans nommer de fournisseur — et enchaîne "
            "sur ce que tu peux faire pour la personne. Ne cite jamais non plus ces noms dans un "
            "raisonnement lu à voix haute.",
            # Limite qu'IRIS a elle-même nommée le 6 septembre 2026 : « je devine parfois au lieu de te dire
            # que je bloque ». En entreprise, un prix, une date ou une adresse faux coûtent cher.
            "FAITS ET INCERTITUDE : pour un prix, une date, une adresse, un horaire, un événement récent ou "
            "toute donnée qui change, ne réponds pas de mémoire : cherche avec web_search quand tu l'as, et cite "
            "d'où vient la réponse. Si tu ne peux pas vérifier, dis clairement que tu ne sais pas et propose de "
            "chercher — ne devine jamais en donnant l'air d'être sûre.",
        ]
        if source == "voice":
            parts.append(
                "Cette demande a été dictée à la voix : réponds vite, en une ou deux phrases orales, sans markdown ni liste. "
                "Si tu as besoin d'une précision pour agir (par exemple quelle musique lancer), pose une seule question "
                "courte qui se termine par un point d'interrogation : IRIS écoutera la réponse immédiatement."
            )
        if has_tools:
            parts.append(
                "Tu contrôles l'ordinateur de l'utilisateur, mais uniquement quand il te le demande. "
                "Quand l'utilisateur demande une action, enchaîne les outils nécessaires sans expliquer comment faire, puis "
                "confirme brièvement le résultat. RÈGLE ABSOLUE : tu ne dis jamais « c'est fait » ou « j'ouvre » sans "
                "avoir réellement appelé l'outil et reçu son résultat ; sans appel d'outil, rien ne se passe sur "
                "l'ordinateur. Ne demande pas de confirmation pour une action simple et sans risque : fais-la. Exemple : « ouvre mon navigateur et mets de la musique » → ouvre le "
                "navigateur, puis demande quelle musique, puis play_youtube avec sa réponse. Tu peux aussi développer des "
                "applications et des sites complets : crée les fichiers avec write_file, installe et lance avec run_command, "
                "vérifie avec read_file ou une capture d'écran. N'exécute jamais d'action destructrice (suppression, "
                "formatage, arrêt) sans demande explicite. Si un outil renvoie une erreur de consentement, explique à "
                "l'utilisateur quoi activer dans Confidentialité."
            )
            parts.append(self._capacites_reelles())
        parts.append(
            "Confidentialité : IRIS traite localement par défaut ; l'utilisateur a explicitement consenti à t'envoyer "
            "cette demande. Ne demande jamais de données sensibles inutiles."
        )
        if self.presence is not None:
            try:
                parts.append(self.presence.context_line())
            except Exception:
                pass
        parts.append(
            "MÉMOIRE : tu ne disposes que des souvenirs listés ci-dessous, enregistrés à partir de ce que "
            "l'utilisateur a réellement dit. N'invente jamais un souvenir et ne déduis jamais un fait personnel "
            "qui n'y figure pas. Si on te demande ce que tu sais de lui, ÉNUMÈRE ce qui est listé : ne réponds "
            "jamais que tu ne sais rien alors que des souvenirs figurent ci-dessous. Si une information précise "
            "manque, dis que celle-là tu ne l'as pas, et propose de la retenir. "
            "Quand tu cites un souvenir, tu peux préciser sa date."
        )
        if memory_ctx:
            parts.append("Souvenirs enregistrés sur cet appareil, utiles à cette demande :\n" + memory_ctx)
        else:
            parts.append("Aucun souvenir n'est encore enregistré pour cet utilisateur.")
        return "\n\n".join(parts)

    # ------------------------------------------------------------------ confirmations
    def set_sink_confirm_vocal(self, cb) -> None:
        """Le fil vocal s'enregistre ici pour pouvoir demander l'accord à voix haute."""
        self._sink_confirm_vocal = cb

    def set_sink_confirm_distant(self, cb) -> None:
        """La télécommande s'enregistre ici : (conv_id, confirm_id, title, detail) -> renvoie la
        demande d'accord au téléphone qui a lancé la commande distante."""
        self._sink_confirm_distant = cb

    async def _confirm(self, conv_id: str, title: str, detail: str, source: str = "text") -> bool:
        loop = asyncio.get_running_loop()
        confirm_id = uuid.uuid4().hex
        fut: asyncio.Future = loop.create_future()
        self._confirms[confirm_id] = fut
        self.hub.publish("chat.confirm", conversation_id=conv_id, confirm_id=confirm_id, title=title, detail=detail)
        # L'écran marche toujours. Par la voix, on demande EN PLUS à voix haute : l'écran et la
        # voix résolvent le même futur (resolve_confirm), le premier arrivé gagne, l'autre est
        # un non-effet.
        if source == "voice" and self._sink_confirm_vocal is not None:
            try:
                self._sink_confirm_vocal(confirm_id, title, detail)
            except Exception as exc:  # pragma: no cover
                log.warning("demande d'accord vocal impossible : %s", exc)
        # Commande distante : l'accord doit remonter au téléphone. Le futur est résolu par le même
        # resolve_confirm, quand le téléphone répond (via la télécommande).
        if source == "distant" and self._sink_confirm_distant is not None:
            try:
                self._sink_confirm_distant(conv_id, confirm_id, title, detail)
            except Exception as exc:  # pragma: no cover
                log.warning("demande d'accord distante impossible : %s", exc)
        try:
            return bool(await asyncio.wait_for(fut, timeout=180))
        except asyncio.TimeoutError:
            return False
        finally:
            self._confirms.pop(confirm_id, None)
            self.hub.publish("chat.confirm_closed", conversation_id=conv_id, confirm_id=confirm_id)

    def resolve_confirm(self, confirm_id: str, approved: bool) -> bool:
        fut = self._confirms.get(confirm_id)
        if fut is None or fut.done():
            return False
        fut.set_result(bool(approved))
        return True

    # ------------------------------------------------------------------ envoi
    def is_busy(self, conv_id: str) -> bool:
        return conv_id in self._running

    def send(self, conv_id: str, text: str, images: list[dict] | None = None, agent: str = "auto", source: str = "text") -> dict:
        if conv_id in self._running:
            raise RuntimeError("Une réponse est déjà en cours dans cette conversation.")
        if self.get_conversation(conv_id) is None:
            raise KeyError("conversation introuvable")
        task = asyncio.get_running_loop().create_task(self._run(conv_id, text, images or [], agent, source))
        self._running[conv_id] = task
        task.add_done_callback(lambda _t: self._running.pop(conv_id, None))
        return {"accepted": True, "conversation_id": conv_id}

    async def run_and_wait(
        self,
        conv_id: str,
        text: str,
        agent: str = "auto",
        source: str = "task",
        speak: Callable[[str], Any] | None = None,
    ) -> dict:
        if conv_id in self._running:
            raise RuntimeError("conversation occupée")
        task = asyncio.get_running_loop().create_task(self._run(conv_id, text, [], agent, source, speak=speak))
        self._running[conv_id] = task
        try:
            return await task
        finally:
            self._running.pop(conv_id, None)

    def cancel(self, conv_id: str) -> bool:
        task = self._running.get(conv_id)
        if task and not task.done():
            task.cancel()
            return True
        return False

    def _cerveau_de_repli(self, echoue: str) -> str | None:
        """Le prochain cerveau disponible quand celui par défaut a une clé morte.

        On ne révèle jamais lequel : ni Claude, ni OpenRouter n'est nommé à l'utilisateur. On
        écarte les IA locales (un repli doit être aussi capable que le cerveau tombé) et l'agent
        qui vient d'échouer. OpenRouter d'abord : c'est le filet éprouvé, avec ses modèles gratuits."""
        try:
            dispo = self.router.available(self.secrets)
        except Exception:
            return None
        candidats = [a for a in ("openrouter", "vela", "gpt", "gemini")
                     if a in dispo and a != echoue and not self.settings.user.agents[a].local]
        return candidats[0] if candidats else None

    # ------------------------------------------------------------------ verrou des lunettes
    def _verrou_lunettes_chat(self, source: str) -> str | None:
        """Porte des lunettes pour le CHAT ÉCRIT (et toute demande qui finit dans `_run`).

        Symétrique du verrou vocal (VoiceListener.lunettes_requises), mais posée ici parce que la
        voix, le texte, les commandes courantes et les routines aboutissent toutes dans `_run` :
        un seul point d'étranglement. Décision de Miguel du 7 septembre 2026 : IRIS est INUTILISABLE
        sans les lunettes VELA — voix ET chat écrit — avec une échappatoire « mode démonstration ».

        Ne verrouille QUE les usages humains ({voice, text, quick, routine}). Les sources de fond
        (task, daily_summary, veille/analyse, résumé) doivent continuer même sans lunettes : elles
        n'ont ni écran ni lunettes et font vivre les tâches, les résumés et la surveillance.

        Présence : une SEULE règle, celle du fil vocal (`lunettes_presentes` : lien basse énergie ou
        micro) ; à défaut, le service BLE. Fail-open volontaire quand la présence est indéterminable :
        aucun service de présence branché, OU aucune paire de lunettes jamais configurée sur cet
        appareil. Sans ce fail-open, `require_glasses` (True par défaut) couperait une application
        fraîchement installée qui n'a encore jamais vu de lunettes — et les tests, qui tournent sans
        lunettes. On ne bloque donc que ce qu'on SAIT absent : des lunettes connues de l'appareil
        (déjà appairées ou mémorisées) mais hors de portée."""
        if source not in ("voice", "text", "quick", "routine"):
            return None
        u = self.settings.user
        if not u.require_glasses or u.demo_sans_lunettes:
            return None
        presentes: bool | None = None
        if self.voice is not None and hasattr(self.voice, "lunettes_presentes"):
            try:
                presentes = bool(self.voice.lunettes_presentes())
            except Exception:  # pragma: no cover - la présence ne doit jamais faire échouer une demande
                presentes = None
        elif self.glasses is not None:
            presentes = bool(getattr(self.glasses, "connected", False))
        if presentes is None:
            return None  # aucun service de présence : indéterminable → on laisse passer
        if presentes:
            return None
        # Lunettes connues absentes. On ne verrouille que si cet appareil connaît des lunettes VELA :
        # sans nom ni adresse mémorisés, on ne peut pas distinguer « lunettes retirées » de « appareil
        # qui n'en a jamais eu », et l'application téléchargée doit pouvoir se montrer.
        g = u.glasses
        if not ((g.name or "").strip() or (g.address or "").strip()):
            return None
        return ("J'ai besoin de tes lunettes VELA connectées pour répondre. "
                "Active le mode démonstration dans les réglages si tu en as besoin sans elles.")

    async def _run(
        self,
        conv_id: str,
        text: str,
        images: list[dict],
        requested_agent: str,
        source: str,
        speak: Callable[[str], Any] | None = None,
        _deja_bascule: bool = False,
    ) -> dict:
        def error(message: str, **extra: Any) -> dict:
            self.hub.publish("chat.error", conversation_id=conv_id, message=message, **extra)
            if speak:
                speak(message)
            return {"error": message}

        speaker = SentenceSpeaker(speak) if speak else None

        text = (text or "").strip()
        if not text and not images:
            return error("Message vide.")

        conv = self.get_conversation(conv_id)
        if conv is None:
            return error("Conversation introuvable.")

        user_msg = self._add_message(conv_id, "user", text, images=images, meta={"source": source})
        self.hub.publish("chat.user_message", conversation_id=conv_id, message=user_msg)

        # Verrou des lunettes VELA (voix + chat écrit), au plus tôt : avant tout appel au modèle,
        # tout quota, toute commande locale. Les sources de fond passent (voir _verrou_lunettes_chat).
        verrou = self._verrou_lunettes_chat(source)
        if verrou:
            refus_id = uuid.uuid4().hex
            self.hub.publish("chat.started", conversation_id=conv_id, message_id=refus_id,
                             agent="local", model="", reason="lunettes VELA requises")
            self.hub.publish("chat.delta", conversation_id=conv_id, message_id=refus_id, text=verrou)
            msg = self._add_message(conv_id, "assistant", verrou, agent="local", model="",
                                    meta={"agent": "local", "source": source, "glasses_required": True},
                                    message_id=refus_id)
            self.hub.publish("chat.done", conversation_id=conv_id, message=msg)
            if speak:
                speak(verrou)
            return {"message": msg, "glasses_required": True}

        assistant_id = uuid.uuid4().hex
        text_parts: list[str] = []
        thinking_parts: list[str] = []
        tool_events: list[dict] = []
        usage: dict = {}
        agent_name = requested_agent
        model = ""
        reason = ""
        try:
            available = self.router.available(self.secrets)
            u = self.settings.user
            # routine vocale : exécution directe, sans passer par le modèle
            routine = self.routines.match(text) if (self.routines is not None and not images) else None
            if routine is not None:
                return await self._run_routine(conv_id, routine, source)
            # commande courante reconnue localement (heure, ouvrir une application ou un site, lancer une vidéo) :
            # exécutée directement, sans appel réseau ni quota, et donc sans les errements des modèles gratuits.
            quick = None
            if not images and source != "task" and u.quick_commands:
                try:
                    from .pc import actions as _actions

                    quick = match_quick_command(text, app_resolver=_actions.confident_app)
                except Exception as exc:  # pragma: no cover - ne doit jamais bloquer la demande
                    log.debug("commandes locales indisponibles : %s", exc)
            if quick is not None and (not quick.tool or u.computer_use):
                return await self._run_quick(conv_id, quick, source)
            if self.plans is not None:
                try:
                    self.plans.check_request()
                except QuotaExceeded as exc:
                    return error(str(exc) + " Passez au plan supérieur dans « Abonnement ».", code="quota")
            # Ce que l'utilisateur énonce de durable est retenu mot pour mot, sans modèle (voir recall.py).
            if source != "task" and not images:
                try:
                    for souvenir in self.memory.capture(text, conversation_id=conv_id):
                        log.info("mémoire : %r (%s)", souvenir["text"][:80], souvenir["kind"])
                        self.hub.publish("memory.captured", text=souvenir["text"], kind=souvenir["kind"], id=souvenir["id"])
                except Exception as exc:  # pragma: no cover - ne doit jamais bloquer une demande
                    log.debug("capture mémoire impossible : %s", exc)
            if self.presence is not None:
                try:
                    self.presence.note_interaction(source)
                except Exception:
                    pass
            wanted = requested_agent if requested_agent not in ("auto", "", None) else conv["agent"]
            agent_name, reason = self.router.select(text, bool(images), available, wanted)
            self.consent.check("transcript", agent=agent_name)
            if images:
                self.consent.check("image", agent=agent_name)

            connector = build_connector(agent_name, self.settings, self.secrets)
            model = connector.model
            is_local = self.settings.user.agents[agent_name].local

            # La mémoire appartient à l'utilisateur et vit sur sa machine : elle est toujours consultée.
            # Le consentement ne conditionne que l'ENVOI de souvenirs à un agent externe.
            memory_ctx = ""
            hits = self.memory.context(text, limit=5)
            if hits and (self.consent.is_granted("memory") or is_local):
                # chaque souvenir est borné : un résumé de journée entier noierait le reste
                memory_ctx = "\n".join(f"- [{h['created_at'][:10]}] {h['text'][:500]}" for h in hits)
                self.memory.touch([h["id"] for h in hits])
                if not is_local:
                    self.consent.log("external_send", data_type="memory", agent=agent_name, detail=f"{len(hits)} souvenirs")

            low_text = re.sub(r"\s+", " ", text.lower())
            is_build = connector.supports_tools and _has(low_text, STRICT_BUILD)
            # L'écran s'ouvre aussi quand il faut PILOTER une application, pas seulement quand
            # l'utilisateur emploie le mot « clique » ou « regarde ».
            pilotage = besoin_de_piloter(low_text)
            is_screen = connector.supports_tools and u.computer_use and (_has(low_text, SCREEN_KEYWORDS) or pilotage)
            if is_screen and self.plans is not None and not self.plans.feature_allowed("screen"):
                is_screen = False
                self.hub.publish("chat.info", conversation_id=conv_id, message_id=assistant_id, text="Le contrôle complet de l'écran est inclus à partir du plan Pro.")
            is_action = source != "task" and connector.supports_tools and (_has(low_text, STRICT_ACTION) or is_build)
            # « mets de la musique » sans titre : forcer un outil empêcherait IRIS de demander quoi lancer.
            if is_action and re.search(r"\b(de la musique|une musique|une vid[ée]o|une chanson|un film|un clip)\s*\.?\s*$", low_text):
                is_action = False
            history = self._history(conv_id, for_action=is_action or is_screen)
            system = self._system_prompt(agent_name, connector.supports_tools, memory_ctx, source)
            if is_screen:
                system += "\n\n" + CONSIGNE_PILOTAGE
            # Le navigateur est offert par défaut, pas seulement quand la demande contient
            # « site » ou « portail ». Constat réel : « quelle heure est-il en Chine ? » ne
            # déclenchait aucun outil web, et IRIS répondait de mémoire — donc faux. Une
            # assistante qui a accès au web doit pouvoir décider elle-même d'aller vérifier.
            is_web = connector.supports_tools and self.web is not None and not self.settings.user.local_only
            # La consigne détaillée, elle, ne sert que pour une vraie navigation sur un site connu.
            if is_web and (_has(low_text, WEB_KEYWORDS) or any(n in low_text for n in self.web.site_names())):
                sites = ", ".join(self.web.site_names()) if self.web is not None else ""
                system += (
                    "\n\nNAVIGATION WEB : utilise les outils web_* (navigateur piloté, fenêtre visible) plutôt que le contrôle "
                    "d'écran. Méthode : web_login(site) pour un site enregistré" + (f" (sites enregistrés : {sites})" if sites else "") +
                    " ou web_open(url), puis web_read pour lire le contenu et la liste des éléments cliquables, puis web_click "
                    "par libellé, et ainsi de suite jusqu'au résultat ; termine en résumant ce que tu as trouvé. Ne demande jamais "
                    "de mot de passe : il est stocké dans le coffre et rempli par web_login. Si un contrôle de sécurité (captcha) "
                    "bloque, dis-le à l'utilisateur et attends qu'il le résolve dans la fenêtre."
                )
            if is_screen:
                system += (
                    "\n\nCONTRÔLE D'ÉCRAN : tu agis comme un humain devant l'écran. Boucle : 1) take_screenshot pour voir "
                    "l'état actuel ; 2) une action (click_text pour un bouton/menu/lien visible — le plus fiable —, sinon "
                    "mouse_click aux coordonnées lues sur la capture, type_text, press_keys, scroll) ; 3) nouvelle capture pour "
                    "vérifier le résultat avant l'étape suivante. Les coordonnées sont celles de la capture (voir screen_info). "
                    "Continue jusqu'à ce que la demande soit accomplie ou que tu constates un blocage, puis résume en une phrase."
                )
            if is_build:
                system += (
                    "\n\nDEMANDE DE CRÉATION : tu dois produire des fichiers réels, pas une description. Procédure : "
                    "1) choisis un nom de dossier court et crée le projet dans ~/Documents/IRIS/<nom> ; "
                    "2) écris CHAQUE fichier complet avec write_file (pour un jeu ou un site simple : un seul index.html "
                    "autonome avec le CSS et le JavaScript inclus) ; 3) ouvre le résultat avec open_path (le fichier index.html) "
                    "ou lance-le avec run_command ; 4) confirme en une phrase où se trouve le projet. "
                    "N'écris jamais le code dans ta réponse : mets-le dans les fichiers."
                )
            # Une seule phrase de plus, et seulement quand OpenCode est réellement utilisable.
            # Aujourd'hui il ne l'est sur aucune machine, donc la consigne envoyée au modèle est
            # rigoureusement celle d'avant : ce câblage n'entre pas dans le chemin de la démonstration.
            if is_build and opencode_utilisable(self.opencode):
                system += (
                    "\n\nPROJET QUI EXISTE DÉJÀ : s'il s'agit de corriger ou de modifier un projet "
                    "existant plutôt que d'en créer un, appelle deleguer_programmation avec son dossier "
                    "au lieu de réécrire les fichiers toi-même."
                )

            tools = None
            run_tool = None
            if connector.supports_tools:
                ctx = ToolContext(
                    settings=self.settings,
                    consent=self.consent,
                    capture=self.capture,
                    memory=self.memory,
                    agent=agent_name,
                    confirm=lambda title, detail: self._confirm(conv_id, title, detail, source),
                    create_task=self.create_task_fn,
                    routines=self.routines,
                    reminders=self.reminders,
                    watches=self.watches,
                    web=self.web,
                    glasses=self.glasses,
                    hub=self.hub,
                    courriel=self.courriel,
                    telephonie=self.telephonie,
                    traduction=self.traduction,
                    voice=self.voice,
                    opencode=self.opencode,
                    # La voix ne voit aucune demande de confirmation : l'outil de délégation en
                    # tient compte lui-même plutôt que d'ouvrir un modal invisible.
                    source=source,
                )
                # On n'expose que les outils utiles à CETTE demande : le clavier et la souris ne servent qu'au
                # contrôle d'écran, les outils web qu'à la navigation. Un modèle gratuit noyé sous 37 outils s'égare.
                besoin_clavier = is_screen or _has(low_text, ["tape ", "écris ", "ecris ", "appuie", "raccourci", "touche"])
                tools = tool_specs(ctx, screen=is_screen, keyboard=besoin_clavier, web=is_web)
                run_tool = make_tool_runner(ctx)

            if not is_local:
                self.consent.log("external_send", data_type="transcript", agent=agent_name, detail=text[:120])
                if images:
                    self.consent.log("external_send", data_type="image", agent=agent_name, detail=f"{len(images)} image(s)")

            self.hub.publish(
                "chat.started",
                conversation_id=conv_id,
                message_id=assistant_id,
                agent=agent_name,
                model=model,
                reason=reason,
            )
            is_voice = source == "voice"
            options = ChatOptions(
                effort=u.voice_effort if is_voice else u.claude_effort,
                thinking_display=u.claude_thinking_display and not is_voice,
                web_search=u.claude_web_search and not is_local,
                model_override=self._pick_model(u, is_voice=is_voice, is_build=is_build or source == "task", is_screen=is_screen, plan_models=self.plans.models() if (self.plans is not None and agent_name == "openrouter") else None),
                force_tools=is_action or is_screen,
                max_rounds=40 if (is_screen or source == "task" or is_build) else 12,
            )
            err_text: str | None = None
            # garde d'action : tant qu'aucun outil n'a été appelé, le texte est retenu (pas affiché, pas lu)
            held: list[str] = []
            release_text = not is_action

            def emit_text(piece: str) -> None:
                text_parts.append(piece)
                if speaker:
                    speaker.feed(piece)
                self.hub.publish("chat.delta", conversation_id=conv_id, message_id=assistant_id, text=piece)

            async def run_pass(hist: list[dict], sys_prompt: str) -> str | None:
                nonlocal usage, release_text
                async for chunk in connector.stream(hist, sys_prompt, tools, run_tool, options):
                    if chunk.kind == "text":
                        if release_text:
                            emit_text(chunk.text)
                        else:
                            held.append(chunk.text)
                    elif chunk.kind == "thinking":
                        thinking_parts.append(chunk.text)
                        self.hub.publish("chat.thinking", conversation_id=conv_id, message_id=assistant_id, text=chunk.text)
                    elif chunk.kind == "tool_use":
                        if not release_text:
                            release_text = True
                            for piece in held:
                                emit_text(piece)
                            held.clear()
                        ev = {**chunk.data, "status": "running"}
                        tool_events.append(ev)
                        self.hub.publish("chat.tool", conversation_id=conv_id, message_id=assistant_id, tool=ev)
                    elif chunk.kind == "tool_result":
                        for ev in tool_events:
                            if ev.get("id") == chunk.data.get("id"):
                                ev.update({"status": "error" if chunk.data.get("is_error") else "done", "result": chunk.data.get("result", "")})
                                self.hub.publish("chat.tool", conversation_id=conv_id, message_id=assistant_id, tool=ev)
                                break
                    elif chunk.kind == "usage":
                        usage = chunk.data
                    elif chunk.kind == "info":
                        self.hub.publish("chat.info", conversation_id=conv_id, message_id=assistant_id, text=chunk.text)
                    elif chunk.kind == "error":
                        return chunk.text
                    elif chunk.kind == "done":
                        break
                return None

            err_text = await run_pass(history, system)
            if is_action and not tool_events and not err_text:
                # le modèle a bavardé sans agir : seconde chance sans historique, consigne explicite
                log.info("action sans outil, nouvelle tentative forcée")
                held.clear()
                self.hub.publish("chat.info", conversation_id=conv_id, message_id=assistant_id, text="Aucune action exécutée, nouvelle tentative…")
                retry_user = {"role": "user", "content": text + "\n\n(Exécute cette demande en appelant l'outil approprié maintenant. Ne réponds pas par du texte seul.)"}
                err_text = await run_pass([retry_user], system)
            if is_action and not tool_events and not err_text:
                held.clear()
                release_text = True
                emit_text(ACTION_FAILED_TEXT)
            if held and not text_parts:
                # sécurité : ne jamais perdre une réponse retenue
                release_text = True
                for piece in held:
                    emit_text(piece)
                held.clear()
            final_text = "".join(text_parts)
            if speaker:
                speaker.flush()
                if speaker.foreign and speak:
                    # garde-fou de langue : le modèle a glissé vers l'anglais → traduction avant lecture
                    log.info("réponse partiellement en anglais : traduction avant lecture (%d phrase(s))", len(speaker.foreign))
                    translated = await self._translate_fr(connector, " ".join(speaker.foreign), options)
                    if translated:
                        speak(translated)
                        self.hub.publish("chat.info", conversation_id=conv_id, message_id=assistant_id, text="Réponse traduite en français avant lecture.")
            meta = {
                "agent": agent_name,
                "model": options.model_override or model,
                "reason": reason,
                "usage": usage,
                "tools": tool_events,
                "thinking": "".join(thinking_parts)[:6000],
                "source": source,
            }
            if err_text:
                meta["error"] = err_text
            msg = self._add_message(conv_id, "assistant", final_text, agent=agent_name, model=model, meta=meta, message_id=assistant_id)
            if conv["title"] == DEFAULT_TITLE and text:
                self.update_conversation(conv_id, title=clean_title(text))
            self.hub.publish("chat.done", conversation_id=conv_id, message=msg)
            if err_text:
                self.hub.publish("chat.error", conversation_id=conv_id, message=err_text)
                if speak and not final_text:
                    speak(err_text)
                return {"message": msg, "error": err_text, "spoken": bool(speaker)}
            return {"message": msg, "spoken": bool(speaker)}

        except ConsentRequired as exc:
            meta = DATA_TYPES.get(exc.data_type, {})
            self.hub.publish(
                "chat.consent_required",
                conversation_id=conv_id,
                data_type=exc.data_type,
                label=meta.get("label", exc.data_type),
                description=meta.get("description", ""),
                agent=agent_name,
            )
            return {"error": f"consentement requis : {exc.data_type}", "consent_required": exc.data_type}
        except LocalOnlyMode:
            return error(
                "Mode 100 % local activé : aucune donnée ne quitte l'ordinateur. Configurez une IA locale ou "
                "désactivez ce mode dans Confidentialité.",
                code="local_only",
            )
        except NoAgentAvailable as exc:
            return error(str(exc), code="no_agent")
        except ConnectorError as exc:
            # Repli SILENCIEUX. Si le cerveau par défaut a une clé morte (invalide, révoquée, sans
            # accès) et qu'on n'a encore rien montré à l'utilisateur, on rejoue la demande sur un
            # autre cerveau — sans un mot. Personne ne doit savoir quel moteur répond, ni qu'on a
            # changé. Demande de Miguel du 6 septembre 2026 : Claude par défaut, un repli qui prend
            # la relève tout seul quand la clé tombe.
            if getattr(exc, "fatal_key", False) and not _deja_bascule and not text_parts and not tool_events:
                repli = self._cerveau_de_repli(agent_name)
                if repli:
                    log.warning("cerveau « %s » injoignable (clé) : bascule silencieuse sur « %s »", agent_name, repli)
                    return await self._run(conv_id, text, images, repli, source, speak=speak, _deja_bascule=True)
            # on garde une trace dans l'historique pour que l'erreur reste visible après rechargement
            self._add_message(
                conv_id, "assistant", "".join(text_parts), agent=agent_name, model=model,
                meta={"agent": agent_name, "model": model, "reason": reason, "error": exc.message, "tools": tool_events, "source": source},
                message_id=assistant_id,
            )
            return error(exc.message, retryable=exc.retryable, agent=agent_name)
        except asyncio.CancelledError:
            partial = "".join(text_parts)
            msg = self._add_message(
                conv_id, "assistant", partial, agent=agent_name, model=model,
                meta={"agent": agent_name, "model": model, "cancelled": True, "tools": tool_events, "source": source},
                message_id=assistant_id,
            )
            self.hub.publish("chat.done", conversation_id=conv_id, message=msg, cancelled=True)
            return {"message": msg, "cancelled": True}
        except Exception as exc:  # pragma: no cover - garde-fou
            log.exception("erreur interne pendant la réponse")
            return error(f"Erreur interne : {exc}")
