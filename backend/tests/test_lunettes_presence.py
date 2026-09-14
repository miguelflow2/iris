"""« Lunettes d'abord » (décisions de Miguel, 2026-09-13).

IRIS est vendue avec les lunettes VELA : toute fonction qui capte ou agit exige des lunettes
présentes (PC ou téléphone attesté) ; le chat écrit a droit à un aperçu limité ; le mode
démonstration est un accès propriétaire caché ; les réglages qui ouvriraient IRIS sans lunettes ne
se modifient pas depuis l'application.
"""
from __future__ import annotations

import pytest

from iris.lunettes_presence import APERCU_MESSAGES, DUREE_ATTESTATION_S, LunettesRequises, PresenceLunettes


class _Horloge:
    def __init__(self) -> None:
        self.t = 1_000_000.0

    def __call__(self) -> float:
        return self.t


def _sans_lunettes(app, monkeypatch, nom: str = "M01 Pro_F444"):
    ctx = app.state.ctx
    ctx.settings.update({"require_glasses": True, "demo_sans_lunettes": False,
                         "glasses": {"name": nom, "address": "65:A2:9F:5C:F4:44" if nom else "", "auto_connect": False}})
    monkeypatch.setattr(ctx.voice, "lunettes_presentes", lambda: False)
    return ctx


# --------------------------------------------------------------------------- présence
def test_sans_preuve_les_lunettes_sont_absentes_meme_sur_un_pc_neuf(app, monkeypatch):
    ctx = _sans_lunettes(app, monkeypatch, nom="")
    assert ctx.presence_lunettes.presentes() is False, "plus de passe-droit pour un appareil qui n'a jamais eu de lunettes"
    with pytest.raises(LunettesRequises) as refus:
        ctx.presence_lunettes.exiger("decrire")
    assert refus.value.status_code == 428
    assert refus.value.detail["code"] == "lunettes_requises" and refus.value.detail["fonction"] == "decrire"
    assert "velaglass.ca" in refus.value.detail["acheter_url"]


def test_les_trois_preuves(app, monkeypatch):
    ctx = _sans_lunettes(app, monkeypatch)
    presence = ctx.presence_lunettes
    monkeypatch.setattr(ctx.voice, "lunettes_presentes", lambda: True)
    assert presence.source() == "pc"
    monkeypatch.setattr(ctx.voice, "lunettes_presentes", lambda: False)
    presence.attester("M01 Pro_F444", "ABC-123", 80)
    assert presence.source() == "telephone"
    presence.retirer_attestation()
    assert presence.source() is None
    ctx.settings.update({"demo_sans_lunettes": True})
    assert presence.source() == "demo"
    ctx.settings.update({"demo_sans_lunettes": False, "require_glasses": False})
    assert presence.source() == "desactive"


def test_lattestation_du_telephone_expire_et_verifie_les_lunettes(app, monkeypatch):
    ctx = _sans_lunettes(app, monkeypatch)
    horloge = _Horloge()
    presence = PresenceLunettes(ctx.settings, ctx.settings.data_dir, voice=ctx.voice, horloge=horloge)
    presence.attester("M01 Pro_F444", "ABC")
    assert presence.presentes()
    horloge.t += DUREE_ATTESTATION_S + 1
    assert not presence.presentes(), "une attestation ancienne ne prouve plus rien"
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as autre:
        presence.attester("Écouteurs de quelqu'un d'autre", "XYZ")
    assert autre.value.status_code == 403


def test_routes_presence_et_attestation(client, app, monkeypatch):
    _sans_lunettes(app, monkeypatch)
    assert client.get("/api/lunettes/presence").json()["presentes"] is False
    r = client.post("/api/lunettes/attestation", json={"nom": "M01 Pro_F444", "identifiant": "ios-1", "batterie": 55})
    assert r.status_code == 200 and r.json()["presentes"] is True and r.json()["source"] == "telephone"
    assert client.delete("/api/lunettes/attestation").json()["presentes"] is False


# --------------------------------------------------------------------------- aperçu du chat écrit
def test_laperçu_du_chat_ecrit_est_limite_puis_invite_aux_lunettes(app, monkeypatch):
    ctx = _sans_lunettes(app, monkeypatch)
    chat = ctx.chat
    for _ in range(APERCU_MESSAGES):
        assert chat._verrou_lunettes_chat("text") is None
    refus = chat._verrou_lunettes_chat("text")
    assert refus and "lunettes" in refus.lower() and "démonstration" not in refus.lower()
    assert ctx.presence_lunettes.apercu_restant() == 0


def test_la_voix_et_le_telephone_distant_nont_pas_de_passe_droit(app, monkeypatch):
    ctx = _sans_lunettes(app, monkeypatch)
    assert ctx.chat._verrou_lunettes_chat("voice"), "la voix passe par les lunettes"
    assert "lunettes" in ctx.voice.lunettes_requises().lower()
    for fond in ("task", "daily_summary", "veille", "resume"):
        assert ctx.chat._verrou_lunettes_chat(fond) is None, fond
    ctx.presence_lunettes.attester("M01 Pro_F444")
    assert ctx.chat._verrou_lunettes_chat("voice") is None and ctx.voice.lunettes_requises() is None


def test_laperçu_survit_au_redemarrage(app, monkeypatch):
    ctx = _sans_lunettes(app, monkeypatch)
    ctx.presence_lunettes.consommer_apercu()
    ctx.presence_lunettes.consommer_apercu()
    neuve = PresenceLunettes(ctx.settings, ctx.settings.data_dir, voice=ctx.voice)
    assert neuve.apercu_restant() == APERCU_MESSAGES - 2


# --------------------------------------------------------------------------- réglages protégés et démo cachée
def test_les_reglages_qui_ouvriraient_iris_sans_lunettes_sont_proteges(client):
    for cle, valeur in (("require_glasses", False), ("demo_sans_lunettes", True)):
        r = client.patch("/api/settings", json={cle: valeur})
        assert r.status_code == 403, cle
    corps = client.get("/api/settings").json()
    assert corps["require_glasses"] is True and corps["demo_sans_lunettes"] is False


def test_le_mode_demo_exige_le_mot_de_passe_du_proprietaire(client, app, monkeypatch):
    _sans_lunettes(app, monkeypatch)
    assert client.post("/api/demo/activer", json={"mot_de_passe": "x"}).status_code == 409, "pas de compte : pas de démo"
    client.post("/api/compte", json={"nouveau": "motdepasse-2026", "nom": "Miguel"})
    assert client.post("/api/demo/activer", json={"mot_de_passe": "mauvais"}).status_code == 403
    r = client.post("/api/demo/activer", json={"mot_de_passe": "motdepasse-2026"})
    assert r.status_code == 200 and r.json()["presentes"] is True
    assert client.post("/api/demo/desactiver").json()["presentes"] is False
