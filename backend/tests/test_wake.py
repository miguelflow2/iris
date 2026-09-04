"""Détection du mot d'activation : grammaire Vosk, faux positifs, rattrapage de la commande.

Les tests qui ont besoin du modèle Vosk français sont ignorés s'il n'est pas installé sur la machine.
Les fichiers audio de référence sont générés une fois dans release/wake-test/ (voix de synthèse française).
"""
from __future__ import annotations

import json
import os
import wave
from pathlib import Path

import pytest

from iris.voice.listener import contains_wake, find_wake_phrase, normalize, wake_phrases

WAKE = "Dis-moi Iris"
ALIASES = ["dis moi iris", "dis iris", "iris", "dit moi iris"]
AUDIO_DIR = Path(__file__).resolve().parents[2] / "release" / "wake-test"


def _model_path() -> Path | None:
    p = Path(os.path.expandvars(r"%APPDATA%\IRIS\iris-data\models\vosk-model-small-fr-0.22"))
    return p if p.is_dir() else None


# --------------------------------------------------------------------------- sans modèle
def test_wake_phrases_normalise_et_dedoublonne():
    phrases = wake_phrases(WAKE, ALIASES)
    assert phrases[0] == "dis moi iris"
    assert len(phrases) == len(set(phrases))
    assert "iris" in phrases


@pytest.mark.parametrize(
    "words, attendu",
    [
        (["dis", "moi", "iris"], 3),
        (["dis", "iris"], 2),
        (["iris"], 1),
        (["dis"], -1),  # mot isolé de la grammaire : ce n'est pas une activation
        (["moi"], -1),
        ([], -1),
    ],
)
def test_find_wake_phrase(words, attendu):
    assert find_wake_phrase(words, wake_phrases(WAKE, ALIASES)) == attendu


@pytest.mark.parametrize("phrase", ["j irais bien au cinema", "ris", "dis moi i risque", "le riz est cuit"])
def test_contains_wake_refuse_les_faux_positifs(phrase):
    """Ces phrases déclenchaient IRIS avant le durcissement de la correspondance d'un alias d'un seul mot."""
    found, _rest = contains_wake(phrase, WAKE, aliases=ALIASES)
    assert not found, f"faux positif sur {phrase!r}"


@pytest.mark.parametrize(
    "phrase, reste",
    [
        ("dis moi iris ouvre mon navigateur", "ouvre mon navigateur"),
        ("dis iris quelle heure est il", "quelle heure est il"),
        ("iris ouvre youtube", "ouvre youtube"),
    ],
)
def test_contains_wake_accepte_et_rend_la_commande(phrase, reste):
    found, rest = contains_wake(phrase, WAKE, aliases=ALIASES)
    assert found and rest == reste


# --------------------------------------------------------------------------- avec le modèle Vosk
def _read_wav_16k(path: Path) -> bytes:
    with wave.open(str(path)) as w:
        assert w.getframerate() == 16000 and w.getnchannels() == 1
        return w.readframes(w.getnframes())


@pytest.mark.skipif(_model_path() is None, reason="modèle Vosk français absent")
@pytest.mark.skipif(not AUDIO_DIR.is_dir(), reason="échantillons audio absents")
def test_grammaire_detecte_ce_que_le_plein_vocabulaire_perd():
    """« Dis-moi Iris » et « Iris » sont perdus en plein vocabulaire (mesuré : « dis-moi », « arès »).
    La grammaire restreinte les reconnaît, et refuse les phrases sans mot d'activation."""
    from iris.voice.stt import VoskEngine

    engine = VoskEngine(_model_path())
    phrases = wake_phrases(WAKE, ALIASES)
    cas = {"w0.wav": True, "w1.wav": True, "w2.wav": True, "w3.wav": True, "w4.wav": False, "w5.wav": False}
    for nom, attendu in cas.items():
        fichier = AUDIO_DIR / nom
        if not fichier.exists():
            continue
        rec = engine.recognizer(phrases, words=True)
        rec.AcceptWaveform(_read_wav_16k(fichier))
        mots = [m for m in VoskEngine.text_of(rec.FinalResult()).split() if m != "[unk]"]
        detecte = find_wake_phrase(mots, phrases) >= 0
        assert detecte is attendu, f"{nom} : détecté={detecte}, attendu={attendu} (mots {mots})"


@pytest.mark.skipif(_model_path() is None, reason="modèle Vosk français absent")
@pytest.mark.skipif(not (AUDIO_DIR / "w1.wav").exists(), reason="échantillon audio absent")
def test_commande_dite_dans_le_meme_souffle_est_rejouee():
    """« Dis-moi Iris, ouvre mon navigateur » : la grammaire rend « [unk] » pour la commande.
    Les horodatages de mots permettent de rejouer cet audio dans le reconnaisseur complet."""
    from iris.voice import stt
    from iris.voice.stt import VoskEngine

    engine = VoskEngine(_model_path())
    phrases = wake_phrases(WAKE, ALIASES)
    pcm = _read_wav_16k(AUDIO_DIR / "w1.wav")

    rec = engine.recognizer(phrases, words=True)
    resultat, pending, offset = "", [], 0
    for i in range(0, len(pcm), 8000):
        bloc = pcm[i : i + 8000]
        pending.append((offset, bloc))
        offset += len(bloc) // 2
        if rec.AcceptWaveform(bloc):
            resultat = rec.Result()
            break
    resultat = resultat or rec.FinalResult()
    mots = [m for m in VoskEngine.text_of(resultat).split() if m != "[unk]"]
    cut = find_wake_phrase(mots, phrases)
    assert cut > 0

    parles = [m for m in (json.loads(resultat).get("result") or []) if m.get("word") != "[unk]"]
    fin_activation = float(parles[cut - 1]["end"])
    assert (len(pcm) / 2 / stt.SAMPLE_RATE) - fin_activation >= 0.3  # il reste bien de la parole après « Iris »

    # On rejoue l'énoncé entier dans le reconnaisseur complet, puis on retire le mot d'activation du texte.
    rec2 = engine.recognizer()
    rec2.AcceptWaveform(pcm)
    tout = VoskEngine.text_of(rec2.FinalResult())
    trouve, commande = contains_wake(tout, WAKE, aliases=ALIASES)
    assert trouve, f"mot d'activation absent du rejeu : {tout!r}"
    assert "ouvre" in commande and "navigateur" in commande, f"commande rejouée : {commande!r}"
