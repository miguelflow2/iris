"""Écoute assistée expérimentale (interface D, chantier du 2026-09-13).

Signaux numpy synthétiques, faux robinet, fausse sortie audio, faux module sounddevice : aucun
micro, aucun haut-parleur, aucun PortAudio réel.

Ce qui est protégé ici, pour une personne malentendante qui met ce son dans ses oreilles :
- le gain demandé est le gain obtenu, et rien ne dépasse le plafond, quel que soit le gain ;
- la réduction de bruit est MESURÉE (le bruit baisse, la voix reste) et désactivable ;
- la sortie reste muette pendant l'apprentissage du bruit et pendant qu'IRIS parle ;
- la latence est mesurée à partir de l'horodatage du micro ;
- jamais de sortie par défaut (effet Larsen), et le verrou PortAudio est toujours rendu ;
- le mode confidentiel arrête tout et le dit.
"""
from __future__ import annotations

import threading
import time
import types

import numpy as np
import pytest

from iris import ecoute_assistee as ea
from iris.alertes_sonores import CONFIDENTIEL, EcouteRefusee
from iris.config import Settings
from iris.voice.elevenlabs import VERROU_PORTAUDIO
from iris.voice.robinet import RobinetAudio

TAUX = 16000
DECALAGE = ea.TRAME - ea.PAS


def _i16(x: np.ndarray) -> np.ndarray:
    return np.clip(np.round(x * 32767), -32768, 32767).astype(np.int16)


def _db(x: np.ndarray) -> float:
    return 10 * np.log10(np.mean(np.asarray(x, dtype=np.float64) ** 2) + 1e-20)


def passer(traitement: ea.TraitementEcoute, signal: np.ndarray) -> np.ndarray:
    morceaux = [traitement.traiter(signal[i:i + 4000].tobytes()) for i in range(0, len(signal), 4000)]
    return np.frombuffer(b"".join(morceaux), dtype=np.int16).astype(np.float64) / 32768.0


def sinus(freq: float, duree: float, niveau_db: float) -> np.ndarray:
    t = np.arange(int(duree * TAUX)) / TAUX
    return np.sqrt(2) * 10 ** (niveau_db / 20) * np.sin(2 * np.pi * freq * t)


def blanc(duree: float, niveau_db: float, graine: int = 2) -> np.ndarray:
    return np.random.default_rng(graine).standard_normal(int(duree * TAUX)) * 10 ** (niveau_db / 20)


# --------------------------------------------------------------------------- traitement
def test_sans_gain_ni_reduction_le_son_ressort_intact_apres_l_apprentissage():
    entree = sinus(440, 4.0, -20) + blanc(4.0, -40)
    sortie = passer(ea.TraitementEcoute(gain_db=0, reduction=0), _i16(entree))
    apprentissage = int(ea.APPRENTISSAGE_S * TAUX)
    assert np.all(sortie[:apprentissage - ea.TRAME] == 0), "muet pendant l'apprentissage du bruit"
    debut = apprentissage + ea.TRAME
    reference = _i16(entree).astype(np.float64)[debut - DECALAGE:len(sortie) - DECALAGE] / 32768.0
    assert np.max(np.abs(sortie[debut:] - reference)) < 2e-3


def test_le_gain_demande_est_le_gain_obtenu():
    entree = _i16(sinus(440, 4.0, -35))
    sortie = passer(ea.TraitementEcoute(gain_db=12, reduction=0), entree)
    debut = int(2.0 * TAUX)
    gain = _db(sortie[debut:]) - _db(entree[debut - DECALAGE:len(sortie) - DECALAGE] / 32768.0)
    assert abs(gain - 12.0) < 0.5


def test_le_limiteur_et_le_plafond_tiennent_quel_que_soit_le_gain():
    entree = _i16(sinus(1000, 4.0, -6))  # crête ≈ -3 dB : déjà très fort
    sortie = passer(ea.TraitementEcoute(gain_db=18, reduction=0), entree)
    plafond = 10 ** (ea.PLAFOND_DB / 20)
    assert np.max(np.abs(sortie)) <= plafond + 1 / 32768
    crete_stable = np.max(np.abs(sortie[int(2.5 * TAUX):]))
    assert abs(20 * np.log10(crete_stable) - ea.LIMITEUR_DB) < 1.0, "le limiteur ramène la crête à -6 dB"


def test_la_reduction_de_bruit_est_mesuree_le_bruit_baisse_la_voix_reste():
    bruit = blanc(6.0, -35, graine=5)
    ton = np.zeros_like(bruit)
    ton[int(4.0 * TAUX):] = sinus(1000, 2.0, -20)
    entree = _i16(bruit + ton)

    def mesures(reduction: int) -> tuple[float, float]:
        sortie = passer(ea.TraitementEcoute(gain_db=0, reduction=reduction), entree)
        calme = sortie[int(2.5 * TAUX):int(3.8 * TAUX)]
        avec_ton = sortie[int(4.5 * TAUX):int(5.8 * TAUX)]
        spectre = np.abs(np.fft.rfft(avec_ton * np.hanning(len(avec_ton)))) ** 2
        case = int(round(1000 * len(avec_ton) / TAUX))
        return _db(calme), 10 * np.log10(spectre[case - 3:case + 4].sum())

    bruit_sans, ton_sans = mesures(0)
    bruit_avec, ton_avec = mesures(100)
    assert bruit_sans - bruit_avec >= 12.0, f"réduction mesurée : {bruit_sans - bruit_avec:.1f} dB"
    assert abs(ton_sans - ton_avec) < 2.0, "la voix (le ton) doit traverser la réduction"
    assert abs(bruit_sans - _db(bruit[int(2.5 * TAUX):int(3.8 * TAUX)])) < 1.0, "réduction 0 = rien d'enlevé"


# --------------------------------------------------------------------------- service (faux contexte)
class FauxFlux:
    def __init__(self, journal: dict):
        self.journal = journal
        self.latence_s = 0.012

    def ecrire(self, pcm: bytes) -> None:
        self.journal["octets"] += len(pcm)
        self.journal["ecritures"] += 1

    def fermer(self) -> None:
        self.journal["fermetures"] += 1


class FausseSortie:
    def __init__(self, nom: str = "Casque (Lunettes VELA Hands-Free)"):
        self.nom = nom
        self.journal = {"octets": 0, "ecritures": 0, "ouvertures": 0, "fermetures": 0}

    def verifier(self) -> str:
        return self.nom

    def ouvrir(self) -> FauxFlux:
        self.journal["ouvertures"] += 1
        return FauxFlux(self.journal)


class Bus:
    def __init__(self):
        self.evenements: list[dict] = []

    def publish(self, type_, **donnees):
        self.evenements.append({"type": type_, **donnees})
        return {}


def faux_contexte(tmp_path, **reglages):
    settings = Settings(tmp_path / "donnees")
    settings.update({"audio_output_device": "Lunettes VELA", **reglages})
    voix = types.SimpleNamespace(robinet=RobinetAudio(), running=True, state="listening", error=None,
                                 start=lambda: None, _last_block=0.0)
    tts = types.SimpleNamespace(is_speaking=False)
    return types.SimpleNamespace(settings=settings, hub=Bus(), voice=voix, tts=tts)


def attendre(condition, delai: float = 8.0) -> bool:
    fin = time.monotonic() + delai
    while time.monotonic() < fin:
        if condition():
            return True
        time.sleep(0.01)
    return False


def nourrir(ctx, service, signal: np.ndarray) -> None:
    """Un bloc à la fois, comme le vrai micro : le suivant n'arrive qu'une fois le précédent lu."""
    file = ctx.voice.robinet._abonnes[service.NOM_ROBINET]
    for i in range(0, len(signal), 4000):
        assert attendre(lambda: file.qsize() == 0, 3.0)
        ctx.voice._last_block = time.time()
        ctx.voice.robinet.publier(signal[i:i + 4000].tobytes())
    attendre(lambda: file.qsize() == 0, 3.0)
    time.sleep(0.1)


def test_le_service_joue_le_son_traite_et_mesure_la_latence(tmp_path):
    ctx = faux_contexte(tmp_path)
    sortie = FausseSortie()
    service = ea.ServiceEcouteAssistee(ctx, sortie=sortie)
    etat = service.demarrer(gain_db=9, reduction=40)
    try:
        assert etat["actif"] and etat["sortie"] == sortie.nom
        assert ctx.settings.user.ecoute_assistee_gain_db == 9 and ctx.settings.user.ecoute_assistee_reduction == 40
        nourrir(ctx, service, _i16(sinus(500, 3.0, -30)))
        assert attendre(lambda: sortie.journal["ecritures"] >= 4)
        assert service.latence_ms is not None and 0 <= service.latence_ms < 1000
        assert service.mesure_latence == "micro"
        assert sortie.journal["octets"] > 0
    finally:
        service.arreter()
    assert not service.actif and "ecoute_assistee" not in ctx.voice.robinet.abonnes()
    assert sortie.journal["fermetures"] >= 1, "le flux (et donc PortAudio) est rendu à l'arrêt"
    assert any(e["type"] == "ecoute_assistee.etat" for e in ctx.hub.evenements)


def test_rien_ne_joue_pendant_qu_iris_parle(tmp_path):
    ctx = faux_contexte(tmp_path)
    sortie = FausseSortie()
    service = ea.ServiceEcouteAssistee(ctx, sortie=sortie)
    service.demarrer()
    try:
        nourrir(ctx, service, _i16(sinus(500, 2.5, -30)))
        assert attendre(lambda: sortie.journal["ecritures"] >= 1)
        ctx.tts.is_speaking = True
        ecrites = sortie.journal["ecritures"]
        nourrir(ctx, service, _i16(sinus(500, 1.5, -30)))
        assert sortie.journal["ecritures"] == ecrites
        assert service.pause_voix and sortie.journal["fermetures"] >= 1
        ctx.tts.is_speaking = False
        time.sleep(0.35)
        nourrir(ctx, service, _i16(sinus(500, 1.0, -30)))
        assert attendre(lambda: sortie.journal["ecritures"] > ecrites)
        assert not service.pause_voix
    finally:
        service.arreter()


def test_un_retard_accumule_est_rattrape_en_sautant_les_vieux_blocs(tmp_path):
    ctx = faux_contexte(tmp_path)
    service = ea.ServiceEcouteAssistee(ctx, sortie=FausseSortie())
    lent = threading.Event()
    original = ea.TraitementEcoute.traiter

    def traiter_lent(self, pcm):
        lent.wait(0.05)
        return original(self, pcm)

    ea.TraitementEcoute.traiter = traiter_lent
    try:
        service.demarrer()
        for i in range(8):
            ctx.voice.robinet.publier(b"\x01\x00" * 4000)
        assert attendre(lambda: service.blocs_sautes > 0, 3.0)
    finally:
        ea.TraitementEcoute.traiter = original
        service.arreter()


def test_le_mode_confidentiel_refuse_et_arrete(tmp_path):
    ctx = faux_contexte(tmp_path, privacy_mode=True)
    service = ea.ServiceEcouteAssistee(ctx, sortie=FausseSortie())
    with pytest.raises(EcouteRefusee, match="confidentiel"):
        service.demarrer()
    ctx.settings.update({"privacy_mode": False})
    service.demarrer()
    ctx.settings.update({"privacy_mode": True})
    assert attendre(lambda: not service.actif, 5.0)
    assert service.raison == CONFIDENTIEL


def test_jamais_de_sortie_par_defaut(tmp_path):
    ctx = faux_contexte(tmp_path, audio_output_device="")
    service = ea.ServiceEcouteAssistee(ctx)  # vraie SortieLunettes : refuse avant de toucher au son
    with pytest.raises(EcouteRefusee, match="Larsen"):
        service.demarrer()
    assert not service.actif


# --------------------------------------------------------------------------- choix de la sortie réelle
class FluxPortAudio:
    def __init__(self, **options):
        self.options = options
        self.latency = 0.02
        self.ecrit = 0
        self.ferme = False

    def start(self):
        pass

    def write(self, donnees):
        self.ecrit += len(donnees)

    def stop(self):
        pass

    def close(self):
        self.ferme = True


def faux_sounddevice(refuse_16k: bool = False):
    flux: list[FluxPortAudio] = []

    def check_output_settings(device, samplerate, channels, dtype):
        if refuse_16k and samplerate == 16000:
            raise ValueError("fréquence refusée")

    def ouvrir(**options):
        flux.append(FluxPortAudio(**options))
        return flux[-1]

    return types.SimpleNamespace(
        query_hostapis=lambda: [{"name": "MME"}],
        query_devices=lambda: [
            {"name": "Haut-parleurs (Realtek)", "max_output_channels": 2, "hostapi": 0, "default_samplerate": 48000},
            {"name": "Casque (Lunettes VELA Stereo)", "max_output_channels": 2, "hostapi": 0, "default_samplerate": 44100},
            {"name": "Casque (Lunettes VELA Hands-Free AG Audio)", "max_output_channels": 1, "hostapi": 0,
             "default_samplerate": 8000},
            {"name": "Micro (Lunettes VELA Hands-Free)", "max_output_channels": 0, "hostapi": 0, "default_samplerate": 8000},
        ],
        check_output_settings=check_output_settings,
        RawOutputStream=ouvrir,
        flux=flux,
    )


def test_la_sortie_des_lunettes_suit_la_regle_des_voix_et_rend_le_verrou(tmp_path, monkeypatch):
    settings = Settings(tmp_path / "donnees")
    settings.update({"audio_output_device": "Lunettes VELA Stereo", "audio_input_device": "Micro (Lunettes VELA Hands-Free)"})
    sortie = ea.SortieLunettes(settings)
    sd = faux_sounddevice(refuse_16k=True)
    monkeypatch.setattr(sortie, "_sounddevice", lambda: sd)
    idx, taux, nom = sortie.choisir()
    assert "Hands-Free" in nom and idx == 2 and taux == 8000, "micro mains libres : la sortie mains libres gagne"
    flux = sortie.ouvrir()
    assert flux is not None and VERROU_PORTAUDIO.locked()
    flux.ecrire(b"\x00\x01" * 1600)  # 0,1 s à 16 kHz, rééchantillonné vers 8 kHz
    assert 0 < sd.flux[-1].ecrit < 3200
    flux.fermer()
    flux.fermer()  # deux fermetures ne libèrent pas deux fois
    assert not VERROU_PORTAUDIO.locked() and sd.flux[-1].ferme
    # Une voix d'IRIS tient PortAudio : on n'ouvre rien, on réessaiera.
    with VERROU_PORTAUDIO:
        assert sortie.ouvrir() is None
    settings.update({"audio_output_device": "Casque absent"})
    with pytest.raises(ea.SortieIndisponible, match="introuvable"):
        sortie.verifier()
    assert not VERROU_PORTAUDIO.locked()


# --------------------------------------------------------------------------- routes
def test_routes_de_l_ecoute_assistee(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from iris.main import create_app

    app = create_app(data_dir=tmp_path / "iris", token="test-token", use_keyring=False, enable_tts=False)
    ctx = app.state.ctx
    try:
        with TestClient(app, headers={"Authorization": "Bearer test-token"}) as client:
            r = client.post("/api/ecoute/assistee/demarrer", json={})
            assert r.status_code == 409 and "Larsen" in r.json()["detail"]
            monkeypatch.setattr(ctx.voice, "start", lambda *a, **k: ctx.voice.status())
            ctx.ecoute_assistee.sortie = FausseSortie()
            r = client.post("/api/ecoute/assistee/demarrer", json={"gain_db": 30})
            assert r.status_code == 200, r.text
            corps = r.json()
            assert corps["assistee"]["actif"] is True and "alertes" in corps and "sous_titres" in corps
            assert ctx.settings.user.ecoute_assistee_gain_db == 18, "gain borné par les réglages"
            assert client.get("/api/ecoute/assistee").json()["experimental"] is True
            r = client.post("/api/ecoute/assistee/arreter")
            assert r.status_code == 200 and r.json()["assistee"]["actif"] is False
    finally:
        ctx.ecoute_assistee.arreter()
        ctx.close()
