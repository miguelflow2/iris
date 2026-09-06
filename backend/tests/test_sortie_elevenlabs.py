"""Par où sort la voix ElevenLabs d'IRIS : le périphérique demandé, à la fréquence qu'il accepte.

Journal réel du 5 septembre 2026, quinze fois de suite : « sortie audio « casque (m01 pro_f444
stereo) » introuvable ou incompatible 24 kHz, sortie par défaut utilisée ». ElevenLabs envoie du PCM
à 24 kHz ; un périphérique Bluetooth ouvert par WASAPI impose le taux de son lien (16 kHz en mains
libres) ; le contrôle échouait, et TOUT retombait sur le haut-parleur du PC — pendant que Miguel
portait ses lunettes. Le site promet « elle répond dans l'oreille ».

Trois promesses sont vérifiées ici :
1. un périphérique qui refuse 24 kHz est ouvert à sa propre fréquence et le flux est rééchantillonné,
   au lieu d'être abandonné ;
2. la voix ElevenLabs suit la MÊME règle de routage que la voix Windows (micro mains libres →
   sortie mains libres, même si le réglage nomme « Stereo ») ;
3. jamais muette : si aucune sortie ne s'ouvre, la voix Windows reprend la phrase, et le journal
   le dit.

Aucun son n'est joué ici, aucun périphérique réel n'est touché, aucun appel réseau n'est fait :
sounddevice et la session HTTP sont remplacés par des faux qui enregistrent ce qu'on leur demande.
"""
from __future__ import annotations

import logging

import numpy as np
import pytest

from iris.config import Settings
from iris.voice.elevenlabs import (
    PRECHAUFFAGE,
    SAMPLE_RATE,
    ElevenLabsSpeaker,
    Reechantillonneur,
    SortieAudioIndisponible,
    racine_lunettes,
)

# Les périphériques réellement vus sur la machine de Miguel (relevé du 2026-09-04), où les lunettes
# « M01 Pro_F444 » apparaissent plusieurs fois : une fois par profil Bluetooth et par hôte audio.
MME, WASAPI = 0, 1
HAUT_PARLEURS = "Haut-parleurs (High Definition Audio Device)"
STEREO = "Casque (M01 Pro_F444 Stereo)"
MAINS_LIBRES_MME = "Casque (M01 Pro_F444 Hands-Free"  # MME tronque les noms à 31 caractères
MAINS_LIBRES_COMPLET = "Casque (M01 Pro_F444 Hands-Free AG Audio)"


def _sortie(nom: str, hote: int = MME, taux: int = 44100, voies: int = 2) -> dict:
    return {"name": nom, "max_output_channels": voies, "max_input_channels": 0, "hostapi": hote, "default_samplerate": taux}


def _entree(nom: str, hote: int = MME, taux: int = 44100) -> dict:
    return {"name": nom, "max_output_channels": 0, "max_input_channels": 1, "hostapi": hote, "default_samplerate": taux}


def _lunettes_allumees() -> list[dict]:
    return [
        _sortie(HAUT_PARLEURS, MME),  # 0
        _entree(MAINS_LIBRES_MME, MME),  # 1 : le micro — même nom que la sortie 3, mais AUCUNE voie de sortie
        _sortie(STEREO, MME),  # 2
        _sortie(MAINS_LIBRES_MME, MME, taux=44100, voies=1),  # 3 : MME ment sur la fréquence (lien réel : 16 kHz)
        _sortie(HAUT_PARLEURS, WASAPI, taux=48000),  # 4
        _sortie(STEREO, WASAPI, taux=48000),  # 5
        _sortie(MAINS_LIBRES_COMPLET, WASAPI, taux=16000, voies=1),  # 6 : WASAPI dit le vrai taux du lien HFP
    ]


class FauxFlux:
    """Flux de sortie sounddevice : enregistre ce qu'on y écrit, ne joue rien."""

    def __init__(self, journal: list, samplerate: int, device):
        self.samplerate = samplerate
        self.device = device
        self.ecrit = b""
        journal.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def write(self, data) -> None:
        self.ecrit += bytes(data)

    @property
    def echantillons(self) -> int:
        return len(self.ecrit) // 2  # int16 mono


class FauxSounddevice:
    """Le module sounddevice, sans PortAudio : des listes à la place des périphériques."""

    def __init__(self, peripheriques: list[dict], refus=(), injouables=()):
        self.peripheriques = peripheriques
        self.refus = set(refus)  # {(index, taux)} que check_output_settings refuse
        self.injouables = set(injouables)  # index (ou "defaut") dont l'ouverture lève
        self.flux: list[FauxFlux] = []
        self.hotes = [{"name": "MME"}, {"name": "Windows WASAPI"}]

    def query_hostapis(self):
        return self.hotes

    def query_devices(self):
        return list(self.peripheriques)

    def check_output_settings(self, device=None, samplerate=None, channels=None, dtype=None):
        if (device, samplerate) in self.refus:
            raise ValueError(f"Invalid sample rate {samplerate} pour le périphérique {device}")

    def RawOutputStream(self, samplerate, channels, dtype, blocksize, device=None):  # noqa: N802 (nom imposé par sounddevice)
        cle = "defaut" if device is None else device
        if cle in self.injouables:
            raise RuntimeError(f"Error opening RawOutputStream: périphérique {cle} indisponible")
        return FauxFlux(self.flux, samplerate, device)


class FauxReponse:
    def __init__(self, pcm: bytes, tailles: list[int] | None = None):
        self.pcm = pcm
        self.tailles = tailles  # tailles de morceaux imposées (la socket rend ce qu'elle a)
        self.status_code = 200
        self.text = ""
        self.ferme = False

    def iter_content(self, chunk_size: int):
        position = 0
        tailles = iter(self.tailles or [])
        while position < len(self.pcm):
            taille = next(tailles, chunk_size)
            yield self.pcm[position : position + taille]
            position += taille

    def close(self) -> None:
        self.ferme = True


class FauxSession:
    """Session requests : rend le PCM préparé, et refuse tout autre appel réseau."""

    def __init__(self, pcm: bytes, tailles: list[int] | None = None):
        self.reponse = FauxReponse(pcm, tailles)

    def post(self, url, headers=None, json=None, stream=False, timeout=None):
        assert "text-to-speech" in url and stream
        return self.reponse

    def get(self, *a, **k):
        raise AssertionError("aucun appel réseau ne doit partir d'ici")


class FauxHub:
    def __init__(self):
        self.evenements: list[tuple[str, dict]] = []

    def publish(self, type_: str, **data):
        self.evenements.append((type_, data))
        return data


def _rampe(n: int = SAMPLE_RATE) -> bytes:
    """Une seconde de PCM 24 kHz dont chaque échantillon vaut son rang : tout saut se voit."""
    return np.arange(n, dtype="<i2").tobytes()


def _voix(data_dir, monkeypatch, sd: FauxSounddevice, sortie: str = "", micro: str = "", pcm: bytes | None = None, tailles=None):
    settings = Settings(data_dir)
    # Après Settings, jamais avant : sa construction recharge backend/.env, qui contient la clé
    # personnelle de Miguel. Une clé factice suffit : rien ne part sur le réseau.
    monkeypatch.setenv("ELEVENLABS_API_KEY", "sk_factice")
    settings.user.audio_output_device = sortie
    settings.user.audio_input_device = micro
    hub = FauxHub()
    sp = ElevenLabsSpeaker(settings, hub)
    sp._sounddevice = lambda: sd
    session = FauxSession(pcm if pcm is not None else _rampe(), tailles)
    sp._http = lambda: session
    return sp, hub, session


# --------------------------------------------------------------------------- le rééchantillonnage
def test_le_reechantillonnage_de_24_a_16_khz_rend_deux_tiers_des_echantillons():
    """Si l'assertion tombe, la voix passe trop vite ou trop lentement dans les lunettes."""
    conv = Reechantillonneur(24000, 16000)
    rampe = _rampe()
    for debut in range(0, len(rampe), 4800):
        conv.convertir(rampe[debut : debut + 4800])
    assert conv.entres == 24000
    assert conv.sortis == 16000


@pytest.mark.parametrize("cible", [8000, 16000, 22050, 44100, 48000])
def test_le_compte_tient_quelle_que_soit_la_taille_des_morceaux(cible):
    """Si l'assertion tombe, un morceau HTTP de taille quelconque fait perdre ou doubler des
    échantillons : la socket rend ce qu'elle a, jamais un multiple garanti."""
    conv = Reechantillonneur(24000, cible)
    rampe = _rampe()
    tailles = [4800, 2, 1234, 8, 9998, 4800, 6, 3000]  # pairs : _stream_and_play ne passe jamais un demi-échantillon int16
    position = 0
    sortie = b""
    while position < len(rampe):
        taille = tailles[len(sortie) % len(tailles)]
        sortie += conv.convertir(rampe[position : position + taille])
        position += taille
    attendu = cible  # une seconde d'audio
    assert abs(conv.sortis - attendu) <= 2, f"{conv.sortis} échantillons pour {attendu} attendus"
    assert len(sortie) == 2 * conv.sortis


@pytest.mark.parametrize("cible", [16000, 44100])
def test_le_reechantillonnage_morceau_par_morceau_ne_fait_aucun_saut(cible):
    """Si l'assertion tombe, chaque frontière de morceau crépite dans l'oreille : le point de
    lecture ne se prolonge pas d'un morceau au suivant."""
    conv = Reechantillonneur(24000, cible)
    rampe = _rampe()
    tailles = [4800, 2, 1234, 8, 9998, 4800, 6, 3000]  # pairs : _stream_and_play ne passe jamais un demi-échantillon int16
    position = 0
    morceaux = []
    i = 0
    while position < len(rampe):
        taille = tailles[i % len(tailles)]
        morceaux.append(conv.convertir(rampe[position : position + taille]))
        position += taille
        i += 1
    sortie = np.frombuffer(b"".join(morceaux), dtype="<i2").astype(np.float64)
    attendu = (24000 / cible) * np.arange(len(sortie))  # une rampe reste une rampe, pente = pas
    assert np.all(np.abs(sortie - attendu) <= 0.5)


def test_a_la_meme_frequence_les_octets_passent_tels_quels():
    """Rien à convertir : pas une copie de plus sur le chemin du premier mot."""
    conv = Reechantillonneur(24000, 24000)
    assert conv.convertir(b"\x01\x02\x03\x04") == b"\x01\x02\x03\x04"


# --------------------------------------------------------------------------- le périphérique demandé
def test_la_sortie_demandee_est_bien_celle_qui_est_ouverte(data_dir, monkeypatch):
    """Si l'assertion tombe, IRIS parle par le haut-parleur du PC pendant que Miguel porte ses lunettes."""
    sd = FauxSounddevice(_lunettes_allumees())
    sp, _hub, session = _voix(data_dir, monkeypatch, sd, sortie=STEREO)
    sp._stream_and_play("Bonjour")
    assert len(sd.flux) == 1
    assert sd.flux[0].device == 2
    assert sd.flux[0].samplerate == SAMPLE_RATE  # MME accepte 24 kHz : rien à convertir
    assert sd.flux[0].echantillons == 24000
    assert session.reponse.ferme


def test_une_sortie_qui_refuse_24_khz_est_ouverte_a_sa_propre_frequence(data_dir, monkeypatch, caplog):
    """Si l'assertion tombe, on retombe sur le journal du 5 septembre 2026 : le périphérique refuse
    24 kHz, on l'abandonne, et le son sort du PC. Il doit sortir DU périphérique demandé."""
    caplog.set_level(logging.INFO, logger="iris.elevenlabs")
    peripheriques = [_sortie(HAUT_PARLEURS, MME), _sortie(MAINS_LIBRES_COMPLET, WASAPI, taux=16000, voies=1)]
    sd = FauxSounddevice(peripheriques, refus={(1, 24000)})
    sp, hub, _session = _voix(data_dir, monkeypatch, sd, sortie=MAINS_LIBRES_MME, micro=MAINS_LIBRES_MME)
    sp._stream_and_play("Bonjour")
    assert len(sd.flux) == 1
    assert sd.flux[0].device == 1
    assert sd.flux[0].samplerate == 16000
    assert abs(sd.flux[0].echantillons - 16000) <= 2  # 24000 → 16000 : deux tiers
    assert "rééchantillonnée depuis 24000" in caplog.text
    assert hub.evenements == []  # aucune alerte : la sortie demandée a bien parlé


def test_quand_lhote_tolerant_refuse_on_passe_a_lautre_hote_plutot_quau_defaut(data_dir, monkeypatch):
    """Si l'assertion tombe, un refus de MME suffit à renvoyer la voix vers le PC alors que WASAPI
    sait ouvrir le même casque, à son vrai taux."""
    sd = FauxSounddevice(_lunettes_allumees(), refus={(3, 24000), (3, 44100), (6, 24000)})
    sp, _hub, _session = _voix(data_dir, monkeypatch, sd, sortie=STEREO, micro=MAINS_LIBRES_MME)
    assert sp._output_device(sd) == (6, 16000)


def test_le_mains_libres_lemporte_quand_le_micro_est_mains_libres(data_dir, monkeypatch):
    """Si l'assertion tombe, la configuration RÉELLE de Miguel (micro « Hands-Free », sortie
    « Stereo » en toutes lettres) parle vers un profil que Windows a mis en veille."""
    sd = FauxSounddevice(_lunettes_allumees())
    sp, _hub, _session = _voix(data_dir, monkeypatch, sd, sortie=STEREO, micro=MAINS_LIBRES_MME)
    idx, taux = sp._output_device(sd)
    assert idx == 3, "le canal mains libres du même casque, sous l'hôte le plus tolérant"
    assert taux == SAMPLE_RATE


def test_sans_micro_mains_libres_la_sortie_stereo_demandee_est_respectee(data_dir, monkeypatch):
    """Si l'assertion tombe, IRIS impose le 8 kHz mono du profil téléphone à quelqu'un dont le
    micro n'est pas dans les lunettes : la stéréo est vivante, et c'est elle qu'on a demandée."""
    sd = FauxSounddevice(_lunettes_allumees())
    sp, _hub, _session = _voix(data_dir, monkeypatch, sd, sortie=STEREO, micro="")
    assert sp._output_device(sd)[0] == 2


def test_le_micro_mains_libres_ne_detourne_pas_une_sortie_dun_autre_appareil(data_dir, monkeypatch):
    """Si l'assertion tombe, choisir les haut-parleurs du PC (démo dans une salle, micro dans les
    lunettes) envoie quand même la voix dans les lunettes."""
    sd = FauxSounddevice(_lunettes_allumees())
    sp, _hub, _session = _voix(data_dir, monkeypatch, sd, sortie=HAUT_PARLEURS, micro=MAINS_LIBRES_MME)
    assert sp._output_device(sd)[0] == 0


def test_lhote_mme_est_prefere_a_wasapi_pour_la_meme_sortie(data_dir, monkeypatch):
    """Même ordre que le micro (listener.score_hote) : MME rééchantillonne et partage le périphérique."""
    sd = FauxSounddevice(_lunettes_allumees())
    sp, _hub, _session = _voix(data_dir, monkeypatch, sd, sortie=STEREO)
    assert sp._output_device(sd)[0] == 2  # et non 5 (WASAPI)


def test_un_micro_sans_voie_de_sortie_nest_jamais_choisi_comme_sortie(data_dir, monkeypatch):
    """Si l'assertion tombe, la voix est envoyée vers l'entrée 1, qui porte le même nom que la
    sortie 3 mais n'a aucune voie de sortie : silence total."""
    sd = FauxSounddevice(_lunettes_allumees())
    sp, _hub, _session = _voix(data_dir, monkeypatch, sd, sortie=MAINS_LIBRES_MME)
    assert sp._output_device(sd)[0] == 3


def test_un_reglage_vide_laisse_la_sortie_par_defaut_sans_rien_enumerer(data_dir, monkeypatch):
    sd = FauxSounddevice(_lunettes_allumees())
    sp, hub, _session = _voix(data_dir, monkeypatch, sd, sortie="")
    assert sp._output_device(sd) == (None, SAMPLE_RATE)
    assert hub.evenements == []


def test_la_racine_des_lunettes_relie_leurs_deux_profils():
    """« Stereo » et « Hands-Free » sont le même casque : Windows ne les relie que par ce préfixe."""
    assert racine_lunettes(STEREO) == "casque (m01 pro_f444"
    assert racine_lunettes(MAINS_LIBRES_COMPLET) == "casque (m01 pro_f444"
    assert racine_lunettes(MAINS_LIBRES_MME) == "casque (m01 pro_f444"
    assert racine_lunettes(HAUT_PARLEURS) == HAUT_PARLEURS.lower()


# --------------------------------------------------------------------------- lunettes éteintes
def test_des_lunettes_eteintes_avertissent_une_fois_et_laissent_parler_le_defaut(data_dir, monkeypatch, caplog):
    """Si l'assertion tombe, soit IRIS se tait quand les lunettes sont éteintes, soit elle répète
    le même avertissement à chaque phrase — quinze fois dans le journal du 5 septembre 2026."""
    caplog.set_level(logging.WARNING, logger="iris.elevenlabs")
    sd = FauxSounddevice([_sortie(HAUT_PARLEURS, MME)])
    sp, hub, _session = _voix(data_dir, monkeypatch, sd, sortie=STEREO, micro=MAINS_LIBRES_MME)
    sp._stream_and_play("Bonjour")
    sp._stream_and_play("Encore")
    assert [f.device for f in sd.flux] == [None, None]
    assert all(f.echantillons == 24000 for f in sd.flux)
    assert [t for t, _ in hub.evenements] == ["tts.fallback"]
    assert "introuvable" in hub.evenements[0][1]["reason"]
    assert caplog.text.count("introuvable") == 1


def test_des_lunettes_qui_reviennent_puis_repartent_sont_signalees_a_nouveau(data_dir, monkeypatch):
    """Cas vécu : les points de terminaison Bluetooth disparaissent puis reviennent."""
    sd = FauxSounddevice([_sortie(HAUT_PARLEURS, MME)])
    sp, hub, _session = _voix(data_dir, monkeypatch, sd, sortie=STEREO)
    assert sp._output_device(sd)[0] is None
    sd.peripheriques = _lunettes_allumees()  # rallumées
    assert sp._output_device(sd)[0] == 2
    sd.peripheriques = [_sortie(HAUT_PARLEURS, MME)]  # éteintes de nouveau
    assert sp._output_device(sd)[0] is None
    assert len([t for t, _ in hub.evenements if t == "tts.fallback"]) == 2


def test_une_sortie_qui_refuse_toutes_les_frequences_le_dit_et_laisse_parler_le_defaut(data_dir, monkeypatch, caplog):
    """Le journal doit distinguer « introuvable » (lunettes éteintes) de « refuse la fréquence »
    (pilote) : ce n'est pas la même panne, ni la même réparation."""
    caplog.set_level(logging.WARNING, logger="iris.elevenlabs")
    sd = FauxSounddevice(_lunettes_allumees(), refus={(2, 24000), (2, 44100), (5, 24000), (5, 48000)})
    sp, hub, _session = _voix(data_dir, monkeypatch, sd, sortie=STEREO)
    assert sp._output_device(sd) == (None, SAMPLE_RATE)
    assert "refuse toutes les fréquences" in caplog.text
    assert "introuvable" not in caplog.text
    assert [t for t, _ in hub.evenements] == ["tts.fallback"]


def test_la_meme_sortie_nest_annoncee_quune_fois_dans_le_journal(data_dir, monkeypatch, caplog):
    """Une ligne quand le routage change, pas une par phrase."""
    caplog.set_level(logging.INFO, logger="iris.elevenlabs")
    sd = FauxSounddevice(_lunettes_allumees())
    sp, _hub, _session = _voix(data_dir, monkeypatch, sd, sortie=STEREO)
    for _ in range(3):
        sp._output_device(sd)
    assert caplog.text.count("dirigée vers") == 1


# --------------------------------------------------------------------------- jamais muette
def test_une_sortie_refusee_a_louverture_retombe_sur_le_defaut_sans_perdre_la_phrase(data_dir, monkeypatch, caplog):
    """check_output_settings peut dire oui et l'ouverture dire non (périphérique pris entre-temps) :
    la phrase sort quand même, par la sortie par défaut, et le journal le dit."""
    caplog.set_level(logging.WARNING, logger="iris.elevenlabs")
    sd = FauxSounddevice(_lunettes_allumees(), injouables={2})
    sp, _hub, _session = _voix(data_dir, monkeypatch, sd, sortie=STEREO)
    sp._stream_and_play("Bonjour")
    assert len(sd.flux) == 1
    assert sd.flux[0].device is None
    assert sd.flux[0].echantillons == 24000
    assert "refusée à l'ouverture" in caplog.text


def test_quand_aucune_sortie_ne_souvre_la_voix_windows_prend_le_relais(data_dir, monkeypatch, caplog):
    """Si l'assertion tombe, IRIS se tait sans un mot dans le journal.

    C'est la promesse au-dessus des autres : quoi qu'il arrive, IRIS parle avec la voix de Windows.
    Une assistante qui se tait a l'air cassée ; une assistante qui change de voix a seulement l'air
    moins jolie."""
    caplog.set_level(logging.INFO, logger="iris.elevenlabs")
    sd = FauxSounddevice(_lunettes_allumees(), injouables={2, "defaut"})
    sp, hub, session = _voix(data_dir, monkeypatch, sd, sortie=STEREO)
    repris = []
    sp.fallback_speak = lambda texte: repris.append(texte) or True
    with pytest.raises(SortieAudioIndisponible) as info:
        sp._stream_and_play("Bonjour")
    assert session.reponse.ferme, "la réponse HTTP ne doit pas rester ouverte"
    sp._handle_failure(info.value, "Bonjour")  # ce que fait _worker
    assert repris == ["Bonjour"]
    assert any(t == "tts.fallback" for t, _ in hub.evenements)
    assert "la voix Windows prend le relais" in caplog.text
    assert sp.available, "une panne de périphérique n'est pas une panne d'ElevenLabs : pas de mise à l'écart"


def test_un_repli_windows_qui_echoue_lui_meme_est_ecrit_dans_le_journal(data_dir, monkeypatch, caplog):
    """Avant, l'échec du repli était avalé (`except Exception: pass`) : IRIS pouvait se taire sans
    qu'aucune ligne ne l'explique."""
    caplog.set_level(logging.WARNING, logger="iris.elevenlabs")
    sd = FauxSounddevice(_lunettes_allumees())
    sp, _hub, _session = _voix(data_dir, monkeypatch, sd, sortie=STEREO)

    def repli_casse(texte):
        raise RuntimeError("SAPI absent")

    sp.fallback_speak = repli_casse
    sp._handle_failure(RuntimeError("réseau coupé"), "Bonjour")
    assert "n'a pas pu reprendre la phrase" in caplog.text

    sp.fallback_speak = lambda texte: False  # synthèse Windows désactivée
    sp._handle_failure(RuntimeError("réseau coupé"), "Bonjour")
    assert "phrase perdue" in caplog.text


# --------------------------------------------------------------------------- le préchauffage
def test_le_prechauffage_ouvre_la_sortie_demandee_sans_un_son(data_dir, monkeypatch, caplog):
    """Le casque bascule en profil téléphone (8,3 s mesurées) : autant que ce soit avant le premier
    « Dis-moi Iris ». sounddevice n'a pas de volume : le silence, ce sont des zéros."""
    caplog.set_level(logging.INFO, logger="iris.elevenlabs")
    sd = FauxSounddevice(_lunettes_allumees())
    sp, hub, _session = _voix(data_dir, monkeypatch, sd, sortie=STEREO, micro=MAINS_LIBRES_MME)
    sp._http = lambda: (_ for _ in ()).throw(AssertionError("le préchauffage ne touche pas au réseau"))
    sp._prechauffer_maintenant()
    assert len(sd.flux) == 1
    assert sd.flux[0].device == 3, "la sortie qui va parler : le mains libres, sous MME"
    assert sd.flux[0].ecrit and set(sd.flux[0].ecrit) == {0}, "que des zéros : personne n'entend rien"
    assert sd.flux[0].echantillons == SAMPLE_RATE // 10
    assert not any(t == "tts.state" for t, _ in hub.evenements), "rien ne se passe pour l'utilisateur"
    assert sp.speaking is False
    assert "préchauffée" in caplog.text


def test_le_prechauffage_passe_par_la_file_sans_demarrer_de_parole(data_dir, monkeypatch):
    """La sentinelle, pas une chaîne : une chaîne finirait un jour dite à voix haute."""
    sd = FauxSounddevice(_lunettes_allumees())
    sp, _hub, _session = _voix(data_dir, monkeypatch, sd, sortie=STEREO)
    monkeypatch.setattr(sp, "_ensure_thread", lambda: None)  # aucun thread : on lit la file à la main
    sp.prechauffer()
    assert sp._queue.get_nowait() is PRECHAUFFAGE
    assert not isinstance(PRECHAUFFAGE, str)
    assert sp._idle.is_set(), "préchauffer n'est pas parler : wait_idle ne doit pas attendre"


def test_sans_cle_elevenlabs_le_prechauffage_ne_fait_rien(data_dir, monkeypatch):
    """Sur une machine neuve sans clé, c'est la voix Windows qui parle : rien à ouvrir ici."""
    sd = FauxSounddevice(_lunettes_allumees())
    sp, _hub, _session = _voix(data_dir, monkeypatch, sd, sortie=STEREO)
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
    monkeypatch.setattr(sp, "_ensure_thread", lambda: None)
    sp.prechauffer()
    assert sp._queue.empty()


def test_un_prechauffage_qui_echoue_ne_casse_rien(data_dir, monkeypatch, caplog):
    """Aucune sortie ne s'ouvre au démarrage : on le note en debug, et la première phrase aura son
    propre repli. Le préchauffage est un confort, jamais une condition."""
    caplog.set_level(logging.DEBUG, logger="iris.elevenlabs")
    sd = FauxSounddevice(_lunettes_allumees(), injouables={2, "defaut"})
    sp, _hub, _session = _voix(data_dir, monkeypatch, sd, sortie=STEREO)
    sp._prechauffer_maintenant()  # ne doit rien lever
    assert "préchauffage de la sortie ElevenLabs impossible" in caplog.text
