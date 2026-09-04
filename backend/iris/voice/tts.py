"""Synthèse vocale hors-ligne (pyttsx3 / SAPI5 sous Windows), dans un thread dédié."""
from __future__ import annotations

import logging
import queue
import re
import threading
import time

from ..config import Settings
from ..events import EventHub
from .elevenlabs import ElevenLabsSpeaker

log = logging.getLogger("iris.tts")

_CODE_BLOCK = re.compile(r"```.*?```", re.DOTALL)
_INLINE_CODE = re.compile(r"`([^`]*)`")
_LINK = re.compile(r"\[([^\]]+)\]\([^)]+\)")
_URL = re.compile(r"https?://\S+")
_MD = re.compile(r"[*_#>|]+")
_BULLET = re.compile(r"^\s*[-•]\s+", re.MULTILINE)


def _num_fr(value: str, ordinal: bool = False) -> str:
    try:
        from num2words import num2words

        v = value.replace(" ", "").replace(" ", "")
        if "," in v or "." in v:
            whole, dec = v.replace(",", ".").split(".", 1)
            dec_words = ("zéro " * (len(dec) - len(dec.lstrip("0")))).strip()
            dec_words = (dec_words + " " + num2words(int(dec.lstrip("0") or "0"), lang="fr")).strip() if dec.lstrip("0") else "zéro"
            return f"{num2words(int(whole or '0'), lang='fr')} virgule {dec_words}"
        return num2words(int(v), lang="fr", to="ordinal" if ordinal else "cardinal")
    except Exception:
        return value


_UNITS = [
    (r"(\d+(?:[.,]\d+)?)\s?%", r"\1 pour cent"),
    (r"(\d+(?:[.,]\d+)?)\s?°\s?[cC]\b", r"\1 degrés"),
    (r"(\d+(?:[.,]\d+)?)\s?km/h\b", r"\1 kilomètres heure"),
    (r"(\d+(?:[.,]\d+)?)\s?km\b", r"\1 kilomètres"),
    (r"(\d+(?:[.,]\d+)?)\s?(?:Go|GB)\b", r"\1 gigaoctets"),
    (r"(\d+(?:[.,]\d+)?)\s?(?:Mo|MB)\b", r"\1 mégaoctets"),
    (r"(\d+(?:[.,]\d+)?)\s?(?:Ko|KB)\b", r"\1 kilooctets"),
    (r"(\d+(?:[.,]\d+)?)\s?ms\b", r"\1 millisecondes"),
    (r"(\d+(?:[.,]\d+)?)\s?\$", r"\1 dollars"),
    (r"(\d+(?:[.,]\d+)?)\s?€", r"\1 euros"),
]


def _hour_words(h: str, mn: str | None) -> str:
    out = _num_fr(h) + (" heure" if h.lstrip("0") == "1" else " heures")
    if mn and mn.strip("0"):
        out += " " + _num_fr(mn.lstrip("0"))
    return out


def frenchify(text: str) -> str:
    """Écrit en toutes lettres heures, nombres, unités et symboles : une voix anglophone prononce alors du français."""
    text = re.sub(r"\b(\d{1,2})\s?[hH:]\s?(\d{2})\b", lambda m: _hour_words(m.group(1), m.group(2)), text)
    text = re.sub(r"\b(\d{1,2})\s?h\b", lambda m: _hour_words(m.group(1), None), text)
    for pat, rep in _UNITS:
        text = re.sub(pat, rep, text)
    text = re.sub(r"\b(\d+)(?:er|ère|re)\b", lambda m: _num_fr(m.group(1), ordinal=True), text)
    text = re.sub(r"\b(\d+)(?:e|ème|ième)\b", lambda m: _num_fr(m.group(1), ordinal=True), text)
    # nombres jusqu'à 7 chiffres (les identifiants plus longs restent tels quels)
    text = re.sub(r"(?<![\w-])(\d{1,7}(?:[.,]\d+)?)(?![\w-])", lambda m: _num_fr(m.group(1)), text)
    text = text.replace("&", " et ").replace("+", " plus ").replace("→", ", ").replace("—", ", ").replace("=", " égale ")
    text = re.sub(r"(?<=\w)\s*/\s*(?=\w)", " sur ", text)
    return text


def speakable(text: str, limit: int = 1500, language: str = "fr") -> str:
    text = _CODE_BLOCK.sub(" (bloc de code) ", text or "")
    text = _INLINE_CODE.sub(r"\1", text)
    text = _LINK.sub(r"\1", text)
    text = _URL.sub(" lien ", text)
    text = _MD.sub("", text)
    text = _BULLET.sub("", text)
    if (language or "fr").lower().startswith("fr"):
        text = frenchify(text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit]


class TextToSpeech:
    def __init__(self, settings: Settings, hub: EventHub, enabled: bool = True):
        self.settings = settings
        self.hub = hub
        self._queue: "queue.Queue[str | None]" = queue.Queue()
        self._idle = threading.Event()
        self._idle.set()
        self._ready = threading.Event()
        self._engine = None
        self._voices: list[dict] = []
        self.available = enabled
        self.error: str | None = None if enabled else "synthèse vocale désactivée"
        self.speaking = False
        self._thread: threading.Thread | None = None
        self._start_lock = threading.Lock()
        self.eleven = ElevenLabsSpeaker(settings, hub)
        self.eleven.fallback_speak = lambda text: self._speak_windows(text)

    def _ensure_started(self) -> None:
        """Démarre le thread moteur à la première utilisation (évite d'initialiser SAPI inutilement)."""
        if not self.available:
            return
        with self._start_lock:
            if self._thread is None:
                self._thread = threading.Thread(target=self._worker, name="iris-tts", daemon=True)
                self._thread.start()
        self._ready.wait(timeout=15)

    def _apply_settings(self) -> None:
        if self._engine is None:
            return
        u = self.settings.user
        try:
            self._engine.setProperty("rate", int(u.tts_rate or 175))
            self._engine.setProperty("volume", 1.0)
            if u.tts_voice:
                self._engine.setProperty("voice", u.tts_voice)
        except Exception as exc:
            log.warning("réglage TTS impossible: %s", exc)

    def _pick_default_voice(self) -> None:
        if self._engine is None or self.settings.user.tts_voice:
            return
        lang = (self.settings.user.language or "fr").lower()[:2]
        for v in self._voices:
            if lang in (v.get("lang") or "").lower() or lang in v["name"].lower():
                try:
                    self._engine.setProperty("voice", v["id"])
                except Exception:
                    pass
                return
        names = ", ".join(v["name"] for v in self._voices) or "aucune"
        msg = f"Windows n'a aucune voix « {lang} » installée (voix disponibles : {names}) : IRIS parlera avec un accent étranger tant qu'ElevenLabs n'est pas actif. Installer « Hortense » ou « Caroline » dans Paramètres Windows › Heure et langue › Voix."
        log.warning("aucune voix Windows en %s : %s", lang, names)
        try:
            self.hub.publish("voice.warning", text=msg)
        except Exception:
            pass

    def _worker(self) -> None:
        try:
            try:  # SAPI5 est un objet COM : initialiser COM dans ce thread
                import comtypes

                comtypes.CoInitialize()
            except Exception:
                pass
            import pyttsx3

            self._engine = pyttsx3.init()
            for v in self._engine.getProperty("voices"):
                langs = getattr(v, "languages", None) or []
                lang = ""
                if langs:
                    first = langs[0]
                    lang = first.decode(errors="ignore") if isinstance(first, bytes) else str(first)
                self._voices.append({"id": v.id, "name": v.name, "lang": lang})
            self._pick_default_voice()
        except Exception as exc:
            self.available = False
            self.error = f"Synthèse vocale indisponible : {exc}"
            log.warning(self.error)
            self._ready.set()
            self._idle.set()
            return
        self._ready.set()
        while True:
            item = self._queue.get()
            if item is None:
                break
            self._idle.clear()
            self.speaking = True
            self.hub.publish("tts.state", speaking=True, text=item[:200])
            try:
                self._apply_settings()
                self._engine.say(item)
                self._engine.runAndWait()
            except Exception as exc:
                log.warning("erreur TTS: %s", exc)
            finally:
                self.speaking = False
                if self._queue.empty():
                    self._idle.set()
                self.hub.publish("tts.state", speaking=False)

    plans = None  # PlanService (injecté)

    def _use_elevenlabs(self) -> bool:
        if self.settings.user.tts_engine == "windows":
            return False
        if self.plans is not None and not self.plans.feature_allowed("elevenlabs"):
            return False
        return self.eleven.available

    @property
    def engine(self) -> str:
        return "elevenlabs" if self._use_elevenlabs() else "windows"

    def speak(self, text: str, force: bool = False) -> bool:
        if not force and not self.settings.user.tts_enabled:
            return False
        clean = speakable(text, language=self.settings.user.language)
        if not clean:
            return False
        if self._use_elevenlabs() and self.eleven.speak(clean):
            if self.plans is not None:
                try:
                    self.plans.count_tts(len(clean))
                except Exception:
                    pass
            return True
        return self._speak_windows(clean)

    def _speak_windows(self, clean: str) -> bool:
        if not self.available:
            return False
        self._ensure_started()
        if not self.available:
            return False
        self._idle.clear()
        self._queue.put(clean)
        return True

    def stop(self) -> None:
        self.eleven.stop()
        try:
            while True:
                self._queue.get_nowait()
        except queue.Empty:
            pass
        if self._engine is not None:
            try:
                self._engine.stop()
            except Exception:
                pass
        self._idle.set()

    def wait_idle(self, timeout: float = 30.0) -> bool:
        deadline = time.time() + timeout
        ok = self.eleven.wait_idle(timeout)
        return self._idle.wait(max(0.1, deadline - time.time())) and ok

    @property
    def is_speaking(self) -> bool:
        return self.speaking or self.eleven.speaking

    def voices(self) -> list[dict]:
        self._ensure_started()
        return list(self._voices)

    def shutdown(self) -> None:
        self.stop()
        self.eleven.shutdown()
        if self._thread is not None:
            self._queue.put(None)
