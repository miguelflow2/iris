"""Débit de la voix (tts_rate) : 185 = 1×, 370 = 2×, 555 = 3×, pour les trois moteurs d'IRIS.

Pourquoi ce fichier : les utilisateurs non voyants aguerris écoutent à 2 ou 3 fois la vitesse
normale. Afficher « 3× » et livrer 2× serait exactement la promesse fausse que VELA s'interdit.
Ces tests vérifient donc la durée RÉELLEMENT produite, pas seulement le paramètre envoyé :

1. l'étirement local (WSOLA) rend durée/taux à ±5 %, sans changer la hauteur (±3 %), sans saut
   aux jonctions, identique en flux et sur le tampon complet ;
2. la voix Windows reçoit le bon Rate SAPI (-10..10), posé après la voix et sans casser le routage ;
3. la voix locale synthétise à sa vitesse naturelle puis étire localement (son length_scale natif,
   mesuré, ratait la cible de 7 à 40 % : voir piper.py) ;
4. la voix premium reçoit speed dans [0,7 ; 1,2] et le reste est étiré localement.

Aucun son, aucun réseau, aucun modèle : signaux synthétiques (sommes de sinus), faux synthétiseur,
faux sounddevice, fausse session HTTP.
"""
from __future__ import annotations

import math

import numpy as np
import pytest

from iris.config import Settings
from iris.voice.elevenlabs import SAMPLE_RATE as TAUX_PREMIUM
from iris.voice.elevenlabs import VITESSE_API_MAX, VITESSE_API_MIN, ElevenLabsSpeaker, repartir_vitesse
from iris.voice.etirement import DEBIT_NORMAL, Etireur, est_identite, etirer_pcm, facteur_debit
from iris.voice.piper import SAMPLE_RATE as TAUX_LOCAL
from iris.voice.piper import PiperSpeaker, taux_etirement
from iris.voice.tts import RATE_SAPI_MAX, RATE_SAPI_MIN, TextToSpeech, mots_minute_pyttsx3, rate_sapi
from tests.test_sortie_elevenlabs import FauxHub, FauxSession, FauxSounddevice, _lunettes_allumees
from tests.test_voix_sortie import MAINS_LIBRES, FauxSapi

TAUX_ACCELERES = (1.5, 2.0, 3.0)


# --------------------------------------------------------------------------- signaux synthétiques
def _somme_de_sinus(rate: int, secondes: float = 2.0) -> np.ndarray:
    """Fondamentale 220 Hz dominante + deux partiels NON harmoniques (l'alignement n'est pas trivial)."""
    t = np.arange(int(rate * secondes)) / rate
    x = 0.55 * np.sin(2 * np.pi * 220 * t) + 0.25 * np.sin(2 * np.pi * 587 * t + 0.3) + 0.12 * np.sin(2 * np.pi * 1210 * t + 1.1)
    return np.rint(x * 20000).astype(np.int16)


def _vibrato(rate: int, secondes: float = 2.5) -> np.ndarray:
    """Hauteur qui glisse (180 ± 40 Hz) et amplitude qui pulse, comme des syllabes : pire cas des jonctions."""
    t = np.arange(int(rate * secondes)) / rate
    frequence = 180 + 40 * np.sin(2 * np.pi * 3 * t)
    phase = 2 * np.pi * np.cumsum(frequence) / rate
    enveloppe = 0.6 + 0.4 * np.sin(2 * np.pi * 4 * t)
    x = enveloppe * (0.6 * np.sin(phase) + 0.3 * np.sin(2 * phase + 0.5) + 0.1 * np.sin(3 * phase + 1.0))
    return np.rint(x * 18000).astype(np.int16)


def _frequence_dominante(pcm: np.ndarray, rate: int) -> float:
    """Pic du spectre (fenêtre de Hann, zéro-padding ×8 pour une résolution fine)."""
    x = pcm.astype(np.float64)
    x = x[len(x) // 10 : len(x) - len(x) // 10]  # hors des bords
    taille = 8 * len(x)
    spectre = np.abs(np.fft.rfft(x * np.hanning(len(x)), n=taille))
    return float(np.fft.rfftfreq(taille, 1 / rate)[int(np.argmax(spectre))])


def _saut_max(pcm: np.ndarray) -> float:
    return float(np.abs(np.diff(pcm.astype(np.float64))).max())


# --------------------------------------------------------------------------- 1. l'étirement local
@pytest.mark.parametrize("rate", [TAUX_LOCAL, TAUX_PREMIUM])
@pytest.mark.parametrize("taux", TAUX_ACCELERES)
def test_la_duree_de_sortie_vaut_la_duree_divisee_par_le_taux(rate, taux):
    """Si l'assertion tombe, « 2× » à l'écran ne veut plus dire deux fois plus court à l'oreille."""
    pcm = _somme_de_sinus(rate)
    sortie = etirer_pcm(pcm, taux, rate)
    attendu = len(pcm) / taux
    assert abs(len(sortie) - attendu) <= 0.05 * attendu
    assert abs(len(sortie) - attendu) <= 1, "la durée est exacte à l'échantillon près, pas seulement à 5 %"
    assert sortie.dtype == np.int16


@pytest.mark.parametrize("taux", TAUX_ACCELERES)
def test_la_hauteur_est_conservee(taux):
    """Si l'assertion tombe, accélérer la voix la rend aiguë (effet « dessin animé »)."""
    rate = TAUX_PREMIUM
    pcm = _somme_de_sinus(rate)
    avant = _frequence_dominante(pcm, rate)
    apres = _frequence_dominante(etirer_pcm(pcm, taux, rate), rate)
    assert abs(avant - 220) <= 1
    assert abs(apres - avant) <= 0.03 * avant


@pytest.mark.parametrize("taux", (0.7, *TAUX_ACCELERES))
def test_aucun_saut_aux_jonctions_ni_a_la_fin(taux):
    """Si l'assertion tombe, chaque raccord de fenêtres claque : un crépitement 80 fois par seconde.

    Un clic est une marche : l'écart entre deux échantillons voisins dépasse de loin celui du signal
    d'origine. Ralentir est inclus : les dernières trames y sont complétées de silence, et une fin
    coupée au milieu d'une onde chutait d'un coup à zéro (2,7 fois le plus grand écart d'origine)
    avant le fondu d'entrée de `vider`."""
    rate = TAUX_LOCAL
    pcm = _vibrato(rate)
    sortie = etirer_pcm(pcm, taux, rate)
    assert _saut_max(sortie) <= 1.2 * _saut_max(pcm)
    # et l'amplitude reste celle d'origine (Hann à 50 % : somme plate), au cœur du signal
    coeur = sortie[len(sortie) // 10 : -len(sortie) // 10].astype(np.float64)
    rms_sortie = math.sqrt(float(np.mean(coeur**2)))
    rms_entree = math.sqrt(float(np.mean(pcm.astype(np.float64) ** 2)))
    assert abs(rms_sortie - rms_entree) <= 0.1 * rms_entree


def test_taux_un_est_l_identite():
    pcm = _somme_de_sinus(TAUX_LOCAL, 0.5)
    assert np.array_equal(etirer_pcm(pcm, 1.0, TAUX_LOCAL), pcm)
    etireur = Etireur(1.0, TAUX_LOCAL)
    assert np.array_equal(etireur.pousser(pcm[:1000]), pcm[:1000]), "aucune latence ajoutée à 1×"
    assert etireur.vider().size == 0
    assert est_identite(1.0) and not est_identite(1.5)


def test_une_entree_vide_ou_minuscule_ne_casse_rien():
    vide = etirer_pcm(np.zeros(0, dtype=np.int16), 2.0, TAUX_PREMIUM)
    assert vide.size == 0 and vide.dtype == np.int16
    etireur = Etireur(3.0, TAUX_PREMIUM)
    assert etireur.pousser(np.zeros(0, dtype=np.int16)).size == 0
    assert etireur.vider().size == 0
    assert etireur.vider().size == 0, "vider deux fois ne rend rien de plus"
    court = etirer_pcm(np.full(10, 1000, dtype=np.int16), 2.0, TAUX_PREMIUM)
    assert len(court) == 5
    assert Etireur(2.0, TAUX_PREMIUM).vider_octets() == b""


@pytest.mark.parametrize("taux", (0.7, 2.5))
def test_le_flux_par_morceaux_rend_exactement_le_tampon_complet(taux):
    """Si l'assertion tombe, la voix premium (lue en flux, morceaux de taille quelconque) sonne
    autrement que le calcul vérifié ci-dessus : chaque frontière de morceau serait une couture."""
    rate = TAUX_PREMIUM
    pcm = _vibrato(rate, 1.5)
    complet = etirer_pcm(pcm, taux, rate)
    etireur = Etireur(taux, rate)
    hasard = np.random.default_rng(13)
    octets = pcm.astype("<i2").tobytes()
    morceaux: list[bytes] = []
    position = 0
    while position < len(octets):
        taille = 2 * int(hasard.integers(1, 2500))  # int16 : nombre pair d'octets
        morceaux.append(etireur.pousser_octets(octets[position : position + taille]))
        position += taille
    morceaux.append(etireur.vider_octets())
    assert np.array_equal(np.frombuffer(b"".join(morceaux), dtype="<i2"), complet)


@pytest.mark.parametrize("taux", (0, -1, float("nan"), float("inf")))
def test_un_taux_invalide_est_refuse(taux):
    with pytest.raises(ValueError):
        Etireur(taux, TAUX_PREMIUM)


def test_facteur_de_debit():
    """185 = vitesse normale ; un réglage illisible vaut la vitesse normale, jamais une voix inaudible."""
    assert DEBIT_NORMAL == 185
    assert facteur_debit(185) == 1.0 and facteur_debit(370) == 2.0 and facteur_debit(555) == 3.0
    for illisible in (None, "vite", 0, -40, float("nan")):
        assert facteur_debit(illisible) == 1.0


# --------------------------------------------------------------------------- 2. la voix Windows (SAPI)
def test_correspondance_du_rate_sapi():
    """Si l'assertion tombe, 1× n'est plus la vitesse normale ou 3× sort de la plage SAPI.

    SAPI : +10 = 3× la vitesse normale, -10 = le tiers, échelle logarithmique (racine dixième de 3
    par cran). Mesuré le 13 septembre 2026 sur la voix SAPI de ce PC : Rate 6 → 2,005×, 10 → 2,96×."""
    assert rate_sapi(185) == 0, "185 = vitesse normale"
    assert rate_sapi(555) == RATE_SAPI_MAX == 10, "555 (3×) = le maximum de SAPI"
    assert rate_sapi(560) == 10 and rate_sapi(100000) == 10, "au-delà : borné, jamais hors plage"
    assert rate_sapi(370) == 6, "2×"
    assert rate_sapi(277) == 4, "1,5×"
    assert rate_sapi(90) == -7
    assert rate_sapi(1) == RATE_SAPI_MIN == -10
    assert rate_sapi("n'importe quoi") == 0
    precedent = -99
    for tts_rate in range(90, 561):
        rate = rate_sapi(tts_rate)
        assert RATE_SAPI_MIN <= rate <= RATE_SAPI_MAX
        assert rate >= precedent, "plus de débit demandé ne rend jamais la voix plus lente"
        precedent = rate
        # Le cran retenu est le plus proche : vitesse SAPI obtenue à ±5,6 % (un demi-cran) de la demande.
        assert abs(3 ** (rate / 10) / facteur_debit(tts_rate) - 1) <= 3 ** 0.05 - 1 + 1e-9


@pytest.mark.parametrize("rate", range(-10, 11))
def test_pyttsx3_retombe_exactement_sur_le_meme_cran(rate):
    """Si l'assertion tombe, pyttsx3 défait le débit au premier changement de voix.

    Formule recopiée de pyttsx3/drivers/sapi5.py (setProperty("rate") et ("voice")) :
    Rate = int(log(mots_minute / a, b)), coefficients par défaut (156,63 ; 1,11)."""
    valeur = mots_minute_pyttsx3(rate)
    assert int(math.log(valeur / 156.63, 1.11)) == rate


class MoteurQuiNote:
    """Moteur pyttsx3 factice : garde l'ORDRE des réglages et expose l'objet SAPI caché."""

    def __init__(self, sapi=None):
        self.proxy = type("P", (), {"_driver": type("D", (), {"_tts": sapi})()})() if sapi is not None else None
        self.reglages: list[tuple[str, object]] = []

    def setProperty(self, nom, valeur):  # noqa: N802 (nom imposé par pyttsx3)
        self.reglages.append((nom, valeur))


def _voix_windows(data_dir, tts_rate: int, voix: str = "", sapi=None, sortie: str = ""):
    settings = Settings(data_dir)
    settings.user.tts_rate = tts_rate
    settings.user.tts_voice = voix
    settings.user.audio_output_device = sortie
    tts = TextToSpeech(settings, FauxHub(), enabled=False)  # aucun thread, aucun COM
    tts._engine = MoteurQuiNote(sapi)
    return tts


def test_le_rate_sapi_est_pose_apres_la_voix(data_dir):
    """Si l'assertion tombe, choisir une voix remet le débit à celui que pyttsx3 avait en mémoire."""
    sapi = FauxSapi([MAINS_LIBRES])
    tts = _voix_windows(data_dir, 555, voix="HKEY_LOCAL_MACHINE\\...\\TTS_MS_FR-FR_HORTENSE_11.0", sapi=sapi)
    tts._apply_settings()
    noms = [nom for nom, _ in tts._engine.reglages]
    assert noms.index("voice") < noms.index("rate")
    assert sapi.Rate == 10
    valeur = dict(tts._engine.reglages)["rate"]
    assert int(math.log(valeur / 156.63, 1.11)) == 10, "pyttsx3 garde en mémoire le même cran"


@pytest.mark.parametrize("tts_rate, attendu", [(185, 0), (370, 6), (90, -7)])
def test_chaque_phrase_windows_recoit_le_debit_du_reglage(data_dir, tts_rate, attendu):
    sapi = FauxSapi([MAINS_LIBRES])
    tts = _voix_windows(data_dir, tts_rate, sapi=sapi)
    tts._apply_settings()
    assert sapi.Rate == attendu


def test_sans_objet_sapi_le_debit_est_transmis_tel_quel(data_dir):
    """Autre pilote que SAPI5 : pas de Rate à calculer, le réglage part en mots par minute."""
    tts = _voix_windows(data_dir, 555, sapi=None)
    tts._apply_settings()
    assert dict(tts._engine.reglages)["rate"] == 555


def test_un_rate_refuse_ne_prive_ni_de_la_voix_ni_des_lunettes(data_dir):
    """Si l'assertion tombe, un débit refusé par SAPI fait parler IRIS par le haut-parleur du PC."""

    class SapiQuiRefuseLeRate(FauxSapi):
        def __setattr__(self, nom, valeur):
            if nom == "Rate":
                raise RuntimeError("E_INVALIDARG")
            super().__setattr__(nom, valeur)

    sapi = SapiQuiRefuseLeRate([MAINS_LIBRES])
    tts = _voix_windows(data_dir, 555, voix="Hortense", sapi=sapi, sortie="M01 Pro_F444")
    tts._apply_settings()  # ne doit rien lever
    assert ("voice", "Hortense") in tts._engine.reglages
    assert sapi.AudioOutput.description == MAINS_LIBRES


# --------------------------------------------------------------------------- 3. la voix locale
class SynthetiseurQuiNote:
    """PiperVoice factice : note CHAQUE appel (arguments compris) et rend un PCM connu par phrase."""

    def __init__(self, pcm: np.ndarray, phrases: int = 3):
        self.pcm = pcm
        self.phrases = phrases
        self.appels: list[tuple[tuple, dict]] = []
        self.config = type("Cfg", (), {"sample_rate": TAUX_LOCAL, "length_scale": 1.0})()

    def synthesize(self, text, *args, **kwargs):
        self.appels.append((args, kwargs))
        pas = len(self.pcm) // self.phrases
        for i in range(self.phrases):
            morceau = self.pcm[i * pas : (i + 1) * pas if i < self.phrases - 1 else len(self.pcm)]
            yield type("Chunk", (), {"audio_int16_bytes": morceau.astype("<i2").tobytes()})()


def _voix_locale(data_dir, tts_rate: int, pcm: np.ndarray):
    settings = Settings(data_dir)
    settings.user.tts_rate = tts_rate
    settings.user.audio_output_device = ""  # sortie par défaut, au taux du modèle : rien à rééchantillonner
    sd = FauxSounddevice(_lunettes_allumees())
    sp = PiperSpeaker(settings, FauxHub())
    synthetiseur = SynthetiseurQuiNote(pcm)
    sp._sounddevice = lambda: sd
    sp._charger = lambda: synthetiseur
    sp._voice_rate = TAUX_LOCAL
    return sp, sd, synthetiseur


def test_taux_d_etirement_de_la_voix_locale():
    assert taux_etirement(185) == 1.0
    assert taux_etirement(370) == 2.0 and taux_etirement(555) == 3.0
    assert taux_etirement(90) == pytest.approx(90 / 185)


@pytest.mark.parametrize("tts_rate", [277, 370, 555])
def test_la_voix_locale_livre_le_debit_demande_sans_changer_la_hauteur(data_dir, tts_rate):
    """Si l'assertion tombe, la voix hors-ligne n'accélère pas (ou monte dans les aigus)."""
    pcm = _somme_de_sinus(TAUX_LOCAL)
    sp, sd, synthetiseur = _voix_locale(data_dir, tts_rate, pcm)
    sp._stream_and_play("Bonjour")
    facteur = tts_rate / 185
    assert len(sd.flux) == 1
    sortie = np.frombuffer(sd.flux[0].ecrit, dtype="<i2")
    assert abs(len(sortie) - len(pcm) / facteur) <= 0.05 * len(pcm) / facteur
    assert abs(_frequence_dominante(sortie, TAUX_LOCAL) - 220) <= 0.03 * 220
    # Synthèse à la vitesse naturelle : length_scale n'est pas touché (mesuré trop imprécis, voir piper.py).
    assert synthetiseur.appels == [((), {})]


def test_a_vitesse_normale_la_voix_locale_rend_le_pcm_intact(data_dir):
    pcm = _somme_de_sinus(TAUX_LOCAL, 1.0)
    sp, sd, _synthetiseur = _voix_locale(data_dir, 185, pcm)
    sp._stream_and_play("Bonjour")
    assert sd.flux[0].ecrit == pcm.astype("<i2").tobytes()


def test_une_phrase_locale_interrompue_ne_joue_pas_sa_fin_retenue(data_dir):
    """« Iris, arrête » : l'étireur retient quelques millisecondes ; elles ne doivent pas sortir après l'arrêt."""
    pcm = _somme_de_sinus(TAUX_LOCAL, 1.0)
    sp, sd, _synthetiseur = _voix_locale(data_dir, 555, pcm)
    sp._stop_flag.set()
    sp._stream_and_play("Bonjour")
    assert sd.flux[0].ecrit == b""


# --------------------------------------------------------------------------- 4. la voix premium
def test_repartition_de_la_vitesse_premium():
    """Le moteur ne fait que [0,7 ; 1,2] ; le produit (moteur × local) vaut toujours la demande."""
    assert repartir_vitesse(185) == (1.0, 1.0)
    for tts_rate in range(90, 561, 7):
        vitesse, reste = repartir_vitesse(tts_rate)
        assert VITESSE_API_MIN <= vitesse <= VITESSE_API_MAX
        assert vitesse * reste == pytest.approx(tts_rate / 185, rel=1e-3)
    assert repartir_vitesse(555) == (1.2, pytest.approx(2.5))
    assert repartir_vitesse(370) == (1.2, pytest.approx(2 / 1.2))
    assert repartir_vitesse(90) == (0.7, pytest.approx((90 / 185) / 0.7))


class SessionQuiNote(FauxSession):
    def __init__(self, pcm: bytes, tailles=None):
        super().__init__(pcm, tailles)
        self.corps: dict | None = None

    def post(self, url, headers=None, json=None, stream=False, timeout=None):
        self.corps = json
        return super().post(url, headers=headers, json=json, stream=stream, timeout=timeout)


def _voix_premium(data_dir, monkeypatch, tts_rate: int, pcm: np.ndarray, tailles=None):
    settings = Settings(data_dir)
    # Après Settings (qui recharge backend/.env) : une clé factice, rien ne part sur le réseau.
    monkeypatch.setenv("ELEVENLABS_API_KEY", "sk_factice")
    settings.user.tts_rate = tts_rate
    settings.user.audio_output_device = ""  # sortie par défaut à 24 kHz : rien à rééchantillonner
    sd = FauxSounddevice(_lunettes_allumees())
    sp = ElevenLabsSpeaker(settings, FauxHub())
    session = SessionQuiNote(pcm.astype("<i2").tobytes(), tailles)
    sp._sounddevice = lambda: sd
    sp._http = lambda: session
    return sp, sd, session


def test_a_vitesse_normale_la_requete_premium_est_celle_d_avant(data_dir, monkeypatch):
    """Si l'assertion tombe, un utilisateur qui n'a rien réglé reçoit une requête modifiée."""
    pcm = _somme_de_sinus(TAUX_PREMIUM, 1.0)
    sp, sd, session = _voix_premium(data_dir, monkeypatch, 185, pcm)
    sp._stream_and_play("Bonjour")
    assert "speed" not in session.corps["voice_settings"]
    assert sd.flux[0].ecrit == pcm.astype("<i2").tobytes()


@pytest.mark.parametrize("tts_rate", [277, 370, 555])
def test_la_voix_premium_livre_le_debit_demande(data_dir, monkeypatch, tts_rate):
    """speed plafonné à 1,2 côté moteur, le reste étiré localement : la durée finale suit la demande.

    Le faux moteur rend l'audio à vitesse normale : on vérifie ici la part LOCALE (durée / reste,
    hauteur conservée) et la valeur de speed envoyée. Ce que le vrai moteur fait de speed n'est pas
    mesurable sans réseau."""
    pcm = _somme_de_sinus(TAUX_PREMIUM)
    # morceaux impairs : la socket coupe au milieu d'un échantillon int16
    sp, sd, session = _voix_premium(data_dir, monkeypatch, tts_rate, pcm, tailles=[4801, 3, 999, 7, 12001])
    sp._stream_and_play("Bonjour")
    vitesse, reste = repartir_vitesse(tts_rate)
    assert session.corps["voice_settings"]["speed"] == vitesse == 1.2
    assert session.corps["voice_settings"]["stability"] == 0.55, "les autres réglages de voix restent intacts"
    sortie = np.frombuffer(sd.flux[0].ecrit, dtype="<i2")
    attendu = len(pcm) / reste
    assert abs(len(sortie) - attendu) <= 0.05 * attendu
    assert abs(_frequence_dominante(sortie, TAUX_PREMIUM) - 220) <= 0.03 * 220


def test_si_le_moteur_refuse_speed_la_phrase_repart_sans_et_tout_est_etire_localement(data_dir, monkeypatch):
    """Si l'assertion tombe, un modèle premium qui ne connaît pas speed renvoie CHAQUE phrase à débit
    non normal vers la voix Windows : l'utilisateur perd sa voix choisie dès qu'il accélère."""
    pcm = _somme_de_sinus(TAUX_PREMIUM, 1.0)
    sp, sd, session = _voix_premium(data_dir, monkeypatch, 555, pcm)
    corps_envoyes: list[dict] = []
    reponse_ok = session.reponse

    class Refus:
        status_code = 422
        text = '{"detail": "speed non accepté"}'

        def close(self):
            pass

    def post(url, headers=None, json=None, stream=False, timeout=None):
        corps_envoyes.append({**json, "voice_settings": dict(json["voice_settings"])})
        return Refus() if len(corps_envoyes) == 1 else reponse_ok

    session.post = post
    replis: list[str] = []
    sp.fallback_speak = lambda texte: replis.append(texte)
    sp._stream_and_play("Bonjour")
    assert len(corps_envoyes) == 2
    assert corps_envoyes[0]["voice_settings"]["speed"] == 1.2
    assert "speed" not in corps_envoyes[1]["voice_settings"]
    sortie = np.frombuffer(sd.flux[0].ecrit, dtype="<i2")
    assert abs(len(sortie) - len(pcm) / 3) <= 0.05 * len(pcm) / 3, "les 3× entiers passent par l'étirement local"
    assert replis == []


def test_la_voix_premium_ralentie_demande_0_7_et_etire_le_reste(data_dir, monkeypatch):
    pcm = _somme_de_sinus(TAUX_PREMIUM, 1.0)
    sp, sd, session = _voix_premium(data_dir, monkeypatch, 90, pcm)
    sp._stream_and_play("Bonjour")
    assert session.corps["voice_settings"]["speed"] == 0.7
    _vitesse, reste = repartir_vitesse(90)
    sortie = np.frombuffer(sd.flux[0].ecrit, dtype="<i2")
    assert abs(len(sortie) - len(pcm) / reste) <= 0.05 * len(pcm) / reste
