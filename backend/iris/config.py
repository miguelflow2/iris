"""Configuration IRIS : dossier de données et réglages utilisateur (settings.json)."""
from __future__ import annotations

import json
import logging
import os
import shutil
import sys
import threading
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, ValidationError, field_validator

log = logging.getLogger("iris.config")

APP_NAME = "IRIS"

# Le nom vendu. C'est ce qu'on dit aux lunettes, et c'est ce que le site promet.
MOT_ACTIVATION = "Dis-moi Iris"

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

VERSION_REGLAGES = 3
# Les paliers s'appelaient Gratuit / Essentiel / Pro / Ultra ; ils s'appellent maintenant
# Gratuit / Pro / Premium / Entreprise. Le renommage n'est pas anodin : « pro » existe des deux
# côtés et ne désigne pas la même chose. D'où le numéro de version — sans lui, chaque relecture
# des réglages rétrograderait un abonné Pro d'un cran.
_RENOMMAGE_PLANS_V2 = {"essentiel": "pro", "pro": "premium", "ultra": "entreprise"}
# Version 3 : deux alias du mot d'activation étaient morts depuis toujours. « irisse » et « hiris »
# n'existent pas dans le vocabulaire du modèle Vosk français ; à chaque ouverture du micro il
# écrivait « Ignoring word missing in vocabulary » et les retirait de la grammaire. Ils ne
# pouvaient donc jamais réveiller IRIS, et les garder dans les réglages faisait croire à une
# tolérance qui n'existait pas. Comparés sous leur forme réduite (minuscules, espaces simples).
_ALIAS_MORTS_V3 = ("dis moi irisse", "dis moi hiris", "irisse", "hiris")


def _compacter(texte: object) -> str:
    """Minuscules, sans espace en tête ni en fin, espaces internes réduits à un seul."""
    return " ".join(str(texte or "").split()).lower()


def migrer(raw: dict) -> dict:
    """Fait suivre des réglages déjà écrits quand le vocabulaire change. Appliqué une seule fois."""
    try:
        version = int(raw.get("settings_version") or 1)
    except (TypeError, ValueError):
        version = 1  # un numéro illisible ne doit pas empêcher de lire tout le reste
    if version < 2:
        ancien = raw.get("plan")
        if ancien in _RENOMMAGE_PLANS_V2:
            raw["plan"] = _RENOMMAGE_PLANS_V2[ancien]
    if version < 3 and isinstance(raw.get("wake_aliases"), list):
        raw["wake_aliases"] = [a for a in raw["wake_aliases"] if _compacter(a) not in _ALIAS_MORTS_V3]
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


class TelephonieConfig(BaseModel):
    """SMS et appels. Les identifiants ne sont PAS ici : selon la voie, ils vivent dans le coffre
    (ancienne voie « twilio ») ou dans l'environnement / backend/.env (« twilio_ligne »). Voir
    telephonie.py et twilio_ligne.py."""

    # Voies possibles :
    #   "iphone"       — défaut : IRIS prépare le message, Miguel touche Envoyer. Rien ne part seul.
    #   "twilio_ligne" — la vraie ligne d'IRIS (décision du 7 septembre 2026) : clé d'API dans
    #                    l'environnement, SMS et appels sortants ET entrants, toujours après accord.
    #   "twilio"       — ancienne voie dormante (Auth Token dans le coffre, SMS seulement).
    #   "aucun"        — téléphonie désactivée.
    fournisseur: str = "iphone"
    numero_par_defaut: str = ""
    indicatif_pays: str = "+1"


class UserSettings(BaseModel):
    assistant_name: str = "IRIS"
    glasses: GlassesConfig = Field(default_factory=GlassesConfig)
    telephonie: TelephonieConfig = Field(default_factory=TelephonieConfig)  # voie SMS/appels ; identifiants hors settings.json
    sites: dict[str, SiteConfig] = Field(default_factory=dict)  # comptes web : mots de passe dans le coffre système
    audio_input_device: str = ""  # "" = micro par défaut ; sinon (partie du) nom du périphérique, ex. lunettes appairées
    audio_output_device: str = ""  # "" = sortie par défaut ; sinon (partie du) nom, ex. sortie Hands-Free des lunettes
    user_name: str = ""
    wake_word: str = MOT_ACTIVATION
    # Variantes acceptées : ce que la reconnaissance entend parfois à la place du mot d'activation,
    # et « Iris » tout court, pour qui trouve le nom complet trop long. Tous ces mots existent dans
    # le vocabulaire du modèle Vosk français — c'est la seule condition pour figurer ici (voir
    # `_ALIAS_MORTS_V3`).
    wake_aliases: list[str] = Field(default_factory=lambda: ["dis moi iris", "dis iris", "iris", "dit moi iris"])
    stop_words: list[str] = Field(default_factory=lambda: ["stop", "stoppe", "arrête", "arrete", "tais-toi", "tais toi", "silence", "chut", "ça suffit", "ca suffit"])
    mute_words: list[str] = Field(default_factory=lambda: ["muet", "mode muet", "coupe le micro", "coupe ton micro", "arrête d'écouter", "arrete d'ecouter", "ne m'écoute plus", "ne m'ecoute plus"])
    language: str = "fr-CA"
    local_only: bool = False  # rien ne quitte l'ordinateur, aucun agent externe
    privacy_mode: bool = False  # mode confidentiel : micro coupé, aucune écoute ni capture tant qu'il est actif
    default_agent: str = "vela"
    routing_mode: Literal["auto", "manual"] = "auto"
    retention_days: int = 0  # 0 = illimité ; sinon 1 (24h), 7, 30...
    tts_enabled: bool = True
    # "auto" = la meilleure voix disponible sans dépendre du nuage : ElevenLabs si une clé est
    #   configurée ET le quota dispo, sinon Piper (français local) s'il est présent, sinon Windows.
    # "piper" = voix française hors-ligne imposée (mode indépendant : rien ne quitte la machine).
    tts_engine: Literal["auto", "elevenlabs", "piper", "windows"] = "auto"
    piper_voice: str = "fr_FR-siwis-medium"  # modèle Piper (fichier .onnx dans piper_voices/)
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
    # Télécommande (canal inverse) : autorise le téléphone à piloter cet ordinateur À DISTANCE via le
    # relais. DÉSACTIVÉ par défaut — une install fraîche n'est jamais pilotable en silence. Les actes
    # irréversibles demandent toujours l'accord (relayé au téléphone), et le périmètre de fichiers tient.
    telecommande: bool = False
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
    # Le pilotage vocal exige des lunettes VELA connectées. C'est une décision commerciale
    # assumée : IRIS est ce qu'il y a DANS les lunettes, et sans elles il ne reste qu'une
    # application de plus. Le chat écrit, lui, reste ouvert — l'application téléchargée depuis
    # le site doit pouvoir montrer quelque chose, et des lunettes en charge ne doivent pas
    # transformer le produit en brique.
    require_glasses: bool = True
    # Échappatoire de démonstration, volontairement absente de l'interface : sur scène, une
    # déconnexion Bluetooth ne doit pas faire taire IRIS. Se modifie dans settings.json ou par
    # PATCH /api/settings. À ne jamais documenter côté client.
    demo_sans_lunettes: bool = False
    # Autorise IRIS à envoyer aux lunettes des commandes autres que celle qu'on a observée. Fermé
    # par défaut, et ce n'est pas de la prudence excessive : sur ces puces, les commandes voisines
    # portent l'écriture du micrologiciel. Une séquence mal devinée, et la paire est morte.
    lunettes_exploration: bool = False
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
    # Domaine réel de VELA : velaglass.ca (acheté chez OVH, 2026-09-08). Le relais sert aussi
    # /api/licence en repli, donc un seul serveur (relais.velaglass.ca) couvre cerveau ET licence
    # tant que le serveur de licences dédié n'existe pas.
    licence_server: str = "https://relais.velaglass.ca"
    # Relais IA de VELA : c'est lui qui détient la clé et choisit le modèle selon l'abonnement.
    # Voir serveur/relais.py. Vider ce champ revient à exiger que le client apporte sa propre clé.
    relay_server: str = "https://relais.velaglass.ca"
    licence_email: str = ""
    licence_auto: bool = True
    agents: dict[str, AgentConfig] = Field(default_factory=_default_agents)

    @field_validator("wake_word", mode="before")
    @classmethod
    def _nettoyer_mot_activation(cls, valeur: object) -> str:
        """Le mot d'activation réel de la machine de Miguel était «  Iris » — avec une espace en
        tête, entrée dans le champ des réglages sans que personne ne la voie. `normalize` l'aurait
        absorbée côté reconnaissance, mais le nom s'affichait ainsi dans l'interface et dans la
        phrase de présentation de la voix (« Dites  Iris pour me parler »). On nettoie à la
        lecture ; vide, on revient au nom vendu plutôt qu'à une IRIS qu'aucun mot ne réveille."""
        propre = " ".join(str(valeur or "").split())
        return propre or MOT_ACTIVATION

    @field_validator("wake_aliases", mode="before")
    @classmethod
    def _nettoyer_alias(cls, valeur: object) -> list[str]:
        """Espaces parasites retirés, vides écartés, doublons fondus (le premier gagne)."""
        if not isinstance(valeur, (list, tuple)):
            return []
        propres: list[str] = []
        for alias in valeur:
            texte = " ".join(str(alias or "").split())
            if texte and _compacter(texte) not in {_compacter(p) for p in propres}:
                propres.append(texte)
        return propres

    def agent(self, name: str) -> AgentConfig:
        if name not in self.agents:
            self.agents[name] = _default_agents().get(name, AgentConfig(label=name))
        return self.agents[name]


def lire_reglages_bruts(path: Path) -> dict:
    """Lit un settings.json tel quel, sans validation. Lève si le fichier n'est pas un objet JSON.

    Encodage « utf-8-sig », et ce n'est pas une coquetterie : le settings.corrupt.json retrouvé
    sur la machine de Miguel (4 septembre 2026, 14 h 57) n'était PAS corrompu. C'était un JSON
    parfaitement valide, réécrit par PowerShell 5.1 (indentation à quatre espaces, deux espaces
    après chaque deux-points : la signature de `ConvertTo-Json | Out-File`), qui commence par une
    marque d'ordre d'octets. `json.loads` la refuse (« Unexpected UTF-8 BOM ») ; IRIS a pris ce
    refus pour une corruption, a mis le fichier de côté et est repartie de zéro : lunettes, clés,
    mot d'activation, tout était perdu au démarrage suivant."""
    texte = path.read_text(encoding="utf-8-sig")
    if not texte.strip():
        raise ValueError("fichier vide")
    raw = json.loads(texte)
    if not isinstance(raw, dict):
        raise ValueError(f"objet JSON attendu, {type(raw).__name__} trouvé")
    return raw


def construire_reglages(raw: dict) -> tuple[UserSettings | None, list[str]]:
    """Valide des réglages bruts. Rend (réglages, champs remis au défaut).

    Un fichier lisible dont UN champ est refusé (une valeur d'un ancien vocabulaire, une faute de
    frappe faite à la main, un réglage écrit par une version plus récente) ne justifie pas de jeter
    les cent autres. On retire les champs refusés, un tour à la fois, et on garde le reste. Rend
    (None, champs) seulement quand rien n'est récupérable."""
    donnees = dict(raw)
    rejetes: list[str] = []
    for _ in range(12):
        try:
            merged = UserSettings(**migrer(dict(donnees)))
        except ValidationError as exc:
            fautifs = []
            for erreur in exc.errors():
                loc = erreur.get("loc") or ()
                if loc and str(loc[0]) in donnees and str(loc[0]) not in fautifs:
                    fautifs.append(str(loc[0]))
            if not fautifs:
                return None, rejetes
            for champ in fautifs:
                donnees.pop(champ, None)
                rejetes.append(champ)
            continue
        except Exception:
            return None, rejetes
        for name, cfg in _default_agents().items():
            merged.agents.setdefault(name, cfg)
        return merged, rejetes
    return None, rejetes


def ecrire_atomique(path: Path, contenu: str) -> None:
    """Écrit d'abord un fichier voisin, le pousse sur le disque, puis le met à la place de l'ancien.

    À aucun instant `path` n'est à moitié écrit : soit l'ancien contenu est entier, soit le nouveau
    l'est. Le `fsync` compte autant que le remplacement — sans lui, une coupure de courant peut
    laisser le nom en place et zéro octet derrière."""
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(contenu)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


class Settings:
    """Réglages persistants + chemins. Thread-safe pour les écritures.

    Une config perdue au démarrage, c'est les lunettes, les clés et le mot d'activation partis.
    Trois garde-fous, donc : l'écriture est atomique (`ecrire_atomique`), chaque écriture réussie
    laisse une copie dans settings.json.bak, et un fichier illisible est restauré depuis cette
    copie au lieu de repartir de zéro. Quand ça arrive, le journal le dit en toutes lettres."""

    def __init__(self, data_dir: Path | None = None):
        self.data_dir = Path(data_dir or default_data_dir())
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.models_dir = self.data_dir / "models"
        self.models_dir.mkdir(exist_ok=True)
        self.settings_path = self.data_dir / "settings.json"
        self.backup_path = self.data_dir / "settings.json.bak"
        self.corrupt_path = self.data_dir / "settings.corrupt.json"
        self.db_path = self.data_dir / "iris.db"
        self.env_loaded = load_env_files(self.data_dir)
        self._lock = threading.Lock()
        # Ce qui s'est passé au chargement, pour que l'interface puisse le dire à l'utilisateur.
        self.restaure_depuis_sauvegarde = False
        self.champs_remis_au_defaut: list[str] = []
        # Base de relais RÉELLEMENT joignable, résolue au démarrage. NON persistée (dépend du
        # réseau du moment) : vide = on utilise `user.relay_server` tel quel. Sert de repli quand
        # un réseau filtré détourne le domaine principal par DNS (constaté sur le wifi d'un cégep,
        # qui renvoyait relais.velaglass.ca vers une impasse 10.1.255.32). Voir connectors.resoudre_relais.
        self.relay_base_override: str = ""
        self.user: UserSettings = self._load()

    def _load(self) -> UserSettings:
        if not self.settings_path.exists():
            user = UserSettings()
            self._write(user)
            return user
        try:
            raw = lire_reglages_bruts(self.settings_path)
        except Exception as exc:
            log.error("settings.json illisible (%s) : mis de côté dans %s, restauration depuis la sauvegarde",
                      exc, self.corrupt_path.name)
            self._mettre_de_cote(deplacer=True)
            return self._restaurer_ou_repartir()
        user, rejetes = construire_reglages(raw)
        if user is not None:
            if rejetes:
                # Le fichier est gardé tel quel à côté : ce qu'on a retiré doit rester consultable.
                self.champs_remis_au_defaut = rejetes
                log.warning("settings.json : champ(s) refusé(s) et remis au défaut : %s (copie dans %s)",
                            ", ".join(rejetes), self.corrupt_path.name)
                self._mettre_de_cote(deplacer=False)
                self._write(user)
            return user
        log.error("settings.json lisible mais irrécupérable : mis de côté dans %s, restauration depuis la sauvegarde",
                  self.corrupt_path.name)
        self._mettre_de_cote(deplacer=True)
        return self._restaurer_ou_repartir()

    def _restaurer_ou_repartir(self) -> UserSettings:
        """Remet en place settings.json.bak si elle est saine ; sinon, et seulement alors, repart de zéro."""
        if self.backup_path.exists():
            try:
                user, rejetes = construire_reglages(lire_reglages_bruts(self.backup_path))
            except Exception as exc:
                user, rejetes = None, []
                log.error("la sauvegarde %s est elle-même illisible (%s)", self.backup_path.name, exc)
            if user is not None:
                self.restaure_depuis_sauvegarde = True
                self.champs_remis_au_defaut = rejetes
                log.warning("réglages RESTAURÉS depuis %s : lunettes, clés et mot d'activation conservés%s",
                            self.backup_path.name,
                            f" (champs remis au défaut : {', '.join(rejetes)})" if rejetes else "")
                self._write(user)
                return user
        else:
            log.error("aucune sauvegarde %s : rien à restaurer", self.backup_path.name)
        log.error("réglages repartis de zéro : lunettes, clés et mot d'activation sont à refaire")
        user = UserSettings()
        self._write(user)
        return user

    def _mettre_de_cote(self, deplacer: bool) -> None:
        """Garde le fichier fautif sous settings.corrupt.json, pour qu'on puisse comprendre après coup."""
        try:
            if deplacer:
                os.replace(self.settings_path, self.corrupt_path)
            else:
                shutil.copyfile(self.settings_path, self.corrupt_path)
        except OSError as exc:
            log.warning("impossible de mettre settings.json de côté (%s)", exc)

    def _write(self, user: UserSettings) -> None:
        contenu = user.model_dump_json(indent=2)
        ecrire_atomique(self.settings_path, contenu)
        # La sauvegarde n'est écrite qu'APRÈS que le fichier principal est en place : elle ne
        # contient jamais autre chose qu'un état qui a réellement été enregistré. Si elle échoue,
        # les réglages sont quand même sauvés — on le note, on ne casse rien.
        try:
            ecrire_atomique(self.backup_path, contenu)
        except OSError as exc:
            log.warning("sauvegarde %s impossible (%s)", self.backup_path.name, exc)

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
