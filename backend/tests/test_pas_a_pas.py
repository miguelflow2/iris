"""Pas à pas « mains occupées » (interface H, chantier du 2026-09-13).

Tout est synthétique : étapes écrites à la main, faux moteur (connecteur simulé), fausse vision, horloge
simulée pour les minuteurs, fausse synthèse vocale. Aucun réseau, aucun micro, aucun Bluetooth.

Ce qui est protégé ici :
- un minuteur vient d'une durée DITE dans l'étape (jamais inventée), et il sonne à l'heure, pour la bonne
  étape, sans sonner après la fin de la session ;
- pendant une session, seules les vraies commandes sont interceptées : une question ordinaire va au modèle ;
- rien ne part au moteur sans « Texte de vos demandes » ; mode local et mode confidentiel refusent, en le disant ;
- « est-ce que c'est bon ? » passe par la vision d'accessibilité avec l'étape en contexte, sans rien retenir.
"""
from __future__ import annotations

import asyncio
import json

import pytest

import iris.chat as chat_module
import iris.pas_a_pas as pap
from iris.connectors.base import BaseConnector, Chunk

# Lunettes d'abord (2026-09-13) : ces tests portent sur la fonction elle-même, lunettes présentes.
# La garde est vérifiée à part, avec et sans lunettes, dans test_garde_lunettes.py.
pytestmark = pytest.mark.usefixtures("lunettes_presentes")

NOMS_INTERDITS = ("claude", "anthropic", "openai", "gpt", "gemini", "google", "elevenlabs", "vosk", "piper",
                  "openrouter", "ollama", "tavily", "brave")

ETAPES_CREPES = [
    "Mélangez 250 g de farine et 3 oeufs.",
    "Laissez reposer la pâte 30 minutes.",
    "Faites cuire chaque crêpe 1 minute de chaque côté.",
]


# --------------------------------------------------------------------------- une seule application
@pytest.fixture(scope="module")
def _application(tmp_path_factory):
    from fastapi.testclient import TestClient

    from iris.main import create_app

    dossier = tmp_path_factory.mktemp("iris-pas-a-pas")
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
    if ctx.pas_a_pas.actif:
        c.post("/api/pas-a-pas/commande", json={"action": "terminer", "parler": False})
    ctx.settings.update({"local_only": False, "privacy_mode": False, "verbosite": "normal",
                         "agents": {"claude": {"active": False}}})
    ctx.secrets.delete_api_key("claude")
    for type_donnee in ("transcript", "audio_raw", "image", "screen", "memory"):
        ctx.consent.set(type_donnee, False)


@pytest.fixture()
def client(app, _application):
    return _application[1]


class FauxMoteur(BaseConnector):
    name = "claude"
    supports_tools = True
    supports_images = True
    appels: list[dict] = []
    reponse = ""

    def __init__(self):
        super().__init__("cle", "faux-modele")

    async def stream(self, messages, system, tools=None, run_tool=None, options=None):
        FauxMoteur.appels.append({"messages": messages, "system": system})
        yield Chunk("text", text=FauxMoteur.reponse)
        yield Chunk("done")

    async def test(self):  # pragma: no cover
        return {"ok": True}


@pytest.fixture()
def moteur(monkeypatch, client):
    FauxMoteur.appels = []
    FauxMoteur.reponse = json.dumps({"titre": "Crêpes", "type": "recette", "etapes": ETAPES_CREPES})
    monkeypatch.setattr(chat_module, "build_connector", lambda name, settings, secrets: FauxMoteur())
    client.put("/api/agents/claude", json={"active": True, "api_key": "sk-test-pas-a-pas"})
    return FauxMoteur


def accorder(client, *types):
    for t in types:
        assert client.put(f"/api/consent/{t}", json={"granted": True}).status_code == 200


class HorlogeSimulee:
    """Temps qui n'avance que sur demande : un minuteur de 30 minutes se teste en quelques millisecondes."""

    def __init__(self):
        self.t = 1000.0
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
    service = pap.ServicePasAPas(ctx, maintenant=horloge.maintenant, dormir=horloge.dormir)
    dits: list[str] = []

    async def dire(texte: str) -> None:
        dits.append(texte)

    service.dire = dire  # type: ignore[method-assign]
    return service, horloge, dits


# --------------------------------------------------------------------------- langue parlée
@pytest.mark.parametrize("texte, attendu", [
    ("Faites cuire 10 minutes à feu moyen.", 600),
    ("Laissez lever 1 h 30.", 5400),
    ("une heure et demie", 5400),
    ("Laissez reposer une demi-heure.", 1800),
    ("deux minutes trente", 150),
    ("quatre-vingt-dix secondes", 90),
    ("Cuire 10 à 12 minutes.", 600),
    ("Cuire 10-12 minutes.", 600),
    ("Laissez sécher 24 h.", 86400),
    ("1 heure et 15 minutes", 4500),
    ("Ajoutez 2 oeufs et cuire 3 minutes.", 180),
    ("Cuire 10 minutes puis laisser tiédir 5 minutes.", 600),
    ("Préchauffez le four à 180 degrés.", None),
    ("Passez à l'étape 3.", None),
    ("Vissez les 4 pattes.", None),
    ("un minuteur", None),
])
def test_la_duree_vient_de_la_phrase_et_nest_jamais_inventee(texte, attendu):
    assert pap.lire_duree(texte) == attendu


def test_la_duree_se_dit_sans_abreviation():
    assert pap.duree_parlee(90) == "1 minute 30 secondes"
    assert pap.duree_parlee(5400) == "1 heure 30 minutes"
    assert pap.duree_parlee(1) == "1 seconde"
    assert pap.duree_parlee(120) == "2 minutes"


@pytest.mark.parametrize("phrase, attendu", [
    ("suivant", ("suivant", None)),
    ("étape suivante s'il te plaît", ("suivant", None)),
    ("c'est fait", ("suivant", None)),
    ("précédent", ("precedent", None)),
    ("répète", ("repeter", None)),
    ("on en est où", ("ou", None)),
    ("lance le minuteur", ("minuteur", None)),
    ("lance un minuteur de cinq minutes", ("minuteur", 300)),
    ("il reste combien au minuteur", ("ou", None)),
    ("arrête le minuteur", ("annuler_minuteur", None)),
    ("est-ce que c'est bon", ("verifier", None)),
    ("c'est fini", ("terminer", None)),
])
def test_les_commandes_de_session_sont_reconnues(phrase, attendu):
    assert pap.action_vocale(phrase) == attendu


@pytest.mark.parametrize("phrase", [
    "quelle heure est-il", "passe à la chanson suivante", "c'est quoi la suite du film ce soir",
    "envoie un texto à Marc", "ouvre youtube", "",
])
def test_une_question_ordinaire_nest_pas_une_commande(phrase):
    assert pap.action_vocale(phrase) is None


def test_les_etapes_sont_nettoyees_et_bornees():
    etapes = pap.construire_etapes(["1. Mélangez.", "  ", "- Cuire 5 minutes", {"texte": "Servez."}, None, 42])
    assert [e["texte"] for e in etapes] == ["Mélangez.", "Cuire 5 minutes", "Servez.", "42"]
    assert [e["n"] for e in etapes] == [1, 2, 3, 4]
    assert etapes[1]["minuteur_s"] == 300 and etapes[0]["minuteur_s"] is None
    assert len(pap.construire_etapes([f"Étape {i}" for i in range(100)])) == pap.ETAPES_MAX


def test_la_reponse_du_moteur_est_validee():
    lu = pap.lire_reponse_moteur('```json\n{"titre": "Crêpes", "type": "recette", "etapes": ["A.", "Cuire 2 minutes."]}\n```')
    assert lu["titre"] == "Crêpes" and lu["type"] == "recette" and lu["etapes"][1]["minuteur_s"] == 120
    assert pap.lire_reponse_moteur('["Un.", "Deux."]')["type"] is None
    for mauvais in ("Voici les étapes : mélangez puis cuisez.", '{"etapes": []}', '{"etapes": "texte"}', "{pas du json"):
        with pytest.raises(ValueError):
            pap.lire_reponse_moteur(mauvais)


# --------------------------------------------------------------------------- routes : étapes fournies
def test_etat_sans_session(client):
    assert client.get("/api/pas-a-pas/etat").json() == {"actif": False}


def test_demarrer_avec_etapes_fournies_rien_ne_part(client, app):
    r = client.post("/api/pas-a-pas/demarrer", json={"sujet": "Crêpes", "type": "recette", "etapes": ETAPES_CREPES,
                                                     "parler": False})
    assert r.status_code == 200
    s = r.json()
    assert s["actif"] is True and s["index"] == 0 and s["type"] == "recette" and s["sujet"] == "Crêpes"
    assert s["source_etapes"] == "fournies" and s["local"] is True and s["avertissement"] is None
    assert [e["minuteur_s"] for e in s["etapes"]] == [None, 1800, 60]
    assert s["phrase"].startswith("Recette : Crêpes. 3 étapes. Étape 1 sur 3 : Mélangez 250 g")
    assert "commence par" in s["limite"] and "veille" in s["limite"]
    assert s["ecoute_active"] is False and "L'écoute vocale est arrêtée" in s["limite"]
    evenements = app.state.ctx.consent.events(20)
    assert not any(e["event_type"] == "external_send" for e in evenements)
    assert client.get("/api/pas-a-pas/etat").json()["id"] == s["id"]


def test_navigation_suivant_precedent_repeter(client):
    client.post("/api/pas-a-pas/demarrer", json={"type": "recette", "etapes": ETAPES_CREPES, "parler": False})
    r = client.post("/api/pas-a-pas/commande", json={"action": "precedent", "parler": False}).json()
    assert r["index"] == 0 and r["phrase"].startswith("Vous êtes à la première étape.")
    r = client.post("/api/pas-a-pas/commande", json={"action": "suivant", "parler": False}).json()
    assert r["index"] == 1
    assert r["phrase"] == "Étape 2 sur 3 : Laissez reposer la pâte 30 minutes. Dites « lance le minuteur » pour 30 minutes."
    assert client.post("/api/pas-a-pas/commande", json={"action": "repeter", "parler": False}).json()["phrase"] == r["phrase"]
    client.post("/api/pas-a-pas/commande", json={"action": "suivant", "parler": False})
    r = client.post("/api/pas-a-pas/commande", json={"action": "suivant", "parler": False}).json()
    assert r["index"] == 2 and "dernière étape" in r["phrase"]
    fin = client.post("/api/pas-a-pas/commande", json={"action": "terminer", "parler": False}).json()
    assert fin["actif"] is False and fin["phrase"] == "Pas à pas terminé."
    assert client.get("/api/pas-a-pas/etat").json() == {"actif": False}


def test_en_mode_concis_letape_est_courte(client, app):
    app.state.ctx.settings.update({"verbosite": "concis"})
    r = client.post("/api/pas-a-pas/demarrer", json={"etapes": ["Cuire 5 minutes."], "parler": False}).json()
    assert r["phrase"] == "Pas à pas : Pas à pas. 1 étape. Étape 1 : Cuire 5 minutes."


def test_refus_documentes(client):
    assert client.post("/api/pas-a-pas/commande", json={"action": "suivant"}).status_code == 409
    assert client.post("/api/pas-a-pas/demarrer", json={"type": "cuisine", "etapes": ["A"]}).status_code == 422
    assert client.post("/api/pas-a-pas/demarrer", json={"etapes": ["  ", ""]}).status_code == 422
    assert client.post("/api/pas-a-pas/demarrer", json={"sujet": ""}).status_code == 422
    client.post("/api/pas-a-pas/demarrer", json={"etapes": ETAPES_CREPES, "parler": False})
    assert client.post("/api/pas-a-pas/commande", json={"action": "danser"}).status_code == 422
    r = client.post("/api/pas-a-pas/commande", json={"action": "minuteur"})
    assert r.status_code == 422 and "ne donne pas de durée" in r.json()["detail"]
    r = client.post("/api/pas-a-pas/commande", json={"action": "minuteur", "secondes": 120, "parler": False}).json()
    assert r["phrase"] == "Minuteur lancé : 2 minutes pour l'étape 1." and r["minuteurs"][0]["duree_s"] == 120
    r = client.post("/api/pas-a-pas/commande", json={"action": "minuteur", "secondes": 120, "parler": False}).json()
    assert "tourne déjà" in r["phrase"]
    r = client.post("/api/pas-a-pas/commande", json={"action": "annuler_minuteur", "parler": False}).json()
    assert r["phrase"] == "Minuteur de l'étape 1 annulé." and r["minuteurs"] == []


def test_mode_confidentiel_refuse_et_arrete_la_session(client, app):
    client.post("/api/pas-a-pas/demarrer", json={"etapes": ETAPES_CREPES, "parler": False})
    assert client.patch("/api/settings", json={"privacy_mode": True}).status_code == 200
    for _ in range(50):
        if not app.state.ctx.pas_a_pas.actif:
            break
        client.get("/api/pas-a-pas/etat")
    assert client.get("/api/pas-a-pas/etat").json() == {"actif": False}
    r = client.post("/api/pas-a-pas/demarrer", json={"etapes": ETAPES_CREPES})
    assert r.status_code == 409 and "confidentiel" in r.json()["detail"]
    client.patch("/api/settings", json={"privacy_mode": False})


# --------------------------------------------------------------------------- routes : étapes rédigées par le moteur
def test_rediger_exige_le_consentement_texte(client, moteur):
    r = client.post("/api/pas-a-pas/demarrer", json={"sujet": "crêpes", "type": "recette"})
    assert r.status_code == 403
    detail = r.json()["detail"]
    assert detail["code"] == "consentement" and detail["data_type"] == "transcript"
    assert moteur.appels == [], "rien ne doit partir sans accord"


def test_etapes_redigees_par_le_moteur_validees_et_annoncees(client, app, moteur):
    accorder(client, "transcript")
    r = client.post("/api/pas-a-pas/demarrer", json={"sujet": "crêpes", "type": "recette", "parler": False})
    assert r.status_code == 200
    s = r.json()
    assert s["source_etapes"] == "moteur" and s["sujet"] == "crêpes" and len(s["etapes"]) == 3
    assert s["etapes"][1]["minuteur_s"] == 1800
    assert "thermomètre" in s["avertissement"] and "rédigées automatiquement" in s["phrase"]
    assert "crêpes" in moteur.appels[0]["messages"][0]["content"]
    assert "JSON" in moteur.appels[0]["system"]
    envois = [e for e in app.state.ctx.consent.events(20) if e["event_type"] == "external_send"]
    assert envois and envois[0]["data_type"] == "transcript"
    texte = json.dumps(s, ensure_ascii=False).lower()
    assert not any(nom in texte for nom in NOMS_INTERDITS)


def test_une_reparation_redigee_dit_la_consigne_de_securite_a_voix_haute(client, app, moteur):
    accorder(client, "transcript")
    app.state.ctx.settings.update({"verbosite": "concis"})
    moteur.reponse = json.dumps({"titre": "Joint de robinet", "type": "reparation",
                                 "etapes": ["Fermez l'arrivée d'eau sous l'évier.", "Démontez la poignée."]})
    s = client.post("/api/pas-a-pas/demarrer", json={"sujet": "changer un joint de robinet", "type": "reparation",
                                                     "parler": False}).json()
    assert "coupez le courant ou l'eau" in s["phrase"] and "professionnel" in s["phrase"]


def test_reponse_illisible_du_moteur(client, moteur):
    accorder(client, "transcript")
    moteur.reponse = "Bien sûr ! Mélangez tout puis faites cuire."
    r = client.post("/api/pas-a-pas/demarrer", json={"sujet": "crêpes", "type": "recette"})
    assert r.status_code == 502 and "fournissez les étapes" in r.json()["detail"]


def test_mode_local_sans_ia_locale_refuse_de_rediger_mais_lit_les_etapes(client, app, moteur):
    accorder(client, "transcript")
    app.state.ctx.settings.update({"local_only": True})
    r = client.post("/api/pas-a-pas/demarrer", json={"sujet": "crêpes", "type": "recette"})
    assert r.status_code == 409 and "100 % local" in r.json()["detail"]
    assert moteur.appels == []
    assert client.post("/api/pas-a-pas/demarrer", json={"etapes": ETAPES_CREPES, "parler": False}).status_code == 200


# --------------------------------------------------------------------------- minuteurs (horloge simulée)
def test_le_minuteur_sonne_a_lheure_pour_la_bonne_etape(app):
    service, horloge, dits = service_simule(app.state.ctx)

    async def scenario():
        await service.demarrer("Crêpes", "recette", ETAPES_CREPES)
        assert dits[-1].startswith("Recette : Crêpes.")
        await service.commande("suivant")
        r = await service.commande("minuteur")
        assert r["phrase"] == "Minuteur lancé : 30 minutes pour l'étape 2."
        await service.commande("suivant")  # on avance pendant que la pâte repose
        await horloge.avancer(1799)
        assert "Minuteur terminé pour l'étape 2." not in dits
        assert service.etat()["minuteurs"] == [{"etape": 2, "duree_s": 1800, "restant_s": 1}]
        await horloge.avancer(1)
        assert dits[-1] == "Minuteur terminé pour l'étape 2."
        assert service.etat()["minuteurs"] == [] and service.etat()["index"] == 2
        await service.terminer()

    asyncio.run(scenario())


def test_terminer_annule_les_minuteurs_qui_ne_sonnent_plus(app):
    service, horloge, dits = service_simule(app.state.ctx)

    async def scenario():
        await service.demarrer("Crêpes", "recette", ETAPES_CREPES)
        await service.commande("suivant")
        await service.commande("minuteur")
        fin = await service.terminer()
        assert fin["phrase"] == "Pas à pas terminé. 1 minuteur annulé."
        await horloge.avancer(4000)
        assert not any("Minuteur terminé" in d for d in dits)

    asyncio.run(scenario())


def test_un_minuteur_dit_a_la_voix_et_on_en_est_ou(app):
    service, horloge, dits = service_simule(app.state.ctx)

    async def scenario():
        await service.demarrer("", "autre", ["Poncez la planche."])
        phrase = await service.interception("lance un minuteur de deux minutes")
        assert phrase == "Minuteur lancé : 2 minutes pour l'étape 1."
        await horloge.avancer(30)
        ou = await service.interception("on en est où")
        assert "Étape 1 sur 1 : Poncez la planche." in ou and "1 minute 30 secondes restantes" in ou
        await horloge.avancer(90)
        assert dits[-1] == "Minuteur terminé pour l'étape 1."
        await service.terminer()

    asyncio.run(scenario())


# --------------------------------------------------------------------------- voix
def test_interception_seulement_pendant_une_session(client, app):
    ctx = app.state.ctx
    voice = ctx.voice
    assert ctx.pas_a_pas.interception("suivant") is None, "hors session, rien n'est intercepté"
    client.post("/api/pas-a-pas/demarrer", json={"type": "recette", "etapes": ETAPES_CREPES, "parler": False})
    assert ctx.pas_a_pas.interception("quelle heure est-il") is None
    assert voice._intercepter("c'est fait") == \
        "Étape 2 sur 3 : Laissez reposer la pâte 30 minutes. Dites « lance le minuteur » pour 30 minutes."
    assert voice._intercepter("répète") .startswith("Étape 2 sur 3")
    assert voice._intercepter("c'est fini") == "Pas à pas terminé."
    assert not ctx.pas_a_pas.actif


def test_demarrage_vocal_redige_par_le_moteur(client, app, moteur):
    accorder(client, "transcript")
    ctx = app.state.ctx
    assert ctx.pas_a_pas.interception_demarrage("c'est quoi un pas à pas") is None
    phrase = ctx.voice._intercepter("guide-moi pas à pas pour faire des crêpes")
    assert phrase.startswith("Recette : Crêpes. 3 étapes.") and "Étape 1 sur 3" in phrase
    assert ctx.pas_a_pas.etat()["type"] == "recette"
    assert "guide-moi pas à pas pour faire des crêpes" in moteur.appels[0]["messages"][0]["content"]


class FausseVision:
    def __init__(self):
        self.appels: list[dict] = []

    async def decrire(self, mode, source="lunettes", image=None, question=None, parler=True, memoriser=True):
        self.appels.append({"mode": mode, "source": source, "image": image, "question": question,
                            "parler": parler, "memoriser": memoriser})
        return {"ok": True, "mode": mode, "source": source, "texte": "La crêpe est dorée sur les bords.",
                "chemin": None, "duree_ms": 12, "local": False}


def test_est_ce_que_cest_bon_regarde_avec_letape_en_contexte(client, app, monkeypatch):
    ctx = app.state.ctx
    vision = FausseVision()
    monkeypatch.setattr(ctx, "accessibilite", vision)
    client.post("/api/pas-a-pas/demarrer", json={"sujet": "Crêpes", "type": "recette", "etapes": ETAPES_CREPES,
                                                 "parler": False})
    client.post("/api/pas-a-pas/commande", json={"action": "suivant", "parler": False})
    client.post("/api/pas-a-pas/commande", json={"action": "suivant", "parler": False})
    assert ctx.voice._intercepter("est-ce que c'est bon") == "D'après la photo : La crêpe est dorée sur les bords."
    appel = vision.appels[0]
    assert appel["mode"] == "scene" and appel["source"] == "lunettes"
    assert appel["memoriser"] is False and appel["parler"] is False
    assert "Faites cuire chaque crêpe 1 minute" in appel["question"] and "cuit à point" in appel["question"]
    assert len(appel["question"]) <= 500
    r = client.post("/api/pas-a-pas/commande", json={"action": "verifier", "parler": False,
                                                     "image": {"media_type": "image/jpeg", "data": "QUJD"}}).json()
    assert vision.appels[1]["source"] == "image" and r["verification"]["texte"].startswith("La crêpe")


def test_sans_vision_la_verification_le_dit(client, app, monkeypatch):
    monkeypatch.setattr(app.state.ctx, "accessibilite", None)
    client.post("/api/pas-a-pas/demarrer", json={"etapes": ETAPES_CREPES, "parler": False})
    r = client.post("/api/pas-a-pas/commande", json={"action": "verifier"})
    assert r.status_code == 409 and "vision" in r.json()["detail"]


# --------------------------------------------------------------------------- délai maximal du moteur
def test_un_moteur_muet_ne_fige_pas_la_voix_au_demarrage(client, app, moteur, monkeypatch):
    """Contre-vérification du 2026-09-14 : sans délai dans ChatService.demander_image_detail, l'écoute gelait
    90 s sur « guide-moi pas à pas… » puis envoyait la même phrase au modèle pendant que la rédaction tournait
    encore. Le délai du moteur rend une phrase courte, bien avant."""
    import time

    class MoteurMuet(FauxMoteur):
        async def stream(self, messages, system, tools=None, run_tool=None, options=None):
            await asyncio.sleep(5.0)
            yield Chunk("text", text=FauxMoteur.reponse)
            yield Chunk("done")

    accorder(client, "transcript")
    monkeypatch.setattr(chat_module, "build_connector", lambda name, settings, secrets: MoteurMuet())
    monkeypatch.setattr(chat_module, "DELAI_MOTEUR_IMAGE_S", 0.3)
    debut = time.monotonic()
    phrase = app.state.ctx.voice._intercepter("guide-moi pas à pas pour faire des crêpes")
    assert time.monotonic() - debut < 3.0, "la voix n'attend pas le moteur au-delà du délai"
    assert phrase == "Le moteur VELA n'a pas répondu. Réessaie dans un instant."
    assert not app.state.ctx.pas_a_pas.actif
