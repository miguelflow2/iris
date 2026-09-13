"""Enregistrement WAV depuis le robinet (interface C) : blocs synthétiques, sans micro.

Prouvé ici : fichier WAV 16 kHz mono complet, annonce vocale selon le réglage, témoin micro,
événement album.nouveau, limite de durée, refus (espace disque, mode confidentiel, mémoire
suspendue, rien en cours) et rétention des fichiers.
"""
from __future__ import annotations

import os
import threading
import time
import wave

import numpy as np
import pytest

from iris import enregistrement_audio as ea

BLOC = (np.sin(np.arange(4000) * 2 * np.pi * 440 / 16000) * 5000).astype(np.int16).tobytes()


def attendre(condition, delai: float = 5.0) -> bool:
    fin = time.monotonic() + delai
    while time.monotonic() < fin:
        if condition():
            return True
        time.sleep(0.02)
    return condition()


@pytest.fixture()
def ecoute(app):
    voice = app.state.ctx.voice
    voice._stop.clear()
    fil = threading.Thread(target=voice._stop.wait, daemon=True)
    fil.start()
    voice._thread = fil
    yield voice
    voice._stop.set()
    fil.join(timeout=1)


@pytest.fixture()
def paroles(app, monkeypatch):
    dites: list[str] = []
    monkeypatch.setattr(app.state.ctx.tts, "speak", lambda texte, force=False: dites.append(texte) or True)
    return dites


def test_enregistre_un_wav_complet_et_lannonce(ecoute, client, app, paroles):
    ctx = app.state.ctx
    publies: list[dict] = []
    original = ctx.hub.publish
    ctx.hub.publish = lambda type_, **data: publies.append({"type": type_, **data}) or original(type_, **data)
    try:
        r = client.post("/api/ecoute/enregistrement/demarrer")
        assert r.status_code == 200, r.text
        nom = r.json()["nom"]
        assert r.json()["actif"] is True and nom.startswith("enregistrement-") and nom.endswith(".wav")
        assert client.post("/api/ecoute/enregistrement/demarrer").status_code == 409, "un seul à la fois"
        assert ctx.capture.snapshot()["mic"] is True
        for _ in range(8):  # 2 s
            ecoute.robinet.publier(BLOC)
        assert attendre(lambda: ctx.enregistreur.session.octets_audio == 64000)
        etat = client.get("/api/ecoute/etat").json()["enregistrement"]
        assert etat == {"actif": True, "nom": nom, "secondes": 2.0}
        fin = client.post("/api/ecoute/enregistrement/arreter").json()
        assert fin == {"nom": nom, "secondes": 2.0, "octets": 64044}
        with wave.open(str(app.state.ctx.settings.data_dir / "captures" / "audio" / nom), "rb") as w:
            assert (w.getnchannels(), w.getsampwidth(), w.getframerate(), w.getnframes()) == (1, 2, 16000, 32000)
            assert w.readframes(4000) == BLOC
        assert attendre(lambda: "Enregistrement." in paroles, 2)
        # « genre » et non « type » : EventHub.publish range le nom de l'événement sous « type ».
        assert any(e["type"] == "album.nouveau" and e["nom"] == nom and e["genre"] == "audio" and e["octets"] == 64044
                   for e in publies)
        assert client.post("/api/ecoute/enregistrement/arreter").status_code == 409
        assert "enregistrement" not in ecoute.robinet.abonnes()
    finally:
        ctx.hub.publish = original


def test_sans_annonce_si_le_reglage_est_coupe(ecoute, app, paroles):
    ctx = app.state.ctx
    ctx.settings.user.annonce_capture = False
    try:
        ctx.enregistreur.demarrer()
        ctx.enregistreur.arreter()
        time.sleep(0.1)
        assert paroles == []
    finally:
        ctx.settings.user.annonce_capture = True


def test_limite_de_duree_arrete_et_garde_le_fichier(ecoute, app, tmp_path):
    ctx = app.state.ctx
    fins: list[dict] = []
    session = ea.SessionEnregistrement(ctx, tmp_path / "limite.wav", "test-limite", fin=fins.append, duree_max_s=0.5)
    session.demarrer()
    for _ in range(4):
        ecoute.robinet.publier(BLOC)
    assert attendre(lambda: not session.actif, 3)
    assert session.raison == ea.DUREE_ATTEINTE and fins[0]["automatique"] is True
    with wave.open(str(tmp_path / "limite.wav"), "rb") as w:
        assert w.getnframes() == 8000


def test_refus_explicables(ecoute, app, monkeypatch):
    ctx = app.state.ctx
    monkeypatch.setattr(ea, "espace_libre", lambda _d: 10 * 1024 * 1024)
    with pytest.raises(ea.EcouteImpossible) as refus:
        ctx.enregistreur.demarrer()
    assert "espace disque" in refus.value.message.lower()
    monkeypatch.setattr(ea, "espace_libre", lambda _d: ea.ESPACE_MIN_DEMARRAGE * 10)
    ctx.memory.suspendre("zone:Clinique")
    try:
        with pytest.raises(ea.EcouteImpossible) as refus:
            ctx.enregistreur.demarrer()
        assert "zone:Clinique" in refus.value.message
    finally:
        ctx.memory.reprendre("zone:Clinique")
    with pytest.raises(ea.EcouteImpossible):
        ctx.enregistreur.arreter()
    assert not ctx.enregistreur.actif


def test_le_mode_confidentiel_arrete_un_enregistrement_en_cours(ecoute, app, paroles):
    ctx = app.state.ctx
    ctx.enregistreur.demarrer()
    ctx.settings.user.privacy_mode = True
    try:
        ctx.ecoute_tic()
        assert not ctx.enregistreur.actif
    finally:
        ctx.settings.user.privacy_mode = False


def test_retention_des_fichiers(tmp_path):
    vieux = tmp_path / "enregistrement-20260101-120000.wav"
    recent = tmp_path / "cours-20260912-090000.wav"
    etranger = tmp_path / "photo-20260101.wav"
    for chemin in (vieux, recent, etranger):
        chemin.write_bytes(b"RIFF")
    ancien = time.time() - 40 * 86400
    os.utime(vieux, (ancien, ancien))
    os.utime(etranger, (ancien, ancien))
    assert ea.purger_fichiers(tmp_path, 0) == []
    assert ea.purger_fichiers(tmp_path, 30) == [vieux.name]
    assert recent.exists() and etranger.exists(), "seuls les fichiers de ce module sont purgés"
