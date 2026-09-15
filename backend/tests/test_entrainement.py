"""Entraînement (interface H, chantier du 2026-09-13).

Tout est synthétique : horloge simulée pour le repos, fausse synthèse vocale, phrases écrites comme la
reconnaissance vocale locale les rend (nombres en lettres). Aucun micro, aucun capteur, aucun réseau.

Ce qui est protégé ici :
- une série n'est comptée que sur une vraie commande (« pas fini » ne compte rien) ;
- le repos est annoncé à l'heure (« Repos : 30 secondes. », « 10 secondes. », « Repos terminé. Série 2. »),
  gèle en pause et reprend là où il en était ;
- l'historique est chiffré, suit la durée de conservation, et n'est pas écrit quand la mémoire est suspendue ;
- la limite (IRIS ne compte pas les répétitions) est toujours dans la réponse.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest

import iris.entrainement as ent

# Lunettes d'abord (2026-09-13) : ces tests portent sur la fonction elle-même, lunettes présentes.
# La garde est vérifiée à part, avec et sans lunettes, dans test_garde_lunettes.py.
pytestmark = pytest.mark.usefixtures("lunettes_presentes")


@pytest.fixture(scope="module")
def _application(tmp_path_factory):
    from fastapi.testclient import TestClient

    from iris.main import create_app

    dossier = tmp_path_factory.mktemp("iris-entrainement")
    application = create_app(data_dir=dossier, token="test-token", use_keyring=False, enable_tts=False)
    application.state.ctx.settings.update({"voice_autostart": False})
    with TestClient(application, headers={"Authorization": "Bearer test-token"}) as c:
        yield application, c
    application.state.ctx.close()


@pytest.fixture()
def app(_application):
    application, c = _application
    yield application
    ctx = application.state.ctx
    if ctx.entrainement.actif:
        c.post("/api/entrainement/commande", json={"action": "terminer", "parler": False})
    ctx.settings.update({"privacy_mode": False, "retention_days": 0, "verbosite": "normal", "entrainement_repos_s": 90})
    for raison in ctx.memory.raisons_suspension():
        ctx.memory.reprendre(raison)
    ctx.db.execute("DELETE FROM entrainement_seances")


@pytest.fixture()
def client(app, _application):
    return _application[1]


class HorlogeSimulee:
    def __init__(self):
        self.t = 5000.0
        self._attentes: list[tuple[float, asyncio.Future]] = []

    def maintenant(self) -> float:
        return self.t

    async def dormir(self, secondes: float) -> None:
        attente = (self.t + max(0.0, secondes), asyncio.get_running_loop().create_future())
        self._attentes.append(attente)
        try:
            await attente[1]
        finally:
            if attente in self._attentes:
                self._attentes.remove(attente)

    async def avancer(self, secondes: float) -> None:
        cible = self.t + secondes
        while True:
            await laisser_tourner()
            prets = [a for a in self._attentes if a[0] <= cible and not a[1].done()]
            if not prets:
                break
            self.t = max(self.t, min(a[0] for a in prets))
            for fin, futur in list(self._attentes):
                if fin <= self.t and not futur.done():
                    futur.set_result(None)
        self.t = cible
        await laisser_tourner()


async def laisser_tourner() -> None:
    for _ in range(30):
        await asyncio.sleep(0)


def service_simule(ctx):
    horloge = HorlogeSimulee()
    service = ent.ServiceEntrainement(ctx, maintenant=horloge.maintenant, dormir=horloge.dormir)
    dits: list[str] = []

    async def dire(texte: str) -> None:
        dits.append(texte)

    service.dire = dire  # type: ignore[method-assign]
    return service, horloge, dits


# --------------------------------------------------------------------------- phrases
@pytest.mark.parametrize("phrase, attendu", [
    ("Démarre l'entraînement", {"exercice": None, "series_cibles": None, "repos_s": None}),
    ("démarre l'entraînement de squats", {"exercice": "squats", "series_cibles": None, "repos_s": None}),
    ("commence une séance d'entraînement de développé couché quatre séries repos une minute trente",
     {"exercice": "développé couché", "series_cibles": 4, "repos_s": 90}),
    ("lance un entraînement de pompes 5 séries repos de 60 secondes",
     {"exercice": "pompes", "series_cibles": 5, "repos_s": 60}),
])
def test_demarrage_vocal_compris(phrase, attendu):
    assert ent.analyser_demarrage(phrase) == attendu


@pytest.mark.parametrize("phrase", [
    "termine l'entraînement", "comment on s'entraîne pour un marathon", "démarre une séance photo",
    "quelle heure est-il", "l'entraînement de hier était dur",
])
def test_ce_qui_nest_pas_un_demarrage(phrase):
    assert ent.analyser_demarrage(phrase) is None


@pytest.mark.parametrize("phrase, attendu", [
    ("série terminée", "serie"), ("fini", "serie"), ("j'ai fini", "serie"), ("une de plus", "serie"),
    ("pas fini", None), ("presque fini", None), ("pause", "pause"), ("reprends", "reprendre"),
    ("termine l'entraînement", "terminer"), ("combien de séries", "etat"), ("quelle heure est-il", None),
    ("j'ai fini de lire le livre de cuisine", None),
])
def test_commandes_de_seance(phrase, attendu):
    assert ent.action_vocale(phrase) == attendu


# --------------------------------------------------------------------------- repos (horloge simulée)
def test_series_et_repos_annonces_a_lheure(app):
    service, horloge, dits = service_simule(app.state.ctx)

    async def scenario():
        s = await service.demarrer("squats", 3, 30)
        assert s["phrase"] == ("Entraînement démarré : squats. Objectif : 3 séries. Repos : 30 secondes. "
                               "Dites « série terminée » après chaque série. Je ne compte pas les répétitions.")
        assert "ne compte pas les répétitions" in s["limite"]
        await horloge.avancer(40)  # première série : 40 s d'effort
        r = await service.commande("serie")
        assert r["phrase"] == "Série 1 sur 3 terminée. Repos : 30 secondes."
        assert r["etat"] == "repos" and r["repos_restant_s"] == 30
        await horloge.avancer(19)
        assert dits[-1] == r["phrase"] and service.etat()["repos_restant_s"] == 11
        await horloge.avancer(1)
        assert dits[-1] == "10 secondes."
        await horloge.avancer(9)
        assert dits[-1] == "10 secondes."
        await horloge.avancer(1)
        assert dits[-1] == "Repos terminé. Série 2."
        assert service.etat()["etat"] == "effort" and service.etat()["repos_restant_s"] == 0
        await service.commande("serie")
        await horloge.avancer(30)
        r = await service.commande("serie")
        assert r["phrase"] == "Série 3 sur 3 terminée : objectif atteint. Dites « termine l'entraînement » pour le bilan."
        assert r["etat"] == "effort"
        await horloge.avancer(60)
        assert dits[-1] == r["phrase"], "aucun repos après l'objectif atteint"
        fin = await service.terminer()
        assert fin["phrase"] == "Séance terminée : squats. 3 séries en 2 minutes 40 secondes. Objectif : 3."
        assert fin["enregistree"] is True and fin["actif"] is False

    asyncio.run(scenario())


def test_la_pause_gele_le_repos_et_ne_compte_pas_dans_la_duree(app):
    service, horloge, dits = service_simule(app.state.ctx)

    async def scenario():
        await service.demarrer(None, None, 60)
        await service.commande("serie")
        await horloge.avancer(20)
        r = await service.commande("pause")
        assert r["phrase"] == "Pause. Dites « reprends » pour continuer." and r["en_pause"] and r["repos_restant_s"] == 40
        await horloge.avancer(300)
        assert service.etat()["repos_restant_s"] == 40 and "Repos terminé" not in " ".join(dits)
        r = await service.commande("reprendre")
        assert r["phrase"] == "On reprend : repos, 40 secondes." and r["etat"] == "repos"
        await horloge.avancer(40)
        assert dits[-1] == "Repos terminé. Série 2."
        fin = await service.terminer()
        assert fin["duree_s"] == 60, "les 300 secondes de pause ne comptent pas"

    asyncio.run(scenario())


def test_une_serie_dite_pendant_le_repos_relance_le_repos(app):
    service, horloge, dits = service_simule(app.state.ctx)

    async def scenario():
        await service.demarrer("tractions", None, 30)
        await service.commande("serie")
        await horloge.avancer(15)
        r = await service.commande("serie")
        assert r["series"] == 2 and r["repos_restant_s"] == 30
        await horloge.avancer(16)
        assert "Repos terminé. Série 2." not in dits, "l'ancien repos ne doit plus sonner"
        await horloge.avancer(14)
        assert dits[-1] == "Repos terminé. Série 3."
        await service.terminer()

    asyncio.run(scenario())


def test_terminer_pendant_le_repos_coupe_les_annonces(app):
    service, horloge, dits = service_simule(app.state.ctx)

    async def scenario():
        await service.demarrer(None, None, 90)
        await service.commande("serie")
        await service.terminer()
        await horloge.avancer(200)
        assert not any(d in ("10 secondes.", "Repos terminé. Série 2.") for d in dits)

    asyncio.run(scenario())


# --------------------------------------------------------------------------- historique
def test_historique_chiffre_et_lisible(client, app):
    client.post("/api/entrainement/demarrer", json={"exercice": "fentes marchées", "parler": False})
    client.post("/api/entrainement/commande", json={"action": "serie", "parler": False})
    client.post("/api/entrainement/commande", json={"action": "serie", "parler": False})
    fin = client.post("/api/entrainement/commande", json={"action": "terminer", "parler": False}).json()
    assert fin["enregistree"] is True
    brut = app.state.ctx.db.query("SELECT donnees_enc FROM entrainement_seances")
    assert len(brut) == 1 and b"fentes" not in bytes(brut[0]["donnees_enc"])
    seances = client.get("/api/entrainement/seances").json()
    assert seances["seances"][0]["exercice"] == "fentes marchées" and seances["seances"][0]["series"] == 2
    assert seances["memoire_suspendue"] is None
    assert client.delete(f"/api/entrainement/seances/{fin['id']}").json() == {"supprime": True}
    assert client.get("/api/entrainement/seances").json()["seances"] == []
    assert client.delete(f"/api/entrainement/seances/{fin['id']}").status_code == 404


def test_memoire_suspendue_rien_nest_ecrit_et_on_le_dit(client, app):
    app.state.ctx.memory.suspendre("mode invité")
    client.post("/api/entrainement/demarrer", json={"parler": False})
    assert client.get("/api/entrainement/etat").json()["memoire_suspendue"] == "mode invité"
    client.post("/api/entrainement/commande", json={"action": "serie", "parler": False})
    fin = client.post("/api/entrainement/commande", json={"action": "terminer", "parler": False}).json()
    assert fin["enregistree"] is False and "mémoire est suspendue" in fin["phrase"]
    assert app.state.ctx.db.query("SELECT id FROM entrainement_seances") == []


def test_sans_serie_rien_nest_enregistre(client, app):
    client.post("/api/entrainement/demarrer", json={"parler": False})
    fin = client.post("/api/entrainement/commande", json={"action": "terminer", "parler": False}).json()
    assert fin["enregistree"] is False and "rien n'est enregistré" in fin["phrase"]


def test_la_duree_de_conservation_sapplique(client, app):
    ctx = app.state.ctx
    service = ctx.entrainement
    client.post("/api/entrainement/demarrer", json={"parler": False})
    client.post("/api/entrainement/commande", json={"action": "serie", "parler": False})
    client.post("/api/entrainement/commande", json={"action": "terminer", "parler": False})
    vieux = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat(timespec="seconds")
    ctx.db.execute("UPDATE entrainement_seances SET debut=?", (vieux,))
    assert len(service.seances()) == 1, "sans durée de conservation, rien n'est effacé"
    ctx.settings.update({"retention_days": 7})
    assert service.seances() == []


# --------------------------------------------------------------------------- routes et refus
def test_refus_documentes(client, app):
    assert client.get("/api/entrainement/etat").json()["actif"] is False
    assert client.post("/api/entrainement/commande", json={"action": "serie"}).status_code == 409
    assert client.post("/api/entrainement/demarrer", json={"repos_s": 5}).status_code == 422
    assert client.post("/api/entrainement/demarrer", json={"series_cibles": 0}).status_code == 422
    s = client.post("/api/entrainement/demarrer", json={"parler": False}).json()
    assert s["repos_s"] == 90, "le repos par défaut vient du réglage"
    r = client.post("/api/entrainement/demarrer", json={})
    assert r.status_code == 409 and "déjà en cours" in r.json()["detail"]
    assert client.post("/api/entrainement/commande", json={"action": "sauter"}).status_code == 422
    assert client.post("/api/entrainement/commande", json={"action": "reprendre", "parler": False}).json()["phrase"] \
        .startswith("La séance n'est pas en pause.")


def test_mode_confidentiel_refuse_et_arrete(client, app):
    client.post("/api/entrainement/demarrer", json={"parler": False})
    client.post("/api/entrainement/commande", json={"action": "serie", "parler": False})
    assert client.patch("/api/settings", json={"privacy_mode": True}).status_code == 200
    for _ in range(50):
        if not app.state.ctx.entrainement.actif:
            break
        client.get("/api/entrainement/etat")
    assert client.get("/api/entrainement/etat").json()["actif"] is False
    assert len(client.get("/api/entrainement/seances").json()["seances"]) == 1, "la séance faite est gardée"
    r = client.post("/api/entrainement/demarrer", json={})
    assert r.status_code == 409 and "confidentiel" in r.json()["detail"]
    client.patch("/api/settings", json={"privacy_mode": False})


def test_voix_demarrer_compter_terminer(client, app):
    ctx = app.state.ctx
    assert ctx.entrainement.interception("série terminée") is None, "hors séance, rien n'est intercepté"
    phrase = ctx.voice._intercepter("démarre l'entraînement de squats trois séries")
    assert phrase.startswith("Entraînement démarré : squats. Objectif : 3 séries. Repos : 1 minute 30 secondes.")
    assert ctx.voice._intercepter("démarre l'entraînement") == "Une séance de squats est déjà en cours : 0 série faite."
    assert ctx.entrainement.interception("quelle heure est-il") is None
    assert ctx.voice._intercepter("série terminée") == "Série 1 sur 3 terminée. Repos : 1 minute 30 secondes."
    assert ctx.voice._intercepter("combien de séries").startswith("1 série sur 3 faite. Repos :")
    assert ctx.voice._intercepter("termine l'entraînement").startswith("Séance terminée : squats. 1 série en")
    assert not ctx.entrainement.actif
