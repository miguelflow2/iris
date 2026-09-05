"""Écoute continue : détection du mot d'activation personnalisé, capture de la commande, réponse vocale.
Tout se passe sur l'appareil avec Vosk ; le repli Google n'est utilisé qu'avec consentement explicite."""
from __future__ import annotations

import asyncio
import difflib
import json
import logging
import queue
import re
import threading
import time
import unicodedata
from typing import Awaitable, Callable

from ..capture import CaptureIndicator
from ..config import Settings
from ..consent import ConsentGate
from ..events import EventHub
from . import stt
from .tts import TextToSpeech

log = logging.getLogger("iris.voice")

BLOCK = 4000  # échantillons (0,25 s à 16 kHz)
COMMAND_TIMEOUT = 12.0  # durée maximale d'une commande, en secondes d'audio réellement traitées
NO_SPEECH_TIMEOUT = 4.0  # si personne ne parle : on rend la main tout de suite au lieu d'attendre 12 s
SILENCE_END = 0.9  # silence qui marque la fin d'une phrase
SPEECH_PEAK = 700  # amplitude minimale considérée comme de la parole (sur 32767)
WEAK_MIC_PEAK = 1500  # en dessous : le micro capte trop faiblement, on le signale à l'utilisateur
POLITESSE = {"ok", "okay", "bon", "merci", "svp", "stp"}  # écartés avant de reconnaître un ordre d'arrêt
CLOUD_TIMEOUT = 4.0  # renfort de reconnaissance cloud : au-delà, on garde la transcription locale


def wake_phrases(wake: str, aliases: list[str] | None = None) -> list[str]:
    """Phrases d'activation normalisées, sans doublon : grammaire Vosk et comparaison exacte."""
    out: list[str] = []
    for phrase in [wake] + list(aliases or []):
        n = normalize(phrase)
        if n and n not in out:
            out.append(n)
    return out


def find_wake_phrase(words: list[str], phrases: list[str]) -> int:
    """Indice du mot suivant la phrase d'activation trouvée dans `words`, ou -1.
    Comparaison exacte : avec la grammaire, Vosk ne peut renvoyer que des mots du vocabulaire d'activation,
    la tolérance floue (qui déclenchait sur « j'irais » ou « ris ») devient inutile et nuisible."""
    for phrase in sorted(phrases, key=lambda p: -len(p.split())):
        toks = phrase.split()
        n = len(toks)
        for i in range(0, len(words) - n + 1):
            if words[i : i + n] == toks:
                return i + n
    return -1


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9 ]+", " ", text.lower()).strip()


def matches_any(text: str, words: list[str]) -> bool:
    """La phrase contient-elle l'un des mots/expressions (tolérant aux accents, à la casse et aux petites erreurs) ?"""
    t = normalize(text)
    if not t:
        return False
    tokens = t.split()
    for w in words or []:
        nw = normalize(w)
        if not nw:
            continue
        if f" {nw} " in f" {t} ":
            return True
        n = len(nw.split())
        if n == 1:
            if any(len(tok) >= 4 and difflib.SequenceMatcher(None, tok, nw).ratio() >= 0.85 for tok in tokens):
                return True
        else:
            for i in range(0, max(0, len(tokens) - n + 1)):
                if difflib.SequenceMatcher(None, " ".join(tokens[i : i + n]), nw).ratio() >= 0.85:
                    return True
    return False


def contains_wake(text: str, wake: str, threshold: float = 0.78, aliases: list[str] | None = None) -> tuple[bool, str]:
    """Détecte le mot d'activation (tolérant aux erreurs de reconnaissance) ou l'un de ses alias.
    Retourne (détecté, reste de la phrase après le mot)."""
    for alias in aliases or []:
        if alias and normalize(alias) != normalize(wake):
            found, rest = contains_wake(text, alias, threshold)
            if found:
                return True, rest
    words = normalize(text).split()
    wake_words = normalize(wake).split()
    if not words or not wake_words:
        return False, ""
    n = len(wake_words)
    wake_str = " ".join(wake_words)
    best_i = -1
    for i in range(0, len(words) - n + 1):
        window = " ".join(words[i : i + n])
        if window == wake_str:
            best_i = i
            break
        # Tolérance aux erreurs de reconnaissance, mais le mot distinctif (le dernier, « iris ») doit être exact :
        # sans cette condition, « dis moi i risque » ou « j'irais » activaient IRIS.
        if n > 1 and words[i + n - 1] == wake_words[-1] and difflib.SequenceMatcher(None, window, wake_str).ratio() >= threshold:
            best_i = i
            break
    if best_i < 0 and n > 1:
        # Un seul mot reconnu (ex. « iris » sans « dis-moi ») : exiger le mot exact, et seulement en tête de
        # phrase. La tolérance floue déclenchait sur « j'irais bien », « ris » ou « dis moi i risque ».
        key = max(wake_words, key=len)
        for i, w in enumerate(words[:4]):
            if len(key) >= 4 and w == key:
                return True, " ".join(words[i + 1 :])
        return False, ""
    if best_i < 0:
        return False, ""
    return True, " ".join(words[best_i + n :])


class VoiceListener:
    def __init__(
        self,
        settings: Settings,
        hub: EventHub,
        consent: ConsentGate,
        capture: CaptureIndicator,
        tts: TextToSpeech,
        on_command: Callable[[str], Awaitable[dict]],
    ):
        self.settings = settings
        self.hub = hub
        self.consent = consent
        self.capture = capture
        self.tts = tts
        self.on_command = on_command
        self.loop: asyncio.AbstractEventLoop | None = None
        self.state = "off"
        self.engine: str | None = None
        self.error: str | None = None
        self.last_transcript = ""
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._ptt = threading.Event()
        self._one_shot = False
        self._audio: "queue.Queue[bytes]" = queue.Queue(maxsize=400)
        self._vosk: stt.VoskEngine | None = None
        self._vosk_path = None
        self.stopped_by_user = False
        self.last_active = 0.0
        self.calibrating = 0  # nb de répétitions du mot d'activation encore attendues
        self.muted = False  # micro coupé volontairement (bouton, raccourci ou commande « muet »)
        self._started_at = 0.0  # anti double clic : une pause < 3 s après le démarrage est ignorée
        self.dropped = 0  # blocs audio perdus (le décodage ne suit pas)
        self.level = 0  # niveau du micro (pic récent, 0-32767) pour l'indicateur de Paramètres › Voix
        self.device_name = ""  # micro réellement ouvert
        self._last_peak = 0  # pic de la dernière commande (pour signaler un micro trop faible)
        self._level_sent = 0.0
        self.paused_until = 0.0  # pause temporaire (bouton « Arrêter l'écoute ») : l'écoute reprend automatiquement après

    # ------------------------------------------------------------------ état
    def model_ready(self) -> bool:
        return stt.model_dir(self.settings.models_dir, self.settings.user.language) is not None

    def mic_devices(self) -> list[str]:
        try:
            import sounddevice as sd

            return [d["name"] for d in sd.query_devices() if d.get("max_input_channels", 0) > 0]
        except Exception:
            return []

    def status(self) -> dict:
        return {
            "state": self.state,
            "engine": self.engine,
            "error": self.error,
            "wake_word": self.settings.user.wake_word,
            "model_ready": self.model_ready(),
            "model_info": stt.VOSK_MODELS[stt.lang_key(self.settings.user.language)],
            "running": self.running,
            "last_transcript": self.last_transcript,
            "tts_available": self.tts.available,
            "muted": self.muted,
            "level": self.level,
            "device": self.device_name,
            "lag": round(self._audio.qsize() * BLOCK / stt.SAMPLE_RATE, 2),
            "dropped": self.dropped,
            "paused_until": self.paused_until if self.paused_until > time.time() else 0.0,
        }

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def _set_state(self, state: str, **extra) -> None:
        self.state = state
        self.last_active = time.time()
        self.hub.publish("voice.state", **self.status(), **extra)

    # ------------------------------------------------------------------ contrôle
    def _narrowband_input(self) -> bool:
        """Micro en qualité téléphone (profil Bluetooth mains libres, 8 kHz) ?"""
        wanted = (self.settings.user.audio_input_device or "").lower()
        if "hands-free" in wanted or "mains libres" in wanted or "hfp" in wanted:
            return True
        try:
            import sounddevice as sd

            idx = self._input_device(sd)
            if idx is not None and sd.query_devices(idx, "input")["default_samplerate"] <= 16000:
                return True
        except Exception:
            pass
        return False

    def _choose_engine(self) -> str:
        pref = self.settings.user.stt_engine
        if pref == "auto" and self._narrowband_input() and self.consent.is_granted("audio_raw") and not self.settings.user.local_only:
            log.info("micro bande étroite : reconnaissance cloud privilégiée")
            return "google"
        if pref in ("auto", "vosk") and self.model_ready():
            return "vosk"
        if pref == "vosk":
            raise RuntimeError("Modèle de reconnaissance hors-ligne absent : téléchargez-le dans Paramètres › Voix.")
        # repli cloud : exige un consentement explicite et pas de mode local
        if self.settings.user.local_only:
            raise RuntimeError("Mode 100 % local : téléchargez le modèle de reconnaissance hors-ligne pour utiliser la voix.")
        if not self.consent.is_granted("audio_raw"):
            raise RuntimeError(
                "Reconnaissance hors-ligne indisponible. Téléchargez le modèle Vosk (Paramètres › Voix) ou autorisez "
                "« Audio brut du micro » dans Confidentialité pour utiliser la reconnaissance cloud."
            )
        return "google"

    def start(self, one_shot: bool = False) -> dict:
        if self.running:
            return self.status()
        if self.muted and not one_shot:
            self.error = "Micro coupé (muet). Cliquez sur « Réactiver le micro » ou Ctrl+Maj+M."
            self._set_state("off")
            return self.status()
        if self.settings.user.privacy_mode:
            self.error = "Mode confidentiel actif : le micro est coupé. Désactivez-le dans Confidentialité pour écouter."
            self.stopped_by_user = True
            self._set_state("off")
            return self.status()
        self.error = None
        try:
            self.engine = self._choose_engine()
        except RuntimeError as exc:
            self.error = str(exc)
            self._set_state("off")
            return self.status()
        if self.engine == "vosk":
            path = stt.model_dir(self.settings.models_dir, self.settings.user.language)
            if self._vosk is None or self._vosk_path != path:
                self._vosk = stt.VoskEngine(path)  # type: ignore[arg-type]
                self._vosk_path = path
        self._one_shot = one_shot
        self.stopped_by_user = False
        self.paused_until = 0.0
        self._started_at = time.time()
        self._stop.clear()
        self._ptt.clear()
        self._thread = threading.Thread(target=self._run, name="iris-voice", daemon=True)
        self._thread.start()
        return self.status()

    def stop(self, by_user: bool = True) -> dict:
        import traceback

        caller = "".join(traceback.format_stack(limit=4)[:-1]).strip().splitlines()
        log.info("écoute arrêtée (by_user=%s) — diagnostic arrêt, appelant : %s", by_user, " | ".join(l.strip() for l in caller if "File" in l)[-300:])
        self.stopped_by_user = by_user
        self._stop.set()
        self._ptt.set()
        thread = self._thread
        if thread and thread.is_alive() and threading.current_thread() is not thread:
            thread.join(timeout=5)
        self._thread = None
        self.capture.set(mic=False, listening=False)
        # Une calibration en cours ne survit pas à l'arrêt du micro : sinon IRIS reste en
        # vocabulaire complet (plus lent, mot d'activation moins fiable) sans que rien ne le dise.
        self.calibrating = 0
        self._set_state("off")
        return self.status()

    def calibrate(self, count: int = 3) -> dict:
        """Apprend les variantes que la reconnaissance produit quand VOUS dites le mot d'activation.

        `count <= 0` annule une calibration en cours : sans ce chemin, un essai abandonné laisse
        IRIS en vocabulaire complet et fait enregistrer comme alias la première phrase entendue."""
        demande = int(count or 0)
        if demande <= 0:
            self.calibrating = 0
            self.hub.publish("voice.calibration", remaining=0, added=None, active=False)
            return {"remaining": 0, "running": self.running, "error": self.error}
        self.calibrating = min(demande, 6)
        self.hub.publish("voice.calibration", remaining=self.calibrating, added=None, active=True)
        if not self.running:
            self.start()
        return {"remaining": self.calibrating, "running": self.running, "error": self.error}

    def _learn_alias(self, heard: str) -> None:
        text = normalize(heard)
        if not text or self.calibrating <= 0:
            return
        self.calibrating -= 1
        aliases = list(self.settings.user.wake_aliases or [])
        found, _ = contains_wake(heard, self.settings.user.wake_word, aliases=aliases)
        added = None
        if not found and text not in [normalize(a) for a in aliases]:
            aliases.append(text)
            self.settings.update({"wake_aliases": aliases})
            added = text
            self.hub.publish("settings.updated", settings=self.settings.user.model_dump())
        self.hub.publish("voice.calibration", remaining=self.calibrating, added=added, heard=heard, active=self.calibrating > 0)

    def pause(self, minutes: float = 10.0) -> dict:
        """Arrêt temporaire : l'écoute reprend d'elle-même après `minutes` (le muet reste l'arrêt explicite)."""
        if self.running and time.time() - self._started_at < 3.0:
            log.info("pause ignorée : l'écoute vient de démarrer (anti double clic)")
            self.hub.publish("voice.info", text="L'écoute vient de démarrer ; cliquez de nouveau dans quelques secondes pour la mettre en pause.")
            return self.status()
        self.paused_until = time.time() + max(1.0, float(minutes)) * 60
        result = self.stop(by_user=True)
        self.hub.publish("voice.paused", until=self.paused_until, minutes=minutes)
        return result

    def mute(self, announce: bool = True) -> dict:
        """Coupe le micro (état muet) : plus aucune écoute jusqu'à réactivation explicite."""
        if announce and self.tts.available:
            self.tts.speak("Micro coupé.", force=True)
            self.tts.wait_idle(timeout=8)
        self.muted = True
        self.stop(by_user=True)
        self.hub.publish("voice.muted", muted=True)
        return self.status()

    def unmute(self) -> dict:
        self.muted = False
        self.hub.publish("voice.muted", muted=False)
        return self.start()

    def interrupt(self) -> None:
        """Coupe la parole d'IRIS immédiatement (mot « stop », bouton)."""
        self.tts.stop()
        self._drain()
        self.hub.publish("voice.interrupted")

    def _wait_speech(self, timeout: float = 120.0, capture: list[bytes] | None = None) -> None:
        """Attend la fin de la parole d'IRIS en guettant le mot « stop ».
        Grammaire restreinte aux mots d'arret : en plein vocabulaire, la voix d'IRIS captee par le micro du
        portable (« j'ai arrete la musique ») declenchait l'interruption toute seule.
        `capture` recueille ce que dit l'utilisateur pendant l'accuse, pour ne pas perdre le debut de sa commande."""
        stop_words = [normalize(w) for w in (self.settings.user.stop_words or []) if normalize(w)]
        rec = None
        if self.engine == "vosk" and self._vosk is not None and stop_words:
            rec = self._vosk.recognizer(stop_words)
        started = time.time()
        while time.time() - started < timeout and not self._stop.is_set():
            if not self.tts.is_speaking and self.tts.wait_idle(timeout=0.05):
                break
            data = self._read(0.15)
            if data is None:
                continue
            if capture is not None and not self.tts.is_speaking:
                capture.append(data)
            if rec is None:
                continue
            final = rec.AcceptWaveform(data)
            text = stt.VoskEngine.text_of(rec.Result()) if final else stt.VoskEngine.text_of(rec.PartialResult(), "partial")
            spoken = [w for w in text.split() if w != "[unk]"]
            # un « stop » isole prononce par l'utilisateur, pas un mot noye dans la phrase d'IRIS
            if spoken and len(spoken) <= 2 and " ".join(spoken) in stop_words and time.time() - started > 0.3:
                log.info("mot d'arret entendu : %r", text)
                self.interrupt()
                break
        if capture is None:
            self._drain()

    def push_to_talk(self) -> dict:
        """Capture une commande immédiatement, sans attendre le mot d'activation."""
        if not self.running:
            return self.start(one_shot=True)
        self._ptt.set()
        return self.status()

    # ------------------------------------------------------------------ boucle audio
    def _resample(self, data: bytes) -> bytes:
        """Rééchantillonne le PCM 16 bits mono de la fréquence native du micro vers 16 kHz (Vosk)."""
        rate = getattr(self, "_native_rate", stt.SAMPLE_RATE)
        if rate == stt.SAMPLE_RATE or not data:
            return data
        import numpy as np

        pcm = np.frombuffer(data, dtype=np.int16)
        n_out = max(1, int(len(pcm) * stt.SAMPLE_RATE / rate))
        x_old = np.linspace(0.0, 1.0, len(pcm), endpoint=False)
        x_new = np.linspace(0.0, 1.0, n_out, endpoint=False)
        return np.interp(x_new, x_old, pcm.astype(np.float32)).astype(np.int16).tobytes()

    def _callback(self, indata, frames, time_info, status) -> None:  # noqa: D401 - signature sounddevice
        try:
            self._audio.put_nowait(self._resample(bytes(indata)))
        except queue.Full:
            # Le décodage a pris du retard : on perd de l'audio. Silencieux auparavant, donc invisible.
            self.dropped += 1
            if self.dropped % 40 == 1:
                log.warning("audio en retard : %d bloc(s) perdu(s), le décodage ne suit pas", self.dropped)

    def _input_device(self, sd) -> int | None:
        """Index du micro choisi (ex. lunettes appairées en casque Bluetooth), sinon None = défaut système."""
        wanted = (self.settings.user.audio_input_device or "").strip().lower()
        if not wanted:
            return None
        try:
            for idx, dev in enumerate(sd.query_devices()):
                if dev.get("max_input_channels", 0) > 0 and wanted in dev["name"].lower():
                    return idx
        except Exception:
            pass
        log.warning("micro « %s » introuvable, micro par défaut utilisé", wanted)
        return None

    def _drain(self) -> None:
        try:
            while True:
                self._audio.get_nowait()
        except queue.Empty:
            pass

    @staticmethod
    def _peak_of(data: bytes) -> int:
        """Amplitude maximale du bloc (0-32767) : sert à savoir si quelqu'un parle et si le micro capte assez fort."""
        if not data:
            return 0
        import numpy as np

        return int(np.abs(np.frombuffer(data, dtype=np.int16)).max())

    def _read(self, timeout: float = 0.3) -> bytes | None:
        try:
            data = self._audio.get(timeout=timeout)
        except queue.Empty:
            return None
        self.level = max(int(self.level * 0.7), self._peak_of(data))
        now = time.time()
        # niveau publié seulement pendant qu'on attend une commande (indicateur de Paramètres › Voix)
        if self.state in ("command", "armed") and now - self._level_sent > 0.5:
            self._level_sent = now
            self.hub.publish("voice.level", peak=self.level, device=self.device_name,
                             lag=round(self._audio.qsize() * BLOCK / stt.SAMPLE_RATE, 2))
        return data

    def _run(self) -> None:
        try:
            import sounddevice as sd

            device = self._input_device(sd)
            self._native_rate = int(sd.query_devices(device, "input")["default_samplerate"]) if device is not None else stt.SAMPLE_RATE
            if self._native_rate <= 0:
                self._native_rate = stt.SAMPLE_RATE
            block = max(400, int(BLOCK * self._native_rate / stt.SAMPLE_RATE))
            stream = sd.RawInputStream(
                samplerate=self._native_rate, blocksize=block, dtype="int16", channels=1, callback=self._callback, device=device
            )
            try:
                self.device_name = sd.query_devices(device if device is not None else sd.default.device[0], "input")["name"]
            except Exception:
                self.device_name = "micro par défaut"
            self.dropped = 0
            log.info("micro %s (%s) à %d Hz (rééchantillonné vers %d Hz)", device if device is not None else "par défaut",
                     self.device_name, self._native_rate, stt.SAMPLE_RATE)
            stream.start()
        except Exception as exc:
            self.error = f"Micro indisponible : {exc}"
            self._thread = None
            self._set_state("off")
            return
        self.capture.set(mic=True, listening=True)
        try:
            if self._one_shot:
                self._command_cycle()
            while not self._stop.is_set() and not self._one_shot:
                self._wake_cycle()
        except Exception as exc:  # pragma: no cover
            log.exception("boucle vocale interrompue")
            self.error = f"Erreur audio : {exc}"
        finally:
            log.info("fin de la boucle vocale (stop=%s one_shot=%s erreur=%s)", self._stop.is_set(), self._one_shot, self.error)
            try:
                stream.stop()
                stream.close()
            except Exception:
                pass
            self.capture.set(mic=False, listening=False)
            self._thread = None
            self._set_state("off")

    # ------------------------------------------------------------------ cycles
    def _wake_cycle(self) -> None:
        """Attend le mot d'activation puis traite la commande."""
        self._set_state("wake")
        wake = self.settings.user.wake_word
        aliases = list(self.settings.user.wake_aliases or [])
        if self.engine == "vosk":
            # Grammaire restreinte aux phrases d'activation : le plein vocabulaire perdait le mot d'activation
            # (mesuré : « Dis-moi Iris » → « dis-moi », « Iris » → « arès ») et coûtait 2 à 4 s par phrase sur
            # cette machine, si bien que l'audio prenait du retard. La grammaire décide en 0,05 s, sans erreur.
            # Exception : pendant la calibration, il faut entendre ce que l'utilisateur dit vraiment.
            calibrating = self.calibrating > 0
            phrases = wake_phrases(wake, aliases)
            mute_words = [normalize(w) for w in (self.settings.user.mute_words or []) if normalize(w)]
            rec = self._vosk.recognizer() if calibrating else self._vosk.recognizer(phrases + mute_words, words=True)  # type: ignore[union-attr]
            pending: list[tuple[int, bytes]] = []  # audio de l'énoncé en cours (pour rejouer la fin de la commande)
            offset = 0
            while not self._stop.is_set():
                if self._ptt.is_set():
                    self._ptt.clear()
                    self._command_cycle()
                    return
                if (self.calibrating > 0) != calibrating:
                    return  # le mode calibration vient de changer : on recrée le bon reconnaisseur
                data = self._read()
                if data is None:
                    continue
                pending.append((offset, data))
                offset += len(data) // 2
                if len(pending) > 48:  # ~12 s : on ne garde que l'énoncé courant
                    pending.pop(0)
                if not rec.AcceptWaveform(data):
                    continue
                result = rec.Result()
                text = stt.VoskEngine.text_of(result)
                if calibrating:
                    if text:
                        self._learn_alias(text)
                    pending, offset = [], 0
                    continue
                words = [w for w in text.split() if w != "[unk]"]
                phrase = " ".join(words)
                if words and len(words) <= 3 and phrase in mute_words:
                    self.hub.publish("voice.transcript", text=phrase)
                    self.mute(announce=True)
                    return
                cut = find_wake_phrase(words, phrases)
                if cut < 0:
                    if words:
                        self.hub.publish("voice.heard", text=phrase)
                    pending, offset = [], 0
                    continue
                log.info("mot d'activation reconnu : %r", text)
                self.hub.publish("voice.wake", text=phrase)
                # Commande dite dans le même souffle : la grammaire ne sait pas la transcrire ([unk]),
                # on rejoue son audio dans le reconnaisseur de commande au lieu de le jeter.
                enchaine = self._utterance_after_wake(result, cut, pending)
                self._command_cycle(ack=not enchaine, primed=enchaine)
                return
        else:
            segment = self._capture_segment(max_seconds=6.0)
            if self._ptt.is_set():
                self._ptt.clear()
                self._command_cycle()
                return
            if not segment:
                return
            text = self._cloud_recognize(segment)
            if not text:
                return
            found, rest = contains_wake(text, wake, aliases=aliases)
            if not found:
                self.hub.publish("voice.heard", text=text)
            if found:
                self.hub.publish("voice.wake", text=text)
                if rest.strip():
                    self._process(rest)
                else:
                    self._command_cycle(ack=True)

    def _utterance_after_wake(self, result_json: str, cut: int, pending: list[tuple[int, bytes]]) -> bytes:
        """Si l'utilisateur a enchaîné sa commande dans le même souffle, renvoie l'audio de TOUT l'énoncé.
        On rejoue l'énoncé entier (mot d'activation compris) dans le reconnaisseur complet plutôt que de couper
        l'audio au millième près : découper juste après « iris » abîmait le premier mot de la commande
        (« ouvre mon navigateur » devenait « vraiment navigateur »). Le mot d'activation sera retiré du texte."""
        try:
            spoken = [w for w in (json.loads(result_json).get("result") or []) if w.get("word") != "[unk]"]
            if not cut or cut > len(spoken):
                return b""
            fin_activation = float(spoken[cut - 1]["end"])
        except Exception:
            return b""
        total = sum(len(data) for _off, data in pending) / 2 / stt.SAMPLE_RATE
        if total - fin_activation < 0.3:
            return b""  # rien n'a été dit après le mot d'activation
        return b"".join(data for _off, data in pending)

    def _command_cycle(self, ack: bool = False, primed: bytes = b"") -> None:
        self._set_state("command")
        captured: list[bytes] = []
        if ack and self.settings.user.voice_ack:
            # On continue d'écouter pendant l'accusé : auparavant « Oui ? » était suivi d'un vidage de la file
            # audio, donc tout ce que l'utilisateur enchaînait aussitôt après était jeté.
            self._say("Oui ?", capture=captured)
        text = self._listen_command(primed=primed + b"".join(captured))
        if text.strip():
            self._process(text)
            self._fenetre_dialogue()
        else:
            self.hub.publish("voice.transcript", text="", empty=True)
            self._say(self._no_speech_message())
            if self._one_shot:
                self._stop.set()

    def _no_speech_message(self) -> str:
        """Message honnête : distinguer « personne n'a parlé » de « le micro ne capte presque rien »."""
        if self._last_peak and self._last_peak < WEAK_MIC_PEAK:
            self.hub.publish(
                "voice.warning",
                text=f"Le micro « {self.device_name} » capte très faiblement (niveau {self._last_peak} sur 32767). "
                "Rapprochez-vous, montez le volume d'entree dans Windows, ou choisissez un autre micro dans Parametres > Voix.",
            )
            return "Je n'ai rien entendu, le micro capte tres faiblement."
        return "Je n'ai rien entendu."

    def _listen_command(self, primed: bytes = b"") -> str:
        """Capture une phrase et la transcrit. Fin detectee par le silence, sortie rapide si personne ne parle."""
        if self.engine != "vosk":
            segment = self._capture_segment(max_seconds=COMMAND_TIMEOUT, wait_for_speech=NO_SPEECH_TIMEOUT)
            text = self._cloud_recognize(segment) if segment else ""
            self._log_stt("google", text, len(segment) / 2 / stt.SAMPLE_RATE if segment else 0.0, 0)
            return text

        rec = self._vosk.recognizer()  # type: ignore[union-attr]
        chunks: list[bytes] = []
        consumed = 0.0  # secondes d'audio reellement traitees (l'horloge murale mentirait si le decodage traine)
        speech = 0.0  # secondes de parole detectee
        last_speech = 0.0
        peak_max = 0
        noise: list[int] = []
        text = ""

        if primed:
            chunks.append(primed)
            consumed = len(primed) / 2 / stt.SAMPLE_RATE
            speech = last_speech = consumed
            peak_max = self._peak_of(primed)
            if rec.AcceptWaveform(primed):
                text = stt.VoskEngine.text_of(rec.Result())

        started = time.time()
        while not text and not self._stop.is_set() and consumed < COMMAND_TIMEOUT and time.time() - started < COMMAND_TIMEOUT * 2:
            data = self._read()
            if data is None:
                continue
            chunks.append(data)
            seconds = len(data) / 2 / stt.SAMPLE_RATE
            consumed += seconds
            peak = self._peak_of(data)
            peak_max = max(peak_max, peak)
            if len(noise) < 4:
                noise.append(peak)  # bruit ambiant mesure sur la premiere seconde
            if peak >= max(SPEECH_PEAK, int(2.5 * (sum(noise) / len(noise)))):
                speech += seconds
                last_speech = consumed
            if rec.AcceptWaveform(data):
                text = stt.VoskEngine.text_of(rec.Result())
                if text:
                    break
                continue
            if speech <= 0.15 and consumed >= NO_SPEECH_TIMEOUT:
                break  # silence complet : inutile d'attendre 12 s avant de le dire
            if speech > 0.3 and consumed - last_speech >= SILENCE_END:
                break  # fin de phrase detectee par le silence
        if not text:
            text = stt.VoskEngine.text_of(rec.FinalResult())

        pcm = b"".join(chunks)
        self._last_peak = peak_max
        self._log_stt("vosk", text, len(pcm) / 2 / stt.SAMPLE_RATE, peak_max)
        return self._strip_wake(self._cloud_upgrade(pcm, text) or text)

    def _strip_wake(self, text: str) -> str:
        """Retire le mot d'activation en tête : l'énoncé rejoué le contient (« dis moi iris ouvre google »)."""
        if not text:
            return text
        found, rest = contains_wake(text, self.settings.user.wake_word, aliases=list(self.settings.user.wake_aliases or []))
        return rest.strip() if found else text

    def _log_stt(self, engine: str, text: str, seconds: float, peak: int) -> None:
        log.info(
            "stt %s: %r (%.1f s d'audio, pic %d, retard %.1f s, %d bloc(s) perdu(s), micro %s)",
            engine, text, seconds, peak, self._audio.qsize() * BLOCK / stt.SAMPLE_RATE, self.dropped, self.device_name,
        )

    def _cloud_upgrade(self, pcm: bytes, local_text: str) -> str:
        """Renfort de reconnaissance cloud pour la COMMANDE seulement (l'activation reste toujours hors ligne).
        Le petit modele local transcrit mal le francais parle du Quebec ; Google le fait nettement mieux.
        Exige le consentement « audio brut » et un reseau : sinon on garde simplement la version locale."""
        u = self.settings.user
        seconds = len(pcm) / 2 / stt.SAMPLE_RATE
        if u.stt_engine == "vosk" or u.local_only or not (0.4 <= seconds <= 20):
            return ""
        if not self.consent.is_granted("audio_raw"):
            return ""
        try:
            import concurrent.futures

            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                got = pool.submit(stt.google_recognize, pcm, stt.SAMPLE_RATE, u.language).result(timeout=CLOUD_TIMEOUT)
            text = (got or "").strip()
        except Exception as exc:
            log.info("renfort cloud indisponible (%s) : transcription locale conservee", type(exc).__name__)
            return ""
        if not text:
            return ""
        self.consent.log("external_send", data_type="audio_raw", agent="google-stt", detail=f"{int(seconds * 1000)} ms d'audio")
        if normalize(text) != normalize(local_text):
            log.info("stt cloud: %r (local: %r)", text, local_text)
        return text

    def _process(self, text: str, depth: int = 0) -> None:
        text = text.strip()
        self.last_transcript = text
        if matches_any(text, list(self.settings.user.mute_words or [])):
            self.hub.publish("voice.transcript", text=text)
            self.mute(announce=True)
            return
        self._set_state("processing")
        self.hub.publish("voice.transcript", text=text)
        started = time.time()
        reply: dict = {}
        if self.loop is not None:
            try:
                future = asyncio.run_coroutine_threadsafe(self.on_command(text), self.loop)
                reply = future.result(timeout=600) or {}
            except Exception as exc:
                log.warning("commande vocale en erreur: %s", exc)
                reply = {"text": "Désolée, je n'ai pas pu traiter cette demande.", "spoken": False}
        reply_text = (reply.get("text") or "").strip()
        self._set_state("speaking")
        if reply_text and not reply.get("spoken"):
            self._say(reply_text)
        else:
            self._wait_speech(timeout=120)
        self.hub.publish("voice.reply", text=reply_text, seconds=round(time.time() - started, 2))
        # IRIS a posé une question : on écoute la réponse tout de suite, sans mot d'activation
        if (
            self.settings.user.voice_followup
            and reply_text.rstrip().endswith("?")
            and depth < 4
            and not self._stop.is_set()
        ):
            self._followup_cycle(depth + 1)
            return
        if self._one_shot:
            if self.settings.user.voice_autostart:
                self._one_shot = False  # on reste en écoute continue du mot d'activation
            else:
                self._stop.set()

    def _est_arret(self, texte: str) -> bool:
        """La phrase entière est-elle un ordre d'arrêt ?

        La comparaison porte sur l'énoncé complet, et pas sur la présence d'un mot. « arrête »
        referme la fenêtre ; « arrête la musique » est une commande adressée à une application, et
        les confondre couperait la conversation au pire moment. Les formules de politesse en tête
        et en fin sont écartées : « ok arrête merci » reste un arrêt."""
        mots = [m for m in normalize(texte).split() if m not in POLITESSE]
        if not mots:
            return False
        dit = " ".join(mots)
        return any(dit == normalize(m) for m in (self.settings.user.stop_words or []) if m)

    def _fenetre_dialogue(self) -> None:
        """Après une réponse, IRIS reste ouverte un moment : on enchaîne sans redire son nom.

        Répéter le mot d'activation à chaque phrase, ce n'est pas une conversation, c'est une
        série de commandes. Pendant cette fenêtre on parle normalement ; chaque échange relance
        le compte ; « arrête » la referme aussitôt ; le silence la referme tout seul. Prononcer
        son nom rouvre une fenêtre, et le compte repart de zéro.

        IRIS continue d'écouter dans tous les cas — c'est le mot d'activation qui redevient
        nécessaire, pas le micro qui se coupe."""
        secondes = int(self.settings.user.voice_conversation_seconds or 0)
        if secondes <= 0 or self._one_shot or self._stop.is_set():
            return
        limite = time.time() + secondes
        self.hub.publish("voice.conversation", open=True, seconds=secondes)
        raison = "silence"
        try:
            while not self._stop.is_set() and time.time() < limite:
                self._set_state("command", conversation=True)
                self._drain()
                texte = self._listen_command()
                if self._stop.is_set():
                    raison = "arrêt"
                    return
                if not texte.strip():
                    continue  # rien dit : on laisse la fenêtre courir jusqu'à son terme
                found, reste = contains_wake(texte, self.settings.user.wake_word, aliases=list(self.settings.user.wake_aliases or []))
                if found:
                    texte = reste  # le nom redit pendant la fenêtre : on ne garde que la demande
                if self._est_arret(texte):
                    raison = "demandé"
                    return
                self._process(texte)
                limite = time.time() + secondes
        finally:
            self.hub.publish("voice.conversation", open=False, reason=raison)
            if not self._stop.is_set():
                self._set_state("wake")

    def _followup_cycle(self, depth: int) -> None:
        self._set_state("command", followup=True)
        self._drain()
        text = self._listen_command()
        found, rest = contains_wake(text, self.settings.user.wake_word, aliases=list(self.settings.user.wake_aliases or []))
        if found:
            text = rest  # l'utilisateur a répété le mot d'activation : on garde seulement la demande
        if text.strip():
            self._process(text, depth=depth)
        elif self._one_shot and not self.settings.user.voice_autostart:
            self._stop.set()

    # ------------------------------------------------------------------ utilitaires
    def _say(self, text: str, capture: list[bytes] | None = None) -> None:
        if self.tts.speak(text, force=True):
            self._wait_speech(timeout=60, capture=capture)
        elif capture is None:
            self._drain()

    def _capture_segment(self, max_seconds: float, wait_for_speech: float = 4.0) -> bytes:
        """Segmentation par énergie (VAD simple) pour le repli cloud : ne renvoie que la parole."""
        import numpy as np

        threshold = 400.0
        ambient: list[float] = []
        chunks: list[bytes] = []
        speaking = False
        silence_since = None
        started = time.time()
        while not self._stop.is_set() and not self._ptt.is_set():
            data = self._read()
            now = time.time()
            if data is None:
                if speaking and silence_since and now - silence_since > 0.8:
                    break
                if not speaking and now - started > wait_for_speech:
                    return b""
                continue
            rms = float(np.sqrt(np.mean(np.frombuffer(data, dtype=np.int16).astype(np.float32) ** 2)) or 0.0)
            if len(ambient) < 4:
                ambient.append(rms)
                threshold = max(300.0, 2.5 * (sum(ambient) / len(ambient)))
                continue
            if rms > threshold:
                if not speaking:
                    speaking = True
                chunks.append(data)
                silence_since = None
            elif speaking:
                chunks.append(data)
                silence_since = silence_since or now
                if now - silence_since > 0.8:
                    break
            elif now - started > wait_for_speech:
                return b""
            if speaking and now - started > max_seconds:
                break
        return b"".join(chunks) if len(chunks) > 2 else b""

    def _cloud_recognize(self, pcm: bytes) -> str:
        if not self.consent.is_granted("audio_raw") or self.settings.user.local_only:
            return ""
        try:
            text = stt.google_recognize(pcm, stt.SAMPLE_RATE, self.settings.user.language)
            self.consent.log("external_send", data_type="audio_raw", agent="google-stt", detail=f"{len(pcm) // 32} ms d'audio")
            return text
        except Exception as exc:
            log.warning("STT cloud en erreur: %s", exc)
            self.error = f"Reconnaissance cloud indisponible : {exc}"
            return ""
