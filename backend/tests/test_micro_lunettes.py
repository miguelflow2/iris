"""Le micro des lunettes VELA : choisir le bon périphérique, dire sa disparition, tenir la qualité téléphone.

AUCUN test n'ouvre de micro ni ne joue de son : les périphériques sont injectés. Les tables
reproduisent l'énumération relevée sur la machine de Miguel le 2026-09-04, lunettes « M01 Pro_F444 »
appairées et connectées (`sd.query_devices()`, aucun flux ouvert).
"""
from __future__ import annotations

import sys
import time

import pytest

from iris.voice.listener import MICRO_MUET, choisir_peripherique, frequence_native

MME, DSOUND, WASAPI, WDMKS = 0, 1, 2, 3
HOTES = [{"name": "MME"}, {"name": "Windows DirectSound"}, {"name": "Windows WASAPI"}, {"name": "Windows WDM-KS"}]


def _dev(nom: str, hote: int, entrees: int = 0, sorties: int = 0, taux: float = 44100.0) -> dict:
    return {"name": nom, "hostapi": hote, "max_input_channels": entrees,
            "max_output_channels": sorties, "default_samplerate": taux}


# Relevé du 2026-09-04. Les index d'origine sont en commentaire : ce qui compte ici est l'ORDRE,
# puisque c'est lui qui piégeait l'ancien code (il retenait le premier nom correspondant).
# Noter le nom tronqué à 31 caractères sous MME : « Casque (M01 Pro_F444 Hands-Free », sans
# « AG Audio ». C'est cette forme-là que l'interface enregistre dans les réglages.
PERIPHERIQUES = [
    _dev("Microphone (Realtek(R) Audio)", MME, entrees=2),                                  # micro du PC
    _dev("Casque (M01 Pro_F444 Hands-Free", MME, entrees=1),                                # 2  : LE bon micro
    _dev("Casque (M01 Pro_F444 Stereo)", MME, sorties=2),                                   # 4  : sortie A2DP
    _dev("Casque (M01 Pro_F444 Hands-Free", MME, sorties=1),                                # 5  : sortie, MÊME nom
    _dev("Casque (M01 Pro_F444 Hands-Free AG Audio)", WASAPI, sorties=1, taux=16000.0),     # 15
    _dev("Casque (M01 Pro_F444 Hands-Free AG Audio)", WASAPI, entrees=1, taux=16000.0),     # 17
    _dev("bthhfenum.sys (M01 Pro_F444)", WDMKS, sorties=1, taux=16000.0),                   # 25
    _dev("bthhfenum.sys (M01 Pro_F444)", WDMKS, entrees=1, taux=16000.0),                   # 26
    _dev("bthhfenum.sys (GT TWS)", WDMKS, entrees=1, taux=8000.0),                          # 22 : l'autre casque
]

SANS_LUNETTES = [_dev("Microphone (Realtek(R) Audio)", MME, entrees=2)]

# Même nom, même hôte, mais la SORTIE énumérée en premier : c'est exactement le piège que tendait
# le parcours d'index d'origine. Ordre construit, pas mesuré — il verrouille l'invariant.
SORTIE_EN_PREMIER = [
    _dev("Casque (GT TWS Hands-Free", MME, sorties=1),
    _dev("Casque (GT TWS Hands-Free", MME, entrees=1, taux=8000.0),
]

# Le nom exact est porté par WASAPI, le nom qui le contient par MME (l'hôte préféré) : seule la
# règle du nom exact peut départager, la préférence d'hôte tirerait dans l'autre sens.
NOM_EXACT_CONTRE_HOTE = [
    _dev("Casque (M01 Pro_F444 Hands-Free AG Audio)", MME, entrees=1),
    _dev("Casque (M01 Pro_F444 Hands-Free", WASAPI, entrees=1, taux=16000.0),
]


class _Sd:
    """Faux module sounddevice : énumération seule, aucun flux, aucun micro ouvert."""

    def __init__(self, devices: list[dict]):
        self._devices = devices

    def query_devices(self, *args, **kwargs):
        return self._devices

    def query_hostapis(self, *args, **kwargs):
        return HOTES


@pytest.fixture()
def evenements(app, monkeypatch):
    """Ce qu'IRIS publie vers l'interface, sans WebSocket : (type, données)."""
    recus: list[tuple[str, dict]] = []
    monkeypatch.setattr(app.state.ctx.hub, "publish", lambda type_, **data: recus.append((type_, data)) or {})
    return recus


def _alertes(evenements, type_: str = "voice.warning") -> list[str]:
    return [data.get("text", "") for nom, data in evenements if nom == type_]


# --------------------------------------------------------------- 1. trouver le bon périphérique
def test_le_micro_des_lunettes_est_choisi_parmi_ses_homonymes():
    """Six périphériques portent « M01 Pro_F444 ». Si le choix tombait ailleurs, IRIS ouvrirait la
    broche WDM-KS du noyau (souvent déjà prise) ou un point de sortie, et n'entendrait rien."""
    assert choisir_peripherique(PERIPHERIQUES, HOTES, "M01 Pro_F444") == 1


def test_une_sortie_ne_peut_jamais_etre_prise_pour_un_micro():
    """« Casque (M01 Pro_F444 Stereo) » n'a aucun canal d'entrée : le retenir ferait échouer
    l'ouverture du flux et Miguel croirait ses lunettes en panne."""
    assert choisir_peripherique(PERIPHERIQUES, HOTES, "M01 Pro_F444 Stereo") is None


def test_la_sortie_enumeree_avant_lentree_ne_gagne_pas():
    """Deux périphériques portent le même nom, la sortie d'abord. Sans le filtre par le sens, on
    ouvrirait un haut-parleur en croyant ouvrir un micro."""
    assert choisir_peripherique(SORTIE_EN_PREMIER, HOTES, "GT TWS") == 1


def test_le_nom_exact_lemporte_sur_le_nom_qui_le_contient():
    """L'interface enregistre le nom MME tronqué à 31 caractères, et ce nom est aussi CONTENU dans
    le nom complet annoncé par WASAPI. Sans cette règle, choisir un périphérique dans la liste
    n'aurait pas garanti d'ouvrir celui-là."""
    assert choisir_peripherique(NOM_EXACT_CONTRE_HOTE, HOTES, "Casque (M01 Pro_F444 Hands-Free") == 1


def test_aucun_micro_demande_veut_dire_micro_par_defaut():
    """Réglage vide = « laisse Windows décider ». Retourner un index ici imposerait un micro que
    personne n'a choisi."""
    assert choisir_peripherique(PERIPHERIQUES, HOTES, "") is None
    assert choisir_peripherique(PERIPHERIQUES, HOTES, "   ") is None


def test_le_micro_est_retrouve_a_partir_du_nom_enregistre_dans_les_reglages(app):
    """Bout en bout depuis le réglage réel : c'est la chaîne qui décide si « Dis-moi Iris » est
    entendu dans les lunettes ou dans le micro du portable."""
    voice = app.state.ctx.voice
    app.state.ctx.settings.update({"audio_input_device": "Casque (M01 Pro_F444 Hands-Free"})
    assert voice._input_device(_Sd(PERIPHERIQUES)) == 1


# --------------------------------------------------------------- 2. dire la disparition du micro
def test_le_micro_disparu_est_dit_a_lutilisateur(app, evenements):
    """Se rabattre en silence sur le micro du PC était le pire des comportements : IRIS écoutait
    l'ordinateur pendant que Miguel parlait dans ses lunettes, sans une erreur nulle part."""
    voice = app.state.ctx.voice
    app.state.ctx.settings.update({"audio_input_device": "Casque (M01 Pro_F444 Hands-Free"})
    assert voice._input_device(_Sd(SANS_LUNETTES)) is None
    textes = _alertes(evenements)
    assert len(textes) == 1
    assert "M01 Pro_F444" in textes[0] and "lunettes" in textes[0].lower()


def test_le_meme_avertissement_nest_jamais_repete(app, evenements):
    """Le chien de garde relance l'écoute toutes les 20 s tant qu'elle ne tourne pas : sans ce
    filtre, un micro absent ferait surgir la même fenêtre trois fois par minute, et un
    avertissement qu'on apprend à ignorer ne vaut pas mieux que le silence qu'on corrige."""
    voice = app.state.ctx.voice
    app.state.ctx.settings.update({"audio_input_device": "Casque (M01 Pro_F444 Hands-Free"})
    for _ in range(3):
        voice._input_device(_Sd(SANS_LUNETTES))
    assert len(_alertes(evenements)) == 1


def test_un_micro_qui_remarche_rouvre_le_droit_de_prevenir(app, evenements):
    """Sinon une panne qui revient des heures plus tard serait filtrée comme un doublon et Miguel
    ne saurait jamais que ses lunettes ont décroché."""
    voice = app.state.ctx.voice
    app.state.ctx.settings.update({"audio_input_device": "Casque (M01 Pro_F444 Hands-Free"})
    voice._input_device(_Sd(SANS_LUNETTES))
    voice._alertes_dites.clear()  # ce que fait `_run` dès que le flux s'ouvre pour de bon
    voice._input_device(_Sd(SANS_LUNETTES))
    assert len(_alertes(evenements)) == 2


def test_le_micro_devenu_muet_arrete_lecoute_et_dit_quoi_faire(app, evenements):
    """Des lunettes qui s'éteignent ne lèvent aucune exception : PortAudio garde le flux « actif »
    et cesse d'appeler le callback. Sans ce garde-fou, IRIS resterait en écoute devant un micro
    mort, sans un mot, et « Dis-moi Iris » ne réveillerait plus rien."""
    voice = app.state.ctx.voice
    voice.device_name = "Casque (M01 Pro_F444 Hands-Free"
    voice._last_block = time.time() - (MICRO_MUET + 1)
    voice._stop.clear()
    assert voice._read(timeout=0.01) is None
    assert voice._stop.is_set(), "l'écoute doit se dénouer, pas continuer dans le vide"
    # Arbitrage du 5 septembre 2026, contre la version precedente de ce test. On ne pose PAS
    # `stopped_by_user` : ce drapeau empeche le chien de garde de jamais reessayer, et IRIS se
    # tairait definitivement parce que des lunettes ont manque d'air une fois. Le 8 septembre,
    # devant les dragons, une assistante qui reessaie toutes les vingt secondes vaut infiniment
    # mieux qu'une assistante muette pour de bon. Ce que le drapeau evitait — l'alerte repetee —
    # est traite ailleurs : `_alerter` ne redit rien deux fois.
    assert not voice.stopped_by_user, "se taire pour toujours est pire que reessayer"
    textes = _alertes(evenements)
    assert len(textes) == 1
    assert "M01 Pro_F444" in textes[0] and "rallumez" in textes[0].lower()
    assert voice.error and "M01 Pro_F444" in voice.error


def test_un_micro_qui_repond_encore_ne_declenche_aucune_alerte(app, evenements):
    """Une file momentanément vide n'est pas une panne : couper l'écoute au moindre blanc rendrait
    IRIS inutilisable, et c'est le cas le plus fréquent puisqu'on lit plus vite qu'on n'enregistre."""
    voice = app.state.ctx.voice
    voice._last_block = time.time()
    voice._stop.clear()
    assert voice._read(timeout=0.01) is None
    assert not voice._stop.is_set()
    assert _alertes(evenements) == []


def test_avant_le_premier_bloc_rien_nest_signale(app, evenements):
    """Au démarrage, `_last_block` vaut 0 : sans ce garde-fou, l'écoute s'arrêterait avant même
    d'avoir commencé, en accusant les lunettes."""
    voice = app.state.ctx.voice
    voice._last_block = 0.0
    voice._stop.clear()
    assert voice._micro_perdu() is False
    assert _alertes(evenements) == []


def test_le_compromis_mono_des_lunettes_est_annonce_une_seule_fois(app, evenements):
    """Le Bluetooth ne porte qu'un lien audio : micro ouvert, la stéréo des lunettes se tait. Le
    taire ferait croire à une panne de son ; le répéter à chaque écoute serait du harcèlement."""
    voice = app.state.ctx.voice
    voice._mono_annonce = False
    voice._prevenir_mono()
    voice._prevenir_mono()
    textes = _alertes(evenements, "voice.info")
    assert len(textes) == 1 and "mono" in textes[0].lower()


# --------------------------------------------------------------- 3. la qualité téléphone
def test_la_frequence_annoncee_par_mme_ne_fait_pas_foi():
    """MME annonce 44100 Hz pour un lien réellement à 16000 Hz. Si on le croyait, la détection de
    bande étroite serait morte et les lunettes passeraient pour un micro large bande."""
    assert frequence_native(PERIPHERIQUES, "M01 Pro_F444") == 16000.0
    assert frequence_native(PERIPHERIQUES, "GT TWS") == 8000.0
    assert frequence_native(PERIPHERIQUES, "Realtek") == 44100.0
    assert frequence_native(PERIPHERIQUES, "casque introuvable") == 0.0


def test_un_casque_sans_hands_free_dans_son_nom_reste_reconnu(app, monkeypatch):
    """Le nom anglais reste le test principal, mais un casque nommé autrement doit encore être
    reconnu comme bande étroite, sinon IRIS le traiterait comme un micro large bande."""
    voice = app.state.ctx.voice
    app.state.ctx.settings.update({"audio_input_device": "GT TWS"})
    monkeypatch.setitem(sys.modules, "sounddevice", _Sd(PERIPHERIQUES))
    assert voice._narrowband_input() is True


def test_le_micro_du_pc_nest_pas_pris_pour_un_micro_telephone(app, monkeypatch):
    """Croire le micro interne en bande étroite ferait choisir les mauvais compromis de traitement
    pour le seul micro qui capte vraiment large."""
    voice = app.state.ctx.voice
    app.state.ctx.settings.update({"audio_input_device": "Realtek"})
    monkeypatch.setitem(sys.modules, "sounddevice", _Sd(PERIPHERIQUES))
    assert voice._narrowband_input() is False


def _sinus(taux: int, secondes: float, hz: float = 440.0) -> bytes:
    import numpy as np

    t = np.arange(int(taux * secondes)) / taux
    return (np.sin(2 * np.pi * hz * t) * 8000).astype(np.int16).tobytes()


def _passages_a_zero(pcm: bytes) -> int:
    import numpy as np

    return int(np.count_nonzero(np.diff(np.signbit(np.frombuffer(pcm, dtype=np.int16).astype(np.int32)))))


def test_les_lunettes_a_16_khz_ne_sont_pas_reechantillonnees(app):
    """Le lien mains libres de ces lunettes fournit 16 kHz, exactement ce que Vosk attend
    (`stt.SAMPLE_RATE`). Un rééchantillonnage inutile ne pourrait qu'abîmer le signal."""
    voice = app.state.ctx.voice
    voice._native_rate = 16000
    pcm = _sinus(16000, 0.25)
    assert voice._resample(pcm) is pcm  # le même objet : rien n'a été touché


def test_le_bloc_de_44100_de_mme_redescend_a_exactement_4000_echantillons(app):
    """MME livre des blocs de 11025 échantillons pour un lien réellement à 16 kHz. S'ils ne
    redescendaient pas à exactement 4000, un résidu s'accumulerait de bloc en bloc et la parole
    dériverait peu à peu — c'est ce rapport entier qui rend l'interpolation linéaire acceptable."""
    voice = app.state.ctx.voice
    voice._native_rate = 44100
    bloc = _sinus(44100, 11025 / 44100)
    assert len(bloc) // 2 == 11025
    sortie = voice._resample(bloc)
    assert len(sortie) // 2 == 4000
    assert abs(_passages_a_zero(sortie) - _passages_a_zero(bloc)) <= 2, "la hauteur du son a changé"


def test_un_casque_a_8_khz_est_remonte_a_16_khz(app):
    """Le « GT TWS » appairé sur cette machine ne fournit que 8 kHz. Sans cette montée, Vosk
    recevrait un signal deux fois trop lent et n'entendrait plus jamais le mot d'activation."""
    voice = app.state.ctx.voice
    voice._native_rate = 8000
    bloc = _sinus(8000, 0.25)
    sortie = voice._resample(bloc)
    assert len(sortie) == 2 * len(bloc)
    assert abs(_passages_a_zero(sortie) - _passages_a_zero(bloc)) <= 2, "la hauteur du son a changé"


def test_le_mot_dactivation_reste_hors_ligne_avec_le_micro_des_lunettes(app, monkeypatch):
    """Basculer TOUT le cycle vers Google parce que le micro est en qualité téléphone envoyait le
    salon en continu par segments de 6 s et rendait la réponse en moins de 5 s impossible — alors
    que c'est justement en bande étroite que la grammaire restreinte est la plus sûre."""
    voice = app.state.ctx.voice
    app.state.ctx.settings.update(
        {"audio_input_device": "Casque (M01 Pro_F444 Hands-Free", "stt_engine": "auto", "local_only": False}
    )
    monkeypatch.setattr(voice, "model_ready", lambda: True)
    monkeypatch.setattr(voice.consent, "is_granted", lambda *a, **k: True)
    assert voice._choose_engine() == "vosk"
