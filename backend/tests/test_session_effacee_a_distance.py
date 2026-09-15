"""Session d'un téléphone révoquée par un effacement à distance (constat iOS du 2026-09-14).

Ce que ces tests protègent : un iPhone perdu est souvent en arrière-plan (WebSocket fermé) au moment de
l'effacement ; il ne reçoit pas verrou.etat. À sa réouverture, sa session est refusée. Avant ce correctif,
le refus était l'ordinaire « jeton de session invalide » : l'app demandait le mot de passe, sans écran de
verrouillage et sans retirer les cours gardés sur le téléphone. Le refus dit maintenant la cause
(detail {code: "efface_a_distance", message}) — mais SEULEMENT à une session réellement émise avant
l'effacement : un jeton inventé, ou une session révoquée par une simple déconnexion, reçoit le refus ordinaire.
"""
from __future__ import annotations

import asyncio

import pytest
from fastapi.testclient import TestClient

MOT_DE_PASSE = "motdepasse-proprietaire"


@pytest.fixture(autouse=True)
def hachage_rapide(monkeypatch):
    monkeypatch.setattr("iris.comptes.ITERATIONS", 2_000)


def _avec(jeton: str) -> dict:
    return {"Authorization": f"Bearer {jeton}"}


def test_session_effacee_a_distance_dit_la_cause(app):
    ctx = app.state.ctx
    ctx.comptes.creer(MOT_DE_PASSE, "Miguel")
    session = ctx.comptes.ouvrir_session()
    with TestClient(app) as c:
        assert c.get("/api/status", headers=_avec(session)).status_code == 200
        resultat = asyncio.run(ctx.verrou.effacer())
        assert resultat["verrouille"] is True

        for chemin in ("/api/status", "/api/confiance/verrou/etat"):
            r = c.get(chemin, headers=_avec(session))
            assert r.status_code == 401, chemin
            detail = r.json()["detail"]
            assert isinstance(detail, dict), f"{chemin} : la cause doit être lisible par l'app ({detail!r})"
            assert detail["code"] == "efface_a_distance"
            # Les clients qui ne lisent que la phrase (page /m) voient encore « verrouillée ».
            assert "verrouill" in detail["message"].lower()

        # Un jeton inventé n'apprend rien de l'état de l'ordinateur.
        assert c.get("/api/status", headers=_avec("abc.9999999999.faux")).json()["detail"] == "jeton de session invalide"

        # Déverrouillée par le propriétaire : l'ancienne session garde sa cause (le téléphone n'a peut-être
        # toujours pas rouvert l'app), et une nouvelle session marche normalement.
        assert ctx.verrou.deverrouiller(MOT_DE_PASSE)["verrouille"] is False
        assert c.get("/api/status", headers=_avec(session)).json()["detail"]["code"] == "efface_a_distance"
        assert c.get("/api/status", headers=_avec(ctx.comptes.ouvrir_session())).status_code == 200


def test_deconnexion_ordinaire_ne_pretend_pas_un_effacement(app):
    ctx = app.state.ctx
    ctx.comptes.creer(MOT_DE_PASSE, "Miguel")
    avant = ctx.comptes.ouvrir_session()
    ctx.comptes.revoquer_tout(motif="effacement")
    apres = ctx.comptes.ouvrir_session()
    ctx.comptes.revoquer_tout()  # « déconnecter tous les appareils » : aucun motif
    with TestClient(app) as c:
        assert c.get("/api/status", headers=_avec(apres)).json()["detail"] == "jeton de session invalide"
    # La déconnexion ordinaire qui SUIT l'effacement n'efface plus sa trace (constat finition B du 2026-09-14 :
    # avant, seule la dernière révocation était retenue et l'iPhone perdu gardait ses cours lisibles).
    assert ctx.comptes.motif_revocation(avant) == "effacement"
    assert ctx.comptes.motif_revocation("") is None
    assert ctx.comptes.motif_revocation("pas-un-jeton") is None


def test_websocket_refuse_avec_la_phrase_d_effacement(app):
    from starlette.websockets import WebSocketDisconnect

    ctx = app.state.ctx
    ctx.comptes.creer(MOT_DE_PASSE, "Miguel")
    session = ctx.comptes.ouvrir_session()
    asyncio.run(ctx.verrou.effacer())
    with TestClient(app) as c:
        with pytest.raises(WebSocketDisconnect) as refus:
            with c.websocket_connect("/ws", headers=_avec(session)):
                pass
    assert refus.value.code == 4401
    assert "effacée à distance" in (refus.value.reason or "")


def test_deconnecter_tous_les_appareils_apres_effacement_garde_la_cause(app):
    """Téléphone perdu : effacement, le propriétaire déverrouille puis clique « Déconnecter tous les appareils »
    (POST /api/compte/deconnexion) et change son mot de passe AVANT que le voleur rouvre l'app. L'ancienne session
    doit encore recevoir le code efface_a_distance, et la phrase ne doit plus dire « est verrouillée »."""
    ctx = app.state.ctx
    ctx.comptes.creer(MOT_DE_PASSE, "Miguel")
    session_iphone = ctx.comptes.ouvrir_session()
    maitre = {"Authorization": "Bearer test-token"}
    with TestClient(app) as c:
        asyncio.run(ctx.verrou.effacer())
        assert c.post("/api/confiance/deverrouiller", json={"mot_de_passe": MOT_DE_PASSE},
                      headers=maitre).status_code == 200
        assert c.post("/api/compte/deconnexion", headers=maitre).status_code == 200
        ctx.comptes.revoquer_tout()  # une seconde révocation ordinaire, pour faire bonne mesure
        ctx.comptes.changer(MOT_DE_PASSE, MOT_DE_PASSE + "-nouveau")
        r = c.get("/api/status", headers=_avec(session_iphone))
        assert r.status_code == 401
        detail = r.json()["detail"]
        assert isinstance(detail, dict), detail
        assert detail["code"] == "efface_a_distance"
        assert "effacée à distance" in detail["message"]
        assert "verrouill" not in detail["message"].lower(), "l'ordinateur est déverrouillé : ne pas dire « verrouillée »"
        # Une session émise APRÈS l'effacement puis révoquée par une simple déconnexion reste un refus ordinaire.
        apres = ctx.comptes.ouvrir_session()
        ctx.comptes.revoquer_tout()
        assert c.get("/api/status", headers=_avec(apres)).json()["detail"] == "jeton de session invalide"


def test_trace_d_effacement_expire_avec_les_sessions(app, monkeypatch):
    """La liste n'est pas éternelle : passé l'échéance maximale des sessions émises sous le secret révoqué,
    l'entrée est retirée."""
    import iris.comptes as comptes_mod

    ctx = app.state.ctx
    ctx.comptes.creer(MOT_DE_PASSE, "Miguel")
    session = ctx.comptes.ouvrir_session()
    ctx.comptes.revoquer_tout(motif="effacement")
    assert ctx.comptes.motif_revocation(session) == "effacement"
    reel = comptes_mod.time.time
    monkeypatch.setattr(comptes_mod.time, "time", lambda: reel() + comptes_mod.DUREE_SESSION + 60)
    assert ctx.comptes.motif_revocation(session) is None
    ctx.comptes.revoquer_tout()
    assert ctx.comptes._lire().get("revocations_motivees") == []
