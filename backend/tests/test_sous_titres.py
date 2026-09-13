"""Sous-titres en direct (interface C) : faux reconnaisseur, blocs synthétiques dans le robinet, sans micro.

Ce qui est prouvé ici : partiels limités à 4 par seconde, une ligne finale par phrase, démarrage de
l'écoute quand elle est arrêtée, refus en mode confidentiel ou sans modèle, « en attente du micro »,
arrêt propre (robinet libéré, témoin micro), journal continu relancé par l'entretien.
"""
from __future__ import annotations

import json
import threading
import time

import numpy as np
import pytest

from iris import sous_titres as st

PAROLE = (np.sin(np.arange(4000) * 2 * np.pi * 220 / 16000) * 9000).astype(np.int16).tobytes()
SILENCE = np.zeros(4000, dtype=np.int16).tobytes()


class FauxReconnaisseur:
    """Protocole Vosk : une phrase par rafale de parole suivie d'un silence."""

    def __init__(self, phrases: list[str]):
        self.phrases = list(phrases)
        self.parole = 0
        self.final = ""

    def AcceptWaveform(self, bloc: bytes) -> bool:
        pic = int(np.abs(np.frombuffer(bloc, dtype=np.int16)).max()) if bloc else 0
        if pic > 1000:
            self.parole += 1
            return False
        if self.parole:
            self.parole = 0
            self.final = self.phrases.pop(0) if self.phrases else ""
            return True
        return False

    def Result(self) -> str:
        texte, self.final = self.final, ""
        return json.dumps({"text": texte})

    def PartialResult(self) -> str:
        if not self.parole or not self.phrases:
            return json.dumps({"partial": ""})
        mots = self.phrases[0].split()
        return json.dumps({"partial": " ".join(mots[: min(len(mots), self.parole)])})

    def FinalResult(self) -> str:
        return json.dumps({"text": ""})


def attendre(condition, delai: float = 5.0) -> bool:
    fin = time.monotonic() + delai
    while time.monotonic() < fin:
        if condition():
            return True
        time.sleep(0.02)
    return condition()


@pytest.fixture()
def ecoute(app):
    """L'écoute « tourne » (fil factice) : le robinet est alimenté à la main par le test."""
    voice = app.state.ctx.voice
    voice._stop.clear()
    fil = threading.Thread(target=voice._stop.wait, daemon=True)
    fil.start()
    voice._thread = fil
    yield voice
    voice._stop.set()
    fil.join(timeout=1)


@pytest.fixture()
def evenements(app):
    ctx = app.state.ctx
    publies: list[dict] = []
    original = ctx.hub.publish

    def publier(type_, **data):
        publies.append({"type": type_, **data})
        return original(type_, **data)

    ctx.hub.publish = publier
    yield publies
    ctx.hub.publish = original


def _brancher(ctx, phrases):
    service = ctx.sous_titres
    service.fabrique_reconnaisseur = lambda: FauxReconnaisseur(phrases)
    return service


def test_partiels_limites_et_une_ligne_par_phrase(ecoute, client, app, evenements):
    ctx = app.state.ctx
    service = _brancher(ctx, ["bonjour tout le monde", "on commence la réunion"])
    r = client.post("/api/ecoute/sous-titres/demarrer")
    assert r.status_code == 200, r.text
    assert r.json()["sous_titres"] is True and r.json()["modele_pret"] in (True, False)
    assert st.NOM_ROBINET in ecoute.robinet.abonnes()
    assert ctx.capture.snapshot()["mic"] is True
    for _ in range(12):  # 3 s de parole livrées d'un coup : le décodage va plus vite que 4 partiels/s
        ecoute.robinet.publier(PAROLE)
    ecoute.robinet.publier(SILENCE)
    assert attendre(lambda: any(e["type"] == "ecoute.sous_titre" and e.get("final") for e in evenements))
    for _ in range(4):
        ecoute.robinet.publier(PAROLE)
    ecoute.robinet.publier(SILENCE)
    assert attendre(lambda: len(service.lignes()) == 2)
    partiels = [e for e in evenements if e["type"] == "ecoute.sous_titre" and e.get("partiel")]
    assert 1 <= len(partiels) <= 3, "au plus 4 partiels par seconde"
    textes = [l["texte"] for l in client.get("/api/ecoute/transcription").json()["lignes"]]
    assert textes == ["Bonjour tout le monde", "On commence la réunion"]
    fin = client.post("/api/ecoute/sous-titres/arreter").json()
    assert [l["texte"] for l in fin["lignes"]] == textes
    assert fin["etat"]["sous_titres"] is False
    assert attendre(lambda: not service.actif)
    assert st.NOM_ROBINET not in ecoute.robinet.abonnes()
    # L'écoute tourne encore : le témoin micro reste allumé.
    assert ctx.capture.snapshot()["mic"] is True
    assert any(e["type"] == "ecoute.etat" for e in evenements)


def test_mode_confidentiel_refuse_sans_toucher_a_lecoute(client, app, monkeypatch):
    ctx = app.state.ctx
    _brancher(ctx, ["rien"])
    appels: list[int] = []
    monkeypatch.setattr(ctx.voice, "start", lambda *a, **k: appels.append(1))
    ctx.settings.user.privacy_mode = True
    try:
        r = client.post("/api/ecoute/sous-titres/demarrer")
        assert r.status_code == 409 and "confidentiel" in r.json()["detail"].lower()
        assert appels == [] and not ctx.sous_titres.actif
        assert client.post("/api/ecoute/enregistrement/demarrer").status_code == 409
    finally:
        ctx.settings.user.privacy_mode = False


def test_modele_hors_ligne_absent_refuse_clairement(ecoute, client, app, monkeypatch):
    monkeypatch.setattr(st.stt, "model_dir", lambda *a, **k: None)  # même si un modèle traîne sur la machine
    r = client.post("/api/ecoute/sous-titres/demarrer")  # vraie fabrique Vosk
    assert r.status_code == 409 and "hors ligne" in r.json()["detail"]
    assert client.get("/api/ecoute/etat").json()["modele_pret"] is False


def test_demarre_lecoute_si_arretee_et_rend_sa_raison(app, monkeypatch):
    ctx = app.state.ctx
    service = _brancher(ctx, ["bonjour"])
    voice = ctx.voice
    appels: list[int] = []

    def faux_start(*_a, **_k):
        appels.append(1)
        voice.error = "Connecte tes lunettes VELA pour utiliser IRIS."
        return {}

    monkeypatch.setattr(voice, "start", faux_start)
    with pytest.raises(st.EcouteImpossible) as refus:
        service.demarrer("ecran")
    assert appels == [1] and "lunettes" in refus.value.message

    def vrai_start(*_a, **_k):
        appels.append(2)
        voice._stop.clear()
        voice._thread = threading.Thread(target=voice._stop.wait, daemon=True)
        voice._thread.start()
        return {}

    monkeypatch.setattr(voice, "start", vrai_start)
    service.demarrer("ecran")
    try:
        assert appels == [1, 2] and service.actif
    finally:
        service.arreter_tout()
        voice._stop.set()


def test_en_attente_du_micro_puis_reprise(ecoute, app, monkeypatch):
    monkeypatch.setattr(st, "ATTENTE_MICRO_S", 0.3)
    service = _brancher(app.state.ctx, ["bonjour"])
    service.demarrer("ecran")
    try:
        assert attendre(lambda: service.raison == st.ATTENTE_MICRO, 3)
        assert "attente du micro" in app.state.ctx.ecoute_etat()["raison"].lower()
        ecoute.robinet.publier(SILENCE)
        assert attendre(lambda: service.raison is None, 3)
    finally:
        service.arreter_tout()
    assert not service.actif


def test_liberer_micro_neteint_que_si_personne_ne_sen_sert(app):
    ctx = app.state.ctx
    ctx.capture.set(mic=True)
    ctx.voice.robinet.abonner("alertes")
    st.liberer_micro(ctx, "sous-titres")
    assert ctx.capture.snapshot()["mic"] is True, "un autre abonné utilise encore le micro"
    ctx.voice.robinet.desabonner("alertes")
    st.liberer_micro(ctx, "sous-titres")
    assert ctx.capture.snapshot()["mic"] is False


def test_journal_continu_relance_par_lentretien_et_ecrit_les_finals(ecoute, app):
    ctx = app.state.ctx
    service = _brancher(ctx, ["marc a parlé du devis"])
    ctx.settings.user.journal_continu = True
    try:
        ctx.ecoute_tic()
        assert "journal" in service.demandes() and service.actif
        assert ctx.ecoute_etat()["journal"] is True
        for _ in range(3):
            ecoute.robinet.publier(PAROLE)
        ecoute.robinet.publier(SILENCE)
        assert attendre(lambda: ctx.journal.compter() == 1)
        assert ctx.journal.chercher("devis")[0]["texte"] == "Marc a parlé du devis"
        ctx.settings.user.journal_continu = False
        ctx.ecoute_tic()
        assert "journal" not in service.demandes()
        assert attendre(lambda: not service.actif)
    finally:
        ctx.settings.user.journal_continu = False
        service.arreter_tout()


def test_mode_confidentiel_arrete_tout_a_lentretien(ecoute, app):
    ctx = app.state.ctx
    service = _brancher(ctx, ["bonjour"])
    service.demarrer("ecran")
    assert service.actif
    ctx.settings.user.privacy_mode = True
    try:
        ctx.ecoute_tic()
        assert not service.actif and service.demandes() == []
    finally:
        ctx.settings.user.privacy_mode = False


def test_transcrire_pcm_date_les_phrases_depuis_le_debut():
    pcm = SILENCE * 4 + PAROLE * 4 + SILENCE * 2 + PAROLE * 2 + SILENCE
    lignes = st.transcrire_pcm(FauxReconnaisseur(["premiere phrase", "le"]), pcm)
    # « le » seul est un bruit typique du petit modèle : pas de ligne.
    assert [l["texte"] for l in lignes] == ["Premiere phrase"]
    assert 0.4 <= lignes[0]["ts"] <= 1.0
    progres: list[float] = []
    st.transcrire_pcm(FauxReconnaisseur(["a b", "c d"]), pcm, progression=progres.append)
    assert progres and progres == sorted(progres) and progres[-1] < 1.0
