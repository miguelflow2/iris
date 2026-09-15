"""Résumé vocal de fin de journée (interface G, chantier du 2026-09-13).

Journée synthétique écrite directement dans la base (tâches, routine, conversations, souvenirs,
journal, reçu, rappels) ; faux cours ; faux moteur (connecteur simulé) ; fausse voix. Aucun réseau,
aucun micro.

Ce qui est protégé ici :
- le résumé ne contient QUE des faits notés, rangés en « fait / reste / rappels / à retenir » ;
- le moteur ne reçoit rien sans « Texte de vos demandes », ni les souvenirs sans « Extraits de mémoire » ;
  sinon la version locale est rendue, et la réponse le dit ;
- la mémorisation reprend summarize_day (un souvenir par jour, remplacé), jamais quand la mémoire est
  suspendue ; rien n'est lu à voix haute en mode confidentiel ni en mode invité ;
- ctx.resume_quotidien est bien la fonction appelée par la boucle quotidienne de main.py.
"""
from __future__ import annotations

import asyncio
import inspect
import uuid
from datetime import date, datetime, timedelta, timezone

import pytest

import iris.chat as chat_module
import iris.quotidien as quotidien
from iris.connectors.base import BaseConnector, Chunk

# Lunettes d'abord (2026-09-13) : ces tests portent sur la fonction elle-même, lunettes présentes.
# La garde est vérifiée à part, avec et sans lunettes, dans test_garde_lunettes.py.
pytestmark = pytest.mark.usefixtures("lunettes_presentes")

NOMS_INTERDITS = ("claude", "anthropic", "openai", "gpt", "gemini", "google", "elevenlabs", "vosk", "piper",
                  "openrouter", "twilio")
TABLES = ("tasks", "messages", "conversations", "memories", "reminders", "rappels_contexte", "recus", "journal_ecoute")


@pytest.fixture(scope="module")
def _application(tmp_path_factory):
    from fastapi.testclient import TestClient

    from iris.main import create_app

    dossier = tmp_path_factory.mktemp("iris-quotidien")
    application = create_app(data_dir=dossier, token="test-token", use_keyring=False, enable_tts=False)
    with TestClient(application, headers={"Authorization": "Bearer test-token"}) as c:
        yield application, c
    application.state.ctx.close()


@pytest.fixture()
def app(_application):
    application, _c = _application
    yield application
    ctx = application.state.ctx
    ctx.settings.update({"local_only": False, "privacy_mode": False, "verbosite": "normal",
                         "agents": {"claude": {"active": False}}})
    ctx.secrets.delete_api_key("claude")
    for type_donnee in ("transcript", "audio_raw", "image", "screen", "memory"):
        ctx.consent.set(type_donnee, False)
    for raison in ctx.memory.raisons_suspension():
        ctx.memory.reprendre(raison)
    for table in TABLES:
        ctx.db.execute(f"DELETE FROM {table}")
    ctx.rappels_contexte._recharger()
    ctx.resume_quotidien.__self__._cache.clear()


@pytest.fixture()
def client(app, _application):
    return _application[1]


@pytest.fixture()
def service(app):
    return app.state.ctx.resume_quotidien.__self__


@pytest.fixture()
def paroles(app, monkeypatch):
    dites: list[tuple[str, bool]] = []

    def parler(texte, force=False):
        dites.append((texte, force))
        return True

    monkeypatch.setattr(app.state.ctx.tts, "speak", parler)
    return dites


class FauxMoteur(BaseConnector):
    name = "claude"
    supports_tools = True
    supports_images = True
    appels: list[dict] = []
    reponse = ""

    def __init__(self):
        super().__init__("cle", "faux-modele")

    async def stream(self, messages, system, tools=None, run_tool=None, options=None):
        FauxMoteur.appels.append({"messages": messages, "system": system, "tools": tools})
        yield Chunk("text", text=FauxMoteur.reponse)
        yield Chunk("done")

    async def test(self):  # pragma: no cover
        return {"ok": True}


@pytest.fixture()
def moteur(monkeypatch, client):
    FauxMoteur.appels = []
    FauxMoteur.reponse = ("## Résumé\n- Aujourd'hui, tu as terminé la tâche **Rapport mensuel**.\n"
                          "- Demain, appelle le dentiste à 9 h.")
    monkeypatch.setattr(chat_module, "build_connector", lambda name, settings, secrets: FauxMoteur())
    client.put("/api/agents/claude", json={"active": True, "api_key": "sk-test-resume"})
    return FauxMoteur


def accorder(client, *types):
    for t in types:
        assert client.put(f"/api/consent/{t}", json={"granted": True}).status_code == 200


class FauxCours:
    def __init__(self, jour: str, erreur: bool = False):
        self.jour, self.erreur = jour, erreur

    def liste(self):
        if self.erreur:
            raise RuntimeError("base des cours illisible")
        return [{"titre": "Chimie organique", "debut": f"{self.jour}T10:00:00-04:00", "duree_s": 2700},
                {"titre": "Vieux cours", "debut": "2026-01-05T10:00:00-05:00", "duree_s": 600}]


def iso_utc_du_jour(jour: str, heure: int = 12) -> str:
    local = datetime.combine(date.fromisoformat(jour), datetime.min.time()).replace(hour=heure).astimezone()
    return local.astimezone(timezone.utc).isoformat(timespec="seconds")


def tache(ctx, titre: str, statut: str, termine_le: str | None) -> None:
    ctx.db.execute(
        "INSERT INTO tasks(id, title, instructions_enc, agent, status, conversation_id, created_at, completed_at) "
        "VALUES(?,?,?,?,?,?,?,?)",
        (uuid.uuid4().hex, titre, ctx.crypto.encrypt("consigne"), "auto", statut, None,
         datetime.now(timezone.utc).isoformat(timespec="seconds"), termine_le),
    )


def journee(app, monkeypatch) -> str:
    """Une journée réaliste, écrite là où les vrais services l'écrivent."""
    ctx = app.state.ctx
    jour = date.today().isoformat()
    maintenant = datetime.now(timezone.utc).isoformat(timespec="seconds")
    tache(ctx, "Rapport mensuel", "done", maintenant)
    tache(ctx, "Sauvegarde", "failed", maintenant)
    tache(ctx, "Veille des prix", "running", None)
    tache(ctx, "Tâche d'hier", "done", (datetime.now(timezone.utc) - timedelta(days=2)).isoformat(timespec="seconds"))
    routine_conv = ctx.chat.create_conversation(title="Nouvelle conversation")
    for _ in range(2):
        ctx.chat._add_message(routine_conv["id"], "assistant", "Routine « mode travail » exécutée : 3 étapes sur 3.",
                              agent="routine", meta={"agent": "routine", "routine": "mode travail"})
    devis = ctx.chat.create_conversation(title="Devis Tremblay")
    ctx.chat._add_message(devis["id"], "user", "Prépare le devis pour la cuisine des Tremblay.")
    ctx.chat._add_message(devis["id"], "assistant", "Le devis est prêt dans tes documents.")
    voix = ctx.chat.create_conversation(title="Voix", kind="voice")
    ctx.chat._add_message(voix["id"], "user", "Quelle heure est-il ?")
    ctx.chat._add_message(voix["id"], "user", "Ouvre la calculatrice.")
    ctx.memory.add("Le code de la porte du bureau change lundi", source="user")
    ctx.memory.add("[Photo 10:12] Des clés sur la table", source="photo", kind="vision")
    ctx.memory.add(f"Résumé du {jour} :\nancien", source="iris", kind="daily_summary")
    ctx.journal.ajouter("on se rejoint au chalet samedi", "sous-titres")
    demain = (date.today() + timedelta(days=1)).isoformat()
    ctx.reminders.create("Appeler le dentiste", at=f"{demain} 09:00")
    ctx.rappels_contexte.creer("Marc", "Lui rendre ses clés")
    ctx.recus._enregistrer({"date": jour, "commercant": "IGA", "sous_total": 22.47, "tps": 0.65, "tvq": 1.3,
                            "tvh": None, "total": 24.42, "devise": "CAD", "categorie": "Alimentation",
                            "moyen_paiement": "Visa", "lignes": [], "confiance": 0.9, "local": True,
                            "controle": {}, "note": None}, b"\xff\xd8faux")
    monkeypatch.setattr(ctx, "cours", FauxCours(jour), raising=False)
    return jour


# --------------------------------------------------------------------------- collecte et version locale
def test_resume_local_construit_uniquement_avec_les_faits_du_jour(app, client, monkeypatch, moteur):
    jour = journee(app, monkeypatch)
    r = client.get("/api/resume/jour")
    assert r.status_code == 200, r.text
    resume = r.json()
    assert resume["date"] == jour and resume["local"] is True
    assert moteur.appels == [], "rien ne doit partir sans « Texte de vos demandes »"
    assert "Texte de vos demandes" in resume["note"] and resume["limite"] == quotidien.LIMITE
    sections = resume["sections"]
    assert sections["fait"] == [
        "Tâche terminée : Rapport mensuel",
        "Routine « mode travail » exécutée 2 fois",
        "Cours « Chimie organique » enregistré (45 minutes)",
        "Conversation « Devis Tremblay »",
        "2 demandes à la voix",
        "1 reçu enregistré, 24,42 $ au total",
        "1 phrase gardée dans le journal d'écoute",
    ]
    assert sections["reste"] == ["Tâche échouée : Sauvegarde", "Tâche encore en cours : Veille des prix",
                                 "À faire quand tu verras Marc : Lui rendre ses clés"]
    assert sections["rappels"] == ["Demain à 9 h : Appeler le dentiste"]
    assert sections["a_retenir"] == ["Le code de la porte du bureau change lundi"]
    texte = resume["texte"]
    assert texte.startswith("Aujourd'hui, tu as terminé la tâche « Rapport mensuel », lancé la routine « mode travail »")
    assert "Il te reste : la tâche « Sauvegarde », qui a échoué" in texte
    assert "Demain, un rappel à 9 h, appeler le dentiste." in texte
    assert "À retenir : le code de la porte du bureau change lundi." in texte
    assert "Tâche d'hier" not in texte and "Vieux cours" not in texte and "clés sur la table" not in texte
    assert quotidien.compter_mots(texte) <= quotidien.MOTS_MAX_LOCAL
    assert not any(n in texte.lower() for n in NOMS_INTERDITS)


def test_une_source_en_panne_ne_retire_que_sa_part(app, client, monkeypatch):
    journee(app, monkeypatch)
    monkeypatch.setattr(app.state.ctx, "cours", FauxCours(date.today().isoformat(), erreur=True), raising=False)
    resume = client.get("/api/resume/jour").json()
    assert "Tâche terminée : Rapport mensuel" in resume["sections"]["fait"]
    assert not any("Chimie" in e for e in resume["sections"]["fait"])


def test_journee_vide_et_journee_passee(app, client):
    vide = client.get("/api/resume/jour", params={"date": "2026-09-01"}).json()
    assert vide["texte"] == ("Je n'ai rien de noté pour le 1er septembre : aucune tâche, aucune conversation, "
                             "aucun souvenir, aucun cours, aucun reçu ni rappel.")
    assert vide["contenu"] is False and vide["local"] is True
    tache(app.state.ctx, "Déclaration de TVQ", "done", iso_utc_du_jour("2026-09-01"))
    passee = client.get("/api/resume/jour", params={"date": "2026-09-01"}).json()
    assert passee["texte"].startswith("Le 1er septembre, tu as terminé la tâche « Déclaration de TVQ ».")
    assert "Aujourd'hui" not in passee["texte"]
    assert client.get("/api/resume/jour", params={"date": "01/09/2026"}).status_code == 422


# --------------------------------------------------------------------------- moteur
def test_avec_consentement_le_moteur_redige_sans_souvenirs_non_autorises(app, client, monkeypatch, moteur):
    journee(app, monkeypatch)
    accorder(client, "transcript")
    resume = client.get("/api/resume/jour").json()
    assert resume["local"] is False and resume["note"] is None
    assert resume["texte"] == "Résumé Aujourd'hui, tu as terminé la tâche Rapport mensuel. Demain, appelle le dentiste à 9 h."
    (appel,) = moteur.appels
    assert appel["tools"] is None
    assert "UNIQUEMENT les faits fournis" in appel["system"] and "150 à 200" in appel["system"]
    message = appel["messages"][0]["content"]
    assert "Tâche terminée : Rapport mensuel" in message and "Demain à 9 h : Appeler le dentiste" in message
    assert "Prépare le devis pour la cuisine des Tremblay." in message
    assert "chalet samedi" not in message, "le journal d'écoute (paroles de tiers) reste local"
    assert "Le devis est prêt" not in message, "les réponses d'IRIS ne partent pas, seulement le titre"
    assert "1 phrase gardée dans le journal d'écoute" in message
    assert "code de la porte" not in message, "les souvenirs exigent « Extraits de mémoire »"
    envois = [e for e in app.state.ctx.consent.events(limit=30) if e["event_type"] == "external_send"]
    assert {e["data_type"] for e in envois} == {"transcript"}
    # Mêmes faits : pas de nouvel envoi. Souvenirs autorisés : nouvel envoi, souvenirs compris.
    assert client.get("/api/resume/jour").json()["texte"] == resume["texte"] and len(moteur.appels) == 1
    accorder(client, "memory")
    client.get("/api/resume/jour")
    assert len(moteur.appels) == 2 and "code de la porte" in moteur.appels[1]["messages"][0]["content"]
    assert not any(n in moteur.appels[1]["system"].lower() for n in NOMS_INTERDITS)


def test_le_journal_d_ecoute_ne_part_jamais_au_moteur(app, client, monkeypatch, moteur):
    """Le journal, ce sont des sous-titres ambiants : la voix de tiers. Même avec tous les consentements,
    aucune de ses phrases n'atteint le moteur ; seul le nombre de phrases est transmis."""
    ctx = app.state.ctx
    journee(app, monkeypatch)
    secret = "le code du coffre de Julie est 4471"
    ctx.journal.ajouter(secret, "sous-titres")
    ctx.journal.ajouter("Julie part à Gaspé demain matin", "journal")
    accorder(client, "transcript", "memory", "audio_raw")
    resume = client.get("/api/resume/jour").json()
    assert resume["local"] is False and moteur.appels
    for appel in moteur.appels:
        contenu = appel["system"] + " ".join(str(m.get("content")) for m in appel["messages"])
        assert "4471" not in contenu and "coffre de Julie" not in contenu and "Gaspé" not in contenu
        assert "chalet samedi" not in contenu
    assert "3 phrases gardées dans le journal d'écoute" in moteur.appels[-1]["messages"][0]["content"]


def test_mode_100_pour_cent_local_et_verbosite(app, client, monkeypatch, moteur):
    journee(app, monkeypatch)
    accorder(client, "transcript")
    app.state.ctx.settings.update({"local_only": True})
    resume = client.get("/api/resume/jour").json()
    assert moteur.appels == [] and resume["local"] is True and "100 % local" in resume["note"]
    app.state.ctx.settings.update({"local_only": False, "verbosite": "concis"})
    client.get("/api/resume/jour")
    assert "110 à 150" in moteur.appels[-1]["system"]


# --------------------------------------------------------------------------- mémoire et voix
def test_resume_quotidien_memorise_remplace_et_lit(app, monkeypatch, paroles, service):
    ctx = app.state.ctx
    jour = journee(app, monkeypatch)
    assert inspect.iscoroutinefunction(ctx.resume_quotidien)
    resultat = asyncio.run(ctx.resume_quotidien(jour))
    assert resultat["memorise"] is True and resultat["parle"] is True
    assert paroles == [(resultat["texte"], False)], "la boucle quotidienne respecte le réglage de voix"
    resumes = [m for m in ctx.memory.list() if m["kind"] == "daily_summary"]
    assert len(resumes) == 1 and resumes[0]["text"] == f"Résumé du {jour} :\n{resultat['texte']}"
    asyncio.run(ctx.resume_quotidien(jour))
    assert len([m for m in ctx.memory.list() if m["kind"] == "daily_summary"]) == 1


def test_memoire_suspendue_ni_memorise_et_mode_invite_muet(app, monkeypatch, paroles):
    ctx = app.state.ctx
    jour = journee(app, monkeypatch)
    ctx.memory.suspendre("zone:Clinique")
    resultat = asyncio.run(ctx.resume_quotidien(jour))
    assert resultat["memorise"] is False and resultat["parle"] is True
    assert [m for m in ctx.memory.list() if m["kind"] == "daily_summary" and "ancien" not in m["text"]] == []
    ctx.memory.reprendre("zone:Clinique")
    ctx.memory.suspendre("invite")
    paroles.clear()
    resultat = asyncio.run(ctx.resume_quotidien(jour))
    assert resultat["parle"] is False and paroles == []


def test_mode_confidentiel_rien_nest_lu(app, client, monkeypatch, paroles):
    ctx = app.state.ctx
    jour = journee(app, monkeypatch)
    ctx.settings.update({"privacy_mode": True})
    resultat = asyncio.run(ctx.resume_quotidien(jour))
    assert resultat["texte"] == "" and "confidentiel" in resultat["ignore"] and paroles == []
    r = client.post("/api/resume/jour/parler", json={"date": None})
    assert r.status_code == 409 and "confidentiel" in r.json()["detail"]


def test_route_parler_lit_a_voix_haute_sauf_en_mode_invite(app, client, monkeypatch, paroles):
    journee(app, monkeypatch)
    r = client.post("/api/resume/jour/parler", json={"date": None})
    assert r.status_code == 200, r.text
    corps = r.json()
    assert corps["parle"] is True and corps["memorise"] is True
    assert paroles == [(corps["texte"], True)]
    app.state.ctx.memory.suspendre("invite")
    r = client.post("/api/resume/jour/parler", json={})
    assert r.status_code == 409 and "invité" in r.json()["detail"]


def test_la_phrase_vocale_resume_ma_journee(app, monkeypatch, service):
    journee(app, monkeypatch)
    assert service.interception("quelle heure est-il") is None
    assert service.interception("résume le document") is None
    demande = service.interception("Iris, résume ma journée")
    assert inspect.iscoroutine(demande)
    texte = asyncio.run(demande)
    assert texte.startswith("Aujourd'hui, tu as terminé")
    app.state.ctx.memory.suspendre("invite")
    assert asyncio.run(service.interception("c'était quoi ma journée")) == quotidien.INVITE
    noms = {nom: priorite for priorite, nom, _f in app.state.ctx.voice._interceptions}
    assert noms.get("quotidien-resume") == 50


def test_textes_fixes_sans_fournisseur_ni_promesse_absolue():
    faits = {"date": "2026-09-13", "aujourdhui": True}
    textes = " ".join([quotidien.LIMITE, quotidien.CONFIDENTIEL, quotidien.INVITE,
                       quotidien.consigne_moteur(faits, "normal")]).lower()
    assert not any(n in textes for n in NOMS_INTERDITS)
    for absolu in ("toujours", "parfait", "instantan", "entièrement"):
        assert absolu not in textes


def test_un_moteur_muet_donne_le_resume_local_dans_le_delai(app, client, monkeypatch, moteur):
    """Contre-vérification du 2026-09-14 : le résumé lu à la voix (interception « résume ma journée ») attendait
    le moteur sans limite. Le délai de ChatService.demander_image_detail rend la version locale, dite."""
    import time

    class MoteurMuet(FauxMoteur):
        async def stream(self, messages, system, tools=None, run_tool=None, options=None):
            await asyncio.sleep(5.0)
            yield Chunk("text", text=FauxMoteur.reponse)
            yield Chunk("done")

    journee(app, monkeypatch)
    accorder(client, "transcript")
    monkeypatch.setattr(chat_module, "build_connector", lambda name, settings, secrets: MoteurMuet())
    monkeypatch.setattr(chat_module, "DELAI_MOTEUR_IMAGE_S", 0.3)
    debut = time.monotonic()
    resume = client.get("/api/resume/jour").json()
    assert time.monotonic() - debut < 3.0, "le résumé n'attend pas le moteur au-delà du délai"
    assert resume["local"] is True and resume["note"] == "Résumé rédigé sur l'ordinateur : le moteur VELA n'a pas répondu."
    assert resume["texte"].startswith("Aujourd'hui, tu as terminé la tâche « Rapport mensuel »")
