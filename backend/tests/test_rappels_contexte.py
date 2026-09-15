"""Rappels contextuels (interface G, chantier du 2026-09-13).

« La prochaine fois que je vois Marc, rappelle-moi de lui rendre ses clés. » Tout est synthétique :
événements du hub fabriqués à la main, fausse voix. Aucun micro, aucune caméra, aucun réseau.

Ce qui est protégé ici :
- chaque source honnête déclenche (sous-titres, commande vocale, « je suis avec… », message écrit,
  texto reçu, brouillon de message, courriel), et un rappel ne se déclenche qu'UNE fois ;
- la phrase de création ne se déclenche pas elle-même, ni un événement arrivé avant la création, ni
  IRIS qui répète le nom juste après (délai de grâce des sous-titres) ;
- mot entier, sans accents : « Marcel » ne déclenche pas « Marc », « helene » déclenche « Hélène » ;
- chiffré en base ; mémoire suspendue = rien de créé ni de déclenché ; mode confidentiel = rien de déclenché.
"""
from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone

import pytest

import iris.rappels_contexte as rc

# Lunettes d'abord (2026-09-13) : ces tests portent sur la fonction elle-même, lunettes présentes.
# La garde est vérifiée à part, avec et sans lunettes, dans test_garde_lunettes.py.
pytestmark = pytest.mark.usefixtures("lunettes_presentes")


@pytest.fixture(scope="module")
def _application(tmp_path_factory):
    from fastapi.testclient import TestClient

    from iris.main import create_app

    dossier = tmp_path_factory.mktemp("iris-rappels")
    application = create_app(data_dir=dossier, token="test-token", use_keyring=False, enable_tts=False)
    with TestClient(application, headers={"Authorization": "Bearer test-token"}) as c:
        yield application, c
    application.state.ctx.close()


@pytest.fixture()
def app(_application):
    application, _c = _application
    yield application
    ctx = application.state.ctx
    ctx.settings.update({"privacy_mode": False, "verbosite": "normal", "retention_days": 0})
    for raison in ctx.memory.raisons_suspension():
        ctx.memory.reprendre(raison)
    ctx.db.execute("DELETE FROM rappels_contexte")
    ctx.rappels_contexte._recharger()


@pytest.fixture()
def client(app, _application):
    return _application[1]


@pytest.fixture()
def service(app):
    return app.state.ctx.rappels_contexte


@pytest.fixture()
def paroles(app, monkeypatch):
    dites: list[str] = []

    def parler(texte, force=False):
        dites.append(texte)
        return True

    monkeypatch.setattr(app.state.ctx.tts, "speak", parler)
    return dites


@pytest.fixture()
def evenements(app, monkeypatch):
    hub = app.state.ctx.hub
    publies: list[dict] = []
    original = hub.publish

    def publier(type_, **data):
        publies.append({"type": type_, **data})
        return original(type_, **data)

    monkeypatch.setattr(hub, "publish", publier)
    return publies


def vieillir(app, service, rappel_id: str, secondes: float = 3600) -> None:
    """Recule la création : sort le rappel du délai de grâce des sous-titres."""
    app.state.ctx.db.execute("UPDATE rappels_contexte SET cree_epoch = cree_epoch - ? WHERE id=?", (secondes, rappel_id))
    service._recharger()


# --------------------------------------------------------------------------- compréhension des phrases
@pytest.mark.parametrize("phrase, attendu", [
    ("La prochaine fois que je vois Marc, rappelle-moi de lui rendre ses clés.", ("Marc", "Lui rendre ses clés")),
    ("la prochaine fois que je vois marc rappelle moi de lui rendre ses clés", ("Marc", "Lui rendre ses clés")),
    ("Quand je parle à Julie, dis-moi de lui demander le document", ("Julie", "Lui demander le document")),
    ("quand je parle a julie dis moi de lui demander le document", ("Julie", "Lui demander le document")),
    ("Rappelle-moi de lui demander le devis quand je parle à Julie", ("Julie", "Lui demander le devis")),
    ("Iris, quand je serai avec ma sœur Julie, rappelle-moi qu'elle me doit 20 dollars",
     ("ma sœur Julie", "Elle me doit 20 dollars")),
    ("Quand j'appelle le dentiste, fais-moi penser à demander la facture", ("le dentiste", "Demander la facture")),
    ("dès que je croise Marie-Claude Tremblay rappelle-moi de lui parler du chalet",
     ("Marie-Claude Tremblay", "Lui parler du chalet")),
])
def test_les_demandes_de_rappel_sont_comprises(phrase, attendu):
    assert rc.analyser_demande(phrase) == attendu


@pytest.mark.parametrize("phrase", [
    "rappelle-moi dans 20 minutes d'appeler Paul",
    "rappelle-moi d'appeler Paul quand je suis au bureau",
    "quand je vois que le colis arrive rappelle-moi de le signer",
    "dis-moi quelle heure il est",
    "si je vois bien, rappelle-moi de sortir les poubelles",
    "je suis avec Marc",
    "",
])
def test_les_autres_phrases_ne_creent_rien(phrase):
    assert rc.analyser_demande(phrase) is None


def test_mot_entier_sans_accents_et_prenom_seul():
    assert rc.cles_personne("Marc Tremblay") == ["marc tremblay", "marc"]
    assert rc.cles_personne("ma sœur Julie") == ["ma soeur julie", "julie"]
    assert rc.cles_personne("mon patron") == ["mon patron"]
    assert rc.mentionne(rc.normaliser("J'ai croisé Marc au café"), rc.cles_personne("Marc"))
    assert not rc.mentionne(rc.normaliser("Marcel est arrivé"), rc.cles_personne("Marc"))
    assert rc.mentionne(rc.normaliser("helene vient souper"), rc.cles_personne("Hélène"))


# --------------------------------------------------------------------------- routes et stockage
def test_creer_lister_supprimer_et_chiffrer(app, client):
    r = client.post("/api/rappels-contexte", json={"personne": "Marc", "texte": "Lui rendre ses clés"})
    assert r.status_code == 200, r.text
    rappel = r.json()
    assert set(rappel) == {"id", "personne", "texte", "cree_le", "declenche_le", "declencheur"}
    assert rappel["personne"] == "Marc" and rappel["declenche_le"] is None
    brut = app.state.ctx.db.one("SELECT * FROM rappels_contexte WHERE id=?", (rappel["id"],))
    assert b"Marc" not in bytes(brut["personne_enc"]) and "clés".encode() not in bytes(brut["texte_enc"])
    liste = client.get("/api/rappels-contexte").json()
    assert [x["id"] for x in liste["rappels"]] == [rappel["id"]] and liste["memoire_suspendue"] is None
    assert client.post("/api/rappels-contexte", json={"personne": "", "texte": "x"}).status_code == 422
    assert client.post("/api/rappels-contexte", json={"personne": "Marc", "texte": " "}).status_code == 422
    assert client.delete(f"/api/rappels-contexte/{rappel['id']}").json() == {"supprime": True}
    assert client.delete(f"/api/rappels-contexte/{rappel['id']}").status_code == 404


# --------------------------------------------------------------------------- déclenchement
SOURCES = [
    ({"type": "ecoute.sous_titre", "partiel": None, "final": "salut marc ça va"}, "sous_titres"),
    ({"type": "voice.transcript", "text": "je suis avec Marc"}, "presence"),
    ({"type": "voice.transcript", "text": "envoie un courriel à Marc pour la réunion"}, "commande_vocale"),
    ({"type": "chat.user_message", "message": {"text": "Marc passe à 15 h", "meta": {"source": "text"}}}, "message_ecrit"),
    ({"type": "telephone.sms_entrant", "de": "+15145550100", "corps": "C'est Marc, j'arrive"}, "sms"),
    ({"type": "telephone.brouillon", "brouillon": {"titre": "Texto", "texte": "Salut Marc, on se voit ?"}}, "brouillon_message"),
    ({"type": "courriel.recu", "sujet": "Réunion", "de": "Marc Tremblay <marc@exemple.ca>"}, "courriel"),
]


@pytest.mark.parametrize("evenement, declencheur", SOURCES)
def test_chaque_source_declenche_une_seule_fois(app, service, paroles, evenements, evenement, declencheur):
    rappel = service.creer("Marc", "Lui rendre ses clés")
    vieillir(app, service, rappel["id"])
    fait = service.traiter_evenement({**evenement, "ts": time.time()})
    assert [d["id"] for d in fait] == [rappel["id"]] and fait[0]["declencheur"] == declencheur
    assert paroles == ["Rappel pour Marc : Lui rendre ses clés."]
    annonces = [e for e in evenements if e["type"] == "rappel.contexte"]
    assert annonces == [{"type": "rappel.contexte", "id": rappel["id"], "personne": "Marc",
                         "texte": "Lui rendre ses clés", "declencheur": declencheur}]
    # Même événement une seconde fois : rien, ni voix ni événement.
    assert service.traiter_evenement({**evenement, "ts": time.time()}) == []
    assert len(paroles) == 1
    stocke = next(r for r in service.liste() if r["id"] == rappel["id"])
    assert stocke["declenche_le"] and stocke["declencheur"] == declencheur


def test_ce_qui_ne_doit_pas_declencher(app, service, paroles):
    rappel = service.creer("Marc", "Lui rendre ses clés")
    # Juste après la création : IRIS répète le nom en confirmant, les sous-titres l'entendent.
    assert service.traiter_evenement({"type": "ecoute.sous_titre", "final": "c'est noté pour marc", "ts": time.time()}) == []
    vieillir(app, service, rappel["id"])
    maintenant = time.time()
    # Phrase de création répétée, événement plus vieux que le rappel, tâche de fond, nom voisin, autre événement.
    assert service.verifier_texte("la prochaine fois que je vois Marc rappelle-moi de lui rendre ses clés",
                                  "commande_vocale") == []
    assert service.traiter_evenement({"type": "voice.transcript", "text": "Marc", "ts": maintenant - 7200}) == []
    assert service.traiter_evenement({"type": "chat.user_message",
                                      "message": {"text": "écris à Marc", "meta": {"source": "task"}}, "ts": maintenant}) == []
    assert service.traiter_evenement({"type": "chat.user_message",
                                      "message": {"text": "Marcel arrive", "meta": {}}, "ts": maintenant}) == []
    assert service.traiter_evenement({"type": "voice.level", "text": "Marc", "ts": maintenant}) == []
    assert service.traiter_evenement({"type": "telephone.appel_entrant", "de": "+15145550100", "ts": maintenant}) == []
    assert paroles == []


def test_memoire_suspendue_ni_creation_ni_declenchement(app, client, service, paroles):
    rappel = service.creer("Julie", "Le document")
    vieillir(app, service, rappel["id"])
    app.state.ctx.memory.suspendre("invite")
    r = client.post("/api/rappels-contexte", json={"personne": "Marc", "texte": "Les clés"})
    assert r.status_code == 409 and "suspendue" in r.json()["detail"]
    assert client.get("/api/rappels-contexte").json()["memoire_suspendue"] == "invite"
    assert "suspendue" in service.interception("La prochaine fois que je vois Marc, rappelle-moi de lui rendre ses clés")
    assert service.verifier_texte("Julie est là", "message_ecrit") == []
    app.state.ctx.memory.reprendre("invite")
    assert [d["personne"] for d in service.verifier_texte("Julie est là", "message_ecrit")] == ["Julie"]
    assert len(service.liste()) == 1


def test_mode_confidentiel_ne_declenche_rien(app, service, paroles):
    rappel = service.creer("Julie", "Le document")
    vieillir(app, service, rappel["id"])
    app.state.ctx.settings.update({"privacy_mode": True})
    assert service.verifier_texte("Julie est là", "message_ecrit") == [] and paroles == []


# --------------------------------------------------------------------------- voix
def test_creation_vocale_puis_je_suis_avec(app, service, paroles):
    assert service.interception("quelle heure est-il") is None
    assert service.interception("je suis avec Marc") is None, "aucun rappel n'attend Marc : le modèle répond"
    phrase = service.interception("la prochaine fois que je vois marc rappelle moi de lui rendre ses clés")
    assert phrase.startswith("C'est noté pour Marc : lui rendre ses clés.") and "je suis avec Marc" in phrase
    (rappel,) = service.liste()
    assert rappel["personne"] == "Marc" and rappel["texte"] == "Lui rendre ses clés"
    assert app.state.ctx.db.one("SELECT origine FROM rappels_contexte")["origine"] == "voix"
    reponse = service.interception("je suis avec Marc")
    assert reponse == "Rappel pour Marc : Lui rendre ses clés."
    assert paroles == [], "l'écoute lit la phrase rendue : IRIS ne doit pas la dire deux fois"
    assert service.liste()[0]["declencheur"] == "presence"
    assert service.interception("je suis avec Marc") is None
    app.state.ctx.settings.update({"verbosite": "concis"})
    assert service.interception("quand je parle à Julie, dis-moi de lui demander le document") == "C'est noté pour Julie."


def test_linterception_est_branchee_sur_lecoute_en_priorite_50(app):
    noms = {nom: priorite for priorite, nom, _f in app.state.ctx.voice._interceptions}
    assert noms.get("quotidien-rappels") == 50


def test_de_bout_en_bout_par_le_hub(app, client, service, paroles):
    rappel = client.post("/api/rappels-contexte", json={"personne": "Hélène", "texte": "Rapporter le livre"}).json()
    vieillir(app, service, rappel["id"])
    app.state.ctx.hub.publish("ecoute.sous_titre", partiel=None, final="bonjour helene", ts=time.time())
    limite = time.monotonic() + 5
    while time.monotonic() < limite:
        etat = client.get("/api/rappels-contexte").json()["rappels"][0]
        if etat["declenche_le"] and paroles:  # la base est écrite avant l'annonce : attendre les deux
            break
        time.sleep(0.05)
    assert etat["declencheur"] == "sous_titres"
    assert paroles == ["Rappel pour Hélène : Rapporter le livre."]


def test_la_retention_efface_les_vieux_rappels(app, service):
    ancien = service.creer("Marc", "Vieux rappel")
    app.state.ctx.db.execute("UPDATE rappels_contexte SET cree_le=? WHERE id=?",
                             ((datetime.now(timezone.utc) - timedelta(days=10)).isoformat(timespec="seconds"), ancien["id"]))
    service.creer("Julie", "Récent")
    app.state.ctx.settings.update({"retention_days": 7})
    assert service.purger() == 1
    assert [r["personne"] for r in service.liste()] == ["Julie"]
    assert [r["personne"] for r in service.en_attente()] == ["Julie"]


def test_textes_visibles_sans_fournisseur():
    textes = " ".join([rc.MEMOIRE_SUSPENDUE, *rc.DECLENCHEURS.values(), rc.phrase_annonce("Marc", "x")]).lower()
    for nom in ("claude", "anthropic", "openai", "gpt", "gemini", "google", "elevenlabs", "vosk", "piper", "twilio"):
        assert nom not in textes
