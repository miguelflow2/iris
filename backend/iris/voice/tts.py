"""Synthèse vocale hors-ligne (pyttsx3 / SAPI5 sous Windows), dans un thread dédié."""
from __future__ import annotations

import logging
import queue
import re
import threading
import time

from ..config import Settings
from ..events import EventHub
from .elevenlabs import PRECHAUFFAGE, ElevenLabsSpeaker, classer_sorties, micro_mains_libres
from .piper import PiperSpeaker

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


# PRECHAUFFAGE (importé d'elevenlabs.py, partagé par les deux voix) passe dans la file d'attente
# comme une phrase, mais n'en est pas une : elle ouvre le périphérique audio sans qu'on entende
# rien. Un objet, pas une chaîne : une chaîne finirait tôt ou tard prononcée à voix haute par un
# chemin qu'on aurait oublié. Les tests l'importent d'ici : le nom reste exposé par ce module.


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
        # « Audio autorisé » figé à la construction, distinct de self.available (qui, lui, passe à
        # False si l'init SAPI échoue au runtime). En production create_app passe enabled=True ; les
        # tests passent enabled=False et NE DOIVENT alors ouvrir aucun périphérique — ni Windows, ni
        # ElevenLabs, ni Piper. Gardé séparé d'available pour qu'une panne SAPI n'étouffe jamais
        # ElevenLabs en production (elle parlerait encore, seule la voix Windows serait perdue).
        self._audio_enabled = enabled
        self.error: str | None = None if enabled else "synthèse vocale désactivée"
        self.speaking = False
        self._thread: threading.Thread | None = None
        self._start_lock = threading.Lock()
        # routage de la sortie audio (voir _appliquer_sortie) : mémorisé pour ne pas ré-énumérer
        # les périphériques à chaque phrase (mesuré : ~70 ms l'énumération SAPI)
        self._sortie_routee = ""  # nom demandé actuellement appliqué à SAPI ("" = rien d'acquis)
        self._sortie_assignee = False  # IRIS a-t-elle déjà imposé une sortie à SAPI ?
        self._sortie_avertie = ""  # nom déjà signalé introuvable (on n'avertit qu'une fois)
        self.eleven = ElevenLabsSpeaker(settings, hub)
        self.eleven.fallback_speak = lambda text: self._speak_windows(text)
        # Voix française locale (mode indépendant) : repli sur Windows si la synthèse locale échoue.
        self.piper = PiperSpeaker(settings, hub)
        self.piper.fallback_speak = lambda text: self._speak_windows(text)

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
        # La sortie audio n'est PAS une propriété pyttsx3 (setProperty lève KeyError) : elle se règle
        # sur l'objet SAPI, juste avant say(). Hors du try ci-dessus pour qu'un réglage de voix raté
        # ne prive pas Miguel du routage vers ses lunettes.
        self._appliquer_sortie()

    # ------------------------------------------------------------------ sortie audio (lunettes)
    def _sapi(self):
        """Objet COM SAPI caché sous pyttsx3, ou None si ce n'est pas le pilote SAPI5.

        pyttsx3 n'offre aucune API de sortie : setProperty("output_device") lève
        KeyError « unknown property » (mesuré sur 2.99, la version installée) et say() ne touche
        jamais AudioOutput. Il faut donc descendre à l'objet privé du pilote — d'où les getattr
        défensifs : requirements.txt autorise pyttsx3 >= 2.98 et cet attribut n'est pas public.
        """
        driver = getattr(getattr(self._engine, "proxy", None), "_driver", None)
        return getattr(driver, "_tts", None)

    @staticmethod
    def _jetons_sortie(sapi) -> list:
        """Sorties audio connues de SAPI. SAPI ne prend pas un nom mais un jeton issu de cette liste."""
        sorties = sapi.GetAudioOutputs()
        try:
            return list(sorties)
        except TypeError:  # collection COM sans itérateur : on passe par Count/Item
            return [sorties.Item(i) for i in range(sorties.Count)]

    @staticmethod
    def _decrire(jeton) -> str:
        try:
            return jeton.GetDescription() or ""
        except Exception:
            return ""

    def _choisir_sortie(self, jetons: list, voulu: str) -> tuple:
        """Jeton dont la description convient à `voulu` (minuscules), sinon (None, "").

        Le réglage est une correspondance partielle, comme pour le micro : « M01 Pro_F444 » désigne
        chez Miguel DEUX sorties, « Stereo » (A2DP) et « Hands-Free AG Audio » (HFP). C'est
        Hands-Free qui gagne. Pourquoi : IRIS écoute « Dis-moi Iris » en permanence, donc le micro
        mains libres des lunettes est ouvert, et Windows met alors le profil stéréo en veille —
        parler vers « Stereo » à ce moment-là, c'est parler dans le vide. Hands-Free reste audible
        dans les deux états, au prix du 8 kHz mono. Une voix moins belle vaut mieux qu'une voix
        inaudible. C'est aussi ce que vise déjà main.py quand on choisit le micro des lunettes.

        La règle elle-même vit dans elevenlabs.py (`classer_sorties`) : ElevenLabs suivait une
        autre règle, et sur la configuration réelle (micro « Hands-Free », sortie « Stereo » nommée
        en toutes lettres) aucune des deux voix n'atteignait le canal mains libres. Avec le micro en
        mains libres, la sortie stéréo demandée est maintenant redirigée vers le canal mains libres
        du même casque — pour les deux voix.
        """
        descriptions = [self._decrire(jeton) for jeton in jetons]
        ordre = classer_sorties(descriptions, voulu, micro_mains_libres(self.settings))
        if not ordre:
            return None, ""
        return jetons[ordre[0]], descriptions[ordre[0]]

    def _replier_sur_defaut(self, sapi, jetons: list) -> str:
        """Ramène la voix sur une sortie encore présente quand la sortie voulue a disparu.

        Ne sert que si IRIS avait déjà imposé les lunettes à SAPI : le jeton assigné pointerait
        alors sur un périphérique éteint et la phrase serait perdue. Tant qu'IRIS n'a rien assigné,
        on ne touche à rien — c'est la sortie par défaut de Windows qui parle, et elle est vivante.
        (Ne jamais assigner None pour « rendre la main » : sonde faite, cela renvoie la voix
        ailleurs au lieu de rétablir le défaut.)
        """
        if not self._sortie_assignee:
            return ""
        for jeton in jetons:
            try:
                sapi.AudioOutput = jeton
            except Exception:
                continue
            self._sortie_assignee = False  # revenu sur une sortie quelconque : plus rien à défaire
            return self._decrire(jeton)
        return ""

    def _appliquer_sortie(self) -> None:
        """Dirige la voix Windows vers audio_output_device, comme ElevenLabs le fait déjà.

        Sans cela le moteur Windows suit aveuglément le périphérique par défaut du système : quand
        Miguel choisit le micro de ses lunettes, main.py écrit la sortie mains libres dans les
        réglages, mais personne ne la lisait sur le chemin pyttsx3 — la voix partait vers le profil
        que Windows venait justement d'endormir.
        """
        voulu = (self.settings.user.audio_output_device or "").strip()
        if not voulu:
            # Réglage vide = « sortie par défaut de Windows » : on ne touche à rien.
            return
        if voulu.lower() == self._sortie_routee.lower():
            return  # déjà routé ; ré-énumérer coûterait ~70 ms par phrase pour rien
        sapi = self._sapi()
        if sapi is None:
            return  # pilote non SAPI5 : rien à router, mais surtout rien à casser
        jetons: list = []
        try:
            jetons = self._jetons_sortie(sapi)
            jeton, desc = self._choisir_sortie(jetons, voulu.lower())
            if jeton is not None:
                sapi.AudioOutput = jeton
                self._sortie_routee = voulu
                self._sortie_assignee = True
                self._sortie_avertie = ""
                log.info("voix Windows dirigée vers « %s »", desc)
                return
        except Exception as exc:
            log.warning("routage de la voix Windows impossible : %s", exc)
        # Échec : IRIS parle quand même. Les points de terminaison Bluetooth disparaissent puis
        # reviennent (constaté à une minute d'intervalle), donc on oublie le cache et on réessaiera
        # à la phrase suivante.
        self._sortie_routee = ""
        repli = self._replier_sur_defaut(sapi, jetons)
        if self._sortie_avertie != voulu:
            self._sortie_avertie = voulu
            ou = f" (voix renvoyée vers « {repli} »)" if repli else ""
            msg = (
                f"Sortie audio « {voulu} » introuvable — lunettes éteintes ou hors de portée : "
                f"IRIS parle par le haut-parleur par défaut{ou}."
            )
            log.warning(msg)
            try:
                self.hub.publish("tts.fallback", reason=msg)
            except Exception:
                pass

    def prechauffer(self) -> None:
        """Ouvre le canal audio d'avance, pour que la PREMIERE phrase ne soit pas la plus lente.

        Mesure sur les lunettes de Miguel le 5 septembre 2026, la meme phrase a chaque fois :

            sortie stereo         3,27 s | 3,27 s | 3,27 s
            sortie mains libres   4,25 s | 3,90 s | 3,90 s
            tout premier passage en mains libres : 8,3 s

        Les huit secondes sont le basculement du casque en profil telephone, paye une seule fois.
        En regime etabli il ne reste que six dixiemes de seconde par phrase. Mais ce basculement,
        s'il n'est pas provoque a l'avance, tombe exactement au pire moment : au tout premier
        << Dis-moi Iris >>, celui qu'on fait devant une salle.

        C'est le chemin QUI VA PARLER qu'on préchauffe. Avant, ce préchauffage sortait tôt dès
        qu'ElevenLabs répondait — c'est-à-dire sur la configuration réelle de Miguel, où c'est
        ElevenLabs qui parle : le canal n'était jamais préchauffé, et la pré-connexion HTTPS
        d'ElevenLabs n'ouvre aucun périphérique. Le casque est le même pour les deux voix : une fois
        basculé par ElevenLabs, il l'est aussi pour la voix Windows si elle doit reprendre."""
        # TTS désactivée (enabled=False au démarrage) = on ne touche À AUCUN périphérique audio, quel
        # que soit le moteur. En production create_app passe enabled=True, donc rien ne change ; mais
        # les tests (enabled=False) ne doivent JAMAIS ouvrir de vrai périphérique PortAudio — sur une
        # machine sans carte son (CI, bac à sable) l'ouverture/fermeture corrompt le tas natif. Avant,
        # ce garde-fou ne coupait que la voix Windows : ElevenLabs et Piper préchauffaient quand même.
        if not self._audio_enabled:
            return
        if self._use_elevenlabs():
            try:
                self.eleven.prechauffer()
            except Exception as exc:
                log.debug("prechauffage de la sortie ElevenLabs impossible : %s", exc)
            # ElevenLabs parle, mais Piper reste le repli hors-ligne : son modèle ONNX met ~5 s à se
            # charger la toute première fois. Sans préchargement, cette attente tomberait sur la
            # PREMIERE phrase de repli — souvent l'instant même où le nuage vient de tomber, le pire
            # moment. On charge donc le modèle en tâche de fond. On n'ouvre AUCUN périphérique audio
            # ici (charger l'ONNX ne touche pas PortAudio) : préchauffage léger, qui ne gêne ni
            # ElevenLabs ni le fil du micro — le canal qui parle vraiment reste préchauffé au-dessus.
            self._prechauffer_piper_fond()
            return
        if self._use_piper():
            try:
                self.piper.prechauffer()
            except Exception as exc:
                log.debug("prechauffage de la sortie Piper impossible : %s", exc)
            return
        try:  # voix Windows : la disponibilité est déjà garantie par le garde-fou en tête de méthode
            self._ensure_started()
            self._queue.put(PRECHAUFFAGE)
        except Exception as exc:
            log.debug("prechauffage de la voix impossible : %s", exc)

    def _prechauffer_piper_fond(self) -> None:
        """Charge le modèle Piper (repli hors-ligne) en arrière-plan, sans ouvrir de périphérique.

        Appelé quand un AUTRE moteur est primaire (ElevenLabs sur la configuration réelle de Miguel) :
        Piper ne parlera peut-être jamais, mais s'il doit reprendre hors-ligne, son modèle ONNX (~5 s
        au tout premier chargement) sera déjà en mémoire — la première phrase de repli ne paiera plus
        cette attente. On ne touche PAS à PortAudio ici (charger le modèle n'ouvre aucune sortie audio),
        donc ce préchauffage n'interfère ni avec ElevenLabs ni avec le fil du micro. Le garde-fou
        _audio_enabled a déjà écarté le cas des tests avant qu'on arrive ici ; et si Piper est absent
        (modèle non installé, paquet piper manquant), on ne fait simplement rien. Fil démon : le
        démarrage n'attend pas, et le chargement est abandonné à l'extinction sans rien bloquer."""
        if not self.piper.available:
            return  # Piper indisponible (fichiers .onnx absents) : aucun modèle à précharger
        def _charger_en_silence() -> None:
            try:
                self.piper._charger()  # ~5 s la première fois, payés ici en fond, pas devant la salle
            except Exception as exc:
                log.debug("préchargement du modèle Piper impossible : %s", exc)
        threading.Thread(target=_charger_en_silence, name="iris-piper-prechauffe", daemon=True).start()

    def _prechauffer_maintenant(self) -> None:
        """Prononce une syllabe a volume nul : le peripherique s'ouvre, personne n'entend rien."""
        try:
            self._apply_settings()
            volume = self._engine.getProperty("volume")
            self._engine.setProperty("volume", 0.0)
            debut = time.time()
            self._engine.say("a")
            self._engine.runAndWait()
            self._engine.setProperty("volume", volume)
            log.info("canal audio prechauffe en %.2f s (%s)", time.time() - debut,
                     self._sortie_routee or "sortie par defaut")
        except Exception as exc:
            log.debug("prechauffage impossible : %s", exc)

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
            if item is PRECHAUFFAGE:
                # Ni etat << en train de parler >>, ni evenement : rien ne se passe pour l'utilisateur.
                self._prechauffer_maintenant()
                continue
            self._idle.clear()
            self.speaking = True
            self.hub.publish("tts.state", speaking=True, text=item[:200])
            try:
                self._apply_settings()
                self._engine.say(item)
                self._engine.runAndWait()
            except Exception as exc:
                log.warning("erreur TTS: %s", exc)
                # la phrase a pu échouer parce que la sortie assignée est morte en cours de route
                # (lunettes éteintes) : on oublie le routage pour le refaire à la phrase suivante
                self._sortie_routee = ""
            finally:
                self.speaking = False
                if self._queue.empty():
                    self._idle.set()
                self.hub.publish("tts.state", speaking=False)

    plans = None  # PlanService (injecté)

    def _use_elevenlabs(self) -> bool:
        u = self.settings.user
        if u.tts_engine in ("windows", "piper"):
            return False
        if u.local_only:
            return False  # mode indépendant : aucune voix ne passe par le nuage
        if self.plans is not None and not self.plans.feature_allowed("elevenlabs"):
            return False
        return self.eleven.available

    def _use_piper(self) -> bool:
        """Piper (français local) est choisi quand ElevenLabs ne l'est pas et que Windows n'est pas
        imposé : c'est le meilleur repli hors-ligne, une vraie voix française avant l'accent Windows."""
        if self.settings.user.tts_engine == "windows":
            return False
        if self._use_elevenlabs():
            return False  # ElevenLabs garde la priorité quand il est utilisable
        return self.piper.available

    @property
    def engine(self) -> str:
        if self._use_elevenlabs():
            return "elevenlabs"
        if self._use_piper():
            return "piper"
        return "windows"

    def speak(self, text: str, force: bool = False) -> bool:
        if not force and not self.settings.user.tts_enabled:
            return False
        clean = speakable(text, language=self.settings.user.language)
        if not clean:
            return False
        # TTS désactivée (tests, enabled=False) : ne dispatcher vers AUCUN moteur qui ouvre un
        # périphérique audio réel (ElevenLabs/Piper), même si une clé ou un modèle est présent —
        # _speak_windows, lui, se garde déjà tout seul via self.available. Voir _audio_enabled.
        if self._audio_enabled and self._use_elevenlabs() and self.eleven.speak(clean):
            if self.plans is not None:
                try:
                    self.plans.count_tts(len(clean))
                except Exception:
                    pass
            return True
        if self._audio_enabled and self._use_piper() and self.piper.speak(clean):
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
        self.piper.stop()
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
        ok = self.piper.wait_idle(max(0.1, deadline - time.time())) and ok
        return self._idle.wait(max(0.1, deadline - time.time())) and ok

    @property
    def is_speaking(self) -> bool:
        return self.speaking or self.eleven.speaking or self.piper.speaking

    def voices(self) -> list[dict]:
        self._ensure_started()
        return list(self._voices)

    def shutdown(self) -> None:
        self.stop()
        self.eleven.shutdown()
        self.piper.shutdown()
        if self._thread is not None:
            self._queue.put(None)
