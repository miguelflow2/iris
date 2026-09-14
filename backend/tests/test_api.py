"""Tests de l'API locale et du flux de conversation avec un connecteur simulé."""
import json

import pytest

import iris.chat as chat_module
from iris.connectors.base import BaseConnector, Chunk, ToolSpec


class FakeConnector(BaseConnector):
    name = "claude"
    supports_tools = True
    calls: list[dict] = []

    def __init__(self, api_key=None, model="fake-model", base_url=None):
        super().__init__(api_key, model, base_url)

    async def stream(self, messages, system, tools=None, run_tool=None, options=None):
        FakeConnector.calls.append({"messages": messages, "system": system, "tools": [t.name for t in (tools or [])]})
        last = messages[-1]["content"]
        text = last if isinstance(last, str) else " ".join(b.get("text", "") for b in last if b.get("type") == "text")
        if "souviens" in text and run_tool:
            yield Chunk("tool_use", data={"id": "t1", "name": "remember", "input": {"text": "fait mémorisé"}})
            result = await run_tool("remember", {"text": "fait mémorisé"})
            yield Chunk("tool_result", data={"id": "t1", "name": "remember", "result": str(result), "is_error": False})
        if "commande" in text and run_tool:
            yield Chunk("tool_use", data={"id": "t2", "name": "run_command", "input": {"command": "echo hi", "reason": "test"}})
            result = await run_tool("run_command", {"command": "echo hi", "reason": "test"})
            yield Chunk("tool_result", data={"id": "t2", "name": "run_command", "result": str(result), "is_error": isinstance(result, dict)})
        yield Chunk("thinking", text="je réfléchis")
        yield Chunk("text", text="Bonjour ")
        yield Chunk("text", text="Miguel !")
        yield Chunk("usage", data={"input_tokens": 10, "output_tokens": 3})
        yield Chunk("done")

    async def test(self):
        return {"ok": True, "message": "ok", "model": self.model, "latency_ms": 1}


@pytest.fixture()
def fake_claude(monkeypatch):
    FakeConnector.calls = []
    monkeypatch.setattr(chat_module, "build_connector", lambda name, settings, secrets: FakeConnector())
    return FakeConnector


def test_health_and_auth(client, app):
    assert client.get("/api/health").json()["ok"] is True
    from fastapi.testclient import TestClient

    with TestClient(app) as anon:
        assert anon.get("/api/status").status_code == 401
        assert anon.get("/api/status?token=test-token").status_code == 200


def test_agents_and_keys(client):
    agents = client.get("/api/agents").json()["agents"]
    assert [a["name"] for a in agents] == ["vela", "openrouter", "claude", "gpt", "gemini", "custom"]
    vela = agents[0]
    assert vela["needs_key"] is False, "l'accès VELA est fourni : le client ne colle aucune clé"
    view = client.put("/api/agents/claude", json={"active": True, "api_key": "sk-ant-abcdefgh12345678"}).json()
    assert view["has_key"] and view["key_masked"].startswith("sk-a") and "abcdefgh" not in view["key_masked"]
    assert view["ready"] is True
    assert "abcdefgh12345678" not in json.dumps(client.get("/api/agents").json())
    view = client.delete("/api/agents/claude/key").json()
    assert view["has_key"] is False and view["ready"] is False


def _setup_ready(client):
    client.put("/api/agents/claude", json={"active": True, "api_key": "sk-ant-test"})
    client.put("/api/consent/transcript", json={"granted": True})


def test_consent_required_before_send(client, fake_claude):
    client.put("/api/agents/claude", json={"active": True, "api_key": "sk-ant-test"})
    conv = client.post("/api/conversations", json={}).json()
    with client.websocket_connect("/ws?token=test-token") as ws:
        assert ws.receive_json()["type"] == "hello"
        ws.send_json({"type": "chat.send", "conversation_id": conv["id"], "text": "salut"})
        events = [ws.receive_json()["type"] for _ in range(2)]
    assert "chat.consent_required" in events
    assert fake_claude.calls == [], "rien ne doit partir sans consentement"
    msgs = client.get(f"/api/conversations/{conv['id']}").json()["messages"]
    assert [m["role"] for m in msgs] == ["user"]


def test_chat_flow_streams_and_persists(client, fake_claude):
    _setup_ready(client)
    conv = client.post("/api/conversations", json={"title": None}).json()
    with client.websocket_connect("/ws?token=test-token") as ws:
        ws.receive_json()
        ws.send_json({"type": "chat.send", "conversation_id": conv["id"], "text": "bonjour, souviens-toi de ça"})
        seen = {}
        done = None
        for _ in range(40):
            ev = ws.receive_json()
            seen.setdefault(ev["type"], []).append(ev)
            if ev["type"] == "chat.done":
                done = ev
                break
    assert done is not None
    assert "chat.started" in seen and "chat.delta" in seen and "chat.thinking" in seen and "chat.tool" in seen
    assert done["message"]["text"] == "Bonjour Miguel !"
    assert done["message"]["meta"]["usage"]["output_tokens"] == 3
    assert done["message"]["meta"]["tools"][0]["status"] == "done"
    detail = client.get(f"/api/conversations/{conv['id']}").json()
    assert [m["role"] for m in detail["messages"]] == ["user", "assistant"]
    # le titre est nettoyé (majuscule initiale, ponctuation de fin retirée) : chat.clean_title
    assert detail["title"] == "Bonjour, souviens-toi de ça"
    assert client.get("/api/memory").json()["count"] == 1
    assert fake_claude.calls[0]["tools"] and "remember" in fake_claude.calls[0]["tools"]
    assert "IRIS" in fake_claude.calls[0]["system"]
    events = client.get("/api/privacy/events").json()["events"]
    assert any(e["event_type"] == "external_send" and e["data_type"] == "transcript" for e in events)


def test_command_requires_confirmation(client, fake_claude):
    _setup_ready(client)
    client.patch("/api/settings", json={"confirm_commands": "always"})
    conv = client.post("/api/conversations", json={}).json()
    with client.websocket_connect("/ws?token=test-token") as ws:
        ws.receive_json()
        ws.send_json({"type": "chat.send", "conversation_id": conv["id"], "text": "lance une commande"})
        confirm = None
        for _ in range(10):
            ev = ws.receive_json()
            if ev["type"] == "chat.confirm":
                confirm = ev
                break
        assert confirm and "echo hi" in confirm["detail"]
        ws.send_json({"type": "chat.confirm_reply", "confirm_id": confirm["confirm_id"], "approved": False})
        for _ in range(20):
            ev = ws.receive_json()
            if ev["type"] == "chat.done":
                break
    events = client.get("/api/privacy/events").json()["events"]
    assert not any(e["event_type"] == "command_executed" for e in events)


def test_local_only_blocks_external(client, fake_claude):
    _setup_ready(client)
    client.patch("/api/settings", json={"local_only": True})
    conv = client.post("/api/conversations", json={}).json()
    with client.websocket_connect("/ws?token=test-token") as ws:
        ws.receive_json()
        ws.send_json({"type": "chat.send", "conversation_id": conv["id"], "text": "bonjour"})
        types = [ws.receive_json()["type"] for _ in range(2)]
    assert "chat.error" in types
    assert fake_claude.calls == []


def test_memory_and_tasks_endpoints(client, fake_claude):
    _setup_ready(client)
    item = client.post("/api/memory", json={"text": "Les lunettes ont une caméra 13 mégapixels"}).json()
    assert client.get("/api/memory", params={"q": "caméra des lunettes"}).json()["items"][0]["id"] == item["id"]
    export = client.get("/api/memory/export")
    assert export.status_code == 200 and "mégapixels" in export.text
    task = client.post("/api/tasks", json={"title": "Rapport", "instructions": "Écris un rapport"}).json()
    assert task["status"] in ("pending", "running", "done")
    import time

    for _ in range(50):
        got = client.get(f"/api/tasks/{task['id']}").json()
        if got["status"] == "done":
            break
        time.sleep(0.05)
    assert got["status"] == "done" and got["result"] == "Bonjour Miguel !"
    assert client.delete(f"/api/tasks/{task['id']}").json()["deleted"] is True


def test_glasses_status_and_prefs(client):
    status = client.get("/api/glasses/status").json()
    assert status["connected"] is False and status["remembered"]["address"] == ""
    assert client.get("/api/status").json()["glasses"]["connected"] is False
    res = client.patch("/api/glasses/prefs", json={"audio_input_device": "Crusher"}).json()
    assert res["connected"] is False
    assert client.get("/api/settings").json()["audio_input_device"] == "Crusher"
    assert client.post("/api/glasses/connect", json={"address": "00:00:00:00:00:00", "name": "fantôme", "attempts": 1}).status_code == 400


def test_voice_status_without_mic(client):
    status = client.get("/api/voice/status").json()
    assert status["state"] == "off" and status["wake_word"] == "Dis-moi Iris"
    started = client.post("/api/voice/start").json()
    # sans modèle Vosk ni consentement audio cloud : refus explicite et explicable
    assert started["running"] is False and started["error"]


class ChattyConnector(FakeConnector):
    """Simule un modèle gratuit qui prétend agir sans appeler d'outil."""

    async def stream(self, messages, system, tools=None, run_tool=None, options=None):
        ChattyConnector.calls.append({"messages": messages, "system": system, "force": getattr(options, "force_tools", None)})
        yield Chunk("text", text="C'est fait, Google est ouvert.")
        yield Chunk("done")


def test_action_guard_never_reports_fake_success(client, monkeypatch):
    ChattyConnector.calls = []
    monkeypatch.setattr(chat_module, "build_connector", lambda name, settings, secrets: ChattyConnector())
    _setup_ready(client)
    # « ouvre google » est désormais exécuté localement, sans modèle : on désactive les commandes locales
    # pour tester ce qui est visé ici, la garde d'action face à un modèle qui prétend avoir agi.
    client.patch("/api/settings", json={"quick_commands": False})
    conv = client.post("/api/conversations", json={}).json()
    with client.websocket_connect("/ws?token=test-token") as ws:
        ws.receive_json()
        ws.send_json({"type": "chat.send", "conversation_id": conv["id"], "text": "ouvre google"})
        deltas, done = [], None
        for _ in range(40):
            ev = ws.receive_json()
            if ev["type"] == "chat.delta":
                deltas.append(ev["text"])
            if ev["type"] == "chat.done":
                done = ev
                break
    assert done is not None
    assert "C'est fait" not in "".join(deltas), "le faux succès ne doit jamais être diffusé"
    assert "pas réussi" in done["message"]["text"]
    assert len(ChattyConnector.calls) == 2 and ChattyConnector.calls[0]["force"] is True
    assert len(ChattyConnector.calls[1]["messages"]) == 1, "seconde tentative sans historique"


def test_build_request_forces_tools(client, monkeypatch):
    """« crée un jeu » doit passer par la garde : forçage d'outil, puis message honnête si rien n'est créé."""
    ChattyConnector.calls = []
    monkeypatch.setattr(chat_module, "build_connector", lambda name, settings, secrets: ChattyConnector())
    _setup_ready(client)
    conv = client.post("/api/conversations", json={}).json()
    with client.websocket_connect("/ws?token=test-token") as ws:
        ws.receive_json()
        ws.send_json({"type": "chat.send", "conversation_id": conv["id"], "text": "crée un jeu simple de morpion"})
        done = None
        for _ in range(40):
            ev = ws.receive_json()
            if ev["type"] == "chat.done":
                done = ev
                break
    assert done and "pas réussi" in done["message"]["text"]
    assert ChattyConnector.calls[0]["force"] is True
    assert "DEMANDE DE CRÉATION" in ChattyConnector.calls[0]["system"]


def test_privacy_mode_blocks_listening(client):
    client.patch("/api/settings", json={"privacy_mode": True})
    st = client.post("/api/voice/start").json()
    assert st["running"] is False and "confidentiel" in (st["error"] or "")
    events = client.get("/api/privacy/events").json()["events"]
    assert any(e["event_type"] == "privacy_mode_enabled" for e in events)
    with client.websocket_connect("/ws?token=test-token") as ws:
        ws.receive_json()
        ws.send_json({"type": "privacy.toggle", "enabled": False})
        seen = [ws.receive_json()["type"] for _ in range(3)]
    assert "privacy.mode" in seen or "settings.updated" in seen
    assert client.get("/api/settings").json()["privacy_mode"] is False


def test_routine_short_circuit_and_summary(client, fake_claude):
    """Une phrase déclencheur exécute la routine sans modèle ; le résumé de journée passe par le modèle."""
    _setup_ready(client)
    routine = client.post("/api/routines", json={"name": "Test", "trigger": "mode test", "steps": [{"tool": "open_path", "args": {"path": "~"}}]}).json()
    assert routine["steps"][0]["tool"] == "open_path"
    conv = client.post("/api/conversations", json={}).json()
    with client.websocket_connect("/ws?token=test-token") as ws:
        ws.receive_json()
        ws.send_json({"type": "chat.send", "conversation_id": conv["id"], "text": "dis-moi iris mode test"})
        seen = []
        done = None
        for _ in range(20):
            ev = ws.receive_json()
            seen.append(ev["type"])
            if ev["type"] == "chat.done":
                done = ev
                break
    assert done and done["message"]["meta"].get("routine") == "Test"
    assert fake_claude.calls == [], "la routine ne doit pas appeler le modèle"
    assert "chat.tool" in seen
    summary = client.post("/api/memory/summarize-day", json={}).json()
    assert summary["stored"] is True and "Bonjour Miguel" in summary["summary"]
    assert any(m["kind"] == "daily_summary" for m in client.get("/api/memory").json()["items"])
    check = client.get("/api/privacy/verify").json()
    assert check["ok"] is True
    assert client.get("/api/privacy/export?format=csv").status_code == 200
    reminder = client.post("/api/reminders", json={"text": "test", "minutes": 30}).json()
    assert client.get("/api/reminders").json()["reminders"][0]["id"] == reminder["id"]
    assert client.delete(f"/api/reminders/{reminder['id']}").json()["deleted"] is True


def test_mute_endpoints(client):
    st = client.post("/api/voice/mute").json()
    assert st["muted"] is True and st["running"] is False
    started = client.post("/api/voice/start").json()
    assert started["running"] is False and "muet" in (started["error"] or "").lower()
    st = client.post("/api/voice/unmute").json()
    assert st["muted"] is False
    kinds = [e["event_type"] for e in client.get("/api/privacy/events").json()["events"]]
    assert "mic_muted" in kinds and "mic_unmuted" in kinds


def test_sites_api(client):
    v = client.put("/api/sites/omnivox", json={"url": "https://cegeptr.omnivox.ca/Login/Account/Login", "username": "2650016", "password": "pw"}).json()
    assert v["has_password"] is True and v["profile"] == "omnivox"
    assert "pw" not in json.dumps(client.get("/api/sites").json())
    v = client.put("/api/sites/omnivox", json={"url": "https://cegeptr.omnivox.ca/Login/Account/Login", "username": "2650016"}).json()
    assert v["has_password"] is True, "mot de passe conservé si non renvoyé"
    assert client.delete("/api/sites/omnivox").json()["deleted"] is True
    assert client.get("/api/sites").json()["sites"] == []


def test_plan_api_and_quota_error(client, fake_claude):
    from iris.plans import make_key

    info = client.get("/api/plan").json()
    assert info["plan"] == "gratuit" and len(info["plans"]) == 4 and info["lunettes"]["price"] == 250.0
    assert client.post("/api/plan/activate", json={"key": "IRIS-x-y"}).status_code == 400
    info = client.post("/api/plan/activate", json={"key": make_key("pro", "2099-01-01")}).json()
    assert info["plan"] == "pro" and info["quota_requests"] == 600
    assert client.get("/api/status").json()["plan"]["label"] == "Pro"
    assert client.post("/api/plan/demo", json={"plan": "gratuit"}).json()["plan"] == "gratuit"
    # quota atteint → erreur explicite, aucune requête envoyée
    _setup_ready(client)
    app_ctx = client.app.state.ctx
    app_ctx.plans._bump(requests=10_000)
    conv = client.post("/api/conversations", json={}).json()
    with client.websocket_connect("/ws?token=test-token") as ws:
        ws.receive_json()
        ws.send_json({"type": "chat.send", "conversation_id": conv["id"], "text": "bonjour"})
        kinds = []
        for _ in range(3):
            ev = ws.receive_json()
            kinds.append((ev["type"], ev.get("code")))
            if ev["type"] == "chat.error":
                break
    assert ("chat.error", "quota") in kinds and fake_claude.calls == []


# --------------------------------------------------------------- le verrou des lunettes (chat écrit)
# Décision de Miguel du 7 septembre 2026 : sans lunettes VELA, IRIS se tait — voix ET chat écrit —,
# avec une seule échappatoire, le mode démonstration. Le chat est verrouillé à un point d'étranglement
# unique dans ChatService._run.
def _lunettes_configurees_absentes(app, monkeypatch, demo: bool = False):
    app.state.ctx.settings.update({
        "require_glasses": True, "demo_sans_lunettes": demo,
        "glasses": {"name": "M01 Pro_F444", "address": "65:A2:9F:5C:F4:44", "auto_connect": False},
    })
    # Présence déterministe : les lunettes sont connues de l'appareil mais hors de portée.
    monkeypatch.setattr(app.state.ctx.voice, "lunettes_presentes", lambda: False)


def test_le_chat_ecrit_exige_les_lunettes_une_fois_laperçu_epuise(client, app, fake_claude, monkeypatch):
    """Décision de Miguel du 2026-09-13 (« lunettes d'abord ») : sans lunettes, le chat écrit a droit
    à un aperçu limité ; une fois épuisé, la demande est refusée AVANT tout appel au modèle, et le
    refus invite aux lunettes SANS jamais mentionner le mode démonstration (accès propriétaire caché)."""
    from iris.lunettes_presence import APERCU_MESSAGES

    _setup_ready(client)
    _lunettes_configurees_absentes(app, monkeypatch)
    presence = app.state.ctx.presence_lunettes
    for _ in range(APERCU_MESSAGES):
        presence.consommer_apercu()
    conv = client.post("/api/conversations", json={}).json()
    with client.websocket_connect("/ws?token=test-token") as ws:
        ws.receive_json()
        ws.send_json({"type": "chat.send", "conversation_id": conv["id"], "text": "bonjour"})
        done = None
        for _ in range(10):
            ev = ws.receive_json()
            if ev["type"] == "chat.done":
                done = ev
                break
    assert done is not None
    assert done["message"]["meta"].get("glasses_required") is True
    texte = done["message"]["text"].lower()
    assert "lunettes" in texte and "démonstration" not in texte
    assert fake_claude.calls == [], "rien ne doit partir au modèle sans lunettes"


def test_le_mode_demonstration_rouvre_le_chat_ecrit(client, app, fake_claude, monkeypatch):
    """L'échappatoire de Miguel : le mode démonstration débloque le chat écrit sans lunettes."""
    _setup_ready(client)
    _lunettes_configurees_absentes(app, monkeypatch, demo=True)
    conv = client.post("/api/conversations", json={}).json()
    with client.websocket_connect("/ws?token=test-token") as ws:
        ws.receive_json()
        ws.send_json({"type": "chat.send", "conversation_id": conv["id"], "text": "bonjour"})
        done = None
        for _ in range(40):
            ev = ws.receive_json()
            if ev["type"] == "chat.done":
                done = ev
                break
    assert done is not None and done["message"]["text"] == "Bonjour Miguel !"
    assert fake_claude.calls, "le modèle doit répondre en mode démonstration"


def test_le_verrou_du_chat_ne_touche_que_les_sources_humaines(app, monkeypatch):
    """Règle du 2026-09-13 : voix, texte, commandes, routines ET téléphone distant exigent les
    lunettes (l'écrit a son aperçu, la voix n'en a pas) ; les sources de fond passent toujours ; plus
    de passe-droit pour un appareil qui n'a jamais connu de lunettes ; la démonstration débloque."""
    from iris.lunettes_presence import APERCU_MESSAGES

    chat = app.state.ctx.chat
    presence = app.state.ctx.presence_lunettes
    _lunettes_configurees_absentes(app, monkeypatch)
    for _ in range(APERCU_MESSAGES):
        presence.consommer_apercu()
    for humaine in ("voice", "text", "quick", "routine", "distant"):
        assert chat._verrou_lunettes_chat(humaine), humaine
    for fond in ("task", "daily_summary", "veille", "resume"):
        assert chat._verrou_lunettes_chat(fond) is None, fond
    # Lunettes présentes : plus de verrou, même pour une source humaine.
    monkeypatch.setattr(app.state.ctx.voice, "lunettes_presentes", lambda: True)
    assert chat._verrou_lunettes_chat("text") is None
    # Aucune paire jamais configurée : ce n'est plus un passe-droit.
    monkeypatch.setattr(app.state.ctx.voice, "lunettes_presentes", lambda: False)
    app.state.ctx.settings.update({"glasses": {"name": "", "address": ""}})
    assert chat._verrou_lunettes_chat("text"), "aperçu épuisé : verrouillé même sur un appareil neuf"
    # L'échappatoire démo (accès propriétaire) débloque tout.
    app.state.ctx.settings.update({"demo_sans_lunettes": True, "glasses": {"name": "M01 Pro_F444", "address": "x"}})
    assert chat._verrou_lunettes_chat("text") is None

