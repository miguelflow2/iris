"""Synthèse vocale ElevenLabs en streaming : audio PCM joué dès les premiers octets reçus.
La clé API vient exclusivement de l'environnement / du fichier .env (jamais du code)."""
from __future__ import annotations

import logging
import os
import queue
import threading
import time

from ..config import Settings
from ..events import EventHub

log = logging.getLogger("iris.elevenlabs")

API_BASE = "https://api.elevenlabs.io/v1"
SAMPLE_RATE = 24000  # output_format=pcm_24000
DEFAULT_VOICE_ID = "EXAVITQu4vr4xnSDxMaL"  # Sarah — voix premade vérifiée français (utilisable au palier gratuit)
FREE_FALLBACK_VOICE_ID = DEFAULT_VOICE_ID
# Voix française native (bibliothèque ElevenLabs, ajoutée au compte) : utilisable seulement avec un forfait payant (Starter et plus)
FRENCH_LIBRARY_VOICE_ID = "FvmvwvObRqIHojkEGh5N"  # Adina — jeune femme francophone, claire et accueillante
DEFAULT_MODEL = "eleven_turbo_v2_5"
MODELS = [
    {"id": "eleven_flash_v2_5", "label": "Flash v2.5 — le plus rapide (accent moins naturel)"},
    {"id": "eleven_turbo_v2_5", "label": "Turbo v2.5 — rapide, meilleure prononciation du français (recommandé)"},
    {"id": "eleven_multilingual_v2", "label": "Multilingual v2 — qualité maximale, plus lent"},
    {"id": "eleven_v3", "label": "v3 — expressif (alpha)"},
]
RETRY_AFTER_FAILURE = 120  # s : après une erreur, on repasse sur Windows puis on réessaie (chien de garde)
QUOTA_THRESHOLDS = (0.8, 0.95, 1.0)  # alertes proactives sur le quota mensuel
QUOTA_CHECK_EVERY = 8  # phrases lues entre deux vérifications du quota


def api_key() -> str:
    return (os.environ.get("ELEVENLABS_API_KEY") or "").strip()


class ElevenLabsSpeaker:
    def __init__(self, settings: Settings, hub: EventHub):
        self.settings = settings
        self.hub = hub
        self._queue: "queue.Queue[str | None]" = queue.Queue()
        self._idle = threading.Event()
        self._idle.set()
        self._stop_flag = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self.speaking = False
        self.error: str | None = None
        self._disabled_until = 0.0
        self._voices_cache: list[dict] = []
        self._session = None
        self._plays_since_check = 0
        self._alerted: set[float] = set()
        self.quota: dict = {}

    # ------------------------------------------------------------------ état
    @property
    def configured(self) -> bool:
        return bool(api_key())

    @property
    def available(self) -> bool:
        return self.configured and time.time() >= self._disabled_until

    def status(self) -> dict:
        u = self.settings.user
        return {
            "configured": self.configured,
            "available": self.available,
            "error": self.error,
            "voice_id": u.elevenlabs_voice_id or DEFAULT_VOICE_ID,
            "model": u.elevenlabs_model or DEFAULT_MODEL,
            "models": MODELS,
            "speaking": self.speaking,
        }

    def _http(self):
        import requests

        if self._session is None:
            self._session = requests.Session()
        return self._session

    def _headers(self) -> dict:
        return {"xi-api-key": api_key(), "Accept": "audio/pcm"}

    # ------------------------------------------------------------------ API
    def voices(self, refresh: bool = False) -> list[dict]:
        if self._voices_cache and not refresh:
            return self._voices_cache
        if not self.configured:
            return []
        try:
            resp = self._http().get(f"{API_BASE}/voices", headers=self._headers(), timeout=20)
            resp.raise_for_status()
            out = []
            for v in resp.json().get("voices", []):
                labels = v.get("labels") or {}
                langs = sorted({x.get("language") for x in (v.get("verified_languages") or []) if x.get("language")})
                out.append(
                    {
                        "voice_id": v["voice_id"],
                        "name": v.get("name", ""),
                        "category": v.get("category", ""),
                        "accent": labels.get("accent", ""),
                        "gender": labels.get("gender", ""),
                        "languages": langs,
                        "french": "fr" in langs or "fr" in (labels.get("language") or "").lower(),
                        # les voix de bibliothèque (professional/generated/cloned) exigent un abonnement payant via l'API
                        "paid_only": v.get("category", "") not in ("premade", ""),
                    }
                )
            out.sort(key=lambda v: (v["paid_only"], not v["french"], v["name"].lower()))
            self._voices_cache = out
            return out
        except Exception as exc:
            self.error = f"Liste des voix ElevenLabs indisponible : {exc}"
            log.warning(self.error)
            return []

    def prewarm(self) -> None:
        """Ouvre la connexion HTTPS à l'avance (poignée de main TLS) pour raccourcir le premier son."""
        if not self.configured:
            return
        try:
            self._http().get(f"{API_BASE}/user", headers=self._headers(), timeout=10)
        except Exception as exc:
            log.debug("pré-connexion ElevenLabs: %s", exc)

    def subscription(self) -> dict:
        if not self.configured:
            return {}
        try:
            resp = self._http().get(f"{API_BASE}/user/subscription", headers=self._headers(), timeout=15)
            resp.raise_for_status()
            d = resp.json()
            return {"tier": d.get("tier"), "used": d.get("character_count"), "limit": d.get("character_limit")}
        except Exception as exc:
            return {"error": str(exc)}

    def check_quota(self) -> dict:
        """Lit le quota mensuel et prévient l'utilisateur à 80 %, 95 % et 100 % (une fois par seuil)."""
        sub = self.subscription()
        if not sub or sub.get("error") or not sub.get("limit"):
            return sub
        self.quota = sub
        self._auto_french_voice(sub)
        ratio = float(sub.get("used") or 0) / float(sub["limit"])
        for threshold in QUOTA_THRESHOLDS:
            if ratio >= threshold and threshold not in self._alerted:
                self._alerted.add(threshold)
                remaining = int(sub["limit"]) - int(sub.get("used") or 0)
                message = (
                    f"Quota ElevenLabs épuisé ({sub['limit']} caractères ce mois-ci) : IRIS parle avec la voix Windows jusqu'au renouvellement."
                    if threshold >= 1.0
                    else f"Quota ElevenLabs à {int(ratio * 100)} % : il reste environ {remaining} caractères ce mois-ci."
                )
                self.hub.publish("tts.quota", ratio=round(ratio, 3), used=sub.get("used"), limit=sub["limit"], message=message, level="error" if threshold >= 1.0 else "warn")
        return sub

    def _auto_french_voice(self, sub: dict) -> None:
        """Dès qu'un forfait payant est actif, bascule de la voix par défaut (anglophone) vers une voix française native."""
        tier = str(sub.get("tier") or "").lower()
        u = self.settings.user
        if tier in ("", "free") or (u.elevenlabs_voice_id and u.elevenlabs_voice_id != DEFAULT_VOICE_ID):
            return
        try:
            self.settings.update({"elevenlabs_voice_id": FRENCH_LIBRARY_VOICE_ID})
            self.hub.publish("tts.fallback", message="Forfait ElevenLabs actif : IRIS utilise maintenant la voix française native « Adina ». Vous pouvez en choisir une autre dans Paramètres › Voix.", level="info")
            log.info("voix française native activée (forfait %s)", tier)
        except Exception as exc:
            log.debug("bascule voix française : %s", exc)

    def retry_if_disabled(self) -> bool:
        """Chien de garde : si ElevenLabs a été mis de côté après une erreur, on vérifie s'il est de nouveau utilisable."""
        if not self.configured or self.available:
            return self.available
        sub = self.subscription()
        if sub and not sub.get("error"):
            if sub.get("limit") and (sub.get("used") or 0) >= sub["limit"]:
                return False  # quota réellement épuisé
            self._disabled_until = 0.0
            self.error = None
            self.hub.publish("tts.state", speaking=False, engine="elevenlabs", restored=True)
            log.info("ElevenLabs de nouveau disponible")
            return True
        return False

    # ------------------------------------------------------------------ lecture
    def _ensure_thread(self) -> None:
        with self._lock:
            if self._thread is None or not self._thread.is_alive():
                self._thread = threading.Thread(target=self._worker, name="iris-elevenlabs", daemon=True)
                self._thread.start()

    def speak(self, text: str) -> bool:
        text = (text or "").strip()
        if not text or not self.available:
            return False
        self._ensure_thread()
        self._idle.clear()
        self._queue.put(text)
        return True

    def stop(self) -> None:
        self._stop_flag.set()
        try:
            while True:
                self._queue.get_nowait()
        except queue.Empty:
            pass
        if not self.speaking:
            self._idle.set()

    def wait_idle(self, timeout: float = 60.0) -> bool:
        return self._idle.wait(timeout)

    def _worker(self) -> None:
        while True:
            item = self._queue.get()
            if item is None:
                break
            self._stop_flag.clear()
            self.speaking = True
            self.hub.publish("tts.state", speaking=True, text=item[:200], engine="elevenlabs")
            try:
                self._stream_and_play(item)
                self._plays_since_check += 1
                if self._plays_since_check >= QUOTA_CHECK_EVERY or not self.quota:
                    self._plays_since_check = 0
                    self.check_quota()
            except Exception as exc:
                self._handle_failure(exc, item)
            finally:
                self.speaking = False
                if self._queue.empty():
                    self._idle.set()
                self.hub.publish("tts.state", speaking=False, engine="elevenlabs")

    def _handle_failure(self, exc: Exception, text: str) -> None:
        status = getattr(getattr(exc, "response", None), "status_code", None)
        body = ""
        try:
            body = getattr(exc, "response").text or ""
        except Exception:
            pass
        if status == 402 and "paid_plan_required" in body and (self.settings.user.elevenlabs_voice_id or DEFAULT_VOICE_ID) != FREE_FALLBACK_VOICE_ID:
            # voix de bibliothèque refusée au palier gratuit : on passe sur une voix gratuite et on rejoue la phrase
            self.settings.update({"elevenlabs_voice_id": FREE_FALLBACK_VOICE_ID})
            self.error = "Cette voix ElevenLabs exige un abonnement payant : IRIS utilise la voix gratuite « Sarah » (français)."
            log.warning(self.error)
            self.hub.publish("tts.fallback", reason=self.error)
            self.hub.publish("settings.updated", settings=self.settings.user.model_dump())
            try:
                self._stream_and_play(text)
                return
            except Exception as exc2:
                exc = exc2
                status = getattr(getattr(exc, "response", None), "status_code", None)
        if status in (401, 402, 429) or "quota" in str(exc).lower():
            self._disabled_until = time.time() + RETRY_AFTER_FAILURE
            self.error = (
                "ElevenLabs indisponible (clé invalide ou quota mensuel épuisé) : voix Windows utilisée pendant 10 minutes."
                if status != 429
                else "ElevenLabs : limite de débit atteinte, voix Windows utilisée pendant 10 minutes."
            )
        else:
            self.error = f"ElevenLabs : {exc}"
        log.warning(self.error)
        self.hub.publish("tts.fallback", reason=self.error)
        # on ne perd pas la phrase : repli immédiat sur la voix Windows
        fallback = getattr(self, "fallback_speak", None)
        if fallback:
            try:
                fallback(text)
            except Exception:
                pass

    def _output_device(self, sd):
        """Index de la sortie audio choisie (ex. lunettes), sinon None = défaut.
        Préfère MME/DirectSound (rééchantillonnage automatique) à WASAPI (fréquence imposée), et vérifie
        que le périphérique accepte le flux PCM 24 kHz avant de l'utiliser."""
        wanted = (self.settings.user.audio_output_device or "").strip().lower()
        if not wanted:
            return None
        try:
            apis = sd.query_hostapis()
            candidates = []
            for idx, dev in enumerate(sd.query_devices()):
                if dev.get("max_output_channels", 0) > 0 and wanted in dev["name"].lower():
                    api = apis[dev["hostapi"]]["name"]
                    score = 3 if api == "MME" else (2 if "DirectSound" in api else (1 if "WASAPI" in api else 0))
                    candidates.append((score, idx))
            for _score, idx in sorted(candidates, reverse=True):
                try:
                    sd.check_output_settings(device=idx, samplerate=SAMPLE_RATE, channels=1, dtype="int16")
                    return idx
                except Exception:
                    continue
        except Exception:
            pass
        log.warning("sortie audio « %s » introuvable ou incompatible 24 kHz, sortie par défaut utilisée", wanted)
        return None

    def _stream_and_play(self, text: str) -> None:
        import sounddevice as sd

        u = self.settings.user
        voice_id = u.elevenlabs_voice_id or DEFAULT_VOICE_ID
        model = u.elevenlabs_model or DEFAULT_MODEL
        url = f"{API_BASE}/text-to-speech/{voice_id}/stream?output_format=pcm_{SAMPLE_RATE}&optimize_streaming_latency=3"
        body = {
            "text": text,
            "model_id": model,
            "voice_settings": {"stability": 0.55, "similarity_boost": 0.8, "style": 0.0, "use_speaker_boost": True},
        }
        if model in ("eleven_flash_v2_5", "eleven_turbo_v2_5"):
            body["language_code"] = (u.language or "fr")[:2]
        started = time.time()
        resp = self._http().post(url, headers={**self._headers(), "Content-Type": "application/json"}, json=body, stream=True, timeout=(10, 60))
        if resp.status_code >= 400:
            detail = resp.text[:200]
            err = RuntimeError(f"HTTP {resp.status_code} {detail}")
            err.response = resp  # type: ignore[attr-defined]
            raise err
        first = True
        pending = b""
        device = self._output_device(sd)
        try:
            out_stream = sd.RawOutputStream(samplerate=SAMPLE_RATE, channels=1, dtype="int16", blocksize=2400, device=device)
        except Exception as exc:
            if device is None:
                raise
            log.warning("sortie audio %s refusée (%s) : sortie par défaut", device, exc)
            out_stream = sd.RawOutputStream(samplerate=SAMPLE_RATE, channels=1, dtype="int16", blocksize=2400)
        with out_stream as out:
            for chunk in resp.iter_content(chunk_size=4800):
                if self._stop_flag.is_set():
                    break
                if not chunk:
                    continue
                if first:
                    log.info("ElevenLabs : premier audio après %.2f s", time.time() - started)
                    first = False
                pending += chunk
                usable = len(pending) - (len(pending) % 2)  # int16 : nombre pair d'octets
                if usable:
                    out.write(pending[:usable])
                    pending = pending[usable:]
        resp.close()

    def shutdown(self) -> None:
        self.stop()
        if self._thread and self._thread.is_alive():
            self._queue.put(None)
