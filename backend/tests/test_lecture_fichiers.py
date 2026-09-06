"""Lire un PDF, une image, un fichier audio — la limite qu'IRIS s'est elle-même reconnue.

Aucun test ne charge le moteur de reconnaissance ni l'OCR reel : ils sont injectes. Ce qui compte
ici : on ne leve jamais sur un fichier abime, on rend une phrase en francais qu'IRIS peut repeter,
et l'audio arrive au moteur en 16 kHz mono quel que soit le WAV d'origine.
"""
from __future__ import annotations

import json
import wave

import numpy as np
import pytest

from iris import lecture_fichiers as lf


@pytest.fixture(autouse=True)
def _perimetre_tmp(tmp_path, monkeypatch):
    """Autorise tmp_path pour ces tests : on lit de vrais fichiers écrits par le test, pas ceux de
    l'utilisateur. Le périmètre de sécurité (chantier du 6 septembre) refuse %TEMP% par défaut, ce
    qui est le bon comportement en production — mais bloquerait toute lecture de fixture ici."""
    from iris.pc import actions

    perimetre = actions.Perimetre(
        autorisees=(tmp_path.resolve(),),
        interdites=(),
        projets=tmp_path.resolve(),
    )
    monkeypatch.setattr(actions, "PERIMETRE", perimetre)


# --------------------------------------------------------------------------- PDF
def test_un_pdf_sans_texte_est_dit_scanne(tmp_path):
    from pypdf import PdfWriter

    fichier = tmp_path / "scan.pdf"
    w = PdfWriter()
    w.add_blank_page(width=200, height=200)
    w.add_blank_page(width=200, height=200)
    with open(fichier, "wb") as fh:
        w.write(fh)
    texte = lf.lire_pdf(str(fichier))
    assert "aucun texte lisible" in texte
    assert "2 page(s)" in texte


def test_un_pdf_chiffre_le_dit_au_lieu_de_planter(tmp_path):
    from pypdf import PdfWriter

    fichier = tmp_path / "secret.pdf"
    w = PdfWriter()
    w.add_blank_page(width=100, height=100)
    w.encrypt("motdepasse")
    with open(fichier, "wb") as fh:
        w.write(fh)
    texte = lf.lire_pdf(str(fichier))
    assert "protégé par un mot de passe" in texte


def test_un_faux_pdf_est_dit_abime(tmp_path):
    fichier = tmp_path / "faux.pdf"
    fichier.write_bytes(b"ceci n'est pas un pdf du tout")
    texte = lf.lire_pdf(str(fichier))
    assert "abîmé" in texte or "n'est pas un vrai PDF" in texte


def test_un_pdf_absent_est_dit_introuvable(tmp_path):
    assert "Je ne trouve pas" in lf.lire_pdf(str(tmp_path / "nulle-part.pdf"))


# --------------------------------------------------------------------------- image
def _png(tmp_path, nom="photo.png", taille=(40, 30)):
    from PIL import Image

    fichier = tmp_path / nom
    Image.new("RGB", taille, (200, 100, 50)).save(fichier)
    return fichier


def test_une_image_sans_texte_dit_ses_dimensions_et_ne_decrit_pas(tmp_path):
    fichier = _png(tmp_path)
    texte = lf.lire_image(str(fichier), ocr=lambda p: [])
    assert "40×30" in texte
    assert "aucun texte lisible" in texte
    assert "je ne décris pas" in texte, "on ne prétend pas voir la scène : on lit du texte, rien d'autre"


def test_le_texte_dune_image_est_rendu(tmp_path):
    fichier = _png(tmp_path)
    texte = lf.lire_image(str(fichier), ocr=lambda p: ["Bonjour", "  VELA  ", ""])
    assert "Bonjour" in texte and "VELA" in texte


def test_un_ocr_qui_echoue_ne_leve_pas(tmp_path):
    fichier = _png(tmp_path)

    def casse(p):
        raise RuntimeError("moteur absent")

    texte = lf.lire_image(str(fichier), ocr=casse)
    assert "reconnaissance indisponible" in texte


def test_un_fichier_qui_nest_pas_une_image_est_dit(tmp_path):
    fichier = tmp_path / "pas.png"
    fichier.write_bytes(b"rien de valide")
    assert "n'est pas une image" in lf.lire_image(str(fichier), ocr=lambda p: [])


# --------------------------------------------------------------------------- audio
class _FauxRec:
    def __init__(self, journal):
        self.journal = journal

    def AcceptWaveform(self, bloc):
        self.journal.append(len(bloc))
        return False

    def Result(self):
        return json.dumps({"text": ""})

    def FinalResult(self):
        return json.dumps({"text": "salut iris"})


class _FauxMoteur:
    def __init__(self):
        self.journal: list[int] = []

    def recognizer(self, *a, **k):
        return _FauxRec(self.journal)


def _wav(tmp_path, taux=44100, canaux=2, secondes=0.5, nom="voix.wav"):
    fichier = tmp_path / nom
    n = int(taux * secondes)
    signal = (np.sin(np.linspace(0, 200 * np.pi, n)) * 8000).astype(np.int16)
    if canaux == 2:
        signal = np.repeat(signal[:, None], 2, axis=1).reshape(-1)
    with wave.open(str(fichier), "wb") as w:
        w.setnchannels(canaux)
        w.setsampwidth(2)
        w.setframerate(taux)
        w.writeframes(signal.tobytes())
    return fichier


def test_le_wav_est_converti_en_16k_mono_avant_le_moteur(tmp_path):
    """Le moteur de la voix attend du 16 kHz mono 16 bits, quel que soit le fichier d'origine."""
    fichier = _wav(tmp_path, taux=44100, canaux=2, secondes=0.5)
    moteur = _FauxMoteur()
    texte = lf.transcrire_audio(str(fichier), moteur=moteur)
    assert "salut iris" in texte
    octets = sum(moteur.journal)
    attendu = int(0.5 * 16000) * 2  # echantillons a 16 kHz, 2 octets chacun, mono
    assert abs(octets - attendu) <= 64, f"le moteur a recu {octets} octets, attendu ~{attendu} (16 kHz mono)"


def test_un_fichier_qui_nest_pas_un_wav_est_refuse_poliment(tmp_path):
    fichier = tmp_path / "chanson.mp3"
    fichier.write_bytes(b"\xff\xfb" * 10)
    texte = lf.transcrire_audio(str(fichier), moteur=_FauxMoteur())
    assert "Je ne lis que les fichiers WAV" in texte


def test_un_audio_trop_long_est_refuse_avec_la_limite(tmp_path, monkeypatch):
    monkeypatch.setattr(lf, "MAX_SECONDES_AUDIO", 0)
    fichier = _wav(tmp_path, secondes=0.5)
    texte = lf.transcrire_audio(str(fichier), moteur=_FauxMoteur())
    assert "trop long" in texte


def test_sans_modele_installe_on_le_dit(tmp_path):
    fichier = _wav(tmp_path, secondes=0.2)
    texte = lf.transcrire_audio(str(fichier), moteur=None, models_dir=None)
    assert "n'est pas installé" in texte


def test_un_wav_sans_parole_le_dit(tmp_path):
    class Muet(_FauxMoteur):
        def recognizer(self, *a, **k):
            rec = _FauxRec(self.journal)
            rec.FinalResult = lambda: json.dumps({"text": ""})
            return rec

    fichier = _wav(tmp_path, secondes=0.2)
    texte = lf.transcrire_audio(str(fichier), moteur=Muet())
    assert "aucune parole" in texte


# --------------------------------------------------------------------------- l'aiguillage et la coupe
def test_laiguillage_renvoie_vers_read_file_pour_du_texte(tmp_path):
    fichier = tmp_path / "notes.txt"
    fichier.write_text("bonjour", encoding="utf-8")
    assert "read_file" in lf.lire_document(str(fichier))


def test_laiguillage_explique_quoi_faire_pour_une_video(tmp_path):
    fichier = tmp_path / "film.mp4"
    fichier.write_bytes(b"0000")
    texte = lf.lire_document(str(fichier))
    assert "exporte la piste en WAV" in texte


def test_un_texte_trop_long_est_coupe_en_le_disant():
    texte = lf._tronquer("a" * (lf.MAX_CARACTERES + 500))
    assert "coupé" in texte
    assert len(texte) < lf.MAX_CARACTERES + 200
