"""Tests des briques locales : chiffrement, réglages, consentement, mémoire, routeur, voix (sans micro)."""
from pathlib import Path

import pytest

from iris.config import Settings
from iris.consent import ConsentGate, ConsentRequired, LocalOnlyMode
from iris.db import Database
from iris.events import EventHub
from iris.memory import MemoryService
from iris.router import AgentRouter, NoAgentAvailable
from iris.security.crypto import Crypto, load_master_key
from iris.security.secrets import SecretStore
from iris.voice.listener import contains_wake
from iris.voice.tts import speakable


def test_crypto_roundtrip(data_dir: Path):
    key, source = load_master_key(data_dir, use_keyring=False)
    assert len(key) == 32 and source == "file"
    key2, _ = load_master_key(data_dir, use_keyring=False)
    assert key == key2, "la clé doit être stable entre deux démarrages"
    c = Crypto(key)
    blob = c.encrypt("données confidentielles — éàü")
    assert blob != b"donn"
    assert c.decrypt(blob) == "données confidentielles — éàü"
    with pytest.raises(Exception):
        Crypto(b"x" * 32).decrypt(blob)


def test_secret_store_file_backend(data_dir: Path):
    key, _ = load_master_key(data_dir, use_keyring=False)
    store = SecretStore(Crypto(key), data_dir, use_keyring=False)
    assert store.backend == "encrypted-file"
    store.set_api_key("claude", "sk-ant-secret-123456")
    assert store.get_api_key("claude") == "sk-ant-secret-123456"
    assert b"sk-ant" not in (data_dir / "secrets.enc").read_bytes()
    assert SecretStore.mask("sk-ant-secret-123456") == "sk-a…3456"
    store.delete_api_key("claude")
    assert store.get_api_key("claude") is None


def test_settings_persist_and_patch(data_dir: Path):
    s = Settings(data_dir)
    assert s.user.wake_word == "Dis-moi Iris"
    s.update({"wake_word": "Salut Vela", "agents": {"claude": {"active": True, "model": "claude-sonnet-5"}}, "bogus": 1})
    s2 = Settings(data_dir)
    assert s2.user.wake_word == "Salut Vela"
    assert s2.user.agents["claude"].active is True
    assert s2.user.agents["claude"].model == "claude-sonnet-5"
    assert s2.user.agents["gemini"].active is False


def test_consent_gate(data_dir: Path):
    s = Settings(data_dir)
    db = Database(data_dir / "t.db")
    gate = ConsentGate(db, s, EventHub())
    with pytest.raises(ConsentRequired):
        gate.check("transcript", agent="claude")
    gate.set("transcript", True)
    gate.check("transcript", agent="claude")
    # agent local : jamais bloqué par le consentement d'envoi externe
    gate.check("image", agent="custom")
    s.update({"local_only": True})
    with pytest.raises(LocalOnlyMode):
        gate.check("transcript", agent="claude")
    gate.check("transcript", agent="custom")
    kinds = [e["event_type"] for e in gate.events()]
    assert "consent_granted" in kinds
    db.close()


def test_memory_search_and_retention(data_dir: Path):
    s = Settings(data_dir)
    db = Database(data_dir / "m.db")
    key, _ = load_master_key(data_dir, use_keyring=False)
    mem = MemoryService(db, Crypto(key), s)
    mem.add("Le mot de passe du wifi du bureau est dans le tiroir")
    mem.add("Réunion fournisseur jeudi pour la RFQ des lunettes")
    mem.add("Miguel préfère les réponses courtes")
    hits = mem.search("quand est la réunion fournisseur ?")
    assert hits and "fournisseur" in hits[0]["text"]
    assert mem.search("zzzz") == []
    raw = db.one("SELECT content_enc FROM memories LIMIT 1")["content_enc"]
    assert b"fournisseur" not in bytes(raw) and b"wifi" not in bytes(raw)
    s.update({"retention_days": 1})
    item = mem.add("souvenir temporaire")
    assert item["retained_until"] is not None
    db.execute("UPDATE memories SET retained_until='2000-01-01T00:00:00+00:00' WHERE id=?", (item["id"],))
    purged = mem.purge_expired()
    assert purged["memories"] == 1
    assert mem.count() == 3
    db.close()


class FakeSecrets:
    def __init__(self, keys):
        self.keys = keys

    def has_api_key(self, name):
        return name in self.keys


def test_router_rules(data_dir: Path):
    s = Settings(data_dir)
    # Claude est le cerveau par défaut depuis le 6 septembre 2026 : le test reflète la vraie config.
    s.update({"default_agent": "claude",
              "agents": {"claude": {"active": True}, "gemini": {"active": True}, "gpt": {"active": True}}})
    router = AgentRouter(s)
    available = router.available(FakeSecrets({"claude", "gemini"}))
    assert available == ["claude", "gemini"], "openrouter actif mais sans clé : non disponible"
    with_or = router.available(FakeSecrets({"openrouter", "claude"}))
    # Depuis le 6 septembre 2026, Claude est le cerveau par défaut : il passe AVANT OpenRouter,
    # même quand les deux sont disponibles. OpenRouter reste le filet de repli.
    assert router.select("ouvre vs code", False, with_or)[0] == "claude"
    assert router.select("bonjour", False, with_or)[0] == "claude"
    assert router.select("ouvre vs code", False, available)[0] == "claude"
    assert router.select("corrige ce bug python", False, available)[0] == "claude"
    assert router.select("quelle est la météo aujourd'hui", False, available)[0] == "claude"
    assert router.select("raconte-moi une histoire", False, available)[0] == "claude"
    assert router.select("bonjour", False, available, requested="gemini") == ("gemini", "choisi manuellement")
    with pytest.raises(NoAgentAvailable):
        router.select("bonjour", False, [])
    s.update({"local_only": True, "agents": {"custom": {"active": True}}})
    available = router.available(FakeSecrets(set()))
    assert available == ["custom"]
    assert router.select("bonjour", False, available)[0] == "custom"
    s.update({"agents": {"custom": {"active": False}}})
    with pytest.raises(NoAgentAvailable):
        router.select("bonjour", False, router.available(FakeSecrets(set())))


def test_dangerous_command_detection():
    from iris.pc.actions import is_dangerous_command
    from iris.tools import needs_confirmation

    assert is_dangerous_command("Remove-Item -Recurse C:\\Users\\x") is True
    assert is_dangerous_command("shutdown /s /t 0") is True
    assert is_dangerous_command("git push --force") is True
    assert is_dangerous_command("npm install && npm run build") is False
    assert is_dangerous_command("Get-Process | Select -First 5") is False
    assert needs_confirmation("dangerous", "echo hi") is False
    assert needs_confirmation("dangerous", "rm -rf /tmp/x") is True
    assert needs_confirmation("always", "echo hi") is True
    assert needs_confirmation("never", "rm -rf /") is False


def test_sentence_speaker_streams_by_sentence():
    from iris.chat import SentenceSpeaker

    spoken = []
    sp = SentenceSpeaker(spoken.append)
    for piece in ["J'ouvre ", "le navigateur. Quelle ", "musique veux-tu ", "écouter ?"]:
        sp.feed(piece)
    assert spoken == ["J'ouvre le navigateur."]
    sp.flush()
    assert spoken == ["J'ouvre le navigateur.", "Quelle musique veux-tu écouter ?"]


def test_wake_word_matching():
    assert contains_wake("dis moi iris ouvre mon navigateur", "Dis-moi Iris") == (True, "ouvre mon navigateur")
    assert contains_wake("dis moi iris", "Dis-moi Iris") == (True, "")
    assert contains_wake("dis-moi iris quelle heure il est", "Dis-moi Iris")[0] is True
    assert contains_wake("hey iris ouvre chrome", "Hey Iris") == (True, "ouvre chrome")
    assert contains_wake("ok vela allume", "Dis-moi Iris", aliases=["ok vela"]) == (True, "allume")
    assert contains_wake("et iris", "Hey Iris")[0] is True
    assert contains_wake("salut vela quelle heure", "Salut Vela") == (True, "quelle heure")
    assert contains_wake("bonjour tout le monde", "Hey Iris")[0] is False
    assert contains_wake("", "Hey Iris")[0] is False


def test_speakable_strips_markdown():
    text = "Voici **le plan** :\n- étape 1\n- étape 2\n```py\nprint(1)\n```\nLien [doc](https://x.y)"
    out = speakable(text)
    assert "**" not in out and "```" not in out and "https" not in out
    assert "étape un" in out and "doc" in out


def test_env_file_loading_and_elevenlabs_fallback(data_dir: Path, monkeypatch):
    import os

    from iris.config import load_env_files, write_env_value
    from iris.voice.elevenlabs import ElevenLabsSpeaker
    from iris.voice.tts import TextToSpeech

    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
    monkeypatch.setattr("iris.config.env_file_candidates", lambda d: [d / ".env"])
    assert load_env_files(data_dir) == []
    path = write_env_value(data_dir, "ELEVENLABS_API_KEY", "sk_test_123")
    assert path.read_text(encoding="utf-8").strip().endswith("ELEVENLABS_API_KEY=sk_test_123")
    assert os.environ["ELEVENLABS_API_KEY"] == "sk_test_123"
    os.environ.pop("ELEVENLABS_API_KEY")
    assert load_env_files(data_dir) == ["ELEVENLABS_API_KEY"]
    s = Settings(data_dir)
    tts = TextToSpeech(s, EventHub(), enabled=False)
    assert tts.eleven.configured is True and tts.engine == "elevenlabs"
    s.update({"tts_engine": "windows"})
    assert tts.engine == "windows"
    write_env_value(data_dir, "ELEVENLABS_API_KEY", "")
    assert ElevenLabsSpeaker(s, EventHub()).configured is False


def test_elevenlabs_paid_voice_fallback_and_quota(data_dir: Path, monkeypatch):
    """Voix payante refusée (402) → bascule sur la voix gratuite ; quota → alerte publiée."""
    import os

    from iris.voice import elevenlabs as el

    monkeypatch.setenv("ELEVENLABS_API_KEY", "sk_test")
    s = Settings(data_dir)
    s.update({"elevenlabs_voice_id": "GoEy5CmodqJy0T9AxjLk"})
    hub = EventHub()
    events = []
    monkeypatch.setattr(hub, "publish", lambda type_, **data: events.append((type_, data)))
    sp = el.ElevenLabsSpeaker(s, hub)

    class FakeResp:
        status_code = 402
        text = '{"detail":{"code":"paid_plan_required"}}'

    played = []

    def fake_stream(text):
        if s.user.elevenlabs_voice_id != el.FREE_FALLBACK_VOICE_ID:
            err = RuntimeError("HTTP 402")
            err.response = FakeResp()
            raise err
        played.append(text)

    monkeypatch.setattr(sp, "_stream_and_play", fake_stream)
    sp._handle_failure(RuntimeError("x") if False else _raise_402(FakeResp), "Bonjour")
    assert s.user.elevenlabs_voice_id == el.FREE_FALLBACK_VOICE_ID and played == ["Bonjour"]
    assert any(t == "tts.fallback" for t, _ in events)
    monkeypatch.setattr(sp, "subscription", lambda: {"tier": "free", "used": 9600, "limit": 10000})
    sp.check_quota()
    quota_events = [d for t, d in events if t == "tts.quota"]
    assert quota_events and quota_events[0]["level"] == "warn" and "reste" in quota_events[0]["message"]
    monkeypatch.setattr(sp, "subscription", lambda: {"tier": "free", "used": 10000, "limit": 10000})
    sp.check_quota()
    assert [d for t, d in events if t == "tts.quota"][-1]["level"] == "error"


def _raise_402(resp_cls):
    err = RuntimeError("HTTP 402")
    err.response = resp_cls()
    return err


def test_glasses_paired_devices_parsing(monkeypatch):
    import subprocess

    from iris.glasses import GlassesService

    class P:
        stdout = (
            "GT TWS|OK|BTHENUM\\DEV_41422233B334\\8&1&0&BLUETOOTHDEVICE_41422233B334\n"
            "M01 Pro_F444|OK|BTHENUM\\DEV_65A29F5CF444\\8&1&0&BLUETOOTHDEVICE_65A29F5CF444\n"
            "M01 Pro_F444|OK|BTHLE\\DEV_65A29F5CF444\\8&36BC9B59&0&65A29F5CF444\n"
        )

    monkeypatch.setattr(subprocess, "run", lambda *a, **k: P())
    monkeypatch.setattr("iris.glasses.sys.platform", "win32")
    devices = GlassesService._paired_devices_sync()
    glasses = next(d for d in devices if d["address"] == "65:A2:9F:5C:F4:44")
    assert glasses["name"] == "M01 Pro_F444" and glasses["paired"] and glasses["le"] and glasses["likely_glasses"]
    assert len(devices) == 2


def test_stop_and_mute_words():
    from iris.voice.listener import contains_wake, matches_any

    stop = ["stop", "arrête", "tais-toi", "silence", "ça suffit"]
    assert matches_any("stop", stop) and matches_any("iris arrête", stop) and matches_any("tais toi", stop)
    assert matches_any("ça suffit maintenant", stop) and not matches_any("ouvre google", stop)
    mute = ["muet", "mode muet", "coupe le micro"]
    assert matches_any("mode muet", mute) and matches_any("coupe le micro s'il te plaît", mute) and not matches_any("mets de la musique", mute)
    aliases = ["dis moi iris", "dis iris", "iris"]
    assert contains_wake("dis iris ouvre google", "Dis-moi Iris", aliases=aliases) == (True, "ouvre google")
    assert contains_wake("iris quelle heure il est", "Dis-moi Iris", aliases=aliases) == (True, "quelle heure il est")


# --------------------------------------------------------------------------- préparatifs au démarrage
# Incident réel : au démarrage, IRIS téléchargeait le modèle vocal sans rien demander. Excellent
# pour un utilisateur, désastreux pour la suite de tests — un modèle de 41 Mo par client, et le
# disque plein. Ces préparatifs n'appartiennent qu'à une vraie session lancée par l'application.
def test_les_preparatifs_reseau_exigent_une_vraie_session(app, monkeypatch):
    from iris import main as m

    monkeypatch.delenv("IRIS_AUTO_SETUP", raising=False)
    assert m.session_reelle() is False

    appels: list[str] = []
    monkeypatch.setattr(m.stt, "download_model", lambda *a, **k: appels.append("modèle"))
    ctx = app.state.ctx
    ctx.assurer_modele_vocal()
    ctx.assurer_acces_vela()
    assert appels == [], "rien ne doit partir sur le réseau sans IRIS_AUTO_SETUP"


def test_lapplication_seule_pose_le_drapeau():
    """Le drapeau vient d'electron/main/backend.ts : nulle part ailleurs."""
    lanceur = Path(__file__).resolve().parents[2] / "electron" / "main" / "backend.ts"
    assert "IRIS_AUTO_SETUP: '1'" in lanceur.read_text(encoding="utf-8")


# --------------------------------------------------------------------------- renommage des forfaits
# Les paliers s'appelaient Gratuit / Essentiel / Pro / Ultra ; ils s'appellent maintenant
# Gratuit / Pro / Premium / Entreprise. « pro » existe des deux côtés sans désigner la même chose :
# sans numéro de version, chaque relecture des réglages rétrograderait l'abonné d'un cran.
def test_un_abonne_ne_perd_pas_ce_quil_a_paye(tmp_path):
    import json

    from iris.config import Settings

    (tmp_path / "settings.json").write_text(json.dumps({"plan": "pro", "plan_expires": "2099-01-01"}), encoding="utf-8")
    s = Settings(tmp_path)
    assert s.user.plan == "premium", "l'ancien Pro à 29,99 $ est devenu Premium"
    from iris.config import VERSION_REGLAGES

    # La version suit VERSION_REGLAGES : une migration ajoutée ne doit pas casser ce test (v3 a
    # purgé les alias morts du mot d'activation le 6 septembre 2026).
    assert s.user.settings_version == VERSION_REGLAGES

    # Deuxième lecture : le plan ne doit plus bouger, sinon Premium deviendrait Entreprise.
    assert Settings(tmp_path).user.plan == "premium"


def test_les_anciens_paliers_sont_tous_repris(tmp_path):
    import json

    from iris.config import Settings

    for ancien, attendu in (("essentiel", "pro"), ("pro", "premium"), ("ultra", "entreprise"), ("gratuit", "gratuit")):
        dossier = tmp_path / ancien
        dossier.mkdir()
        (dossier / "settings.json").write_text(json.dumps({"plan": ancien}), encoding="utf-8")
        assert Settings(dossier).user.plan == attendu, ancien
