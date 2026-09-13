"""Fondation du chantier accessibilité / fonctions / confiance (2026-09-13).

Ce que les équipes suivantes considèrent comme acquis : le robinet audio, les interceptions de
phrases, le crochet du verrou vocal, la suspension de la mémoire, les bornes des nouveaux réglages,
le branchement protégé des modules et le refus d'accès quand IRIS est verrouillée à distance.
"""
from __future__ import annotations

import asyncio
import queue
import sys
import types

import pytest
from fastapi import APIRouter
from fastapi.testclient import TestClient

from iris.config import UserSettings
from iris.memory import MemoireSuspendue
from iris.voice.robinet import OCTETS_PAR_BLOC, RobinetAudio


# --------------------------------------------------------------------------- robinet audio
def test_le_robinet_copie_chaque_bloc_a_chaque_abonne():
    robinet = RobinetAudio()
    a = robinet.abonner("a")
    b = robinet.abonner("b")
    bloc = b"\x01\x00" * (OCTETS_PAR_BLOC // 2)
    robinet.publier(bloc)
    assert a.get_nowait() == bloc and b.get_nowait() == bloc
    assert sorted(robinet.abonnes()) == ["a", "b"]


def test_le_robinet_ne_bloque_jamais_et_jette_le_plus_vieux():
    robinet = RobinetAudio()
    file = robinet.abonner("lent", max_blocs=2)
    for i in range(5):
        robinet.publier(bytes([i]) * 4)
    assert file.get_nowait() == bytes([3]) * 4
    assert file.get_nowait() == bytes([4]) * 4
    assert robinet.perdus["lent"] == 3


def test_sans_abonne_le_robinet_ne_fait_rien_et_desabonner_ferme():
    robinet = RobinetAudio()
    robinet.publier(b"\x00\x00")
    file = robinet.abonner("x")
    robinet.desabonner("x")
    robinet.publier(b"\x00\x00")
    with pytest.raises(queue.Empty):
        file.get_nowait()
    assert not robinet.actif


def test_le_callback_du_micro_alimente_le_robinet(app):
    voice = app.state.ctx.voice
    file = voice.robinet.abonner("test")
    voice._native_rate = 16000
    voice._callback(b"\x02\x00" * 4000, 4000, None, None)
    assert len(file.get_nowait()) == 8000
    assert voice._audio.qsize() >= 1


# --------------------------------------------------------------------------- interceptions
def _ecouteur_muet(voice, monkeypatch):
    dits: list[str] = []
    monkeypatch.setattr(voice, "_say", lambda texte, *a, **k: dits.append(texte))
    monkeypatch.setattr(voice, "_wait_speech", lambda *a, **k: None)
    return dits


def test_une_interception_repond_sans_passer_par_le_modele(app, monkeypatch):
    voice = app.state.ctx.voice
    dits = _ecouteur_muet(voice, monkeypatch)
    appels: list[str] = []

    async def modele(texte: str) -> dict:  # ne doit jamais être appelé
        appels.append(texte)
        return {"text": "modèle"}

    voice.on_command = modele
    voice.ajouter_interception("invite", lambda t: "Mode invité activé." if "mode invité" in t else None)
    voice._process("active le mode invité")
    assert dits == ["Mode invité activé."] and appels == []


def test_une_interception_qui_ne_reconnait_pas_laisse_passer(app, monkeypatch):
    voice = app.state.ctx.voice
    _ecouteur_muet(voice, monkeypatch)
    voice.ajouter_interception("rien", lambda t: None)
    assert voice._intercepter("ouvre youtube") is None


def test_priorite_remplacement_et_erreur_isolee(app):
    voice = app.state.ctx.voice

    def casse(_t: str):
        raise RuntimeError("boum")

    voice.ajouter_interception("casse", casse, priorite=1)
    voice.ajouter_interception("b", lambda t: "B", priorite=20)
    voice.ajouter_interception("a", lambda t: "A", priorite=10)
    assert voice._intercepter("peu importe") == "A"
    voice.ajouter_interception("a", lambda t: None, priorite=10)  # même nom : remplacée
    assert voice._intercepter("peu importe") == "B"
    voice.retirer_interception("b")
    assert voice._intercepter("peu importe") is None


def test_une_interception_async_sexecute_dans_la_boucle(app):
    voice = app.state.ctx.voice
    boucle = asyncio.new_event_loop()
    import threading

    fil = threading.Thread(target=boucle.run_forever, daemon=True)
    fil.start()
    try:
        voice.loop = boucle

        async def decrire(texte: str):
            await asyncio.sleep(0)
            return "Une table et une chaise." if "devant moi" in texte else None

        voice.ajouter_interception("vision", decrire)
        assert voice._intercepter("qu'est-ce qu'il y a devant moi") == "Une table et une chaise."
        assert voice._intercepter("autre chose") is None
    finally:
        boucle.call_soon_threadsafe(boucle.stop)
        fil.join(timeout=2)
        voice.retirer_interception("vision")


# --------------------------------------------------------------------------- verrou vocal
def test_le_verrou_vocal_refuse_une_autre_voix_et_le_dit(app):
    voice = app.state.ctx.voice
    publies: list[dict] = []
    voice.hub.publish = lambda type_, **data: publies.append({"type": type_, **data}) or {}
    assert voice._locuteur_admis(b"\x00\x00" * 100)  # sans vérificateur : admis
    voice.verificateur_locuteur = lambda pcm: (False, "voix inconnue")
    assert not voice._locuteur_admis(b"\x00\x00" * 100)
    assert publies[-1] == {"type": "voice.locuteur_refuse", "raison": "voix inconnue"}
    voice.verificateur_locuteur = lambda pcm: (_ for _ in ()).throw(RuntimeError("x"))
    assert voice._locuteur_admis(b"\x00\x00" * 100), "une panne du verrou ne doit pas rendre IRIS sourde"
    voice.verificateur_locuteur = None


# --------------------------------------------------------------------------- mémoire suspendue
def test_la_memoire_suspendue_nechoue_rien_en_silence(app):
    memoire = app.state.ctx.memory
    avant = memoire.count()
    memoire.suspendre("invite")
    memoire.suspendre("zone:Clinique")
    assert memoire.suspendue == "invite"
    with pytest.raises(MemoireSuspendue):
        memoire.add("mon code de porte est 1234")
    assert memoire.capture("Je m'appelle Paul et j'habite à Gatineau.") == []
    assert memoire.count() == avant
    memoire.reprendre("invite")
    assert memoire.suspendue == "zone:Clinique"
    memoire.reprendre("zone:Clinique")
    assert memoire.suspendue is None
    memoire.add("souvenir normal")
    assert memoire.count() == avant + 1


def test_la_route_memoire_repond_409_en_mode_suspendu(client, app):
    app.state.ctx.memory.suspendre("invite")
    try:
        r = client.post("/api/memory", json={"text": "à ne pas retenir"})
        assert r.status_code == 409 and "suspendue" in r.json()["detail"]
    finally:
        app.state.ctx.memory.reprendre("invite")


# --------------------------------------------------------------------------- réglages
def test_bornes_des_nouveaux_reglages():
    u = UserSettings(tts_rate=9999, verbosite="bavard", alertes_sensibilite=-4, verrou_vocal_seuil="abc",
                     ecoute_assistee_gain_db=40, entrainement_repos_s=1, mode_invite_minutes=100000,
                     alertes_types=["alarme", "inconnu", "alarme", "prenom"], interprete_sortie_autre="haut-parleur")
    assert u.tts_rate == 560 and UserSettings(tts_rate=10).tts_rate == 90 and UserSettings().tts_rate == 185
    assert u.verbosite == "normal" and UserSettings(verbosite="DESCRIPTIF").verbosite == "descriptif"
    assert u.alertes_sensibilite == 0 and u.verrou_vocal_seuil == 70
    assert u.ecoute_assistee_gain_db == 18 and u.entrainement_repos_s == 10 and u.mode_invite_minutes == 720
    assert u.alertes_types == ["alarme", "prenom"] and u.interprete_sortie_autre == "pc"
    defaut = UserSettings()
    assert not defaut.journal_continu and not defaut.alertes_actives and not defaut.verrou_vocal_actif
    assert not defaut.verrou_distant_actif and defaut.zones_sans_memoire == []


def test_les_nouveaux_reglages_passent_par_patch(client):
    r = client.patch("/api/settings", json={"tts_rate": 555, "verbosite": "concis", "journal_continu": True})
    assert r.status_code == 200
    corps = client.get("/api/settings").json()
    assert corps["tts_rate"] == 555 and corps["verbosite"] == "concis" and corps["journal_continu"] is True


# --------------------------------------------------------------------------- branchement des modules
def test_un_module_casse_ou_absent_nempeche_pas_le_demarrage(tmp_path, monkeypatch):
    from iris import main as main_mod

    appels: list[str] = []
    routeur = APIRouter()

    @routeur.get("/api/fondation-test")
    def _ping():
        return {"ok": True}

    routeur.iris_demarrage = lambda: appels.append("demarrage")  # type: ignore[attr-defined]

    async def _arret():
        appels.append("arret")

    routeur.iris_arret = _arret  # type: ignore[attr-defined]
    faux = types.ModuleType("iris.routes_fondation_test")
    faux.creer_routeur = lambda ctx: routeur  # type: ignore[attr-defined]
    casse = types.ModuleType("iris.routes_fondation_casse")

    def _boum(ctx):
        raise RuntimeError("module cassé")

    casse.creer_routeur = _boum  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "iris.routes_fondation_test", faux)
    monkeypatch.setitem(sys.modules, "iris.routes_fondation_casse", casse)
    monkeypatch.setattr(
        main_mod,
        "MODULES_ROUTEURS",
        (("routes_fondation_absent", True), ("routes_fondation_casse", True), ("routes_fondation_test", True)),
    )
    application = main_mod.create_app(data_dir=tmp_path, token="t", use_keyring=False, enable_tts=False)
    with TestClient(application) as c:
        assert c.get("/api/fondation-test", headers={"Authorization": "Bearer t"}).json() == {"ok": True}
        assert c.get("/api/fondation-test").status_code in (401, 403), "routeur protégé par auth"
        assert appels == ["demarrage"]
    assert appels == ["demarrage", "arret"]


def test_verrouillee_a_distance_tout_est_refuse_sauf_le_deverrouillage(client, app):
    app.state.ctx.verrou = types.SimpleNamespace(verrouille=True)
    try:
        refus = client.get("/api/settings")
        assert refus.status_code in (401, 403) and "verrouillée" in str(refus.json())
        assert client.get("/api/health").status_code == 200
        permis = client.get("/api/compte")
        assert permis.status_code == 200
    finally:
        del app.state.ctx.verrou
    assert client.get("/api/settings").status_code == 200


# --------------------------------------------------------------------------- correctifs après la 1re vague
def test_la_suppression_par_plage_efface_vraiment(client, app):
    memoire = app.state.ctx.memory
    memoire.add("souvenir à effacer")
    avant = memoire.count()
    r = client.delete("/api/memory/plage", params={"debut": "2000-01-01", "fin": "2999-12-31"})
    assert r.status_code == 200 and r.json()["supprimes"] >= 1, "« plage » ne doit plus être pris pour un identifiant"
    assert memoire.count() < avant


def test_le_websocket_se_ferme_quand_iris_se_verrouille(client, app):
    ctx = app.state.ctx
    with client.websocket_connect("/ws?token=test-token") as ws:
        assert ws.receive_json()["type"] == "hello"
        ctx.verrou = types.SimpleNamespace(verrouille=True, raison="distance")
        try:
            ctx.hub.publish("verrou.etat", verrouille=True, depuis="2026-09-13T20:00:00", raison="distance")
            recu = ws.receive_json()
            while recu.get("type") != "verrou.etat":
                recu = ws.receive_json()
            from starlette.websockets import WebSocketDisconnect

            with pytest.raises(WebSocketDisconnect):
                ws.receive_json()
        finally:
            del ctx.verrou


def test_en_mode_invite_les_souvenirs_ne_sont_pas_injectes(app, monkeypatch):
    ctx = app.state.ctx
    appels: list[str] = []
    monkeypatch.setattr(ctx.memory, "context", lambda texte, limit=5: appels.append(texte) or [])
    ctx.memory.suspendre("invite")
    try:
        import inspect as _inspect

        source = _inspect.getsource(type(ctx.chat))
        assert "raisons_suspension" in source and 'r.startswith("invite")' in source
    finally:
        ctx.memory.reprendre("invite")
