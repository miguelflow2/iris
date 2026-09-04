"""Reconnaissance vocale : Vosk (hors-ligne, sur l'appareil) en priorité, Google (cloud) en repli avec consentement."""
from __future__ import annotations

import json
import logging
import shutil
import zipfile
from pathlib import Path
from typing import Callable

log = logging.getLogger("iris.stt")

SAMPLE_RATE = 16000

VOSK_MODELS = {
    "fr": {
        "name": "vosk-model-small-fr-0.22",
        "url": "https://alphacephei.com/vosk/models/vosk-model-small-fr-0.22.zip",
        "size_mb": 41,
        "label": "Français (petit modèle, 41 Mo)",
    },
    "en": {
        "name": "vosk-model-small-en-us-0.15",
        "url": "https://alphacephei.com/vosk/models/vosk-model-small-en-us-0.15.zip",
        "size_mb": 40,
        "label": "English (small model, 40 MB)",
    },
}


def lang_key(language: str) -> str:
    return "en" if (language or "fr").lower().startswith("en") else "fr"


def model_dir(models_dir: Path, language: str) -> Path | None:
    info = VOSK_MODELS[lang_key(language)]
    path = models_dir / info["name"]
    if path.is_dir() and any((path / sub).exists() for sub in ("am", "conf", "graph")):
        return path
    return None


def download_model(models_dir: Path, language: str, progress: Callable[[int, int], None] | None = None) -> Path:
    """Télécharge et décompresse le modèle Vosk (bloquant, à lancer dans un thread)."""
    import requests

    info = VOSK_MODELS[lang_key(language)]
    models_dir.mkdir(parents=True, exist_ok=True)
    zip_path = models_dir / (info["name"] + ".zip")
    with requests.get(info["url"], stream=True, timeout=60) as resp:
        resp.raise_for_status()
        total = int(resp.headers.get("content-length") or 0)
        done = 0
        with open(zip_path, "wb") as fh:
            for chunk in resp.iter_content(chunk_size=1 << 16):
                if chunk:
                    fh.write(chunk)
                    done += len(chunk)
                    if progress:
                        progress(done, total)
    target = models_dir / info["name"]
    if target.exists():
        shutil.rmtree(target, ignore_errors=True)
    with zipfile.ZipFile(zip_path) as zf:
        zf.extractall(models_dir)
    zip_path.unlink(missing_ok=True)
    if not target.exists():  # archive avec un autre nom de racine
        candidates = [p for p in models_dir.iterdir() if p.is_dir() and p.name.startswith("vosk-model")]
        if candidates:
            candidates[0].rename(target)
    return target


class VoskEngine:
    """Enveloppe du modèle Vosk : crée des reconnaisseurs (avec ou sans grammaire)."""

    def __init__(self, path: Path, sample_rate: int = SAMPLE_RATE):
        from vosk import Model, SetLogLevel

        SetLogLevel(-1)
        self.sample_rate = sample_rate
        self.model = Model(str(path))

    def recognizer(self, grammar: list[str] | None = None, words: bool = False):
        """Reconnaisseur Vosk. Avec `grammar`, le décodage est restreint à ces phrases (plus « [unk] ») :
        mesuré sur le petit modèle français, le plein vocabulaire perdait « Dis-moi Iris » (→ « dis-moi »)
        et « Iris » (→ « arès ») en 2 à 4 s, là où la grammaire les reconnaît sans erreur en 0,05 s.
        `words=True` ajoute les horodatages de chaque mot (pour rejouer la fin d'une phrase)."""
        from vosk import KaldiRecognizer

        phrases = [p for p in dict.fromkeys(grammar or []) if p]
        if phrases:
            rec = KaldiRecognizer(self.model, self.sample_rate, json.dumps(phrases + ["[unk]"]))
        else:
            rec = KaldiRecognizer(self.model, self.sample_rate)
        rec.SetWords(words)
        return rec

    @staticmethod
    def text_of(result_json: str, key: str = "text") -> str:
        try:
            return (json.loads(result_json).get(key) or "").strip()
        except Exception:
            return ""


def google_recognize(pcm: bytes, sample_rate: int, language: str) -> str:
    """STT cloud (Google Web Speech via SpeechRecognition). Ne l'appeler qu'avec le consentement audio_raw."""
    import speech_recognition as sr

    recognizer = sr.Recognizer()
    audio = sr.AudioData(pcm, sample_rate, 2)
    try:
        return recognizer.recognize_google(audio, language=language or "fr-CA")
    except sr.UnknownValueError:
        return ""
