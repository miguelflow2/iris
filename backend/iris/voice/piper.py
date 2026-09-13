"""Synthèse vocale française HORS-LIGNE via Piper (modèle ONNX local, aucun réseau, aucune clé).

C'est le pilier du « mode indépendant » d'IRIS : elle parle français même si tout le nuage est
coupé (Anthropic, ElevenLabs, OpenRouter tous fermés) et sans envoyer une seule syllabe dehors.

La voix par défaut est `fr_FR-siwis-medium` (22050 Hz, mono, int16). Ce module RÉUTILISE tout le
chemin de sortie audio déjà éprouvé pour ElevenLabs (routage vers le canal mains libres des
lunettes, rééchantillonnage quand le périphérique refuse la fréquence native) — voir
`classer_sorties` et `Reechantillonneur` dans elevenlabs.py. La seule différence est la SOURCE du
PCM : ici il naît localement (Piper), là il descend d'une socket HTTPS.

Import de piper et chargement du modèle : au dernier moment (le modèle pèse ~60 Mo en mémoire, on
ne le charge pas si Piper n'est jamais utilisé). Les tests remplacent sounddevice par un faux, comme
pour ElevenLabs."""
from __future__ import annotations

import logging
import queue
import sys
import threading
import time
from pathlib import Path

from ..config import Settings
from ..events import EventHub
from .elevenlabs import (
    PRECHAUFFAGE,
    VERROU_PORTAUDIO,
    Reechantillonneur,
    SortieAudioIndisponible,
    _score_hote,
    classer_sorties,
    micro_mains_libres,
)

log = logging.getLogger("iris.piper")

SAMPLE_RATE = 22050  # fr_FR-siwis-medium ; les autres voix Piper annoncent leur propre taux (lu à la synthèse)
DEFAULT_VOICE = "fr_FR-siwis-medium"


def _dossiers_voix() -> list[Path]:
    """Où chercher les modèles Piper : dans le bundle figé (PyInstaller) puis à côté du code (dev).

    En dev, piper.py est dans backend/iris/voice/ → les voix vivent dans backend/piper_voices/.
    Une fois figé, PyInstaller les dépose sous sys._MEIPASS/piper_voices (voir le .spec)."""
    dossiers: list[Path] = []
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        dossiers.append(Path(meipass) / "piper_voices")
    dossiers.append(Path(__file__).resolve().parents[2] / "piper_voices")
    return dossiers


def _espeak_data_dir() -> Path | None:
    """Dossier espeak-ng dans le bundle figé (piper/espeak-ng-data), sinon None (Piper le trouve seul).

    `collect_all("piper")` dépose les données sous piper/espeak-ng-data ; on gère aussi un dépôt à la
    racine du bundle au cas où le .spec les y placerait."""
    meipass = getattr(sys, "_MEIPASS", None)
    if not meipass:
        return None
    for cand in (Path(meipass) / "piper" / "espeak-ng-data", Path(meipass) / "espeak-ng-data"):
        if cand.is_dir():
            return cand
    return None


def trouver_modele(nom: str) -> Path | None:
    """Chemin du fichier .onnx pour la voix `nom` (avec ou sans l'extension), sinon None.

    Exige que le .onnx ET son .onnx.json soient présents : Piper a besoin des deux (le JSON porte
    le taux d'échantillonnage, la config de phonèmes espeak-ng, l'inventaire des locuteurs)."""
    nom = (nom or DEFAULT_VOICE).strip()
    if nom.endswith(".onnx"):
        nom = nom[: -len(".onnx")]
    for dossier in _dossiers_voix():
        onnx = dossier / f"{nom}.onnx"
        if onnx.is_file() and onnx.with_suffix(".onnx.json").is_file():
            return onnx
    return None


class PiperSpeaker:
    """Même interface publique que ElevenLabsSpeaker (speak/stop/wait_idle/prechauffer/shutdown/
    status/available), pour que TextToSpeech puisse choisir l'un ou l'autre sans rien savoir de
    plus. `fallback_speak` est branché par TextToSpeech : si la synthèse locale échoue, la voix
    Windows reprend la phrase — jamais muette."""

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
        self._voice = None  # PiperVoice chargé (paresseux)
        self._voice_nom = ""  # nom du modèle actuellement chargé (recharge si le réglage change)
        self._voice_rate = SAMPLE_RATE  # taux réel du modèle chargé
        self._disabled = False  # chargement définitivement impossible (modèle absent, piper non installé)
        self.fallback_speak = None  # branché par TextToSpeech
        # routage de la sortie : on n'avertit qu'une fois, comme ElevenLabsSpeaker
        self._sortie_avertie = ""
        self._sortie_annoncee: tuple = ()

    # ------------------------------------------------------------------ état
    @property
    def configured(self) -> bool:
        """Vrai si le modèle demandé est présent sur le disque (indépendant de piper installé)."""
        return trouver_modele(self.settings.user.piper_voice) is not None

    @property
    def available(self) -> bool:
        return self.configured and not self._disabled

    def status(self) -> dict:
        return {
            "configured": self.configured,
            "available": self.available,
            "error": self.error,
            "voice": self.settings.user.piper_voice or DEFAULT_VOICE,
            "sample_rate": self._voice_rate,
            "speaking": self.speaking,
            "offline": True,
        }

    # ------------------------------------------------------------------ chargement du modèle
    def _charger(self):
        """Charge (une fois) le PiperVoice pour la voix des réglages ; le recharge si elle change."""
        nom = (self.settings.user.piper_voice or DEFAULT_VOICE).strip()
        if self._voice is not None and self._voice_nom == nom:
            return self._voice
        modele = trouver_modele(nom)
        if modele is None:
            self._disabled = True
            raise SortieAudioIndisponible(
                f"voix Piper « {nom} » introuvable (fichiers .onnx/.onnx.json absents de piper_voices/)"
            )
        # espeak-ng : Piper le résout par défaut à côté de son package (piper/espeak-ng-data), ce qui
        # marche en dev. Dans le bundle figé, le __file__ d'un module empaqueté ne pointe pas toujours
        # à côté de ses données : on passe donc le chemin EXPLICITEMENT à load() quand on le trouve.
        from piper import PiperVoice

        espeak_dir = _espeak_data_dir()
        debut = time.time()
        voix = (
            PiperVoice.load(str(modele), espeak_data_dir=espeak_dir)
            if espeak_dir is not None
            else PiperVoice.load(str(modele))
        )
        self._voice = voix
        self._voice_nom = nom
        # Le taux réel du modèle (config.sample_rate), avec repli sur la valeur par défaut.
        taux = getattr(getattr(voix, "config", None), "sample_rate", None)
        self._voice_rate = int(taux) if taux else SAMPLE_RATE
        log.info("voix Piper « %s » chargée en %.2f s (%d Hz)", nom, time.time() - debut, self._voice_rate)
        return voix

    # ------------------------------------------------------------------ file d'attente / thread
    def _ensure_thread(self) -> None:
        with self._lock:
            if self._thread is None or not self._thread.is_alive():
                self._thread = threading.Thread(target=self._worker, name="iris-piper", daemon=True)
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

    def prechauffer(self) -> None:
        """Ouvre la sortie (lunettes) une fois, en silence, avant la première phrase — et en profite
        pour charger le modèle, pour que le premier « Dis-moi Iris » ne paie ni le basculement du
        casque ni les ~5 s de chargement du modèle ONNX."""
        if not self.available:
            return
        self._ensure_thread()
        self._queue.put(PRECHAUFFAGE)

    def _prechauffer_maintenant(self) -> None:
        try:
            self._charger()  # ~5 s la première fois : payé ici, en silence, pas devant la salle — et
            #                  HORS verrou, car charger le modèle ONNX ne touche pas PortAudio.
            # Le reste sous VERROU_PORTAUDIO : le préchauffage ne pose pas l'état « en train de parler »,
            # c'est donc ce verrou qui empêche le fil du micro de fermer PortAudio pendant que ce flux de
            # sortie est ouvert (sinon Pa_Terminate le fermerait d'autorité et corromprait le tas natif).
            with VERROU_PORTAUDIO:
                sd = self._sounddevice()
                debut = time.time()
                device, taux = self._output_device(sd)
                flux, taux = self._ouvrir_sortie(sd, device, taux)
                with flux as out:
                    out.write(bytes(2 * max(1, taux // 10)))  # 100 ms de silence (int16 mono)
                log.info("sortie Piper préchauffée en %.2f s (%s)", time.time() - debut,
                         f"sortie {device} à {taux} Hz" if device is not None else "sortie par défaut")
        except Exception as exc:
            log.debug("préchauffage Piper impossible : %s", exc)

    def _worker(self) -> None:
        while True:
            item = self._queue.get()
            if item is None:
                break
            if item is PRECHAUFFAGE:
                self._prechauffer_maintenant()
                continue
            self._stop_flag.clear()
            self.speaking = True
            self.hub.publish("tts.state", speaking=True, text=item[:200], engine="piper")
            try:
                self._stream_and_play(item)
            except Exception as exc:
                self._handle_failure(exc, item)
            finally:
                self.speaking = False
                if self._queue.empty():
                    self._idle.set()
                self.hub.publish("tts.state", speaking=False, engine="piper")

    def _handle_failure(self, exc: Exception, text: str) -> None:
        self.error = f"Piper : {exc}"
        log.warning(self.error)
        try:
            self.hub.publish("tts.fallback", reason=self.error)
        except Exception:
            pass
        fallback = self.fallback_speak
        if not fallback:
            log.warning("aucune voix de repli branchée : la phrase Piper est perdue")
            return
        try:
            if fallback(text) is False:
                log.warning("la voix Windows n'a pas pu reprendre la phrase Piper : phrase perdue")
        except Exception as exc2:
            log.warning("repli Windows après échec Piper impossible : %s", exc2)

    # ------------------------------------------------------------------ sortie audio (repris d'ElevenLabs)
    @staticmethod
    def _sounddevice():
        import sounddevice as sd

        return sd

    def _signaler_sortie(self, voulu: str, raison: str) -> None:
        cle = f"{voulu}|{raison}"
        if self._sortie_avertie == cle:
            return
        self._sortie_avertie = cle
        self._sortie_annoncee = ()
        msg = f"Sortie audio « {voulu} » {raison} : Piper parle par la sortie par défaut de Windows."
        log.warning(msg)
        try:
            self.hub.publish("tts.fallback", reason=msg)
        except Exception:
            pass

    def _annoncer_sortie(self, idx: int, nom: str, taux: int) -> None:
        self._sortie_avertie = ""
        if self._sortie_annoncee == (idx, taux):
            return
        self._sortie_annoncee = (idx, taux)
        if taux == self._voice_rate:
            log.info("voix Piper dirigée vers la sortie %s (%s) à %d Hz", idx, nom, taux)
        else:
            log.info("voix Piper dirigée vers la sortie %s (%s) à %d Hz (rééchantillonnée depuis %d Hz)",
                     idx, nom, taux, self._voice_rate)

    def _output_device(self, sd) -> tuple[int | None, int]:
        """(index, fréquence d'ouverture) de la sortie choisie ; (None, taux du modèle) = sortie par défaut.

        Même logique que ElevenLabsSpeaker._output_device, à ceci près que le taux « idéal » est
        celui du modèle Piper chargé (`self._voice_rate`), pas le 24 kHz d'ElevenLabs. Le routage
        (canal mains libres des lunettes) et le repli suivent `classer_sorties`, la règle partagée."""
        ideal = self._voice_rate
        voulu = (self.settings.user.audio_output_device or "").strip().lower()
        if not voulu:
            return None, ideal
        try:
            apis = sd.query_hostapis()
            devices = list(sd.query_devices())
        except Exception as exc:
            self._signaler_sortie(voulu, f"inaccessible (énumération des sorties impossible : {exc})")
            return None, ideal
        noms: list[str] = []
        scores: list[int] = []
        index: list[int] = []
        for idx, dev in enumerate(devices):
            try:
                voies = int(dev.get("max_output_channels", 0) or 0)
            except (TypeError, ValueError):
                voies = 0
            if voies <= 0:
                continue
            try:
                hote = apis[int(dev.get("hostapi", -1))].get("name") or ""
            except Exception:
                hote = ""
            noms.append(dev.get("name") or "")
            scores.append(_score_hote(hote))
            index.append(idx)
        ordre = classer_sorties(noms, voulu, micro_mains_libres(self.settings), scores)
        if not ordre:
            self._signaler_sortie(voulu, "introuvable — lunettes éteintes ou hors de portée")
            return None, ideal
        refus = []
        for position in ordre:
            idx = index[position]
            try:
                natif = int(float(devices[idx].get("default_samplerate") or 0))
            except (TypeError, ValueError):
                natif = 0
            essayes: list[int] = []
            for taux in (ideal, natif):
                if taux <= 0 or taux in essayes:
                    continue
                essayes.append(taux)
                try:
                    sd.check_output_settings(device=idx, samplerate=taux, channels=1, dtype="int16")
                except Exception:
                    continue
                self._annoncer_sortie(idx, noms[position], taux)
                return idx, taux
            refus.append(f"{noms[position]} (index {idx}, ni {ideal} ni {natif} Hz)")
        self._signaler_sortie(voulu, "refuse toutes les fréquences essayées (" + "; ".join(refus) + ")")
        return None, ideal

    def _ouvrir_sortie(self, sd, device: int | None, taux: int) -> tuple:
        """Flux de sortie sur `device` au taux `taux`, sinon sur la sortie par défaut au taux du modèle."""
        if device is not None:
            try:
                flux = sd.RawOutputStream(samplerate=taux, channels=1, dtype="int16", blocksize=max(1, taux // 10), device=device)
                return flux, taux
            except Exception as exc:
                log.warning("sortie audio %s refusée à l'ouverture (%s) : sortie par défaut utilisée", device, exc)
                self._sortie_annoncee = ()
        try:
            flux = sd.RawOutputStream(samplerate=self._voice_rate, channels=1, dtype="int16", blocksize=max(1, self._voice_rate // 10))
            return flux, self._voice_rate
        except Exception as exc:
            raise SortieAudioIndisponible(f"aucune sortie audio ne s'ouvre, pas même celle par défaut ({exc})") from exc

    def _stream_and_play(self, text: str) -> None:
        sd = self._sounddevice()
        voice = self._charger()  # hors verrou : le modèle ONNX ne touche pas PortAudio
        # Choix du périphérique et flux ouvert sous VERROU_PORTAUDIO : tant que ce flux de sortie est
        # ouvert, le fil du micro ne doit pas fermer PortAudio pour ré-énumérer (Pa_Terminate le
        # fermerait d'autorité, corruption du tas). Voir VERROU_PORTAUDIO dans elevenlabs.py.
        with VERROU_PORTAUDIO:
            device, taux = self._output_device(sd)
            out_stream, taux = self._ouvrir_sortie(sd, device, taux)
            convertisseur = Reechantillonneur(self._voice_rate, taux)
            started = time.time()
            first = True
            with out_stream as out:
                for chunk in voice.synthesize(text):
                    if self._stop_flag.is_set():
                        break
                    data = getattr(chunk, "audio_int16_bytes", None)
                    if not data:
                        continue
                    if first:
                        log.info("Piper : premier audio après %.2f s", time.time() - started)
                        first = False
                    pret = convertisseur.convertir(data)
                    if pret:  # le convertisseur peut retenir un morceau trop court pour interpoler
                        out.write(pret)

    def shutdown(self) -> None:
        self.stop()
        if self._thread and self._thread.is_alive():
            self._queue.put(None)
