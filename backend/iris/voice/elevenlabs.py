"""Synthèse vocale ElevenLabs en streaming : audio PCM joué dès les premiers octets reçus.
La clé API vient exclusivement de l'environnement / du fichier .env (jamais du code).

Ce module porte aussi la règle de routage de la sortie audio (`classer_sorties`) que la voix
Windows (tts.py) partage : c'est ici que l'on décide par quel périphérique — les lunettes — la voix
sort, et à quelle fréquence (`Reechantillonneur` quand le périphérique refuse le 24 kHz)."""
from __future__ import annotations

import logging
import os
import queue
import threading
import time

from ..config import Settings
from ..events import EventHub
from .etirement import Etireur, est_identite, facteur_debit
from .rotation_cles import CODES_BASCULE, etiquette, pool_elevenlabs

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
# Plage acceptée par voice_settings.speed de l'API text-to-speech v1 (1,0 = vitesse normale).
# Au-delà, le reste du facteur demandé par tts_rate est appliqué localement (etirement.Etireur).
# Précision réelle de speed NON MESURÉE (aucun appel réseau depuis les tests) : la voix locale,
# elle, a été mesurée et son réglage natif ratait la cible de 7 à 40 % (voir piper.py). Si une mesure
# montre le même défaut ici, mettre VITESSE_API_MIN = VITESSE_API_MAX = 1.0 : tout le facteur
# passera alors par l'étirement local, dont la durée est exacte.
VITESSE_API_MIN = 0.7
VITESSE_API_MAX = 1.2


def repartir_vitesse(tts_rate: object) -> tuple[float, float]:
    """(speed envoyé au moteur, taux d'étirement local restant) pour le réglage tts_rate.

    185 → (1,0 ; 1,0) ; 277 → (1,2 ; 1,25) ; 370 → (1,2 ; 1,667) ; 555 → (1,2 ; 2,5) ; 90 → (0,7 ; 0,695).
    Le produit des deux vaut toujours le facteur demandé."""
    facteur = facteur_debit(tts_rate)
    vitesse = round(min(VITESSE_API_MAX, max(VITESSE_API_MIN, facteur)), 3)
    reste = facteur / vitesse
    return vitesse, (1.0 if est_identite(reste) else reste)

# Passe dans la file d'attente comme une phrase, mais n'en est pas une : elle ouvre le périphérique
# audio sans qu'on entende rien. Un objet, pas une chaîne : une chaîne finirait tôt ou tard
# prononcée à voix haute par un chemin qu'on aurait oublié. Partagée avec tts.py pour que les deux
# voix (ElevenLabs et Windows) préchauffent avec la même sentinelle.
PRECHAUFFAGE = object()

# Verrou qui SÉRIALISE tout accès à PortAudio entre les fils qui OUVRENT un flux de sortie (les voix
# ElevenLabs et Piper — y compris pendant le préchauffage) et le fil du micro qui FERME PortAudio
# pour ré-énumérer les périphériques (listener.rafraichir_peripheriques appelle Pa_Terminate puis
# Pa_Initialize).
#
# La course, observée en plantant IRIS quand les lunettes Bluetooth sont éteintes : `Pa_Terminate`
# ferme D'AUTORITÉ tout flux resté ouvert, y compris un flux ouvert depuis un AUTRE thread ; appelé
# pendant qu'un flux de sortie est ouvert, il libère sous les pieds de l'autre thread de la mémoire
# native encore utilisée → corruption du tas (0xc0000374). Le préchauffage (`_prechauffer_maintenant`)
# ouvre justement un flux de sortie SANS jamais poser l'état « en train de parler » : le garde-fou
# `tts.is_speaking` du listener ne voyait donc pas ce flux-là, et rien n'empêchait le fil du micro de
# fermer PortAudio pile pendant le préchauffage (lunettes éteintes → il cherche activement à
# ré-énumérer pour retrouver le micro des lunettes).
#
# Un `Lock` simple (non ré-entrant) : le speaker le tient tant qu'un flux lui est ouvert ; le listener
# l'acquiert SANS bloquer avant de fermer PortAudio et renonce à ré-énumérer s'il est pris (au lieu de
# stopper le fil vocal — il retentera). Le speaker ne prend jamais le verrou du listener, et le
# listener prend celui-ci en dernier : aucun cycle, donc aucun interblocage possible.
VERROU_PORTAUDIO = threading.Lock()

# Ce qui, dans le nom d'un périphérique Windows, signe le profil Bluetooth mains libres (HFP).
# Même liste que le listener (`_narrowband_input`) : un micro reconnu « mains libres » d'un côté
# doit l'être de l'autre, sinon les deux bouts de la voix ne parlent pas du même casque.
MARQUES_MAINS_LIBRES = ("hands-free", "mains libres", "hfp")


def api_key() -> str:
    """La clé ElevenLabs du moment. ELEVENLABS_API_KEY peut en contenir plusieurs (séparées par des
    virgules) : le pool alterne et bascule quand l'une est épuisée (voir rotation_cles)."""
    return pool_elevenlabs().courante()


# --------------------------------------------------------------------------- routage de la sortie
def est_mains_libres(nom: str) -> bool:
    """Le nom désigne-t-il le canal mains libres d'un casque Bluetooth ?"""
    bas = (nom or "").lower()
    return any(marque in bas for marque in MARQUES_MAINS_LIBRES)


def micro_mains_libres(settings: Settings) -> bool:
    """Le micro choisi dans les réglages est-il le canal mains libres des lunettes ?

    Le test est celui du NOM, comme dans le listener : c'est le seul qui ne mente pas (MME annonce
    44100 Hz pour un lien qui est réellement à 16000 Hz). Tant que ce micro est choisi, il faut
    supposer que le profil téléphone est actif et que Windows a mis la stéréo en veille."""
    return est_mains_libres(settings.user.audio_input_device or "")


def racine_lunettes(nom: str) -> str:
    """Ce que partagent les deux sorties d'un même casque, en minuscules.

    « Casque (M01 Pro_F444 Stereo) » et « Casque (M01 Pro_F444 Hands-Free AG Audio) » sont le MÊME
    casque vu par deux profils Bluetooth ; Windows ne les relie par rien d'autre que ce préfixe.
    C'est ce préfixe qu'on cherche quand il faut passer de l'un à l'autre."""
    bas = (nom or "").strip().lower()
    for suffixe in (" stereo", " hands-free", " mains libres"):
        coupe = bas.find(suffixe)
        if coupe > 0:
            return bas[:coupe]
    return bas


def classer_sorties(noms: list[str], voulu: str, mains_libres: bool, scores: list[int] | None = None) -> list[int]:
    """Positions, dans `noms`, des sorties qui conviennent — la meilleure d'abord, [] si aucune.

    Une seule règle pour les deux voix (SAPI dans tts.py, ElevenLabs ici), parce qu'elles se
    contredisaient : SAPI visait le canal mains libres, ElevenLabs visait « Stereo », et sur la
    configuration réelle de Miguel (micro « Hands-Free », sortie « Stereo ») la voix ElevenLabs
    partait vers un profil que Windows venait d'endormir — journal du 5 septembre 2026, quinze fois
    de suite « sortie audio … introuvable ou incompatible 24 kHz, sortie par défaut utilisée ».

    1. Une sortie convient si son nom contient `voulu` (correspondance partielle, comme pour le
       micro : MME tronque les noms à 31 caractères et c'est cette forme tronquée que l'interface
       enregistre).
    2. Quand le micro est en mains libres, le canal mains libres du MÊME casque convient aussi,
       même si le réglage nomme la sortie stéréo : le Bluetooth classique ne porte qu'un lien audio
       à la fois, et c'est le profil téléphone qui l'a pris.
    3. Entre plusieurs sorties qui conviennent, le mains libres l'emporte (il reste audible dans
       les deux états, au prix du 8 kHz mono — une voix moins belle vaut mieux qu'une voix
       inaudible), puis l'hôte le plus tolérant (`scores`, voir `_score_hote`), puis le premier vu.
    """
    voulu = (voulu or "").strip().lower()
    if not voulu:
        return []
    racine = racine_lunettes(voulu)
    classement = []
    for position, nom in enumerate(noms):
        bas = (nom or "").lower()
        mains_libres_ici = est_mains_libres(bas)
        if voulu in bas or (mains_libres and mains_libres_ici and racine in bas):
            score = scores[position] if scores else 0
            classement.append((mains_libres_ici, score, -position, position))
    return [candidat[-1] for candidat in sorted(classement, reverse=True)]


def _score_hote(nom_hote: str) -> int:
    """Confiance accordée à un hôte audio de Windows pour ouvrir une sortie (le plus grand gagne).

    Même ordre que le listener (`score_hote`) — dupliqué ici parce que listener.py importe tts.py
    qui importe ce module : MME et DirectSound passent par le moteur audio de Windows, qui
    rééchantillonne tout seul et partage le périphérique ; WASAPI impose la fréquence du pilote ;
    WDM-KS ouvre la broche du noyau, souvent déjà prise."""
    api = (nom_hote or "").lower()
    if "mme" in api:
        return 3
    if "directsound" in api:
        return 2
    if "wasapi" in api:
        return 1
    return 0


class SortieAudioIndisponible(RuntimeError):
    """Aucune sortie audio — ni celle demandée, ni celle par défaut — n'a pu être ouverte."""


class Reechantillonneur:
    """Ramène le PCM 24 kHz d'ElevenLabs au taux qu'accepte la sortie, morceau après morceau.

    Pourquoi : un périphérique Bluetooth ouvert par WASAPI impose la fréquence de son lien (16000 Hz
    en mains libres, 8000 Hz sur les casques plus anciens), et refuse le flux 24 kHz tel quel.
    Avant, ce refus faisait abandonner le périphérique demandé — la voix sortait du haut-parleur du
    PC pendant que Miguel portait ses lunettes. Ici on convertit, et le son sort DU périphérique
    demandé. numpy suffit, aucune dépendance à ajouter.

    Pourquoi un objet à état et pas `np.interp` sur chaque morceau isolément : les morceaux HTTP
    n'ont pas une taille garantie (la socket rend ce qu'elle a), et le point de lecture entre deux
    échantillons source doit se prolonger d'un morceau au suivant — sinon chaque frontière de
    morceau fait un petit saut, audible comme un crépitement, et le compte dérive."""

    def __init__(self, source: int, cible: int):
        import numpy as np

        self.source = int(source)
        self.cible = int(cible)
        self.pas = self.source / self.cible  # avancée, en échantillons source, par échantillon produit
        self._reste = np.zeros(0, dtype=np.float32)  # échantillons source pas encore consommés
        self._position = 0.0  # point de lecture du prochain échantillon produit, dans `_reste` + le morceau à venir
        self.entres = 0
        self.sortis = 0

    def convertir(self, data: bytes) -> bytes:
        """PCM int16 mono au taux source → PCM int16 mono au taux cible (peut rendre b"" si trop court)."""
        if self.source == self.cible:
            return data
        import numpy as np

        pcm = np.frombuffer(data, dtype="<i2").astype(np.float32)
        self.entres += len(pcm)
        tampon = np.concatenate((self._reste, pcm))
        dernier = len(tampon) - 1
        if dernier < self._position:  # pas encore de quoi interpoler : on garde tout pour la suite
            self._reste = tampon
            return b""
        nombre = int((dernier - self._position) // self.pas) + 1
        positions = self._position + self.pas * np.arange(nombre)
        sortie = np.interp(positions, np.arange(len(tampon)), tampon)
        suivante = self._position + self.pas * nombre
        consommes = min(int(suivante), len(tampon))
        self._reste = tampon[consommes:]
        self._position = suivante - consommes
        self.sortis += nombre
        return np.clip(np.rint(sortie), -32768, 32767).astype("<i2").tobytes()


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
        # routage de la sortie : on n'avertit qu'une fois par (nom, raison) et on n'annonce le
        # périphérique ouvert que quand il change — le journal du 5 septembre 2026 répétait le même
        # avertissement à chaque phrase, quinze fois, et plus personne ne le lisait
        self._sortie_avertie = ""
        self._sortie_annoncee: tuple = ()

    # ------------------------------------------------------------------ état
    @property
    def configured(self) -> bool:
        return bool(pool_elevenlabs())

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

    def _headers(self, cle: str | None = None) -> dict:
        return {"xi-api-key": cle if cle is not None else api_key(), "Accept": "audio/pcm"}

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

    def prechauffer(self) -> None:
        """Ouvre la sortie (lunettes) une fois, en silence, avant la première phrase.

        Sur la configuration réelle de Miguel c'est ElevenLabs qui parle, et ce chemin-là n'était
        jamais préchauffé : tts.prechauffer() sortait tôt dès que ElevenLabs répondait. Le
        basculement du casque en profil téléphone (jusqu'à 8 s, mesuré le 5 septembre 2026) tombait
        donc sur le tout premier « Dis-moi Iris ». La pré-connexion HTTPS (`prewarm`) ne suffit
        pas : elle raccourcit le premier octet, pas l'ouverture du périphérique."""
        if not self.available:
            return
        self._ensure_thread()
        self._queue.put(PRECHAUFFAGE)

    def _prechauffer_maintenant(self) -> None:
        """Ouvre la sortie choisie et y écrit un dixième de seconde de silence.

        sounddevice n'a pas de volume : le silence, ce sont des zéros. Le périphérique s'ouvre, le
        casque bascule s'il doit basculer, personne n'entend rien.

        Tout se passe sous VERROU_PORTAUDIO : le préchauffage ne pose pas l'état « en train de
        parler », donc c'est ce verrou — et non `is_speaking` — qui empêche le fil du micro de fermer
        PortAudio pendant que ce flux de sortie est ouvert (sinon : corruption du tas natif)."""
        try:
            with VERROU_PORTAUDIO:
                sd = self._sounddevice()
                debut = time.time()
                device, taux = self._output_device(sd)
                flux, taux = self._ouvrir_sortie(sd, device, taux)
                with flux as out:
                    out.write(bytes(2 * max(1, taux // 10)))  # int16 mono : 2 octets par échantillon, 100 ms
                log.info("sortie ElevenLabs préchauffée en %.2f s (%s)", time.time() - debut,
                         f"sortie {device} à {taux} Hz" if device is not None else "sortie par défaut")
        except Exception as exc:
            log.debug("préchauffage de la sortie ElevenLabs impossible : %s", exc)

    def _worker(self) -> None:
        while True:
            item = self._queue.get()
            if item is None:
                break
            if item is PRECHAUFFAGE:
                # Ni état « en train de parler », ni événement : rien ne se passe pour l'utilisateur.
                self._prechauffer_maintenant()
                continue
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
        self._reprendre_avec_windows(text)

    def _reprendre_avec_windows(self, text: str) -> None:
        """On ne perd pas la phrase : repli immédiat sur la voix Windows, et le journal le dit.

        Jamais muette. Avant, l'échec du repli lui-même était avalé (`except Exception: pass`) :
        IRIS pouvait se taire sans qu'aucune ligne ne l'explique."""
        fallback = getattr(self, "fallback_speak", None)
        if not fallback:
            log.warning("aucune voix de repli branchée : la phrase est perdue")
            return
        try:
            if fallback(text) is False:
                log.warning("la voix Windows n'a pas pu reprendre la phrase (synthèse Windows indisponible) : phrase perdue")
            else:
                log.info("la voix Windows prend le relais pour cette phrase")
        except Exception as exc:
            log.warning("la voix Windows n'a pas pu reprendre la phrase : %s", exc)

    @staticmethod
    def _sounddevice():
        """Le module sounddevice, importé au dernier moment (les tests le remplacent par un faux)."""
        import sounddevice as sd

        return sd

    def _signaler_sortie(self, voulu: str, raison: str) -> None:
        """Dit une fois pourquoi la sortie demandée n'est pas utilisée, dans le journal et à l'écran."""
        cle = f"{voulu}|{raison}"
        if self._sortie_avertie == cle:
            return
        self._sortie_avertie = cle
        self._sortie_annoncee = ()
        msg = f"Sortie audio « {voulu} » {raison} : IRIS parle par la sortie par défaut de Windows."
        log.warning(msg)
        try:
            self.hub.publish("tts.fallback", reason=msg)
        except Exception:
            pass

    def _annoncer_sortie(self, idx: int, nom: str, taux: int) -> None:
        """Journalise la sortie retenue, seulement quand elle change."""
        self._sortie_avertie = ""  # retrouvée : une disparition ultérieure devra être redite
        if self._sortie_annoncee == (idx, taux):
            return
        self._sortie_annoncee = (idx, taux)
        if taux == SAMPLE_RATE:
            log.info("voix ElevenLabs dirigée vers la sortie %s (%s) à %d Hz", idx, nom, taux)
        else:
            log.info("voix ElevenLabs dirigée vers la sortie %s (%s) à %d Hz (rééchantillonnée depuis %d Hz)", idx, nom, taux, SAMPLE_RATE)

    def _output_device(self, sd) -> tuple[int | None, int]:
        """(index, fréquence d'ouverture) de la sortie choisie ; (None, 24000) = sortie par défaut.

        Trois choses ont changé par rapport au code qui remplissait le journal du 5 septembre 2026 :

        1. Le choix du périphérique suit `classer_sorties`, la même règle que la voix Windows :
           quand le micro est en mains libres, c'est le canal mains libres du casque qui est visé,
           même si le réglage nomme « Stereo ».
        2. Un périphérique qui refuse 24 kHz n'est plus abandonné : on l'ouvre au taux qu'il
           annonce (`default_samplerate`) et `Reechantillonneur` convertit le flux. Le son sort DU
           périphérique demandé.
        3. Le journal distingue « introuvable » (lunettes éteintes) de « refuse la fréquence », et
           ne le dit qu'une fois.
        """
        voulu = (self.settings.user.audio_output_device or "").strip().lower()
        if not voulu:
            return None, SAMPLE_RATE
        try:
            apis = sd.query_hostapis()
            devices = list(sd.query_devices())
        except Exception as exc:
            self._signaler_sortie(voulu, f"inaccessible (énumération des sorties impossible : {exc})")
            return None, SAMPLE_RATE
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
            return None, SAMPLE_RATE
        refus = []
        for position in ordre:
            idx = index[position]
            try:
                natif = int(float(devices[idx].get("default_samplerate") or 0))
            except (TypeError, ValueError):
                natif = 0
            essayes: list[int] = []
            for taux in (SAMPLE_RATE, natif):
                if taux <= 0 or taux in essayes:
                    continue
                essayes.append(taux)
                try:
                    sd.check_output_settings(device=idx, samplerate=taux, channels=1, dtype="int16")
                except Exception:
                    continue
                self._annoncer_sortie(idx, noms[position], taux)
                return idx, taux
            refus.append(f"{noms[position]} (index {idx}, ni {SAMPLE_RATE} ni {natif} Hz)")
        self._signaler_sortie(voulu, "refuse toutes les fréquences essayées (" + "; ".join(refus) + ")")
        return None, SAMPLE_RATE

    def _ouvrir_sortie(self, sd, device: int | None, taux: int) -> tuple:
        """Flux de sortie ouvert sur `device` au taux `taux`, sinon sur la sortie par défaut à 24 kHz.

        Renvoie (flux, taux réellement ouvert). Lève SortieAudioIndisponible si rien ne s'ouvre :
        c'est alors à la voix Windows de reprendre (`_handle_failure`)."""
        if device is not None:
            try:
                flux = sd.RawOutputStream(samplerate=taux, channels=1, dtype="int16", blocksize=max(1, taux // 10), device=device)
                return flux, taux
            except Exception as exc:
                log.warning("sortie audio %s refusée à l'ouverture (%s) : sortie par défaut utilisée", device, exc)
                self._sortie_annoncee = ()
        try:
            flux = sd.RawOutputStream(samplerate=SAMPLE_RATE, channels=1, dtype="int16", blocksize=2400)
            return flux, SAMPLE_RATE
        except Exception as exc:
            raise SortieAudioIndisponible(f"aucune sortie audio ne s'ouvre, pas même celle par défaut ({exc})") from exc

    def _stream_and_play(self, text: str) -> None:
        sd = self._sounddevice()

        u = self.settings.user
        voice_id = u.elevenlabs_voice_id or DEFAULT_VOICE_ID
        model = u.elevenlabs_model or DEFAULT_MODEL
        url = f"{API_BASE}/text-to-speech/{voice_id}/stream?output_format=pcm_{SAMPLE_RATE}&optimize_streaming_latency=3"
        body = {
            "text": text,
            "model_id": model,
            "voice_settings": {"stability": 0.55, "similarity_boost": 0.8, "style": 0.0, "use_speaker_boost": True},
        }
        # Débit : la part que le moteur sait faire lui-même, le reste par étirement local du PCM.
        # À vitesse normale la requête reste exactement celle d'avant (aucun champ speed ajouté).
        vitesse, reste = repartir_vitesse(u.tts_rate)
        if not est_identite(vitesse):
            body["voice_settings"]["speed"] = vitesse
        etireur = None if reste == 1.0 else Etireur(reste, SAMPLE_RATE)
        if model in ("eleven_flash_v2_5", "eleven_turbo_v2_5"):
            body["language_code"] = (u.language or "fr")[:2]
        started = time.time()
        # Rotation : on tente chaque clé du pool ; une clé qui répond « quota atteint » (401/402/429)
        # est mise en pénalité et on passe à la suivante. À une seule clé, comportement d'avant.
        pool = pool_elevenlabs()
        resp = None
        for _ in range(max(1, len(pool))):
            cle = pool.courante()
            resp = self._http().post(url, headers={**self._headers(cle), "Content-Type": "application/json"}, json=body, stream=True, timeout=(10, 60))
            if resp.status_code in CODES_BASCULE and len(pool) > 1:
                log.warning("TTS %s clé %s : bascule sur une autre clé", resp.status_code, etiquette(cle))
                resp.close()
                pool.marquer_epuisee(cle)
                continue
            break
        if resp.status_code in (400, 422) and "speed" in body["voice_settings"]:
            # Requête refusée alors qu'elle porte speed (modèle qui ne le connaît pas, par exemple) :
            # sans ce second essai, CHAQUE phrase à débit non normal tomberait sur la voix Windows.
            # On la renvoie sans speed et tout le facteur passe par l'étirement local.
            log.warning("TTS %s avec speed=%s : nouvel essai sans speed, débit appliqué localement",
                        resp.status_code, body["voice_settings"]["speed"])
            resp.close()
            del body["voice_settings"]["speed"]
            facteur = facteur_debit(u.tts_rate)
            etireur = None if est_identite(facteur) else Etireur(facteur, SAMPLE_RATE)
            resp = self._http().post(url, headers={**self._headers(pool.courante()), "Content-Type": "application/json"}, json=body, stream=True, timeout=(10, 60))
        if resp.status_code < 400:
            pool.apres_usage()  # énoncé réussi : alterner pour le prochain
        if resp.status_code >= 400:
            detail = resp.text[:200]
            err = RuntimeError(f"HTTP {resp.status_code} {detail}")
            err.response = resp  # type: ignore[attr-defined]
            raise err
        first = True
        pending = b""
        # Sous VERROU_PORTAUDIO du choix du périphérique jusqu'à la fermeture du flux : tant que ce
        # flux de sortie est ouvert, le fil du micro ne doit pas fermer PortAudio pour ré-énumérer
        # (Pa_Terminate fermerait ce flux d'autorité et corromprait le tas). `is_speaking` couvre déjà
        # ce chemin, mais le verrou ferme la micro-fenêtre entre son passage à True et l'ouverture réelle.
        with VERROU_PORTAUDIO:
            device, taux = self._output_device(sd)
            try:
                out_stream, taux = self._ouvrir_sortie(sd, device, taux)
            except Exception:
                resp.close()
                raise
            convertisseur = Reechantillonneur(SAMPLE_RATE, taux)
            interrompu = False
            with out_stream as out:
                for chunk in resp.iter_content(chunk_size=4800):
                    if self._stop_flag.is_set():
                        interrompu = True
                        break
                    if not chunk:
                        continue
                    if first:
                        log.info("ElevenLabs : premier audio après %.2f s", time.time() - started)
                        first = False
                    pending += chunk
                    usable = len(pending) - (len(pending) % 2)  # int16 : nombre pair d'octets
                    if usable:
                        morceau = pending[:usable]
                        pending = pending[usable:]
                        if etireur is not None:
                            # Étiré à 24 kHz, AVANT le rééchantillonnage vers la sortie : l'étireur
                            # garde quelques millisecondes pour raccorder le morceau suivant.
                            morceau = etireur.pousser_octets(morceau)
                        pret = convertisseur.convertir(morceau) if morceau else b""
                        if pret:  # le convertisseur peut garder un morceau trop court pour la suite
                            out.write(pret)
                if etireur is not None and not interrompu and not self._stop_flag.is_set():
                    reste_pcm = etireur.vider_octets()  # la fin de la phrase, retenue par l'étireur
                    pret = convertisseur.convertir(reste_pcm) if reste_pcm else b""
                    if pret:
                        out.write(pret)
            resp.close()

    def shutdown(self) -> None:
        self.stop()
        if self._thread and self._thread.is_alive():
            self._queue.put(None)
