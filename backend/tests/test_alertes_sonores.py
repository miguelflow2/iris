"""Alertes sonores locales (interface D, chantier du 2026-09-13).

Tout est synthétique : signaux numpy générés (avertisseur T3, sirène, klaxon, carillon, coups
frappés), bruit rose, parole imitée par des sinusoïdes modulées, mélodie simple ; faux robinet, fausse
voix, faux reconnaisseur pour le prénom. Aucun micro, aucun modèle, aucun réseau.

Ce qui est protégé ici, pour une personne sourde qui se fie à l'alerte :
- chaque type est reconnu sur son signal, et SEULEMENT lui ;
- le bruit, la parole et la musique ne déclenchent rien, à toutes les sensibilités ;
- une alarme qui continue n'inonde pas d'alertes (anti-rebond de 8 s) mais continue d'être signalée ;
- la sensibilité change vraiment ce qui est entendu ;
- le service publie l'événement, parle si demandé, respecte les types choisis et s'arrête en mode
  confidentiel en le disant ;
- la route dit que ce n'est pas un avertisseur homologué, et le test passe par le vrai détecteur.
"""
from __future__ import annotations

import json
import time
import types

import numpy as np
import pytest

from iris import alertes_sonores as al
from iris.config import Settings
from iris.voice.robinet import RobinetAudio

TAUX = 16000


# --------------------------------------------------------------------------- signaux négatifs
def _i16(x: np.ndarray) -> np.ndarray:
    return np.clip(np.round(x * 32767), -32768, 32767).astype(np.int16)


def bruit_rose(duree: float, niveau_db: float, graine: int = 1) -> np.ndarray:
    return _i16(al._bruit_rose(int(duree * TAUX), np.random.default_rng(graine)) * 10 ** (niveau_db / 20))


def parole_synthetique(duree: float = 8.0, graine: int = 3, niveau_db: float = -18.0) -> np.ndarray:
    """Syllabes voisées : fondamentale 105-150 Hz qui varie (intonation), harmoniques façonnées par des
    formants de voyelles, enveloppe syllabique, pauses entre les mots, quelques fricatives."""
    rng = np.random.default_rng(graine)
    n = int(duree * TAUX)
    sortie = np.zeros(n)
    voyelles = [(730, 1090, 2440), (270, 2290, 3010), (570, 840, 2410), (440, 1020, 2240), (530, 1840, 2480)]
    t0 = 0.3
    while t0 < duree - 0.5:
        for _ in range(int(rng.integers(2, 5))):
            d = rng.uniform(0.14, 0.28)
            ns = int(d * TAUX)
            tt = np.arange(ns) / TAUX
            formants = voyelles[int(rng.integers(len(voyelles)))]
            f0 = rng.uniform(105, 150) * (1 + 0.08 * np.sin(2 * np.pi * rng.uniform(2, 5) * tt + rng.uniform(0, 6)))
            phase = 2 * np.pi * np.cumsum(f0) / TAUX
            syllabe = np.zeros(ns)
            for k in range(1, 40):
                fk = k * f0.mean()
                if fk > 4000:
                    break
                g = sum(1 / (1 + ((fk - F) / (B / 2)) ** 2) for F, B in zip(formants, (90, 110, 170)))
                syllabe += g * k ** -0.5 * np.sin(k * phase)
            syllabe *= np.sin(np.pi * tt / d) ** 0.7
            i = int(t0 * TAUX)
            if rng.random() < 0.35:
                nf = int(rng.uniform(0.05, 0.1) * TAUX)
                fricative = np.diff(np.concatenate([[0.0], rng.standard_normal(nf)])) * 0.15 * np.hanning(nf)
                j = max(0, i - nf)
                sortie[j:j + nf] += fricative[: len(sortie[j:j + nf])]
            sortie[i:i + ns] += syllabe[: len(sortie[i:i + ns])]
            t0 += d + rng.uniform(0.0, 0.06)
        t0 += rng.uniform(0.15, 0.5)
    sortie *= 10 ** (niveau_db / 20) / (np.sqrt(np.mean(sortie[sortie != 0] ** 2)) + 1e-12)
    return _i16(sortie + al._bruit_rose(n, rng) * 10 ** (-55 / 20))


def musique_simple(duree: float = 8.0, base: float = 523.3, tempo: float = 0.4) -> np.ndarray:
    """Mélodie façon piano : attaque nette, décroissance, quatre harmoniques, une note par temps."""
    n = int(duree * TAUX)
    sortie = np.zeros(n)
    melodie = [0, 2, 4, 0, 0, 2, 4, 0, 4, 5, 7, 4, 5, 7]
    t0, i = 0.2, 0
    while t0 < duree - 0.6:
        f = base * 2 ** (melodie[i % len(melodie)] / 12)
        d = tempo * (2 if i % 7 == 6 else 1)
        ns = int(min(d * 1.5, 1.2) * TAUX)
        tt = np.arange(ns) / TAUX
        note = sum(a * np.sin(2 * np.pi * (k + 1) * f * tt) for k, a in enumerate((1, 0.5, 0.25, 0.12)))
        note *= np.exp(-tt / 0.25) * np.minimum(1, tt / 0.005)
        j = int(t0 * TAUX)
        sortie[j:j + ns] += note[: len(sortie[j:j + ns])]
        t0 += d
        i += 1
    sortie *= 10 ** (-20 / 20) / (np.sqrt(np.mean(sortie ** 2)) + 1e-12)
    return _i16(sortie + al._bruit_rose(n, np.random.default_rng(9)) * 10 ** (-55 / 20))


def detecter(signal: np.ndarray, sensibilite: int = 50) -> list[dict]:
    detecteur = al.DetecteurAcoustique(sensibilite)
    trouvees: list[dict] = []
    for i in range(0, len(signal), 4000):
        trouvees += detecteur.traiter(signal[i:i + 4000].tobytes())
    return trouvees


# --------------------------------------------------------------------------- détecteur
@pytest.mark.parametrize("type_", al.TYPES_ACOUSTIQUES)
def test_chaque_type_est_reconnu_sur_son_signal_et_seulement_lui(type_):
    trouvees = detecter(al.signal_synthetique(type_))
    assert [t["type"] for t in trouvees] == [type_]
    assert 0.5 <= trouvees[0]["confiance"] <= 0.99


def test_le_micro_mains_libres_en_bande_etroite_suffit():
    """Le micro des lunettes en profil mains libres coupe au-dessus de 3,4 kHz environ (qualité téléphone)."""
    def bande_telephone(signal: np.ndarray) -> np.ndarray:
        spectre = np.fft.rfft(signal.astype(np.float64))
        f = np.fft.rfftfreq(len(signal), 1 / TAUX)
        spectre *= np.clip((3550 - f) / 300, 0, 1) * np.clip((f - 150) / 150, 0, 1)
        return np.clip(np.fft.irfft(spectre, len(signal)), -32768, 32767).astype(np.int16)

    for type_ in al.TYPES_ACOUSTIQUES:
        assert [t["type"] for t in detecter(bande_telephone(al.signal_synthetique(type_)))] == [type_], type_


_ROSE, _PAROLE, _MUSIQUE = bruit_rose(8.0, -25), parole_synthetique(), musique_simple()


# Le bruit rose n'a aucune attaque ni raie : à 0, où presque tous les seuils sont plus stricts qu'à 50,
# il n'apporte rien. La parole et la musique, elles, sont vérifiées aux trois sensibilités (le veto de
# la sonnette dépend des attaques repérées, qui changent avec la sensibilité).
@pytest.mark.parametrize("nom,signal,sensibilite", [
    ("bruit rose", _ROSE, 50), ("bruit rose", _ROSE, 100),
    ("parole", _PAROLE, 0), ("parole", _PAROLE, 50), ("parole", _PAROLE, 100),
    ("musique", _MUSIQUE, 0), ("musique", _MUSIQUE, 50), ("musique", _MUSIQUE, 100),
])
def test_bruit_rose_parole_et_musique_ne_declenchent_rien(nom, signal, sensibilite):
    assert detecter(signal, sensibilite) == [], f"fausse alerte sur {nom} (sensibilité {sensibilite})"


def test_une_alarme_qui_continue_est_resignalee_mais_pas_en_rafale():
    bip = al._ton(3150.0, 0.5, (1.0, 0.0, 0.08)) * al._rampe(int(0.5 * TAUX), 80)
    sons = [(2.0 + cycle * 3.0 + i * 1.0, bip) for cycle in range(7) for i in range(3)]
    signal = al._composer(23.0, sons, -20.0, -55.0, 4)
    instants = [t["t"] for t in detecter(signal) if t["type"] == "alarme"]
    assert len(instants) >= 2, "une alarme qui dure 20 s doit être signalée plus d'une fois"
    assert all(b - a >= al.ANTI_REBOND_S for a, b in zip(instants, instants[1:]))
    assert len(instants) <= 3


def test_la_sensibilite_change_ce_qui_est_entendu():
    faible = al.signal_synthetique("klaxon", niveau_db=-35.0, bruit_db=-40.0)
    assert detecter(faible, 0) == []
    fortes = detecter(faible, 100)
    assert [t["type"] for t in fortes] == ["klaxon"]
    # Le seuil de confiance du prénom suit la même logique : plus sensible = plus permissif.
    assert al.DetecteurPrenom.seuil(100) < al.DetecteurPrenom.seuil(50) < al.DetecteurPrenom.seuil(0)


def test_un_silence_numerique_parfait_ne_plante_ni_ne_declenche():
    assert detecter(np.zeros(5 * TAUX, dtype=np.int16), 100) == []


# --------------------------------------------------------------------------- prénom
class FauxReconnaisseur:
    """Rend, à chaque bloc « accepté », le résultat JSON qu'on lui a préparé (comme Vosk avec SetWords)."""

    def __init__(self, resultats: list[dict]):
        self.resultats = list(resultats)
        self.blocs = 0

    def AcceptWaveform(self, _bloc: bytes) -> bool:
        self.blocs += 1
        return bool(self.resultats)

    def Result(self) -> str:
        return json.dumps(self.resultats.pop(0))


def test_le_prenom_est_reconnu_avec_une_confiance_suffisante_seulement():
    mot = lambda conf: {"result": [{"word": "hélène", "conf": conf}], "text": "hélène"}  # noqa: E731
    detecteur = al.DetecteurPrenom(FauxReconnaisseur([mot(0.6), mot(0.9), mot(0.95)]), "Hélène")
    assert detecteur.traiter(b"\x00\x00", 50, 1.0) is None  # 0,6 < seuil 0,75
    trouve = detecteur.traiter(b"\x00\x00", 50, 2.0)
    assert trouve and trouve["type"] == "prenom" and trouve["confiance"] == 0.9
    assert detecteur.traiter(b"\x00\x00", 50, 5.0) is None, "anti-rebond de 8 s"


def test_le_prenom_dit_par_iris_elle_meme_est_ignore():
    reconnaisseur = FauxReconnaisseur([{"result": [{"word": "marc", "conf": 1.0}]}])
    detecteur = al.DetecteurPrenom(reconnaisseur, "marc")
    assert detecteur.traiter(b"\x00\x00", 50, 1.0, ignorer=True) is None
    assert reconnaisseur.blocs == 1, "l'audio est consommé pour garder le décodage continu"


def test_prenom_depuis_le_nom_complet():
    assert al.prenom_depuis("Miguel Tremblay") == "miguel"
    assert al.prenom_depuis("  Jean-François Côté") == "jean-françois"
    assert al.prenom_depuis("") == ""


# --------------------------------------------------------------------------- service (faux contexte)
class Bus:
    def __init__(self):
        self.evenements: list[dict] = []

    def publish(self, type_, **donnees):
        evenement = {"type": type_, **donnees}
        self.evenements.append(evenement)
        return evenement

    def de_type(self, type_):
        return [e for e in self.evenements if e["type"] == type_]


def faux_contexte(tmp_path, **reglages):
    settings = Settings(tmp_path / "donnees")
    settings.update(reglages)
    dits: list[tuple[str, bool]] = []
    voix = types.SimpleNamespace(robinet=RobinetAudio(), running=True, state="listening", error=None,
                                 start=lambda: None, _last_block=0.0)
    tts = types.SimpleNamespace(is_speaking=False, speak=lambda texte, force=False: dits.append((texte, force)) or True)
    return types.SimpleNamespace(settings=settings, hub=Bus(), voice=voix, tts=tts), dits


def attendre(condition, delai: float = 10.0) -> bool:
    fin = time.monotonic() + delai
    while time.monotonic() < fin:
        if condition():
            return True
        time.sleep(0.02)
    return False


def publier(robinet: RobinetAudio, signal: np.ndarray) -> None:
    for i in range(0, len(signal), 4000):
        robinet.publier(signal[i:i + 4000].tobytes())


def test_le_service_signale_parle_et_respecte_les_types_choisis(tmp_path):
    ctx, dits = faux_contexte(tmp_path, alertes_types=["sonnette"], alertes_voix=True)
    service = al.ServiceAlertes(ctx, fabrique_reconnaisseur=lambda prenom: None)
    service.demarrer()
    try:
        publier(ctx.voice.robinet, al.signal_synthetique("alarme"))  # type non choisi : rien
        publier(ctx.voice.robinet, al.signal_synthetique("sonnette"))
        assert attendre(lambda: ctx.hub.de_type("alerte.sonore"))
        time.sleep(0.3)
    finally:
        service.arreter()
    alertes = ctx.hub.de_type("alerte.sonore")
    assert [a["genre"] for a in alertes] == ["sonnette"]
    assert alertes[0]["test"] is False and alertes[0]["libelle"] == "Sonnette"
    assert dits == [("Sonnette détectée.", True)]
    assert service.dernieres[0]["type"] == "sonnette"
    assert not service.actif and "alertes" not in ctx.voice.robinet.abonnes()


def test_sans_voix_l_alerte_reste_silencieuse_mais_publiee(tmp_path):
    ctx, dits = faux_contexte(tmp_path, alertes_voix=False)
    service = al.ServiceAlertes(ctx, fabrique_reconnaisseur=lambda prenom: None)
    trouvees = []
    for i in range(0, len(signal := al.signal_synthetique("porte")), 4000):
        trouvees += service.traiter_bloc(signal[i:i + 4000].tobytes())
    assert [t["type"] for t in trouvees] == ["porte"] and dits == []
    assert ctx.hub.de_type("alerte.sonore")[0]["genre"] == "porte"


def test_le_mode_confidentiel_refuse_le_demarrage_et_arrete_le_fil(tmp_path):
    ctx, _dits = faux_contexte(tmp_path, privacy_mode=True)
    service = al.ServiceAlertes(ctx, fabrique_reconnaisseur=lambda prenom: None)
    with pytest.raises(al.EcouteRefusee, match="confidentiel"):
        service.demarrer()
    ctx.settings.update({"privacy_mode": False})
    service.demarrer()
    assert service.actif
    ctx.settings.update({"privacy_mode": True})
    assert attendre(lambda: not service.actif, 5.0)
    assert service.raison == al.CONFIDENTIEL


def test_en_attente_du_micro_quand_aucun_bloc_n_arrive(tmp_path):
    ctx, _dits = faux_contexte(tmp_path)
    ctx.voice.running, ctx.voice.state, ctx.voice.error = False, "off", "Micro coupé (muet)."
    service = al.ServiceAlertes(ctx, fabrique_reconnaisseur=lambda prenom: None)
    service.ATTENTE_MICRO_S = 0.3
    etat = service.demarrer()
    try:
        assert etat["raison"] == "Micro coupé (muet)." and etat["en_marche"]
        assert attendre(lambda: service.en_attente_micro, 3.0)
        assert service.etat()["en_attente_micro"] is True
    finally:
        service.arreter()


def test_le_prenom_du_service_vient_des_reglages(tmp_path):
    ctx, _dits = faux_contexte(tmp_path, user_name="", alertes_types=["prenom"])
    demandes: list[str] = []
    service = al.ServiceAlertes(ctx, fabrique_reconnaisseur=lambda prenom: demandes.append(prenom) or FauxReconnaisseur(
        [{"result": [{"word": prenom, "conf": 0.97}]}]))
    assert service.traiter_bloc(b"\x00\x00" * 4000) == []
    assert "Aucun prénom" in service.etat()["prenom"]["raison"] and demandes == []
    ctx.settings.update({"user_name": "Miguel Tremblay"})
    service.recharger_prenom()
    trouvees = service.traiter_bloc(b"\x00\x00" * 4000)
    assert demandes == ["miguel"] and [t["type"] for t in trouvees] == ["prenom"]
    assert service.etat()["prenom"] == {"prenom": "miguel", "disponible": True, "raison": None}


# --------------------------------------------------------------------------- routes
# Application légère : le routeur des alertes, le vrai bus d'événements et les vrais réglages, sans le
# reste d'IRIS. Le branchement dans create_app (authentification, crochets de démarrage) est prouvé
# par test_fondation_2026_09_13.py et par les routes de test_ecoute_assistee.py et test_bouton_lunettes.py ;
# le construire ici coûtait jusqu'à dix secondes sur une machine chargée.
@pytest.fixture(scope="module")
def application(tmp_path_factory):
    import asyncio
    from contextlib import asynccontextmanager

    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from iris import routes_alertes
    from iris.events import EventHub

    settings = Settings(tmp_path_factory.mktemp("iris-alertes"))
    hub = EventHub()
    voix = types.SimpleNamespace(robinet=RobinetAudio(), running=False, state="off", error="Micro non ouvert (test).",
                                 start=lambda: None, model_ready=lambda: False)
    ctx = types.SimpleNamespace(settings=settings, hub=hub, voice=voix, glasses=types.SimpleNamespace(connected=False),
                                tts=types.SimpleNamespace(is_speaking=False, speak=lambda texte, force=False: True))
    routeur = routes_alertes.creer_routeur(ctx)

    @asynccontextmanager
    async def cycle(_app):
        hub.bind_loop(asyncio.get_running_loop())
        await routeur.iris_demarrage()
        yield
        await routeur.iris_arret()

    app = FastAPI(lifespan=cycle)
    app.include_router(routeur)
    with TestClient(app) as client:
        yield ctx, client


def reglages(ctx, **patch) -> None:
    """Ce que fait PATCH /api/settings de main.py : enregistrer, puis publier settings.updated."""
    user = ctx.settings.update(patch)
    ctx.hub.publish("settings.updated", settings=user.model_dump())


def test_la_route_dit_que_ce_n_est_pas_un_avertisseur_homologue(application):
    ctx, client = application
    corps = client.get("/api/alertes").json()
    assert "ne remplacent pas un avertisseur homologué" in corps["avertissement"]
    assert [t["id"] for t in corps["types"]] == ["alarme", "sirene", "klaxon", "sonnette", "porte", "prenom"]
    assert set(corps) >= {"actives", "types", "sensibilite", "voix", "dernieres", "limites"}
    assert ctx.alertes is not None and ctx.ecoute_assistee is not None and ctx.bouton is not None


def test_tester_passe_par_le_vrai_detecteur_et_publie_une_alerte_de_test(application, monkeypatch):
    ctx, client = application
    publies: list[dict] = []
    original = ctx.hub.publish
    monkeypatch.setattr(ctx.hub, "publish", lambda t, **d: publies.append({"type": t, **d}) or original(t, **d))
    appels: list[int] = []
    vrai = al.DetecteurAcoustique.traiter
    monkeypatch.setattr(al.DetecteurAcoustique, "traiter", lambda self, bloc: appels.append(1) or vrai(self, bloc))
    r = client.post("/api/alertes/tester", json={"type": "alarme"})
    assert r.status_code == 200 and r.json()["detecte"] is True and r.json()["confiance"] >= 0.5
    assert appels, "le test doit passer par DetecteurAcoustique.traiter"
    alerte = [e for e in publies if e["type"] == "alerte.sonore"][-1]
    assert alerte["genre"] == "alarme" and alerte["test"] is True
    assert client.post("/api/alertes/tester", json={"type": "prenom"}).status_code == 422
    assert client.post("/api/alertes/tester", json={"type": "tonnerre"}).status_code == 422


def test_les_alertes_suivent_le_reglage_et_le_mode_confidentiel(application):
    ctx, client = application
    try:
        reglages(ctx, alertes_actives=True)
        assert attendre(lambda: ctx.alertes.actif, 5.0), "settings.updated doit démarrer les alertes"
        assert client.get("/api/alertes").json()["raison"] == "Micro non ouvert (test)."
        reglages(ctx, privacy_mode=True)
        assert attendre(lambda: not ctx.alertes.actif, 5.0)
        assert ctx.alertes.raison == al.CONFIDENTIEL
        r = client.post("/api/alertes/activer")
        assert r.status_code == 409 and "confidentiel" in r.json()["detail"]
        reglages(ctx, privacy_mode=False)
        assert attendre(lambda: ctx.alertes.actif, 5.0), "fin du mode confidentiel : les alertes voulues reprennent"
        r = client.post("/api/alertes/desactiver")
        assert r.status_code == 200 and r.json()["en_marche"] is False and not ctx.settings.user.alertes_actives
    finally:
        reglages(ctx, privacy_mode=False, alertes_actives=False)
        attendre(lambda: not ctx.alertes.actif, 5.0)
    assert not ctx.alertes.actif
