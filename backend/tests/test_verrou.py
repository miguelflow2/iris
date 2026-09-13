"""Verrouillage d'IRIS et effacement à distance (interface I, 2026-09-13).

Ce que ces tests protègent : un verrou refuse TOUTES les routes protégées (via ctx.verrou et
main.raison_de_refus) sauf celles qui servent à déverrouiller ; il survit à un redémarrage ; il coupe
l'écoute et les lunettes et les empêche de revenir ; seul le mot de passe du propriétaire déverrouille ;
le code de secours est haché, limité en tentatives, et exigé par la commande distante ; l'effacement
supprime tout ce qu'il annonce et laisse le compte ; la télécommande n'accepte que le verrou quand seul
le verrouillage à distance est activé. Fausses lunettes, faux micro, faux WebSocket : aucun réseau.
"""
from __future__ import annotations

import asyncio
import json
import uuid
from types import SimpleNamespace

import pytest
from starlette.websockets import WebSocketDisconnect

from iris.verrou import RefusVerrou, VerrouIRIS, code_conforme, hacher_code

MOT_DE_PASSE = "motdepasse-proprietaire"
CODE = "secours-2468"


class FausseEcoute:
    def __init__(self, running: bool = True):
        self.running = running
        self.arrets: list[bool] = []
        self.robinet = SimpleNamespace(abonnes=lambda: [])
        self.muted = False
        self.verificateur_locuteur = None

    def stop(self, by_user: bool = True):
        self.arrets.append(by_user)
        self.running = False

    def start(self):
        self.running = True


class FaussesLunettes:
    def __init__(self):
        self.connected = True
        self.deconnexions = 0
        self.oubliees = False

    async def disconnect(self):
        self.deconnexions += 1
        self.connected = False

    def forget(self):
        self.oubliees = True

    async def auto_connect_on_start(self):
        return None


@pytest.fixture(autouse=True)
def hachage_rapide(monkeypatch):
    """Mêmes algorithmes (PBKDF2, scrypt), coût réduit : les tests vérifient la logique, pas la lenteur."""
    monkeypatch.setattr("iris.comptes.ITERATIONS", 2_000)
    monkeypatch.setattr("iris.verrou.SCRYPT", {"n": 2 ** 10, "r": 8, "p": 1})


def _proprietaire(ctx) -> None:
    ctx.comptes.creer(MOT_DE_PASSE, "Miguel")


# --------------------------------------------------------------------------- verrouiller / déverrouiller
def test_sans_mot_de_passe_on_refuse_de_verrouiller(client):
    r = client.post("/api/confiance/verrouiller")
    assert r.status_code == 409 and "mot de passe" in r.json()["detail"]
    assert client.get("/api/settings").status_code == 200


def test_verrouillee_tout_est_refuse_sauf_le_deverrouillage(client, app):
    ctx = app.state.ctx
    _proprietaire(ctx)
    etat = client.post("/api/confiance/verrouiller").json()
    assert etat["verrouille"] is True and etat["raison"] == "local" and etat["depuis"]
    for methode, chemin in (("get", "/api/settings"), ("get", "/api/status"), ("get", "/api/memory"),
                            ("get", "/api/confiance/zones"), ("post", "/api/confiance/invite/activer")):
        refus = getattr(client, methode)(chemin)
        assert refus.status_code == 401 and "verrouillée" in refus.json()["detail"], chemin
    assert client.get("/api/health").status_code == 200
    assert client.get("/api/confiance/verrou/etat").json()["verrouille"] is True
    # le code de secours ne se change pas pendant le verrou, même si le chemin reste joignable
    assert client.post("/api/confiance/verrou/code", json={"code": CODE}).status_code == 423
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/ws?token=test-token") as ws:
            ws.receive_json()

    assert client.post("/api/confiance/deverrouiller", json={"mot_de_passe": "mauvais"}).status_code == 403
    ouvert = client.post("/api/confiance/deverrouiller", json={"mot_de_passe": MOT_DE_PASSE})
    assert ouvert.status_code == 200 and ouvert.json()["verrouille"] is False
    assert client.get("/api/settings").status_code == 200
    evenements = [e["event_type"] for e in ctx.consent.events(limit=20)]
    assert {"verrouillage", "deverrouillage_refuse", "deverrouillage"} <= set(evenements)


def test_trop_de_mots_de_passe_errones_ralentit(client, app):
    _proprietaire(app.state.ctx)
    client.post("/api/confiance/verrouiller")
    codes = [client.post("/api/confiance/deverrouiller", json={"mot_de_passe": "faux"}).status_code for _ in range(9)]
    assert codes[:8] == [403] * 8 and codes[8] == 429
    assert client.post("/api/confiance/deverrouiller", json={"mot_de_passe": MOT_DE_PASSE}).status_code == 429


def test_le_verrou_survit_au_redemarrage(app, data_dir):
    from fastapi.testclient import TestClient

    from iris.main import create_app

    ctx = app.state.ctx
    _proprietaire(ctx)
    asyncio.run(ctx.verrou.verrouiller("distance"))
    relance = create_app(data_dir=data_dir, token="t2", use_keyring=False, enable_tts=False)
    try:
        with TestClient(relance, headers={"Authorization": "Bearer t2"}) as c:
            assert relance.state.ctx.verrou.verrouille is True
            assert c.get("/api/settings").status_code == 401
            assert c.get("/api/confiance/verrou/etat").json()["raison"] == "distance"
    finally:
        relance.state.ctx.close()


def test_verrouiller_coupe_ecoute_lunettes_et_services_puis_les_empeche_de_revenir(app, monkeypatch):
    ctx = app.state.ctx
    _proprietaire(ctx)
    ecoute, lunettes = FausseEcoute(), FaussesLunettes()
    arrets: list[str] = []
    monkeypatch.setattr(ctx, "voice", ecoute)
    monkeypatch.setattr(ctx, "glasses", lunettes)
    monkeypatch.setattr(ctx, "sous_titres", SimpleNamespace(arreter_tout=lambda: arrets.append("sous-titres")), raising=False)
    monkeypatch.setattr(ctx, "alertes", SimpleNamespace(actif=True, arreter=lambda raison=None: arrets.append(f"alertes:{raison}")), raising=False)
    monkeypatch.setattr(ctx, "enregistreur", SimpleNamespace(actif=True, arreter=lambda: arrets.append("enregistrement")), raising=False)

    async def scenario():
        await ctx.verrou.verrouiller("local")
        assert ecoute.arrets == [True] and lunettes.deconnexions == 1
        assert arrets == ["sous-titres", "alertes:verrouillage", "enregistrement"]
        garde = asyncio.create_task(ctx.verrou.surveiller(intervalle=0.01))
        ecoute.running = True  # le chien de garde vocal relance l'écoute...
        lunettes.connected = True  # ... et les lunettes se reconnectent toutes seules
        await asyncio.sleep(0.2)
        garde.cancel()
        assert not ecoute.running and not lunettes.connected, "rien ne se rallume pendant le verrou"

    asyncio.run(scenario())


# --------------------------------------------------------------------------- code de secours
def test_code_de_secours_hache_limite_et_protege(app):
    ctx = app.state.ctx
    verrou = ctx.verrou
    with pytest.raises(RefusVerrou):
        verrou.definir_code("123")
    verrou.definir_code(CODE)
    brut = verrou.fichier.read_text(encoding="utf-8")
    assert CODE not in brut and json.loads(brut)["code"]["algo"] in ("scrypt", "pbkdf2")
    assert verrou.verifier_code(CODE) == "ok"
    assert [verrou.verifier_code("mauvais-code") for _ in range(5)] == ["refuse"] * 5
    assert verrou.verifier_code(CODE) == "trop_de_tentatives", "même le bon code attend la fin de la fenêtre"
    # remplacer un code existant exige le mot de passe dès qu'un compte existe
    _proprietaire(ctx)
    with pytest.raises(RefusVerrou) as refus:
        verrou.definir_code("nouveau-code-99")
    assert refus.value.code == 403
    assert verrou.definir_code("nouveau-code-99", MOT_DE_PASSE)["code_defini"] is True
    empreinte = hacher_code("abcdef")
    assert code_conforme(empreinte, "abcdef") and not code_conforme(empreinte, "abcdeg")


def test_commande_distante_exige_activation_code_et_mot_de_passe(app):
    ctx = app.state.ctx
    verrou = ctx.verrou

    def commande(action="verrouiller", code=CODE):
        return asyncio.run(verrou.commande_distante(action, code))

    assert commande()["etat"] == "desactive"
    ctx.settings.update({"verrou_distant_actif": True})
    assert commande()["etat"] == "sans_code"
    verrou.definir_code(CODE)
    assert commande(code="pas-le-bon")["etat"] == "code_refuse"
    assert commande(action="formater")["etat"] == "action_inconnue"
    assert commande()["etat"] == "sans_mot_de_passe" and not verrou.verrouille
    _proprietaire(ctx)
    resultat = commande()
    assert resultat == {"ok": True, "etat": "verrouille", "message": "L'ordinateur est verrouillé."}
    assert verrou.verrouille and verrou.raison == "distance"
    assert CODE not in json.dumps(ctx.consent.events(limit=50)), "le code n'est jamais journalisé"


# --------------------------------------------------------------------------- effacement
def _inserer(db, table: str, **valeurs) -> None:
    """Insère une ligne factice dans une table d'une autre équipe, sans connaître son schéma exact."""
    colonnes = db.query(f"PRAGMA table_info({table})")
    ligne: dict = {}
    for col in colonnes:
        nom, genre = col["name"], (col["type"] or "").upper()
        if nom in valeurs:
            ligne[nom] = valeurs[nom]
        elif col["pk"] and "INT" not in genre:
            ligne[nom] = uuid.uuid4().hex
        elif col["notnull"] and col["dflt_value"] is None:
            ligne[nom] = b"x" if "BLOB" in genre else (0 if ("INT" in genre or "REAL" in genre) else "x")
    db.execute(f"INSERT INTO {table}({', '.join(ligne)}) VALUES({', '.join('?' * len(ligne))})", list(ligne.values()))


def test_effacement_complet_garde_le_compte_et_le_jeton_dappareil(app, data_dir):
    ctx = app.state.ctx
    _proprietaire(ctx)
    session = ctx.comptes.ouvrir_session()
    ctx.settings.update({"verrou_distant_actif": True})
    ctx.verrou.definir_code(CODE)

    ctx.memory.add("mon code de porte est 1234")
    conv = ctx.chat.create_conversation(title="Privée")
    ctx.chat._add_message(conv["id"], "user", "message privé")
    tables = {r["name"] for r in ctx.db.query("SELECT name FROM sqlite_master WHERE type='table'")}
    for table in ("journal_ecoute", "cours", "recus", "rappels_contexte", "reminders", "tasks"):
        if table in tables:
            _inserer(ctx.db, table, id="ligne-" + table)
    if "cours_lignes" in tables:
        _inserer(ctx.db, "cours_lignes", cours_id="ligne-cours")
    (data_dir / "captures" / "audio").mkdir(parents=True, exist_ok=True)
    (data_dir / "captures" / "photo.jpg").write_bytes(b"\xff\xd8")
    (data_dir / "captures" / "audio" / "enregistrement-1.wav").write_bytes(b"RIFF")
    (data_dir / "recus").mkdir(exist_ok=True)
    (data_dir / "recus" / "recu.jpg").write_bytes(b"\xff\xd8")
    (data_dir / "telecommande-pairing").write_text("abcd1234", encoding="utf-8")
    ctx.verrou_vocal.definir_consentement(True)
    ctx.verrou_vocal.fichier.write_bytes(ctx.crypto.encrypt('{"echantillons": []}'))
    ctx.zones.creer("Clinique", 45.5, -73.6, 200)
    ctx.secrets.set_api_key("vela", "jeton-appareil")
    agent = next(a for a in ctx.settings.user.agents if a != "vela")
    ctx.secrets.set_api_key(agent, "cle-byok")
    ctx.secrets.set_site("courriel", "moi@exemple.ca", "mot-de-passe-courriel")
    ctx.settings.update({"glasses": {"address": "AA:BB", "name": "VELA K900", "auto_connect": True}})

    resultat = asyncio.run(ctx.verrou.commande_distante("effacer", CODE))
    assert resultat["ok"] is True and resultat["etat"] in ("efface", "efface_partiel")
    assert resultat["verrouille"] is True and ctx.verrou.verrouille

    for table in ("memories", "messages", "conversations", "journal_ecoute", "cours", "cours_lignes", "recus",
                  "rappels_contexte", "reminders", "tasks"):
        if table in tables:
            assert ctx.db.one(f"SELECT COUNT(*) AS n FROM {table}")["n"] == 0, table
    assert not any(p.is_file() for p in (data_dir / "captures").rglob("*"))
    assert not any((data_dir / "recus").iterdir())
    assert not ctx.verrou_vocal.fichier.exists() and ctx.verrou_vocal.consentement() is None
    assert ctx.settings.user.zones_sans_memoire == []
    assert not (data_dir / "telecommande-pairing").exists()
    assert ctx.comptes.session_valide(session) is False, "les téléphones doivent se reconnecter"
    assert ctx.secrets.get_api_key(agent) is None and ctx.secrets.get_site("courriel") is None
    assert ctx.secrets.get_api_key("vela") == "jeton-appareil", "l'ordinateur reste verrouillable à distance"
    assert ctx.settings.user.glasses.address == "" and ctx.settings.user.glasses.auto_connect is False
    # le compte et le mot de passe restent : on peut déverrouiller
    assert ctx.comptes.configure and ctx.verrou.deverrouiller(MOT_DE_PASSE)["verrouille"] is False
    assert ctx.verrou.code_defini, "le code de secours reste pour un prochain verrouillage"


# --------------------------------------------------------------------------- télécommande
class FauxChat:
    def set_sink_confirm_distant(self, cb):
        self.sink = cb


def _telecommande(telecommande: bool, distant: bool, verrou=None):
    from iris.telecommande import Telecommande

    reglages = SimpleNamespace(user=SimpleNamespace(relay_server="https://relais.exemple", local_only=False,
                                                    telecommande=telecommande, verrou_distant_actif=distant),
                               data_dir="/dossier/inexistant")
    tc = Telecommande(FauxChat(), reglages, obtenir_jeton=lambda: "jeton")
    tc.verrou = verrou
    envois: list[dict] = []

    async def enregistrer(message):
        envois.append(message)

    tc._envoyer = enregistrer
    return tc, envois


def test_telecommande_nouvre_le_canal_que_pour_ce_qui_est_active():
    assert _telecommande(False, False)[0].actif() is False
    assert _telecommande(False, True)[0].actif() is True, "le verrouillage à distance seul ouvre le canal"


def test_seul_le_verrou_passe_quand_la_telecommande_est_coupee():
    class FauxVerrou:
        verrouille = False

        async def commande_distante(self, action, code):
            return {"ok": code == CODE, "etat": "verrouille" if code == CODE else "code_refuse", "message": "m"}

    tc, envois = _telecommande(False, True, FauxVerrou())

    async def scenario():
        await tc._traiter({"type": "commande", "req_id": "c1", "texte": "ouvre le navigateur"})
        await tc._traiter({"type": "verrou", "req_id": "v1", "action": "verrouiller", "code": CODE})
        await asyncio.sleep(0.05)

    asyncio.run(scenario())
    commande = next(m for m in envois if m["req_id"] == "c1")
    assert commande["type"] == "resultat" and "désactivée" in commande["reponse"]
    verrou = next(m for m in envois if m["req_id"] == "v1")
    assert verrou == {"type": "resultat", "req_id": "v1", "verrou": True, "ok": True, "etat": "verrouille", "message": "m"}


def test_aucune_commande_distante_pendant_le_verrou():
    tc, envois = _telecommande(True, True, SimpleNamespace(verrouille=True))
    executees: list[str] = []

    async def executer(req_id, texte):
        executees.append(texte)

    tc._executer = executer

    async def scenario():
        await tc._traiter({"type": "commande", "req_id": "c2", "texte": "supprime mes fichiers"})
        await asyncio.sleep(0.05)

    asyncio.run(scenario())
    assert executees == [] and "verrouillée" in envois[0]["reponse"]


def test_verrou_distant_refuse_si_reglage_coupe():
    tc, envois = _telecommande(True, False, VerrouIRIS.__new__(VerrouIRIS))
    asyncio.run(tc._verrou_distant("v2", "verrouiller", CODE))
    assert envois[0]["etat"] == "desactive" and envois[0]["verrou"] is True
