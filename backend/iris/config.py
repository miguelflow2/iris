"""Configuration IRIS : dossier de données et réglages utilisateur (settings.json)."""
from __future__ import annotations

import json
import os
import sys
import threading
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

APP_NAME = "IRIS"

ENV_KEYS = ("ELEVENLABS_API_KEY",)


def env_file_candidates(data_dir: Path) -> list[Path]:
    """Fichiers .env lus (dans l'ordre) : dossier de données, dossier backend (dev), dossier courant."""
    here = Path(__file__).resolve().parents[1]
    return [data_dir / ".env", here / ".env", Path.cwd() / ".env"]


def load_env_files(data_dir: Path) -> list[str]:
    """Charge les variables des fichiers .env sans écraser celles déjà présentes dans l'environnement."""
    loaded: list[str] = []
    for path in env_file_candidates(data_dir):
        try:
            if not path.is_file():
                continue
            for line in path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                key, value = key.strip(), value.strip().strip('"').strip("'")
                if key and value and not os.environ.get(key):
                    os.environ[key] = value
                    loaded.append(key)
        except Exception:
            continue
    return loaded


def write_env_value(data_dir: Path, key: str, value: str) -> Path:
    """Écrit/remplace une clé dans <data_dir>/.env (jamais dans le code) et met à jour l'environnement."""
    path = data_dir / ".env"
    lines: list[str] = []
    if path.is_file():
        lines = [l for l in path.read_text(encoding="utf-8").splitlines() if not l.strip().startswith(f"{key}=")]
    if not lines:
        lines = ["# Clés API IRIS — ne jamais committer ce fichier"]
    if value:
        lines.append(f"{key}={value}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    if value:
        os.environ[key] = value
    else:
        os.environ.pop(key, None)
    return path

AGENT_NAMES = ("vela", "openrouter", "claude", "gpt", "gemini", "custom")

VERSION_REGLAGES = 2
# Les paliers s'appelaient Gratuit / Essentiel / Pro / Ultra ; ils s'appellent maintenant
# Gratuit / Pro / Premium / Entreprise. Le renommage n'est pas anodin : « pro » existe des deux
# côtés et ne désigne pas la même chose. D'où le numéro de version — sans lui, chaque relecture
# des réglages rétrograderait un abonné Pro d'un cran.
_RENOMMAGE_PLANS_V2 = {"essentiel": "pro", "pro": "premium", "ultra": "entreprise"}


def migrer(raw: dict) -> dict:
    """Fait suivre des réglages déjà écrits quand le vocabulaire change. Appliqué une seule fois."""
    if int(raw.get("settings_version") or 1) < 2:
        ancien = raw.get("plan")
        if ancien in _RENOMMAGE_PLANS_V2:
            raw["plan"] = _RENOMMAGE_PLANS_V2[ancien]
    raw["settings_version"] = VERSION_REGLAGES
    return raw


def default_data_dir() -> Path:
    env = os.environ.get("IRIS_DATA_DIR")
    if env:
        return Path(env)
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA") or Path.home())
        return base / "iris-desktop" / "iris-data"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "iris-desktop" / "iris-data"
    return Path.home() / ".local" / "share" / "iris-desktop" / "iris-data"


class AgentConfig(BaseModel):
    label: str = ""
    active: bool = False
    model: str = ""
    base_url: str = ""  # agents perso / OpenAI-compatible (Ollama, LM Studio, vLLM...)
    local: bool = False  # True = ne quitte pas la machine (autorisé en mode local uniquement)


def _default_agents() -> dict[str, AgentConfig]:
    return {
        # L'accès IA fourni par VELA : actif d'emblée, sans clé à coller. C'est lui qui fait
        # qu'IRIS répond dès la première minute sur une machine neuve.
        "vela": AgentConfig(label="VELA", model="", active=True),
        "openrouter": AgentConfig(label="OpenRouter", model="minimax/minimax-m3:free", active=True),
        "claude": AgentConfig(label="Claude", model="claude-opus-5"),
        "gpt": AgentConfig(label="GPT", model="gpt-5"),
        "gemini": AgentConfig(label="Gemini", model="gemini-2.5-pro"),
        "custom": AgentConfig(
            label="IA locale / perso",
            model="llama3.2",
            base_url="http://127.0.0.1:11434/v1",
            local=True,
        ),
    }


class SiteConfig(BaseModel):
    url: str = ""
    username: str = ""
    label: str = ""


class GlassesConfig(BaseModel):
    address: str = ""
    name: str = ""
    auto_connect: bool = False


class UserSettings(BaseModel):
    assistant_name: str = "IRIS"
    glasses: GlassesConfig = Field(default_factory=GlassesConfig)
    sites: dict[str, SiteConfig] = Field(default_factory=dict)  # comptes web : mots de passe dans le coffre système
    audio_input_device: str = ""  # "" = micro par défaut ; sinon (partie du) nom du périphérique, ex. lunettes appairées
    audio_output_device: str = ""  # "" = sortie par défaut ; sinon (partie du) nom, ex. sortie Hands-Free des lunettes
    user_name: str = ""
    wake_word: str = "Dis-moi Iris"
    # variantes acceptées (ce que la reconnaissance vocale entend parfois à la place du mot d'activation)
    wake_aliases: list[str] = Field(default_factory=lambda: ["dis moi iris", "dis iris", "iris", "dis moi irisse", "dis moi hiris", "dit moi iris"])
    stop_words: list[str] = Field(default_factory=lambda: ["stop", "stoppe", "arrête", "arrete", "tais-toi", "tais toi", "silence", "chut", "ça suffit", "ca suffit"])
    mute_words: list[str] = Field(default_factory=lambda: ["muet", "mode muet", "coupe le micro", "coupe ton micro", "arrête d'écouter", "arrete d'ecouter", "ne m'écoute plus", "ne m'ecoute plus"])
    language: str = "fr-CA"
    local_only: bool = False  # rien ne quitte l'ordinateur, aucun agent externe
    privacy_mode: bool = False  # mode confidentiel : micro coupé, aucune écoute ni capture tant qu'il est actif
    default_agent: str = "vela"
    routing_mode: Literal["auto", "manual"] = "auto"
    retention_days: int = 0  # 0 = illimité ; sinon 1 (24h), 7, 30...
    tts_enabled: bool = True
    tts_engine: Literal["auto", "elevenlabs", "windows"] = "auto"  # auto = ElevenLabs si configuré, sinon Windows
    elevenlabs_voice_id: str = "EXAVITQu4vr4xnSDxMaL"  # Sarah — premade, français vérifié, palier gratuit
    elevenlabs_model: str = "eleven_turbo_v2_5"
    tts_rate: int = 185
    tts_voice: str = ""
    voice_ack: bool = True  # petit accusé vocal après le mot d'activation (si aucune commande dans la même phrase)
    stt_engine: Literal["auto", "vosk", "google"] = "auto"
    voice_autostart: bool = True
    voice_effort: Literal["low", "medium", "high"] = "low"  # voix = réponse rapide (< 5 s)
    voice_model: str = ""  # modèle rapide pour la voix ("" = même modèle que l'agent)
    reasoning_model: str = ""  # modèle pour la création, les tâches longues et les demandes complexes ("" = agent)
    vision_model: str = ""  # modèle qui voit l'écran pour le contrôle d'écran ("" = agent, doit accepter les images)
    # Accès depuis le téléphone, sur le réseau local. DÉSACTIVÉ par défaut : IRIS exécute des
    # commandes sur l'ordinateur, l'ouvrir au réseau est une décision qui se prend sciemment.
    # Le jeton de session reste exigé dans tous les cas.
    remote_access: bool = False
    # IRIS démarre avec la session Windows : elle est présente en continu, pas seulement quand on y pense.
    start_with_windows: bool = True
    # Commandes courantes exécutées sans modèle (heure, ouvrir une application ou un site, lancer une vidéo).
    # Désactivable si l'on préfère que tout passe par l'agent.
    quick_commands: bool = True
    computer_use: bool = True  # souris + capture d'écran + OCR : IRIS agit dans n'importe quelle application
    daily_summary_enabled: bool = True
    daily_summary_time: str = "21:00"
    voice_followup: bool = True  # si IRIS pose une question, elle écoute la réponse sans mot d'activation
    # Fenêtre de dialogue : après une réponse, IRIS reste ouverte ce nombre de secondes. On enchaîne
    # sans redire son nom, chaque échange relance le compte, « arrête » la referme. 0 = désactivée.
    voice_conversation_seconds: int = 45
    # confirmation avant d'exécuter une commande : toujours / seulement les commandes dangereuses / jamais
    confirm_commands: Literal["always", "dangerous", "never"] = "dangerous"
    claude_effort: Literal["low", "medium", "high"] = "medium"
    claude_thinking_display: bool = True
    claude_web_search: bool = True  # recherche web côté serveur Anthropic (outil web_search)
    history_window: int = 40  # nb de messages renvoyés à l'agent
    onboarded: bool = False
    plan: Literal["gratuit", "pro", "premium", "entreprise"] = "gratuit"
    settings_version: int = VERSION_REGLAGES
    plan_expires: str = ""  # AAAA-MM-JJ ("" = sans échéance)
    plan_demo: bool = False  # plan choisi sans clé (mode démonstration)
    license_key: str = ""
    # Activation automatique : IRIS demande sa clé au serveur de licences VELA avec le courriel d'achat,
    # puis revérifie chaque jour (renouvellement, expiration, annulation). Vide = activation manuelle.
    licence_server: str = "https://licences.vela.app"
    # Relais IA de VELA : c'est lui qui détient la clé et choisit le modèle selon l'abonnement.
    # Voir serveur/relais.py. Vider ce champ revient à exiger que le client apporte sa propre clé.
    relay_server: str = "https://relais.vela.app"
    licence_email: str = ""
    licence_auto: bool = True
    agents: dict[str, AgentConfig] = Field(default_factory=_default_agents)

    def agent(self, name: str) -> AgentConfig:
        if name not in self.agents:
            self.agents[name] = _default_agents().get(name, AgentConfig(label=name))
        return self.agents[name]


class Settings:
    """Réglages persistants + chemins. Thread-safe pour les écritures."""

    def __init__(self, data_dir: Path | None = None):
        self.data_dir = Path(data_dir or default_data_dir())
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.models_dir = self.data_dir / "models"
        self.models_dir.mkdir(exist_ok=True)
        self.settings_path = self.data_dir / "settings.json"
        self.db_path = self.data_dir / "iris.db"
        self.env_loaded = load_env_files(self.data_dir)
        self._lock = threading.Lock()
        self.user: UserSettings = self._load()

    def _load(self) -> UserSettings:
        if self.settings_path.exists():
            try:
                raw = migrer(json.loads(self.settings_path.read_text(encoding="utf-8")))
                merged = UserSettings(**raw)
                for name, cfg in _default_agents().items():
                    merged.agents.setdefault(name, cfg)
                return merged
            except Exception:
                backup = self.settings_path.with_suffix(".corrupt.json")
                self.settings_path.replace(backup)
        user = UserSettings()
        self._write(user)
        return user

    def _write(self, user: UserSettings) -> None:
        tmp = self.settings_path.with_suffix(".tmp")
        tmp.write_text(user.model_dump_json(indent=2), encoding="utf-8")
        tmp.replace(self.settings_path)

    def save(self) -> None:
        with self._lock:
            self._write(self.user)

    def update(self, patch: dict) -> UserSettings:
        with self._lock:
            data = self.user.model_dump()
            for key, value in patch.items():
                if key == "sites" and isinstance(value, dict):
                    data["sites"] = {k: (v if isinstance(v, dict) else v) for k, v in value.items()}
                elif key == "agents" and isinstance(value, dict):
                    for agent_name, agent_patch in value.items():
                        current = data["agents"].get(agent_name, AgentConfig().model_dump())
                        current.update(agent_patch or {})
                        data["agents"][agent_name] = current
                elif key in data:
                    data[key] = value
            self.user = UserSettings(**data)
            self._write(self.user)
            return self.user
