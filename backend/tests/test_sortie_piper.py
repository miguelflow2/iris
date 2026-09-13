"""Par où sort la voix Piper (française, hors-ligne), et qu'elle reste une voix — jamais muette.

Piper est le pilier du « mode indépendant » : IRIS parle français sans clé, sans réseau, même si
tout le nuage est coupé. La SOURCE du PCM est locale (le modèle ONNX), mais le chemin de sortie est
exactement celui d'ElevenLabs — routage vers le canal mains libres des lunettes, rééchantillonnage
quand le périphérique refuse le taux natif du modèle (22050 Hz). Ces promesses-là sont donc revérifiées
ici, pour la source locale :

1. la sortie demandée (les lunettes) est bien celle qui s'ouvre ;
2. un périphérique qui refuse 22050 Hz est ouvert à sa fréquence et le flux est rééchantillonné,
   pas abandonné vers le haut-parleur du PC ;
3. jamais muette : si aucune sortie ne s'ouvre, la voix Windows reprend la phrase.

Aucun son n'est joué. Le modèle Piper lui-même est remplacé par un faux qui rend un PCM connu — sauf
un unique test de bout en bout (`test_le_vrai_modele_...`) qui charge le vrai modèle s'il est présent,
pour prouver que le câblage réel produit bien de l'audio français.
"""
from __future__ import annotations

import logging
import sys

import numpy as np
import pytest

from iris.config import Settings
from iris.voice.elevenlabs import Reechantillonneur, SortieAudioIndisponible
from iris.voice.piper import PRECHAUFFAGE, SAMPLE_RATE, PiperSpeaker, trouver_modele

# On réutilise les faux périphériques du test ElevenLabs : c'est la même machine, les mêmes lunettes.
from tests.test_sortie_elevenlabs import (
    HAUT_PARLEURS,
    MAINS_LIBRES_COMPLET,
    MAINS_LIBRES_MME,
    STEREO,
    FauxHub,
    FauxSounddevice,
    _lunettes_allumees,
    _sortie,
)


class FauxChunk:
    """Un morceau audio Piper : seul `audio_int16_bytes` est lu par _stream_and_play."""

    def __init__(self, data: bytes):
        self.audio_int16_bytes = data
        self.sample_rate = SAMPLE_RATE
        self.sample_width = 2
        self.sample_channels = 1


class FauxVoix:
    """PiperVoice sans ONNX : rend un PCM connu, découpé en morceaux comme le vrai le ferait."""

    def __init__(self, pcm: bytes, morceaux: int = 3):
        self.pcm = pcm
        self.morceaux = morceaux
        self.config = type("Cfg", (), {"sample_rate": SAMPLE_RATE})()

    def synthesize(self, text: str):
        pas = max(2, (len(self.pcm) // self.morceaux) & ~1)  # frontières paires (int16)
        for debut in range(0, len(self.pcm), pas):
            yield FauxChunk(self.pcm[debut : debut + pas])


def _rampe(n: int = SAMPLE_RATE) -> bytes:
    """Une seconde de PCM 22050 Hz dont chaque échantillon vaut son rang : tout saut se voit."""
    return np.arange(n, dtype="<i2").tobytes()


def _voix(data_dir, sd: FauxSounddevice, sortie: str = "", micro: str = "", pcm: bytes | None = None):
    settings = Settings(data_dir)
    settings.user.audio_output_device = sortie
    settings.user.audio_input_device = micro
    hub = FauxHub()
    sp = PiperSpeaker(settings, hub)
    sp._sounddevice = lambda: sd
    sp._charger = lambda: FauxVoix(pcm if pcm is not None else _rampe())  # pas d'ONNX chargé
    sp._voice_rate = SAMPLE_RATE
    return sp, hub


# --------------------------------------------------------------------------- présence du modèle
def test_configured_suit_la_presence_du_fichier_de_voix(data_dir):
    """Piper est « configuré » dès que le .onnx et son .json sont sur le disque — aucune clé requise."""
    settings = Settings(data_dir)
    sp = PiperSpeaker(settings, FauxHub())
    # Sur cette machine de dev le modèle fr_FR-siwis-medium est présent : configured doit être vrai.
    attendu = trouver_modele(settings.user.piper_voice) is not None
    assert sp.configured is attendu
    if attendu:
        assert sp.available is True


def test_une_voix_absente_desactive_piper_proprement(data_dir):
    """Si l'assertion tombe, une install sans modèle fait planter la synthèse au lieu de replier."""
    settings = Settings(data_dir)
    settings.user.piper_voice = "voix_qui_nexiste_pas"
    sp = PiperSpeaker(settings, FauxHub())
    assert sp.configured is False
    assert sp.available is False
    assert sp.speak("Bonjour") is False, "un speak sans voix ne doit rien mettre en file"


# --------------------------------------------------------------------------- le périphérique demandé
def test_la_sortie_demandee_est_bien_celle_qui_est_ouverte(data_dir):
    """Si l'assertion tombe, la voix française locale sort du PC pendant que Miguel porte ses lunettes."""
    sd = FauxSounddevice(_lunettes_allumees())
    sp, _hub = _voix(data_dir, sd, sortie=STEREO)
    sp._stream_and_play("Bonjour")
    assert len(sd.flux) == 1
    assert sd.flux[0].device == 2
    assert sd.flux[0].samplerate == SAMPLE_RATE  # MME accepte 22050 : rien à convertir
    assert sd.flux[0].echantillons == SAMPLE_RATE


def test_une_sortie_qui_refuse_22khz_est_ouverte_a_sa_frequence_et_reechantillonnee(data_dir, caplog):
    """Le canal mains libres impose 16 kHz : on convertit 22050 → 16000, on n'abandonne pas."""
    caplog.set_level(logging.INFO, logger="iris.piper")
    peripheriques = [_sortie(HAUT_PARLEURS), _sortie(MAINS_LIBRES_COMPLET, hote=1, taux=16000, voies=1)]
    sd = FauxSounddevice(peripheriques, refus={(1, SAMPLE_RATE)})
    sp, hub = _voix(data_dir, sd, sortie=MAINS_LIBRES_MME, micro=MAINS_LIBRES_MME)
    sp._stream_and_play("Bonjour")
    assert len(sd.flux) == 1
    assert sd.flux[0].device == 1
    assert sd.flux[0].samplerate == 16000
    ratio = 16000 / SAMPLE_RATE
    assert abs(sd.flux[0].echantillons - SAMPLE_RATE * ratio) <= 3
    assert "rééchantillonnée depuis 22050" in caplog.text
    assert hub.evenements == []  # la sortie demandée a parlé : aucune alerte


def test_le_mains_libres_lemporte_quand_le_micro_est_mains_libres(data_dir):
    """Même règle partagée que Windows et ElevenLabs : micro mains libres → sortie mains libres."""
    sd = FauxSounddevice(_lunettes_allumees())
    sp, _hub = _voix(data_dir, sd, sortie=STEREO, micro=MAINS_LIBRES_MME)
    idx, taux = sp._output_device(sd)
    assert idx == 3, "le canal mains libres du même casque, sous l'hôte le plus tolérant"
    assert taux == SAMPLE_RATE


def test_un_reglage_vide_laisse_la_sortie_par_defaut_au_taux_du_modele(data_dir):
    sd = FauxSounddevice(_lunettes_allumees())
    sp, hub = _voix(data_dir, sd, sortie="")
    assert sp._output_device(sd) == (None, SAMPLE_RATE)
    assert hub.evenements == []


# --------------------------------------------------------------------------- jamais muette
def test_quand_aucune_sortie_ne_souvre_la_voix_windows_prend_le_relais(data_dir, caplog):
    """La promesse au-dessus des autres : quoi qu'il arrive, IRIS parle — ici via le repli Windows."""
    caplog.set_level(logging.WARNING, logger="iris.piper")
    sd = FauxSounddevice(_lunettes_allumees(), injouables={2, "defaut"})
    sp, hub = _voix(data_dir, sd, sortie=STEREO)
    repris = []
    sp.fallback_speak = lambda texte: repris.append(texte) or True
    with pytest.raises(SortieAudioIndisponible) as info:
        sp._stream_and_play("Bonjour")
    sp._handle_failure(info.value, "Bonjour")  # ce que fait _worker
    assert repris == ["Bonjour"]
    assert any(t == "tts.fallback" for t, _ in hub.evenements)


def test_un_repli_windows_qui_echoue_est_ecrit_dans_le_journal(data_dir, caplog):
    caplog.set_level(logging.WARNING, logger="iris.piper")
    sd = FauxSounddevice(_lunettes_allumees())
    sp, _hub = _voix(data_dir, sd, sortie=STEREO)
    sp.fallback_speak = lambda texte: False  # synthèse Windows indisponible
    sp._handle_failure(RuntimeError("modèle corrompu"), "Bonjour")
    assert "phrase perdue" in caplog.text


# --------------------------------------------------------------------------- le préchauffage
def test_le_prechauffage_ouvre_la_sortie_demandee_sans_un_son(data_dir, caplog):
    """Le casque bascule en profil téléphone : autant que ce soit avant le premier « Dis-moi Iris »."""
    caplog.set_level(logging.INFO, logger="iris.piper")
    sd = FauxSounddevice(_lunettes_allumees())
    sp, hub = _voix(data_dir, sd, sortie=STEREO, micro=MAINS_LIBRES_MME)
    sp._prechauffer_maintenant()
    assert len(sd.flux) == 1
    assert sd.flux[0].device == 3, "la sortie qui va parler : le mains libres, sous MME"
    assert sd.flux[0].ecrit and set(sd.flux[0].ecrit) == {0}, "que des zéros : personne n'entend rien"
    assert not any(t == "tts.state" for t, _ in hub.evenements)
    assert sp.speaking is False
    assert "préchauffée" in caplog.text


def test_le_prechauffage_passe_par_la_file_sans_demarrer_de_parole(data_dir, monkeypatch):
    sd = FauxSounddevice(_lunettes_allumees())
    sp, _hub = _voix(data_dir, sd, sortie=STEREO)
    monkeypatch.setattr(sp, "_ensure_thread", lambda: None)
    sp.prechauffer()
    assert sp._queue.get_nowait() is PRECHAUFFAGE
    assert not isinstance(PRECHAUFFAGE, str)
    assert sp._idle.is_set(), "préchauffer n'est pas parler"


# --------------------------------------------------------------------------- le vrai modèle
# Preuve que le vrai ONNX se charge et rend de l'audio français — mais dans un SOUS-PROCESSUS.
# Charger onnxruntime dans le processus pytest (qui a déjà initialisé COM/pyttsx3, sounddevice,
# vosk...) corrompt le tas sous Windows (0xc0000374) : le crash n'est pas dans Piper, c'est la
# cohabitation de tous ces moteurs natifs dans un même processus de test. En production, IRIS ne
# charge JAMAIS Piper dans un tel processus (le backend n'importe pas pytest), donc l'isolation ici
# reflète mieux le réel que ne le ferait un chargement en ligne. Le câblage de _stream_and_play est
# couvert au-dessus par FauxVoix (vrais morceaux, vrai rééchantillonnage) ; ce test-ci ne vérifie
# qu'une chose de plus : le modèle réel produit bien de l'audio 22050 Hz non vide.
_EXTRAIT_SYNTHESE = """
import sys
from piper import PiperVoice
v = PiperVoice.load(sys.argv[1])
n = 0
sr = 0
for c in v.synthesize("Bonjour, il est quatorze heures trente."):
    n += len(c.audio_int16_bytes)
    sr = c.sample_rate
print(f"{n} {sr}")
"""


@pytest.mark.skipif(trouver_modele("fr_FR-siwis-medium") is None, reason="modèle Piper fr_FR-siwis-medium absent")
def test_le_vrai_modele_produit_de_laudio_francais_a_22khz():
    """Bout en bout, dans un sous-processus : le vrai ONNX se charge et rend du PCM 22050 Hz non vide."""
    import subprocess

    modele = trouver_modele("fr_FR-siwis-medium")
    res = subprocess.run(
        [sys.executable, "-c", _EXTRAIT_SYNTHESE, str(modele)],
        capture_output=True, text=True, timeout=120,
    )
    assert res.returncode == 0, f"la synthèse Piper a échoué : {res.stderr[-500:]}"
    octets, taux = (int(x) for x in res.stdout.split())
    assert taux == SAMPLE_RATE
    assert octets > SAMPLE_RATE, "au moins une demi-seconde d'audio réel (int16 : 2 octets/échantillon)"
