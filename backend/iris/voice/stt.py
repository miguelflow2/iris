"""Reconnaissance vocale : Vosk (hors-ligne, sur l'appareil) en priorité, cloud en repli avec consentement.

Pour une langue étrangère (mode traduction), le modèle hors ligne ne sert à rien : il ne connaît que
le français. La parole part alors vers un service en ligne, et ce module choisit lequel :
ElevenLabs Scribe d'abord (service officiel, sous contrat, avec la clé déjà utilisée pour la voix),
Google Web Speech ensuite (endpoint gratuit et non officiel, clé de démonstration partagée,
throttlé). Quand aucune voie ne rend de texte, `ReconnaissanceImpossible` le dit — en français, et
sans jamais être avalée : c'est ce qui permet à l'écoute de PARLER au lieu de se taire."""
from __future__ import annotations

import io
import json
import logging
import os
import shutil
import sys
import threading
import time
import wave
import zipfile
from pathlib import Path
from typing import Callable

from .rotation_cles import CODES_BASCULE, etiquette, pool_elevenlabs

log = logging.getLogger("iris.stt")

SAMPLE_RATE = 16000

# ------------------------------------------------------------------ reconnaissance d'une langue étrangère
SCRIBE_URL = "https://api.elevenlabs.io/v1/speech-to-text"
SCRIBE_MODEL = "scribe_v2"
# Connexion, puis lecture. Un segment de conversation fait 2 à 6 s ; Scribe le rend d'ordinaire en
# 1 à 2 s. Au-delà de la lecture, on passe à Google plutôt que d'attendre : l'interlocuteur, lui,
# n'attend pas.
SCRIBE_TIMEOUT = (4.0, 10.0)
# `recognize_google` passe ce délai à `urlopen`. Sans lui, le délai est None : un appel vers
# l'endpoint non officiel pouvait pendre indéfiniment, et le fil de traduction avec lui.
GOOGLE_TIMEOUT = 8.0
AGENT_SCRIBE = "elevenlabs-scribe"
AGENT_GOOGLE = "google-stt"

# Pourquoi la reconnaissance a échoué — un code par cause, et la phrase française qui va avec.
RESEAU = "reseau"
REFUS = "refus"
PANNE = "panne"
INCOMPRIS = "incompris"
CONSENTEMENT = "consentement"
NON_CONFIGURE = "non_configure"
INCONNU = "inconnu"
PHRASES_RAISONS = {
    RESEAU: "pas de réseau",
    REFUS: "service refusé",
    PANNE: "service en panne",
    INCOMPRIS: "rien compris",
    CONSENTEMENT: "consentement audio non donné",
    NON_CONFIGURE: "aucun service de reconnaissance configuré",
    INCONNU: "raison inconnue",
}
# Quand deux voies échouent pour des raisons différentes, on dit celle qui en sait le plus long sur
# l'AUDIO : un service qui a reçu la parole et n'y a rien trouvé est plus fiable qu'un service qui
# n'a jamais répondu. Puis le refus (une clé ou un quota, ça se corrige), puis la panne, puis le réseau.
ORDRE_RAISONS = (INCOMPRIS, REFUS, PANNE, RESEAU, NON_CONFIGURE, CONSENTEMENT, INCONNU)
# Locale complète pour Google, à partir d'un code court. Même table que le listener
# (`LOCALES_ETRANGERES`) — dupliquée parce que listener.py importe ce module, pas l'inverse.
LOCALES_GOOGLE = {"en": "en-US", "fr": "fr-CA", "es": "es-ES", "pt": "pt-BR", "it": "it-IT", "de": "de-DE"}


class ReconnaissanceImpossible(Exception):
    """Aucune voie n'a rendu de texte, et voici pourquoi, en français.

    Levée — jamais avalée — pour qu'à l'autre bout l'écoute puisse dire « je n'ai pas pu entendre »
    au lieu de se taire. Avant, une `RequestError` de Google remontait jusqu'à un `except Exception`
    qui ne faisait qu'écrire une ligne de journal : IRIS restait muette devant quelqu'un, et le
    propriétaire croyait qu'elle n'avait rien entendu.

    `raison` est l'un des codes ci-dessus (RESEAU, REFUS, PANNE, INCOMPRIS, CONSENTEMENT,
    NON_CONFIGURE, INCONNU) ; `str(exc)` est le message complet pour le journal ; `a_dire` est la
    phrase courte à prononcer, sans code ni adresse."""

    def __init__(self, raison: str, detail: str = "") -> None:
        self.raison = raison if raison in PHRASES_RAISONS else INCONNU
        self.detail = (detail or "").strip() if raison in PHRASES_RAISONS else f"{raison} {detail}".strip()
        message = PHRASES_RAISONS[self.raison]
        if self.detail:
            message = f"{message} — {self.detail}"
        super().__init__(message)

    @property
    def a_dire(self) -> str:
        """Ce qu'IRIS peut dire à voix haute : la cause, rien de technique."""
        return f"Je n'ai pas pu entendre : {PHRASES_RAISONS[self.raison]}."

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


def dossiers_modeles(models_dir: Path) -> list[Path]:
    """Où chercher un modèle, dans l'ordre.

    D'abord celui que l'utilisateur a téléchargé, ensuite celui livré avec l'application. Le
    second existe parce qu'un modèle absent rendait IRIS complètement sourde sur une machine
    neuve : le moteur refusait de démarrer, le micro s'ouvrait, et rien n'était jamais entendu.
    Personne ne doit avoir à cliquer sur « Télécharger » pour qu'elle entende."""
    dossiers = [Path(models_dir)]
    exe = Path(sys.executable).resolve()
    if getattr(sys, "frozen", False):
        # Application installée : le moteur est dans resources/backend, les modèles dans resources/models.
        dossiers += [exe.parent / "models", exe.parent.parent / "models"]
    dossiers.append(Path(__file__).resolve().parents[3] / "resources-modeles")  # dépôt, en développement
    vus: list[Path] = []
    for d in dossiers:
        if d not in vus:
            vus.append(d)
    return vus


def model_dir(models_dir: Path, language: str) -> Path | None:
    info = VOSK_MODELS[lang_key(language)]
    for dossier in dossiers_modeles(models_dir):
        path = dossier / info["name"]
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


def _raison_google(exc: Exception) -> str:
    """Traduit le message d'une `RequestError` de SpeechRecognition en cause.

    La bibliothèque n'a que deux formes : « recognition connection failed: … » (URLError : pas de
    réseau, DNS) et « recognition request failed: <raison HTTP> » (HTTPError : la clé de démonstration
    refusée, ou le service lui-même en panne)."""
    bas = str(exc).lower()
    if "connection failed" in bas or "timed out" in bas or "timeout" in bas:
        return RESEAU
    if any(mot in bas for mot in ("unavailable", "gateway", "internal server")):
        return PANNE
    if "request failed" in bas:
        return REFUS
    return RESEAU


def google_recognize(pcm: bytes, sample_rate: int, language: str) -> str:
    """STT cloud (Google Web Speech via SpeechRecognition). Ne l'appeler qu'avec le consentement audio_raw.

    Rend "" quand Google n'a rien compris (c'est un silence normal sur le chemin du mot
    d'activation, pas une erreur). Lève `ReconnaissanceImpossible` quand Google n'a pas pu être
    interrogé : avant, cette `RequestError` remontait telle quelle et finissait avalée plus haut."""
    try:
        import speech_recognition as sr
    except ImportError as exc:
        raise ReconnaissanceImpossible(NON_CONFIGURE, "SpeechRecognition n'est pas installé") from exc

    recognizer = sr.Recognizer()
    recognizer.operation_timeout = GOOGLE_TIMEOUT
    audio = sr.AudioData(pcm, sample_rate, 2)
    try:
        return recognizer.recognize_google(audio, language=language or "fr-CA")
    except sr.UnknownValueError:
        return ""
    except sr.RequestError as exc:
        raise ReconnaissanceImpossible(_raison_google(exc), f"Google : {exc}") from exc


# ------------------------------------------------------------------ ElevenLabs Scribe
def cle_elevenlabs() -> str:
    """Même source que la voix (voice/elevenlabs.py) : le pool de clés de l'environnement, jamais le
    code. ELEVENLABS_API_KEY peut en contenir plusieurs (virgules) : voir rotation_cles."""
    return pool_elevenlabs().courante()


_session = None
_verrou_session = threading.Lock()


def _client_http():
    """Session `requests` partagée : la poignée de main TLS ne se paie qu'une fois par conversation."""
    global _session
    import requests

    with _verrou_session:
        if _session is None:
            _session = requests.Session()
        return _session


def wav_en_memoire(pcm: bytes, rate: int) -> bytes:
    """Entête WAV + PCM 16 bits mono, construits en mémoire : aucun fichier temporaire à écrire ni
    à oublier d'effacer, pour de l'audio qui est la voix d'un tiers."""
    usable = len(pcm) - (len(pcm) % 2)  # int16 : nombre pair d'octets
    tampon = io.BytesIO()
    with wave.open(tampon, "wb") as sortie:
        sortie.setnchannels(1)
        sortie.setsampwidth(2)
        sortie.setframerate(int(rate))
        sortie.writeframes(pcm[:usable])
    return tampon.getvalue()


def code_court(langue: str) -> str:
    """« en-US », « EN », « en » -> « en » ; "" si rien. Scribe veut un code ISO, pas une locale."""
    brut = (langue or "").strip().lower().replace("_", "-")
    return brut.split("-")[0][:3] if brut else ""


def locale_google(langue: str) -> str:
    """Google veut l'inverse : une locale complète. Une locale reçue est gardée telle quelle."""
    brut = (langue or "").strip().replace("_", "-")
    if "-" in brut:
        return brut
    return LOCALES_GOOGLE.get(brut.lower(), brut or "en-US")


def scribe_recognize(pcm: bytes, rate: int, langue: str, *, client=None, cle: str | None = None) -> str:
    """STT ElevenLabs Scribe. Ne l'appeler qu'avec le consentement audio_raw.

    Rend le texte entendu ("" si Scribe n'a trouvé aucun mot). Lève `ReconnaissanceImpossible`
    quand Scribe n'a pas pu être interrogé (clé absente, réseau, refus, panne). Multilingue :
    Scribe détecte la langue lui-même, `langue` n'est qu'un indice.

    `client` : tout objet avec `.post(url, headers=, data=, files=, timeout=)` — les tests en
    injectent un faux, la production prend la session partagée."""
    # `cle` imposée (tests) : une seule tentative, sans rotation. Sinon on tire du pool et on bascule
    # d'une clé à l'autre quand l'une refuse (quota atteint), pour étaler sur plusieurs comptes.
    pool = pool_elevenlabs()
    rotation = cle is None
    if not rotation and not cle:
        raise ReconnaissanceImpossible(NON_CONFIGURE, "clé ELEVENLABS_API_KEY absente")
    if rotation and not pool:
        raise ReconnaissanceImpossible(NON_CONFIGURE, "clé ELEVENLABS_API_KEY absente")
    client = client or _client_http()
    champs = {"model_id": SCRIBE_MODEL, "tag_audio_events": "false"}  # les rires et bruits ne se traduisent pas
    code = code_court(langue)
    if code:
        champs["language_code"] = code
    contenu_wav = wav_en_memoire(pcm, rate)
    resp = None
    statut = 0
    debut = time.time()
    for _ in range(max(1, len(pool)) if rotation else 1):
        cle_utilisee = pool.courante() if rotation else cle
        debut = time.time()
        try:
            resp = client.post(
                SCRIBE_URL,
                headers={"xi-api-key": cle_utilisee},
                data=champs,
                files={"file": ("parole.wav", contenu_wav, "audio/wav")},
                timeout=SCRIBE_TIMEOUT,
            )
        except Exception as exc:
            raise ReconnaissanceImpossible(RESEAU, f"Scribe injoignable ({exc})") from exc
        statut = int(getattr(resp, "status_code", 0) or 0)
        if rotation and statut in CODES_BASCULE and len(pool) > 1:
            log.warning("Scribe %s clé %s : bascule sur une autre clé", statut, etiquette(cle_utilisee))
            pool.marquer_epuisee(cle_utilisee)
            continue
        break
    if rotation and statut < 400:
        pool.apres_usage()  # reconnaissance réussie : alterner pour la prochaine
    if statut >= 500:
        raise ReconnaissanceImpossible(PANNE, f"Scribe HTTP {statut}")
    if statut >= 400:
        extrait = (getattr(resp, "text", "") or "")[:120].replace("\n", " ")
        raise ReconnaissanceImpossible(REFUS, f"Scribe HTTP {statut} {extrait}".strip())
    try:
        corps = resp.json() or {}
    except Exception as exc:
        raise ReconnaissanceImpossible(PANNE, "réponse Scribe illisible") from exc
    texte = str(corps.get("text") or "").strip()
    detectee = str(corps.get("language_code") or "")
    duree_ms = len(pcm) // max(1, 2 * int(rate) // 1000)  # int16 mono : 2 octets par échantillon
    log.info("Scribe : %d ms d'audio rendus en %.2f s (langue entendue : %s)", duree_ms, time.time() - debut, detectee or "?")
    if detectee and code and detectee[:2] != code[:2]:
        log.info("Scribe a entendu « %s » alors que « %s » était attendu", detectee, code)
    return texte


def _consenti(consentement) -> bool:
    """Le consentement peut être un booléen ou une fonction ; dans le doute (erreur), rien ne part."""
    try:
        return bool(consentement() if callable(consentement) else consentement)
    except Exception as exc:
        log.warning("consentement audio invérifiable (%s) : rien n'est envoyé", exc)
        return False


def _bilan(echecs: list[tuple[str, ReconnaissanceImpossible]]) -> ReconnaissanceImpossible:
    """Une seule exception pour toutes les voies : la cause la plus parlante, et le détail de chacune."""
    raisons = {exc.raison for _, exc in echecs}
    dominante = next((r for r in ORDRE_RAISONS if r in raisons), INCONNU)
    detail = " ; ".join(f"{voie} : {exc}" for voie, exc in echecs)
    return ReconnaissanceImpossible(dominante, detail)


def reconnaitre_etranger(
    pcm: bytes,
    rate: int,
    langue: str,
    *,
    consentement: bool | Callable[[], bool] = False,
    client=None,
    journal: Callable[[str, str], None] | None = None,
) -> str:
    """La parole d'un interlocuteur, dans une langue étrangère, devient du texte — ou une exception qui dit pourquoi.

    Scribe d'abord (officiel, sous contrat, la clé déjà lue pour la voix), Google Web Speech en
    repli si Scribe n'est pas configuré ou échoue. Rend le texte, jamais "". Lève
    `ReconnaissanceImpossible` — avec `raison` et `a_dire` — quand aucune voie n'a rendu de texte.

    `consentement` : booléen ou fonction ; rien ne part tant qu'il n'est pas vrai (la valeur par
    défaut est le refus : appeler sans le dire, c'est ne rien envoyer). La voix envoyée est celle
    d'un tiers qui n'a rien signé — c'est au propriétaire d'avoir accordé `audio_raw`.
    `journal(agent, detail)` : appelé AVANT chaque envoi, et seulement quand un envoi a lieu, pour le
    registre chaîné des sorties (« qu'est-ce qui est SORTI de cet ordinateur, et vers qui ? »).
    `client` : client HTTP injectable pour Scribe (tests)."""
    if not _consenti(consentement):
        raise ReconnaissanceImpossible(CONSENTEMENT, "rien n'a été envoyé")
    if not pcm:
        raise ReconnaissanceImpossible(INCOMPRIS, "aucun audio à reconnaître")
    duree_ms = len(pcm) // max(1, 2 * int(rate) // 1000)
    detail_envoi = f"traduction : {duree_ms} ms d'audio en {langue or '?'}"
    echecs: list[tuple[str, ReconnaissanceImpossible]] = []

    if pool_elevenlabs():
        if journal:
            journal(AGENT_SCRIBE, detail_envoi)
        try:
            texte = scribe_recognize(pcm, rate, langue, client=client)
        except ReconnaissanceImpossible as exc:
            echecs.append(("Scribe", exc))
            log.warning("Scribe n'a pas entendu : %s", exc)
        except Exception as exc:  # défaut imprévu : on le nomme et on passe à la voie suivante
            echecs.append(("Scribe", ReconnaissanceImpossible(PANNE, f"{type(exc).__name__}: {exc}")))
            log.warning("Scribe a échoué de façon imprévue : %s", exc)
        else:
            if texte:
                return texte
            echecs.append(("Scribe", ReconnaissanceImpossible(INCOMPRIS, "aucun mot trouvé")))
    else:
        echecs.append(("Scribe", ReconnaissanceImpossible(NON_CONFIGURE, "clé ELEVENLABS_API_KEY absente")))

    if journal:
        journal(AGENT_GOOGLE, detail_envoi)
    try:
        texte = (google_recognize(pcm, rate, locale_google(langue)) or "").strip()
    except ReconnaissanceImpossible as exc:
        echecs.append(("Google", exc))
        log.warning("Google n'a pas entendu : %s", exc)
    except Exception as exc:
        echecs.append(("Google", ReconnaissanceImpossible(PANNE, f"{type(exc).__name__}: {exc}")))
        log.warning("Google a échoué de façon imprévue : %s", exc)
    else:
        if texte:
            if echecs:
                log.info("Google a pris le relais de Scribe (%s)", echecs[-1][1])
            return texte
        echecs.append(("Google", ReconnaissanceImpossible(INCOMPRIS, "aucun mot trouvé")))

    raise _bilan(echecs)
