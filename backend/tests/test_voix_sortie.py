"""Par où sort la voix Windows d'IRIS : le réglage « audio_output_device » doit atteindre SAPI.

Sur le forfait Gratuit, IRIS parle avec la voix de Windows (pyttsx3/SAPI5) et non avec ElevenLabs.
Ce chemin-là ignorait totalement le périphérique choisi : la voix suivait la sortie par défaut du
système, donc les haut-parleurs du PC dès que Windows bascule — exactement pendant « Dis-moi Iris »,
où le micro mains libres des lunettes met le profil stéréo en veille.

Aucun son n'est joué ici et aucun périphérique réel n'est touché : le moteur est un faux qui expose
le même chemin d'accès à SAPI que pyttsx3 (engine.proxy._driver._tts).
"""
from __future__ import annotations

import pytest

from iris.config import Settings
from iris.voice.tts import TextToSpeech

# Les trois sorties réellement vues par SAPI sur la machine de Miguel (relevé du 2026-09-04).
STEREO = "Casque (M01 Pro_F444 Stereo)"
MAINS_LIBRES = "Casque (M01 Pro_F444 Hands-Free AG Audio)"
HAUT_PARLEURS = "Haut-parleurs (High Definition Audio Device)"

INTACT = object()  # sentinelle : AudioOutput n'a jamais été assigné


class FauxJeton:
    """Jeton de sortie SAPI : SAPI ne prend pas un nom, mais un de ces objets."""

    def __init__(self, description: str):
        self.description = description

    def GetDescription(self) -> str:  # noqa: N802 (nom imposé par l'API COM)
        return self.description


class FauxSapi:
    def __init__(self, descriptions: list[str]):
        self.jetons = [FauxJeton(d) for d in descriptions]
        self.AudioOutput = INTACT  # noqa: N815 (nom imposé par l'API COM)
        self.enumerations = 0

    def GetAudioOutputs(self):  # noqa: N802 (nom imposé par l'API COM)
        self.enumerations += 1
        return list(self.jetons)


class FauxMoteur:
    """Moteur pyttsx3 factice : mêmes propriétés, même objet SAPI caché, aucune parole."""

    def __init__(self, sapi=None):
        self.proxy = type("FauxProxy", (), {"_driver": type("FauxPilote", (), {"_tts": sapi})()})() if sapi else None
        self.proprietes: dict = {}

    def setProperty(self, nom, valeur):  # noqa: N802 (nom imposé par pyttsx3)
        self.proprietes[nom] = valeur


class FauxHub:
    def __init__(self):
        self.evenements: list[tuple[str, dict]] = []

    def publish(self, type_: str, **data):
        self.evenements.append((type_, data))
        return data


def _voix(data_dir, sortie: str = "", sorties_presentes: list[str] | None = None, micro: str = ""):
    settings = Settings(data_dir)
    settings.user.audio_output_device = sortie
    settings.user.audio_input_device = micro
    hub = FauxHub()
    # enabled=False : aucun thread, aucun moteur réel, aucun COM initialisé
    tts = TextToSpeech(settings, hub, enabled=False)
    sapi = FauxSapi(sorties_presentes if sorties_presentes is not None else [STEREO, MAINS_LIBRES, HAUT_PARLEURS])
    tts._engine = FauxMoteur(sapi)
    return tts, sapi, hub


def test_la_sortie_demandee_arrive_bien_jusqua_sapi(data_dir):
    """Si l'assertion tombe, IRIS parle par le haut-parleur du PC pendant que Miguel porte ses lunettes.

    Le nom demandé est celui qu'écrit main.py, tronqué à 31 caractères par MME : la correspondance
    partielle doit suffire à retrouver la description complète de SAPI.
    """
    tts, sapi, _hub = _voix(data_dir, sortie="Casque (M01 Pro_F444 Hands-Free")
    tts._apply_settings()
    assert sapi.AudioOutput.description == MAINS_LIBRES


def test_entre_les_deux_sorties_des_lunettes_c_est_hands_free_qui_gagne(data_dir):
    """Si l'assertion tombe, un nom générique choisit « Stereo », que Windows endort dès que le micro
    mains libres est ouvert — c'est-à-dire pendant tout « Dis-moi Iris » : voix inaudible."""
    tts, sapi, _hub = _voix(data_dir, sortie="M01 Pro_F444")
    tts._apply_settings()
    assert sapi.AudioOutput.description == MAINS_LIBRES


def test_avec_le_micro_mains_libres_la_sortie_stereo_demandee_est_redirigee_vers_le_mains_libres(data_dir):
    """Si l'assertion tombe, la configuration RÉELLE de Miguel parle dans le vide.

    Relevé dans %APPDATA%/IRIS le 6 septembre 2026 : micro « Casque (M01 Pro_F444 Hands-Free »,
    sortie « Casque (M01 Pro_F444 Stereo) » — nommée en toutes lettres, donc « M01 Pro_F444 » seul
    ne suffisait plus à retrouver le canal mains libres. Or dès que le micro mains libres écoute,
    Windows suspend la stéréo : la sortie demandée existe, mais rien n'en sort.
    """
    tts, sapi, _hub = _voix(data_dir, sortie=STEREO, micro="Casque (M01 Pro_F444 Hands-Free")
    tts._apply_settings()
    assert sapi.AudioOutput.description == MAINS_LIBRES


def test_sans_micro_mains_libres_la_sortie_stereo_demandee_est_respectee(data_dir):
    """Si l'assertion tombe, IRIS impose le 8 kHz mono du profil téléphone à quelqu'un qui n'écoute
    pas par les lunettes : la stéréo est alors bien vivante, et c'est elle qu'on a demandée."""
    tts, sapi, _hub = _voix(data_dir, sortie=STEREO, micro="")
    tts._apply_settings()
    assert sapi.AudioOutput.description == STEREO


def test_le_micro_mains_libres_ne_detourne_pas_une_sortie_dun_autre_appareil(data_dir):
    """Si l'assertion tombe, choisir les haut-parleurs du PC comme sortie (pour une démo dans une
    salle, micro dans les lunettes) envoie quand même la voix dans les lunettes."""
    tts, sapi, _hub = _voix(data_dir, sortie=HAUT_PARLEURS, micro="Casque (M01 Pro_F444 Hands-Free")
    tts._apply_settings()
    assert sapi.AudioOutput.description == HAUT_PARLEURS


def test_des_lunettes_absentes_laissent_parler_la_sortie_par_defaut(data_dir):
    """Si l'assertion tombe, IRIS lève ou se tait quand les lunettes sont éteintes.

    Rien ne doit être assigné (IRIS n'avait encore rien imposé : le défaut de Windows est vivant),
    et l'utilisateur doit être prévenu.
    """
    tts, sapi, hub = _voix(data_dir, sortie="M01 Pro_F444", sorties_presentes=[HAUT_PARLEURS])
    tts._apply_settings()
    assert sapi.AudioOutput is INTACT
    assert [t for t, _ in hub.evenements] == ["tts.fallback"]
    assert "M01 Pro_F444" in hub.evenements[0][1]["reason"]


def test_des_lunettes_eteintes_en_cours_de_route_ramenent_la_voix_sur_le_haut_parleur(data_dir):
    """Si l'assertion tombe, SAPI garde un jeton mort et la phrase suivante est perdue.

    Cas vécu : les points de terminaison Bluetooth disparaissent puis reviennent. Après une phrase
    en échec, _worker remet le routage à zéro — on rejoue cet état ici.
    """
    tts, sapi, hub = _voix(data_dir, sortie="M01 Pro_F444")
    tts._apply_settings()
    assert sapi.AudioOutput.description == MAINS_LIBRES

    sapi.jetons = [FauxJeton(HAUT_PARLEURS)]  # lunettes éteintes
    tts._sortie_routee = ""  # ce que fait _worker après une erreur de parole
    tts._apply_settings()

    assert sapi.AudioOutput.description == HAUT_PARLEURS
    assert any(t == "tts.fallback" for t, _ in hub.evenements)


def test_un_reglage_vide_ne_touche_a_aucune_sortie(data_dir):
    """Si l'assertion tombe, IRIS impose une sortie que personne n'a demandée : assigner à la place
    du défaut de Windows envoie la voix ailleurs (sonde faite sur la machine)."""
    tts, sapi, hub = _voix(data_dir, sortie="")
    tts._apply_settings()
    assert sapi.AudioOutput is INTACT
    assert sapi.enumerations == 0
    assert hub.evenements == []


def test_la_sortie_deja_routee_n_est_pas_re_enumeree_a_chaque_phrase(data_dir):
    """Si l'assertion tombe, chaque phrase paie ~70 ms d'énumération SAPI, sur un budget de 5 s."""
    tts, sapi, _hub = _voix(data_dir, sortie="M01 Pro_F444")
    tts._apply_settings()
    tts._apply_settings()
    tts._apply_settings()
    assert sapi.enumerations == 1


def test_le_meme_peripherique_introuvable_n_avertit_quune_fois(data_dir):
    """Si l'assertion tombe, chaque phrase prononcée lunettes éteintes jette une alerte à l'écran."""
    tts, _sapi, hub = _voix(data_dir, sortie="M01 Pro_F444", sorties_presentes=[HAUT_PARLEURS])
    tts._apply_settings()
    tts._apply_settings()
    assert len([t for t, _ in hub.evenements if t == "tts.fallback"]) == 1


def test_un_moteur_sans_objet_sapi_ne_fait_pas_echouer_la_parole(data_dir):
    """Si l'assertion tombe, IRIS devient muette là où pyttsx3 n'utilise pas le pilote SAPI5 ou
    a renommé son attribut privé (requirements.txt autorise pyttsx3 >= 2.98)."""
    tts, _sapi, hub = _voix(data_dir, sortie="M01 Pro_F444")
    tts._engine = FauxMoteur(sapi=None)
    tts._apply_settings()  # ne doit rien lever
    assert tts._engine.proprietes["rate"] > 0
    assert hub.evenements == []


@pytest.mark.parametrize("sortie", ["m01 pro_f444", "M01 PRO_F444", "  M01 Pro_F444  "])
def test_le_nom_du_peripherique_est_reconnu_sans_egard_a_la_casse(data_dir, sortie):
    """Si l'assertion tombe, un nom saisi à la main dans les réglages ne route plus rien."""
    tts, sapi, _hub = _voix(data_dir, sortie=sortie)
    tts._apply_settings()
    assert sapi.AudioOutput.description == MAINS_LIBRES


# --------------------------------------------------------------------------- le premier mot
# Mesure sur les vraies lunettes le 5 septembre 2026 : la meme phrase prend 3,27 s par le canal
# stereo et 3,90 s par le canal mains libres — mais 8,3 s la toute premiere fois, parce que le
# casque doit basculer en profil telephone. Sans prechauffage, ces huit secondes tombent sur le
# tout premier << Dis-moi Iris >>, celui qu'on fait devant une salle.
def test_le_prechauffage_nest_jamais_prononce():
    """Une sentinelle, pas une chaine : une chaine finirait un jour dite a voix haute."""
    from iris.voice.tts import PRECHAUFFAGE

    assert not isinstance(PRECHAUFFAGE, str)


def test_le_prechauffage_ne_fait_aucun_bruit(app, monkeypatch):
    """Volume remis a zero pendant l'ouverture du peripherique, puis restaure."""
    tts = app.state.ctx.tts
    volumes = []
    dits = []

    class FauxMoteur:
        def getProperty(self, nom):
            return 0.9 if nom == "volume" else None

        def setProperty(self, nom, valeur):
            if nom == "volume":
                volumes.append(valeur)

        def say(self, texte):
            dits.append(texte)

        def runAndWait(self):
            pass

    monkeypatch.setattr(tts, "_engine", FauxMoteur())
    monkeypatch.setattr(tts, "_apply_settings", lambda: None)
    tts._prechauffer_maintenant()

    assert volumes and volumes[0] == 0.0, "le volume doit tomber a zero avant d'ouvrir"
    assert volumes[-1] == 0.9, "et etre remis exactement comme il etait"
    assert len(dits) == 1 and len(dits[0]) <= 2, "une syllabe suffit a ouvrir le peripherique"


def test_quand_elevenlabs_repond_cest_sa_sortie_qui_est_prechauffee(app, monkeypatch):
    """Si l'assertion tombe, la configuration réelle (ElevenLabs actif) n'est jamais préchauffée.

    L'ancienne règle sortait tôt dès qu'ElevenLabs répondait, au motif qu'il avait « sa propre
    pré-connexion » — une poignée de main HTTPS, qui n'ouvre aucun périphérique. Le basculement du
    casque (8,3 s mesurées) tombait donc sur le tout premier « Dis-moi Iris ». C'est le chemin qui
    va parler qu'on préchauffe : ElevenLabs ouvre sa sortie, la file SAPI n'est pas touchée.
    """
    tts = app.state.ctx.tts
    monkeypatch.setattr(tts, "_use_elevenlabs", lambda: True)
    prechauffes = []
    monkeypatch.setattr(tts.eleven, "prechauffer", lambda: prechauffes.append("elevenlabs"))
    mis = []
    monkeypatch.setattr(tts._queue, "put", lambda x: mis.append(x))
    tts.prechauffer()
    assert prechauffes == ["elevenlabs"]
    assert mis == []


def test_quand_windows_parle_cest_la_file_sapi_qui_est_prechauffee(app, monkeypatch):
    """Le chemin Windows garde son préchauffage : la sentinelle part dans la file SAPI, pas ailleurs."""
    from iris.voice.tts import PRECHAUFFAGE

    tts = app.state.ctx.tts
    monkeypatch.setattr(tts, "_use_elevenlabs", lambda: False)
    monkeypatch.setattr(tts, "available", True)
    monkeypatch.setattr(tts, "_ensure_started", lambda: None)  # aucun thread, aucun moteur réel
    prechauffes = []
    monkeypatch.setattr(tts.eleven, "prechauffer", lambda: prechauffes.append("elevenlabs"))
    mis = []
    monkeypatch.setattr(tts._queue, "put", lambda x: mis.append(x))
    tts.prechauffer()
    assert mis == [PRECHAUFFAGE]
    assert prechauffes == []
