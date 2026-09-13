"""Verrou vocal (interface I, 2026-09-13) : caractéristiques MFCC, score calibré, consentement
biométrique, stockage chiffré, installation du vérificateur dans l'écoute.

Voix SYNTHÉTIQUES : un « locuteur » est une fréquence fondamentale et une longueur de conduit vocal
(facteur appliqué aux formants) ; chaque phrase tire au hasard ses voyelles, son intonation et son souffle.
Même locuteur, phrases différentes = score haut ; autre timbre = score bas. Aucun micro, aucun réseau.
"""
from __future__ import annotations

import threading
import time
from functools import lru_cache

import numpy as np
import pytest

from iris import verrou_vocal as vv
from iris.verrou_vocal import RefusVerrouVocal

TAUX = 16000
VOYELLES = ((730, 1090, 2440), (530, 1840, 2480), (270, 2290, 3010), (570, 840, 2410),
            (300, 870, 2240), (660, 1720, 2410), (490, 910, 2350))


@lru_cache(maxsize=None)
def voix(f0: float, conduit: float, secondes: float, graine: int) -> bytes:
    """Synthèse additive : harmoniques de f0 pondérées par trois formants (× conduit), syllabes et pauses."""
    rng = np.random.default_rng(graine)
    n = int(secondes * TAUX)
    t = np.arange(n) / TAUX
    contour = f0 * (1 + 0.08 * np.sin(2 * np.pi * rng.uniform(0.3, 0.8) * t + rng.uniform(0, 6))
                    + 0.01 * np.sin(2 * np.pi * 5.5 * t))
    phase = 2 * np.pi * np.cumsum(contour) / TAUX
    sortie = np.zeros(n)
    pos = 0
    while pos < n:
        duree = int(rng.uniform(0.12, 0.3) * TAUX)
        fin = min(n, pos + duree)
        formants = VOYELLES[int(rng.integers(len(VOYELLES)))]
        k = np.arange(1, int(7800 / f0) + 1)[:, None]
        fk = k * float(contour[pos:fin].mean())  # enveloppe par syllabe : assez fin pour le timbre, bien plus rapide
        amp = np.ones_like(fk) / k
        for j, formant in enumerate(formants):
            f = formant * conduit
            b = 60 + 40 * j
            amp /= np.sqrt((1 - (fk / f) ** 2) ** 2 + (fk * b / f ** 2) ** 2 + 1e-9)
        amp[fk > 7800] = 0
        segment = (amp * np.sin(k * phase[pos:fin][None, :])).sum(axis=0)
        rampe = min(160, (fin - pos) // 4)
        if rampe:
            segment[:rampe] *= np.linspace(0, 1, rampe)
            segment[-rampe:] *= np.linspace(1, 0, rampe)
        sortie[pos:fin] = segment
        pos = fin + (int(rng.uniform(0.02, 0.15) * TAUX) if rng.random() < 0.35 else 0)
    sortie /= np.max(np.abs(sortie)) + 1e-9
    sortie += 0.02 * rng.standard_normal(n)
    sortie *= rng.uniform(0.3, 0.8) / (np.max(np.abs(sortie)) + 1e-9)
    return (sortie * 32767).astype(np.int16).tobytes()


PROPRIETAIRE = (120.0, 1.0)
AUTRE_TIMBRE = (210.0, 1.18)


def _service(app):
    return app.state.ctx.verrou_vocal


def _enregistrer_proprietaire(service, n: int = 3) -> None:
    service.definir_consentement(True)
    for graine in range(n):
        service.ajouter_echantillon_pcm(voix(*PROPRIETAIRE, 4.0, graine))


# --------------------------------------------------------------------------- caractéristiques
def test_mfcc_cmn_deltas_et_rejet_du_silence_et_du_bruit_stable():
    mesures = vv.caracteristiques(voix(*PROPRIETAIRE, 2.0, 1))
    assert mesures["n"] > 150
    assert mesures["trames"].shape == (mesures["n"], 2 * vv.NB_COEFS)
    # normalisation cepstrale : la moyenne des coefficients statiques normalisés est nulle
    assert np.allclose(mesures["trames"][:, :vv.NB_COEFS].mean(axis=0), 0, atol=1e-9)
    assert mesures["modulation"] > vv.MODULATION_MIN
    assert vv.caracteristiques(b"\x00\x00" * TAUX)["n"] == 0
    assert vv.caracteristiques(b"")["n"] == 0
    t = np.arange(2 * TAUX) / TAUX
    sifflement = (0.3 * 32767 * np.sin(2 * np.pi * 1000 * t)).astype(np.int16).tobytes()
    souffle = (0.2 * 32767 * np.random.default_rng(0).standard_normal(2 * TAUX)).clip(-32767, 32767)
    for stable in (sifflement, souffle.astype(np.int16).tobytes()):
        assert vv.caracteristiques(stable)["modulation"] < vv.MODULATION_MIN, "un son stable n'est pas de la parole"


def test_banc_mel_et_dct_bien_formes():
    assert vv.BANC_MEL.shape == (vv.NB_FILTRES, vv.NFFT // 2 + 1)
    assert (vv.BANC_MEL.sum(axis=1) > 0).all()
    assert np.allclose(vv.DCT @ vv.DCT.T, np.eye(vv.NB_FILTRES), atol=1e-9), "DCT orthonormée"


# --------------------------------------------------------------------------- score
def test_meme_locuteur_score_haut_autre_timbre_score_bas():
    echantillons = []
    for graine in range(3):
        m = vv.caracteristiques(voix(*PROPRIETAIRE, 4.0, graine))
        echantillons.append({"n": m["n"], "moyenne": m["moyenne"], "carres": m["carres"]})
    modele = vv.construire_modele(echantillons)
    echelle = vv.calibrer(echantillons)

    def score(pcm: bytes) -> int:
        m = vv.caracteristiques(pcm)
        return vv.score_depuis_ecart(vv.ecart(m["moyenne"], m["n"], modele), echelle)

    memes = [score(voix(*PROPRIETAIRE, 2.0, 100 + g)) for g in range(4)]
    autres = [score(voix(*AUTRE_TIMBRE, 2.0, 200 + g)) for g in range(4)]
    assert min(memes) >= 70, memes
    assert max(autres) <= 40, autres
    assert vv.score_depuis_ecart(0.0, 1.0) == 100 and vv.score_depuis_ecart(5.0, 1.0) == 50


# --------------------------------------------------------------------------- consentement et stockage
def test_aucun_enregistrement_sans_consentement_expres(app):
    service = _service(app)
    with pytest.raises(RefusVerrouVocal) as refus:
        service.ajouter_echantillon_pcm(voix(*PROPRIETAIRE, 4.0, 0))
    assert refus.value.code == 403
    assert not service.fichier.exists()


def test_empreinte_chiffree_rechargee_puis_effacee_au_retrait_du_consentement(app):
    service = _service(app)
    _enregistrer_proprietaire(service)
    assert service.pret and service.fichier.exists()
    brut = service.fichier.read_bytes()
    assert b"moyenne" not in brut and b"echantillons" not in brut, "l'empreinte doit être chiffrée"
    relu = vv.VerrouVocal(app.state.ctx)
    assert len(relu._echantillons) == 3
    etat = service.definir_consentement(False)
    assert etat["echantillons"] == 0 and not etat["consentement_biometrique"]
    assert not service.fichier.exists()


def test_un_echantillon_sans_parole_est_refuse(app):
    service = _service(app)
    service.definir_consentement(True)
    with pytest.raises(RefusVerrouVocal) as refus:
        service.ajouter_echantillon_pcm(b"\x00\x00" * (4 * TAUX))
    assert refus.value.code == 422


# --------------------------------------------------------------------------- vérificateur dans l'écoute
def test_le_verrou_refuse_une_autre_voix_et_admet_le_proprietaire(app):
    ctx = app.state.ctx
    service = _service(app)
    publies: list[dict] = []
    ctx.voice.hub.publish = lambda type_, **data: publies.append({"type": type_, **data}) or {}
    _enregistrer_proprietaire(service)
    assert ctx.voice.verificateur_locuteur is None, "réglage inactif : rien n'est installé"
    ctx.settings.update({"verrou_vocal_actif": True, "verrou_vocal_seuil": 70})
    service.appliquer()
    assert ctx.voice.verificateur_locuteur == service.verifier and service.etat()["actif"] is True
    assert ctx.voice._locuteur_admis(voix(*PROPRIETAIRE, 2.0, 300))
    assert not ctx.voice._locuteur_admis(voix(*AUTRE_TIMBRE, 2.0, 301))
    assert publies[-1]["type"] == "voice.locuteur_refuse" and "voix non reconnue" in publies[-1]["raison"]
    admis, raison = service.verifier(voix(*PROPRIETAIRE, 0.3, 302))
    assert not admis and "trop courte" in raison
    ctx.settings.update({"verrou_vocal_actif": False})
    service.appliquer()
    assert ctx.voice.verificateur_locuteur is None


def test_effacer_retire_le_verificateur_et_le_reglage(app):
    ctx = app.state.ctx
    service = _service(app)
    _enregistrer_proprietaire(service)
    ctx.settings.update({"verrou_vocal_actif": True})
    service.appliquer()
    service.effacer()
    assert ctx.voice.verificateur_locuteur is None
    assert ctx.settings.user.verrou_vocal_actif is False


# --------------------------------------------------------------------------- routes et robinet
def test_routes_voix_etat_consentement_echantillon_par_le_robinet_et_test(client, app, monkeypatch):
    ctx = app.state.ctx
    service = _service(app)
    etat = client.get("/api/confiance/voix").json()
    assert etat["consentement_biometrique"] is False and etat["enregistree"] is False
    assert "mot de passe reste la vraie protection" in etat["limite"]
    assert "biométrique" in etat["texte_consentement"] and "Commission d'accès" in etat["note_legale"]
    assert client.post("/api/confiance/voix/echantillon", json={"secondes": 2}).status_code == 403
    assert client.post("/api/confiance/voix/consentement", json={"accepte": True}).json()["consentement_biometrique"]

    monkeypatch.setattr(service, "_empechement", lambda: None)  # l'écoute « tourne » : le robinet est ouvert

    def micro(pcm: bytes) -> threading.Thread:
        def publier() -> None:
            for _ in range(200):
                if vv.NOM_ROBINET in ctx.voice.robinet.abonnes():
                    break
                time.sleep(0.01)
            for i in range(0, len(pcm), 8000):
                ctx.voice.robinet.publier(pcm[i:i + 8000])
        fil = threading.Thread(target=publier, daemon=True)
        fil.start()
        return fil

    for graine in range(3):
        fil = micro(voix(*PROPRIETAIRE, 2.5, 10 + graine))
        r = client.post("/api/confiance/voix/echantillon", json={"secondes": 2.5})
        fil.join(timeout=5)
        assert r.status_code == 200, r.text
    assert r.json() == {"echantillons": 3, "pret": True}
    assert vv.NOM_ROBINET not in ctx.voice.robinet.abonnes(), "désabonné après l'enregistrement"

    fil = micro(voix(*AUTRE_TIMBRE, 2.5, 50))
    essai = client.post("/api/confiance/voix/tester", json={"secondes": 2.5})
    fil.join(timeout=5)
    assert essai.status_code == 200 and essai.json()["admis"] is False and 0 <= essai.json()["score"] <= 100

    assert client.delete("/api/confiance/voix").json()["echantillons"] == 0


def test_en_attente_du_micro_et_mode_confidentiel(app, monkeypatch):
    ctx = app.state.ctx
    service = _service(app)
    monkeypatch.setattr(vv, "ATTENTE_MICRO_S", 0.3)
    monkeypatch.setattr(service, "_empechement", lambda: None)
    with pytest.raises(RefusVerrouVocal) as refus:
        service.enregistrer(2)
    assert refus.value.code == 409 and "En attente du micro" in refus.value.message
    monkeypatch.undo()
    ctx.settings.update({"privacy_mode": True})
    with pytest.raises(RefusVerrouVocal) as refus:
        service.enregistrer(2)
    assert refus.value.code == 409 and "confidentiel" in refus.value.message
