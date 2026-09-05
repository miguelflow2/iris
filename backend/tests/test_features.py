"""Tests : index d'applications, routines, rappels, registre infalsifiable, niveaux de modèles, résumé de journée."""
from datetime import datetime
from pathlib import Path

import pytest

from iris.config import Settings
from iris.consent import ConsentGate
from iris.db import Database
from iris.events import EventHub


def test_app_index_search_and_kinds(monkeypatch):
    from iris.pc.apps import AppIndex

    idx = AppIndex()
    monkeypatch.setattr(idx, "_start_menu", lambda: [{"name": "Visual Studio Code", "kind": "shortcut", "path": "x.lnk"}, {"name": "Google Chrome", "kind": "shortcut", "path": "c.lnk"}])
    monkeypatch.setattr(idx, "_steam", lambda: [{"name": "Rocket League", "kind": "steam", "appid": "252950", "launch": "steam://rungameid/252950"}])
    monkeypatch.setattr(idx, "_start_apps", lambda: [{"name": "Spotify", "kind": "store", "appid": "SpotifyAB.SpotifyMusic_zpdnekdrzrea0!Spotify", "launch": "shell:AppsFolder\\x"}, {"name": "Google Chrome", "kind": "store", "appid": "Chrome", "launch": "shell:AppsFolder\\c"}])
    apps = idx.build()
    assert len(apps) == 4, "Chrome dédupliqué entre raccourci et Store"
    assert idx.best("spotify")["kind"] == "store"
    assert idx.best("rocket league")["launch"].startswith("steam://")
    assert idx.best("visual studio")["name"] == "Visual Studio Code"
    assert idx.best("rockt leage")["name"] == "Rocket League", "tolérance aux fautes"
    assert idx.search("zzzz") == []


@pytest.mark.asyncio
async def test_routines_match_run_and_record(data_dir: Path):
    from iris.routines import RoutineService

    db = Database(data_dir / "r.db")
    hub = EventHub()
    svc = RoutineService(db, hub)
    routine = svc.create("Mode travail", "mode travail", [{"tool": "open_application", "args": {"name": "VS Code"}}, {"tool": "search_memory", "args": {}}, {"tool": "open_url", "args": {"url": "https://github.com"}}])
    assert len(routine["steps"]) == 2, "search_memory n'est pas une étape rejouable"
    assert svc.match("dis moi iris mode travail")["id"] == routine["id"]
    assert svc.match("mode travaille")["id"] == routine["id"], "tolérance"
    assert svc.match("quelle heure il est") is None
    calls = []

    async def fake_run(tool, args):
        calls.append((tool, args))
        return "ok"

    results = await svc.run(routine, fake_run)
    assert [c[0] for c in calls] == ["open_application", "open_url"] and all(r["ok"] for r in results)
    assert svc.get(routine["id"])["runs"] == 1
    # enregistrement
    svc.start_recording("Soirée", "mode soirée")
    svc.record("play_youtube", {"query": "lofi"})
    svc.record("search_memory", {"query": "x"})
    rec = svc.stop_recording()
    assert rec and rec["steps"] == [{"tool": "play_youtube", "args": {"query": "lofi"}}]
    assert svc.find_by_name("soiree")["name"] == "Soirée"
    assert svc.delete(rec["id"]) and svc.find_by_name("soirée") is None
    db.close()


def test_reminders_parse_and_due(data_dir: Path):
    from iris.reminders import ReminderService, parse_due

    now = datetime(2026, 9, 2, 14, 0)
    assert parse_due(minutes=20, now=now) == datetime(2026, 9, 2, 14, 20)
    assert parse_due(at="15:30", now=now) == datetime(2026, 9, 2, 15, 30)
    assert parse_due(at="9h", now=now) == datetime(2026, 9, 3, 9, 0), "heure passée → demain"
    assert parse_due(at="demain 09:15", now=now) == datetime(2026, 9, 3, 9, 15)
    with pytest.raises(ValueError):
        parse_due()
    db = Database(data_dir / "rem.db")
    fired = []
    svc = ReminderService(db, EventHub(), announce=fired.append)
    item = svc.create("appeler Paul", minutes=0.0001)
    assert svc.list()[0]["id"] == item["id"]
    due = svc.due_now(datetime.now().replace(year=2100))
    assert due and due[0]["id"] == item["id"]
    svc.fire(due[0])
    assert fired == ["Rappel : appeler Paul"] and svc.list() == []
    db.close()


def test_transparency_register_hash_chain(data_dir: Path):
    s = Settings(data_dir)
    db = Database(data_dir / "c.db")
    gate = ConsentGate(db, s, EventHub())
    gate.log("external_send", data_type="transcript", agent="openrouter", detail="bonjour")
    gate.log("screen_captured", data_type="screen")
    gate.log("command_executed", agent="openrouter", detail="echo hi")
    check = gate.verify()
    assert check["ok"] is True and check["count"] == 3 and check["last_hash"]
    exported = gate.export("json")
    assert '"verification"' in exported and "echo hi" in exported
    assert gate.export("csv").splitlines()[0].startswith("id,created_at,event_type")
    # falsification a posteriori : détectée
    db.execute("UPDATE privacy_events SET detail='rien' WHERE event_type='command_executed'")
    tampered = gate.verify()
    assert tampered["ok"] is False and tampered["first_bad_id"] is not None
    db.close()


def test_pick_model_tiers(data_dir: Path):
    from iris.chat import ChatService

    s = Settings(data_dir)
    s.update({"voice_model": "fast/model", "reasoning_model": "big/model", "vision_model": "eyes/model"})
    u = s.user
    assert ChatService._pick_model(u, is_voice=True) == "fast/model"
    assert ChatService._pick_model(u, is_voice=True, is_build=True) == "big/model"
    assert ChatService._pick_model(u, is_screen=True, is_build=True) == "eyes/model"
    assert ChatService._pick_model(u) is None
    s.update({"vision_model": ""})
    assert ChatService._pick_model(s.user, is_screen=True) is None


def test_site_credentials_and_tools(data_dir: Path):
    from iris.security.crypto import Crypto, load_master_key
    from iris.security.secrets import SecretStore
    from iris.tools import TOOL_SPECS
    from iris.web import SITE_PROFILES, WebAgent

    key, _ = load_master_key(data_dir, use_keyring=False)
    store = SecretStore(Crypto(key), data_dir, use_keyring=False)
    store.set_site("omnivox", "2650016", "secret-pw")
    assert store.get_site("omnivox") == {"username": "2650016", "password": "secret-pw"}
    assert b"secret-pw" not in (data_dir / "secrets.enc").read_bytes()
    store.delete_site("omnivox")
    assert store.get_site("omnivox") is None
    names = {t.name for t in TOOL_SPECS}
    assert {"web_open", "web_login", "web_read", "web_click", "web_fill", "web_screenshot"} <= names
    s = Settings(data_dir)
    s.update({"sites": {"omnivox": {"url": "https://cegeptr.omnivox.ca/Login/Account/Login", "username": "2650016", "label": "Omnivox"}}})
    agent = WebAgent(s, EventHub(), store)
    assert agent.resolve_site("Omnivox")[0] == "omnivox" and agent.resolve_site("cegeptr")[0] == "omnivox"
    assert SITE_PROFILES["omnivox"]["logged_in"]("https://cegeptr.omnivox.ca/intr/") is True
    assert SITE_PROFILES["omnivox"]["logged_in"]("https://cegeptr.omnivox.ca/Login/Account/Login") is False
    with pytest.raises(RuntimeError):
        agent.login("omnivox")  # mot de passe absent → message clair, aucune navigation


def test_plans_quota_and_keys(monkeypatch, data_dir: Path):
    from iris.plans import PLANS, PlanService, QuotaExceeded, make_key, verify_key

    s = Settings(data_dir)
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)  # Settings recharge .env ; sans clé personnelle : les paliers s'appliquent
    db = Database(data_dir / "p.db")
    hub = EventHub()
    events = []
    hub.publish = lambda type_, **data: events.append((type_, data))  # type: ignore[method-assign]
    svc = PlanService(db, s, hub)
    assert svc.plan == "gratuit" and not svc.feature_allowed("elevenlabs") and svc.models()["reasoning"] == ""
    # quota gratuit
    for _ in range(PLANS["gratuit"]["quota_requests"]):
        svc.check_request()
    with pytest.raises(QuotaExceeded):
        svc.check_request()
    assert any(t == "plan.quota" for t, _ in events)
    # clé d'abonnement Premium valide, puis expirée
    key = make_key("premium", "2099-12-31", "miguel@vela.app")
    info = svc.activate(key)
    assert info["plan"] == "premium" and svc.feature_allowed("screen") and svc.feature_allowed("elevenlabs")
    assert svc.models()["reasoning"] == "anthropic/claude-sonnet-5"
    assert svc.usage()["requests_limit"] == 1000
    with pytest.raises(ValueError):
        svc.activate(make_key("entreprise", "2000-01-01"))
    with pytest.raises(ValueError):
        svc.activate("IRIS-bidon-signature")
    assert verify_key(key)["plan"] == "premium"
    # mode démo
    assert svc.set_demo("entreprise")["plan"] == "entreprise" and svc.models()["reasoning"] == "anthropic/claude-opus-5"
    s.update({"plan_expires": "2000-01-01", "plan": "premium", "plan_demo": False})
    assert svc.plan == "gratuit", "plan expiré → gratuit"
    db.close()


def test_calibration_annulable(app):
    """Une calibration lancée doit pouvoir être arrêtée : sinon un essai abandonné laisse IRIS
    en vocabulaire complet et fait enregistrer comme variante la première phrase entendue."""
    voice = app.state.ctx.voice
    voice.calibrate(3)
    assert voice.calibrating == 3
    voice.calibrate(0)
    assert voice.calibrating == 0
    # Une phrase entendue après l'annulation n'ajoute plus d'alias.
    avant = list(app.state.ctx.settings.user.wake_aliases or [])
    voice._learn_alias("bonjour tout le monde")
    assert list(app.state.ctx.settings.user.wake_aliases or []) == avant


def test_calibration_stoppee_par_arret_du_micro(app):
    voice = app.state.ctx.voice
    voice.calibrate(3)
    voice.stop(by_user=True)
    assert voice.calibrating == 0


# --------------------------------------------------------------------------- piloter une application
@pytest.mark.parametrize(
    "phrase",
    [
        "ouvre spotify et joue ma playlist",
        "ouvre mon application spotify et mets ma liste de musique aimee",
        "ouvre word et ecris une lettre",
        "trouve mes documents de cegep",
        "joue mes chansons aimees",
    ],
)
def test_iris_recoit_les_yeux_et_les_mains(phrase):
    """Sans outils d'écran, IRIS ouvrait l'application puis restait plantée devant, incapable
    de cliquer. Ces demandes doivent lui donner de quoi regarder et agir."""
    from iris.chat import besoin_de_piloter

    assert besoin_de_piloter(phrase), f"aucun outil d'écran pour : {phrase!r}"


@pytest.mark.parametrize(
    "phrase",
    ["ouvre spotify", "quelle heure est-il", "crée un jeu de morpion", "explique-moi git status"],
)
def test_lecran_reste_ferme_quand_il_ne_sert_a_rien(phrase):
    """Offrir l'écran à tout va, c'est ce qui provoquait les boucles de clics à l'aveugle."""
    from iris.chat import besoin_de_piloter

    assert not besoin_de_piloter(phrase), f"écran ouvert inutilement pour : {phrase!r}"


def test_la_consigne_de_pilotage_interdit_le_clic_a_laveugle():
    from iris.chat import CONSIGNE_PILOTAGE

    assert "take_screenshot" in CONSIGNE_PILOTAGE and "VÉRIFIER" in CONSIGNE_PILOTAGE
    assert "jamais au hasard" in CONSIGNE_PILOTAGE
    assert "recherche sur le web" in CONSIGNE_PILOTAGE, "sa bibliothèque n'est pas sur le web"
