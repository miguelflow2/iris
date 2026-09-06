"""Lire ce qui n'est pas du texte : un PDF, une image, un fichier audio.

Limite qu'IRIS a elle-même énoncée le 6 septembre 2026 : « je ne peux pas lire un PDF, une image, un
fichier audio ou une vidéo sans outil adapté ». Elle avait raison — `read_file` faisait
`read_text(errors="replace")` et rendait du charabia sur un PDF. Ce module lui donne l'outil.

Trois lecteurs, avec ce qu'on avait déjà sous la main :
  - PDF   : pypdf (pur Python, aucune dépendance native), page par page, plafonné.
  - image : l'OCR déjà présent pour l'écran (rapidocr) — le texte QUE contient l'image, pas une
            description de la scène ; on le dit franchement quand il n'y a pas de texte.
  - audio : le même moteur Vosk que la voix, après conversion en 16 kHz mono 16 bits.

Deux règles. Aucune fonction ne lève sur un fichier abîmé, chiffré ou absent : elle rend une phrase
en français qui dit ce qui bloque — IRIS doit pouvoir le répéter à voix haute. Et le chemin passe
par le périmètre de fichiers de `pc/actions.py` quand il existe : lire n'est pas écrire, mais un
PDF dans un dossier qu'IRIS n'a pas le droit de toucher n'a pas à être lu non plus.
"""
from __future__ import annotations

import logging
import wave
from pathlib import Path
from typing import Callable

log = logging.getLogger("iris.lecture")

MAX_PAGES_PDF = 60
MAX_CARACTERES = 40_000  # au-delà, ce n'est plus une lecture, c'est un déversement dans le contexte
MAX_SECONDES_AUDIO = 15 * 60

EXTENSIONS_PDF = {".pdf"}
EXTENSIONS_IMAGE = {".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp", ".tif", ".tiff"}
EXTENSIONS_AUDIO = {".wav", ".wave"}


def _resoudre(chemin: str) -> Path:
    """Le chemin, passé par le périmètre d'IRIS s'il existe. Sinon, résolu simplement."""
    try:
        from .pc.actions import resoudre_dans_perimetre  # ajouté par le chantier sécurité

        return resoudre_dans_perimetre(chemin)
    except ImportError:
        return Path(chemin).expanduser().resolve()


def _tronquer(texte: str) -> str:
    if len(texte) <= MAX_CARACTERES:
        return texte
    return texte[:MAX_CARACTERES] + f"\n[… coupé : {len(texte) - MAX_CARACTERES} caractères de plus. Demande une page ou une section précise.]"


# --------------------------------------------------------------------------- PDF
def lire_pdf(chemin: str, pages: tuple[int, int] | None = None) -> str:
    """Le texte d'un PDF. `pages` = (première, dernière), à partir de 1, facultatif."""
    try:
        cible = _resoudre(chemin)
    except Exception as exc:
        return f"Je ne peux pas lire ce fichier : {exc}"
    if not cible.is_file():
        return f"Je ne trouve pas le fichier « {cible.name} »."
    try:
        from pypdf import PdfReader
    except ImportError:
        return "La lecture de PDF n'est pas installée sur cet ordinateur (il manque pypdf)."
    try:
        lecteur = PdfReader(str(cible))
        if lecteur.is_encrypted:
            # pypdf ne lève PAS quand le mot de passe est faux : il rend un code (0 = pas
            # déchiffré). Sans ce test, un PDF protégé passait pour « abîmé » — faux et trompeur.
            try:
                deverrouille = lecteur.decrypt("")
            except Exception:
                deverrouille = 0
            if not deverrouille:
                return f"Le PDF « {cible.name} » est protégé par un mot de passe : je ne peux pas le lire."
        total = len(lecteur.pages)
        debut, fin = (1, total) if pages is None else (max(1, pages[0]), min(total, pages[1]))
        if fin - debut + 1 > MAX_PAGES_PDF:
            fin = debut + MAX_PAGES_PDF - 1
        morceaux = []
        for numero in range(debut, fin + 1):
            texte = (lecteur.pages[numero - 1].extract_text() or "").strip()
            if texte:
                morceaux.append(f"[page {numero}]\n{texte}")
        if not morceaux:
            return (f"Le PDF « {cible.name} » ({total} page(s)) ne contient aucun texte lisible : c'est "
                    "probablement un document scanné, une image. Je peux essayer de le lire comme une image si tu me l'exportes.")
        entete = f"« {cible.name} » — {total} page(s)" + (f", pages {debut} à {fin}" if (debut, fin) != (1, total) else "")
        return _tronquer(entete + "\n\n" + "\n\n".join(morceaux))
    except Exception as exc:
        log.debug("PDF illisible %s : %s", cible.name, type(exc).__name__)
        return f"Je n'arrive pas à lire « {cible.name} » : le fichier semble abîmé ou n'est pas un vrai PDF."


# --------------------------------------------------------------------------- image
def lire_image(chemin: str, ocr: Callable[[str], list] | None = None) -> str:
    """Ce qu'une image CONTIENT comme texte, et ses dimensions. Pas une description de la scène.

    `ocr` est injectable : les tests ne chargent pas le moteur de reconnaissance."""
    try:
        cible = _resoudre(chemin)
    except Exception as exc:
        return f"Je ne peux pas lire ce fichier : {exc}"
    if not cible.is_file():
        return f"Je ne trouve pas l'image « {cible.name} »."
    try:
        from PIL import Image

        with Image.open(cible) as img:
            largeur, hauteur = img.size
            mode = img.mode
    except Exception:
        return f"« {cible.name} » n'est pas une image que je sais ouvrir."
    entete = f"« {cible.name} » — image {largeur}×{hauteur} ({mode})"

    if ocr is None:
        ocr = _ocr_par_defaut
    try:
        lignes = ocr(str(cible))
    except Exception as exc:
        log.debug("OCR impossible sur %s : %s", cible.name, type(exc).__name__)
        return entete + ". Je n'ai pas pu y chercher de texte (reconnaissance indisponible)."
    textes = [str(l).strip() for l in (lignes or []) if str(l).strip()]
    if not textes:
        return entete + ". Elle ne contient aucun texte lisible ; je ne décris pas ce qu'elle montre."
    return _tronquer(entete + ". Texte lu dans l'image :\n" + "\n".join(textes))


def _ocr_par_defaut(chemin: str) -> list[str]:
    """L'OCR de l'écran, réutilisé sur un fichier. Rend la liste des lignes de texte trouvées."""
    from rapidocr_onnxruntime import RapidOCR

    resultat, _ = RapidOCR()(chemin)
    if not resultat:
        return []
    # rapidocr rend [ [boîte, texte, confiance], ... ]
    return [ligne[1] for ligne in resultat if len(ligne) > 1]


# --------------------------------------------------------------------------- audio
def _pcm_16k_mono(cible: Path) -> tuple[bytes, float]:
    """Le PCM 16 kHz mono 16 bits attendu par Vosk, quel que soit le WAV d'origine, et sa durée."""
    import numpy as np

    with wave.open(str(cible), "rb") as w:
        canaux, largeur, taux, trames = w.getnchannels(), w.getsampwidth(), w.getframerate(), w.getnframes()
        duree = trames / float(taux or 1)
        if duree > MAX_SECONDES_AUDIO:
            raise ValueError(f"trop long ({duree / 60:.0f} min) : je lis au plus {MAX_SECONDES_AUDIO // 60} minutes")
        brut = w.readframes(trames)
    if largeur == 2:
        pcm = np.frombuffer(brut, dtype=np.int16).astype(np.float32)
    elif largeur == 1:
        pcm = (np.frombuffer(brut, dtype=np.uint8).astype(np.float32) - 128.0) * 256.0
    elif largeur == 4:
        pcm = np.frombuffer(brut, dtype=np.int32).astype(np.float32) / 65536.0
    else:
        raise ValueError("format d'échantillon inconnu")
    if canaux > 1:
        pcm = pcm.reshape(-1, canaux).mean(axis=1)
    if taux != 16000 and len(pcm):
        n_out = max(1, int(len(pcm) * 16000 / taux))
        x_old = np.linspace(0.0, 1.0, len(pcm), endpoint=False)
        x_new = np.linspace(0.0, 1.0, n_out, endpoint=False)
        pcm = np.interp(x_new, x_old, pcm)
    return np.clip(pcm, -32768, 32767).astype(np.int16).tobytes(), duree


def transcrire_audio(chemin: str, moteur=None, models_dir: Path | None = None, langue: str = "fr") -> str:
    """Le texte dit dans un fichier audio WAV, par le moteur hors ligne de la voix.

    `moteur` est injectable (un objet avec `.recognizer()`), sinon on charge le modèle Vosk de
    `models_dir` pour `langue` — le même que pour « Dis-moi Iris »."""
    try:
        cible = _resoudre(chemin)
    except Exception as exc:
        return f"Je ne peux pas lire ce fichier : {exc}"
    if not cible.is_file():
        return f"Je ne trouve pas le fichier audio « {cible.name} »."
    if cible.suffix.lower() not in EXTENSIONS_AUDIO:
        return (f"Je ne lis que les fichiers WAV pour l'instant ; « {cible.name} » n'en est pas un. "
                "Convertis-le en WAV et je le transcris.")
    try:
        pcm, duree = _pcm_16k_mono(cible)
    except ValueError as exc:
        return f"Je ne peux pas transcrire « {cible.name} » : {exc}."
    except Exception:
        return f"« {cible.name} » n'est pas un WAV que je sais lire."

    if moteur is None:
        try:
            from .voice import stt

            dossier = stt.model_dir(models_dir, langue) if models_dir is not None else None
            if dossier is None:
                return ("Le modèle de reconnaissance hors ligne n'est pas installé : télécharge-le dans "
                        "Paramètres › Voix, et je pourrai transcrire.")
            moteur = stt.VoskEngine(dossier)
        except Exception as exc:
            log.debug("moteur vosk indisponible : %s", type(exc).__name__)
            return "Le moteur de reconnaissance n'est pas disponible sur cet ordinateur."

    try:
        from .voice.stt import VoskEngine

        rec = moteur.recognizer()
        morceaux = []
        pas = 16000 * 2  # une seconde par bloc
        for i in range(0, len(pcm), pas):
            if rec.AcceptWaveform(pcm[i:i + pas]):
                texte = VoskEngine.text_of(rec.Result())
                if texte:
                    morceaux.append(texte)
        final = VoskEngine.text_of(rec.FinalResult())
        if final:
            morceaux.append(final)
    except Exception as exc:
        log.debug("transcription impossible %s : %s", cible.name, type(exc).__name__)
        return f"Je n'ai pas réussi à transcrire « {cible.name} »."
    texte = " ".join(m for m in morceaux if m).strip()
    entete = f"« {cible.name} » — {duree:.0f} s d'audio"
    if not texte:
        return entete + ". Je n'y ai entendu aucune parole reconnaissable."
    return _tronquer(entete + ". Transcription :\n" + texte)


# --------------------------------------------------------------------------- l'aiguillage
def lire_document(chemin: str, **options) -> str:
    """Lit un fichier selon son type. C'est ce qu'appellera l'outil `lire_document`."""
    suffixe = Path(chemin).suffix.lower()
    if suffixe in EXTENSIONS_PDF:
        return lire_pdf(chemin, pages=options.get("pages"))
    if suffixe in EXTENSIONS_IMAGE:
        return lire_image(chemin, ocr=options.get("ocr"))
    if suffixe in EXTENSIONS_AUDIO:
        return transcrire_audio(chemin, moteur=options.get("moteur"), models_dir=options.get("models_dir"),
                                langue=options.get("langue", "fr"))
    if suffixe in {".mp4", ".mov", ".avi", ".mkv", ".mp3", ".m4a", ".ogg", ".flac"}:
        return (f"Je ne sais pas encore lire « {Path(chemin).name} » ({suffixe}) : pour une vidéo ou un audio "
                "compressé, exporte la piste en WAV et je la transcris.")
    return (f"« {Path(chemin).name} » n'est ni un PDF, ni une image, ni un WAV. Pour un fichier texte, "
            "utilise read_file.")
