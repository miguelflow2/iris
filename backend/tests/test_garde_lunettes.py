"""Garde « lunettes d'abord » sur les routes qui captent ou agissent (règle commerciale du 2026-09-13).

VELA vend des lunettes ; IRIS est ce qu'elles contiennent. Chaque route qui voit, écoute, enregistre ou
fait agir IRIS doit refuser en 428 {code: "lunettes_requises"} quand les lunettes manquent, AVANT tout
travail — et laisser passer dès que l'app téléphone les atteste. À l'inverse, consulter, exporter,
corriger et effacer ses données, la confidentialité et la sécurité (mode invité, zones, verrouillage)
restent permis sans lunettes : c'est la Loi 25, et le verrouillage sert justement quand elles sont perdues.

Les corps envoyés « avec lunettes » sont choisis pour que le service refuse vite pour une AUTRE raison
(mode inconnu, consentement absent, modèle absent…) : le test prouve que la garde laisse passer, sans
ouvrir le micro, la caméra, l'écran ni le réseau.
"""
from __future__ import annotations

import asyncio
import time

import pytest
from fastapi.testclient import TestClient

from iris.lunettes_presence import MESSAGE_LUNETTES_AILLEURS, MESSAGE_REQUISES, URL_ACHAT

# (méthode, chemin, corps JSON) — la liste de la mission de l'intégrateur, route par route.
ROUTES_GARDEES = [
    ("POST", "/api/accessibilite/decrire", {"mode": "inconnu", "source": "image"}),
    ("POST", "/api/accessibilite/ou-est", {"question": ""}),
    ("POST", "/api/ecoute/sous-titres/demarrer", None),
    ("POST", "/api/ecoute/enregistrement/demarrer", None),
    ("POST", "/api/ecoute/resume", {"lignes": []}),
    ("POST", "/api/cours/demarrer", {"titre": "Essai", "matiere": None}),
    ("POST", "/api/cours/importer", {"titre": "Essai", "nom_fichier": "x.wav", "data": "pas du base64 !"}),
    ("POST", "/api/cours/inconnu/generer", {"quoi": "fiches"}),
    ("POST", "/api/alertes/activer", None),
    ("POST", "/api/ecoute/assistee/demarrer", {}),
    ("POST", "/api/lunettes/bouton/apprendre", {"secondes": 2}),
    ("POST", "/api/album/bd", {"nom": "inexistant.jpg"}),
    ("POST", "/api/traduction/ecran", {"langue_cible": "zz-invalide"}),
    ("POST", "/api/interprete/demarrer", {"langue_autre": "xx"}),
    ("POST", "/api/interprete/texte", {"qui": "moi", "texte": "", "langue": "en"}),
    ("POST", "/api/resume/jour/parler", {"date": "pas-une-date"}),
    ("POST", "/api/rappels-contexte", {"personne": "", "texte": ""}),
    ("POST", "/api/recus/analyser", {"source": "inconnue", "image": None}),
    ("POST", "/api/pas-a-pas/demarrer", {"sujet": "Essai", "type": "inconnu", "etapes": ["a"], "parler": False}),
    ("POST", "/api/pas-a-pas/commande", {"action": "suivant", "parler": False}),
    ("POST", "/api/entrainement/demarrer", {"exercice": "squats", "series_cibles": 999, "parler": False}),
    ("POST", "/api/entrainement/commande", {"action": "serie", "parler": False}),
    ("POST", "/api/achats/comparer", {"source": "inconnue", "image": None, "requete": None}),
    ("POST", "/api/confiance/voix/echantillon", {"secondes": 1}),
    ("POST", "/api/confiance/voix/tester", {"secondes": 1}),
    ("POST", "/api/partage/demarrer", {"source": "inconnue"}),
    ("POST", "/api/tasks", {"title": "Essai", "instructions": ""}),
    ("POST", "/api/watches", {"name": "Essai", "url": "pas-une-adresse", "criteria": "prix"}),
    ("POST", "/api/routines/inconnue/run", None),
    ("POST", "/api/memory/summarize-day", {"day": "pas-une-date"}),
    ("POST", "/api/glasses/photo", {"reconnaissance": False}),
    ("POST", "/api/traduction/demarrer", {"langue": "xx"}),
]

# Routes qui ouvrent le micro, l'écran ou la caméra de l'ordinateur (constat du 2026-09-14) : des lunettes
# attestées par le téléphone seulement sont dehors, ces routes refusent alors en 409 et le disent.
ROUTES_CAPTURE_PC = {
    "/api/ecoute/sous-titres/demarrer", "/api/ecoute/enregistrement/demarrer", "/api/cours/demarrer",
    "/api/alertes/activer", "/api/ecoute/assistee/demarrer", "/api/lunettes/bouton/apprendre",
    "/api/traduction/ecran", "/api/confiance/voix/echantillon", "/api/confiance/voix/tester",
    "/api/partage/demarrer", "/api/glasses/photo", "/api/traduction/demarrer",
}
NOM_LUNETTES = "VELA K900"

# Consultation, export, correction, effacement, confidentialité, sécurité, réglages : jamais de 428.
ROUTES_LIBRES = [
    ("GET", "/api/lunettes/presence", None),
    ("GET", "/api/settings", None),
    ("GET", "/api/memory", None),
    # « Où ai-je posé » exige les lunettes (fonction qui agit) ; chercher soi-même dans ses données, non.
    ("GET", "/api/memory?q=cles", None),
    ("GET", "/api/journal?q=cles", None),
    ("DELETE", "/api/memory/plage?debut=2020-01-01&fin=2020-01-02", None),
    ("GET", "/api/journal", None),
    ("DELETE", "/api/journal?tout=true", None),
    ("GET", "/api/ecoute/etat", None),
    ("GET", "/api/ecoute/transcription", None),
    ("POST", "/api/ecoute/sous-titres/arreter", None),
    ("GET", "/api/cours", None),
    ("DELETE", "/api/cours/inconnu", None),
    ("GET", "/api/album", None),
    ("DELETE", "/api/album/inexistant.jpg", None),
    ("GET", "/api/recus", None),
    ("GET", "/api/recus/export?format=csv", None),
    ("DELETE", "/api/recus/inconnu", None),
    ("GET", "/api/rappels-contexte", None),
    ("DELETE", "/api/rappels-contexte/inconnu", None),
    ("GET", "/api/entrainement/seances", None),
    ("POST", "/api/entrainement/commande", {"action": "terminer", "parler": False}),
    ("POST", "/api/pas-a-pas/commande", {"action": "terminer", "parler": False}),
    ("GET", "/api/alertes", None),
    ("POST", "/api/alertes/desactiver", None),
    ("POST", "/api/alertes/tester", {"type": "klaxon"}),
    ("POST", "/api/ecoute/assistee/arreter", None),
    ("POST", "/api/interprete/arreter", None),
    ("GET", "/api/interprete/etat", None),
    ("POST", "/api/partage/arreter", None),
    ("GET", "/api/partage/etat", None),
    ("GET", "/api/confiance/voix", None),
    ("POST", "/api/confiance/voix/consentement", {"accepte": False}),
    ("DELETE", "/api/confiance/voix", None),
    ("GET", "/api/confiance/zones", None),
    ("POST", "/api/confiance/zones", {"nom": "Maison", "lat": 45.5, "lon": -73.6, "rayon_m": 100}),
    ("GET", "/api/confiance/invite", None),
    ("POST", "/api/confiance/invite/activer", {"minutes": 5}),
    ("POST", "/api/confiance/invite/desactiver", None),
    ("GET", "/api/confiance/verrou/etat", None),
    ("DELETE", "/api/lunettes/bouton", None),
    ("GET", "/api/lunettes/bouton", None),
]


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    from iris.main import create_app

    app = create_app(data_dir=tmp_path_factory.mktemp("garde"), token="test-token", use_keyring=False, enable_tts=False)
    # Aucune écoute au démarrage : ce fichier ne doit jamais ouvrir le micro.
    # Des lunettes déjà connectées une fois à cet ordinateur (nom retenu) : sans elles, aucune attestation.
    app.state.ctx.settings.update({"voice_autostart": False, "require_glasses": True, "demo_sans_lunettes": False,
                                   "glasses": {"name": NOM_LUNETTES, "address": "AA:BB:CC:DD:EE:FF", "auto_connect": False}})
    with TestClient(app, headers={"Authorization": "Bearer test-token"}, raise_server_exceptions=False) as c:
        yield c
    app.state.ctx.close()


@pytest.fixture()
def sans_lunettes(client):
    client.delete("/api/lunettes/attestation")
    presence = client.get("/api/lunettes/presence").json()
    assert presence["presentes"] is False, presence
    return client


def _appel(client, methode, chemin, corps):
    return client.request(methode, chemin, json=corps) if corps is not None else client.request(methode, chemin)


@pytest.mark.parametrize("methode,chemin,corps", ROUTES_GARDEES, ids=[f"{m} {c}" for m, c, _ in ROUTES_GARDEES])
def test_route_qui_capte_ou_agit_exige_les_lunettes(sans_lunettes, methode, chemin, corps, monkeypatch):
    r = _appel(sans_lunettes, methode, chemin, corps)
    assert r.status_code == 428, (r.status_code, r.text)
    detail = r.json()["detail"]
    assert detail["code"] == "lunettes_requises"
    assert detail["message"] == MESSAGE_REQUISES
    assert detail["acheter_url"] == URL_ACHAT
    assert detail["fonction"]
    # Le refus ne trahit jamais l'accès propriétaire caché.
    assert "demo" not in r.text.lower() and "démonstration" not in r.text.lower()

    # Les lunettes attestées par l'app téléphone : la garde laisse passer (le service décide du reste), sauf pour
    # ce qui ouvrirait le micro, l'écran ou la caméra de l'ordinateur resté à la maison.
    att = sans_lunettes.post("/api/lunettes/attestation",
                             json={"nom": NOM_LUNETTES, "identifiant": "telephone-1", "source": "telephone"})
    assert att.status_code == 200 and att.json()["presentes"] is True
    try:
        r2 = _appel(sans_lunettes, methode, chemin, corps)
        assert r2.status_code != 428, (r2.status_code, r2.text)
        if chemin in ROUTES_CAPTURE_PC:
            assert r2.status_code == 409 and r2.json()["detail"] == MESSAGE_LUNETTES_AILLEURS, (r2.status_code, r2.text)
    finally:
        sans_lunettes.delete("/api/lunettes/attestation")
    if chemin in ROUTES_CAPTURE_PC:
        # Les lunettes vues par l'ordinateur lui-même : la garde laisse passer.
        monkeypatch.setattr(sans_lunettes.app.state.ctx.voice, "lunettes_presentes", lambda: True)
        r3 = _appel(sans_lunettes, methode, chemin, corps)
        assert r3.status_code != 428 and not (r3.status_code == 409 and r3.text.find("connectées à ton téléphone") >= 0),             (r3.status_code, r3.text)


@pytest.mark.parametrize("methode,chemin,corps", ROUTES_LIBRES, ids=[f"{m} {c}" for m, c, _ in ROUTES_LIBRES])
def test_consulter_effacer_et_securite_restent_permis_sans_lunettes(sans_lunettes, methode, chemin, corps):
    r = _appel(sans_lunettes, methode, chemin, corps)
    assert r.status_code != 428, (r.status_code, r.text)
    assert r.status_code < 500, (r.status_code, r.text)


def test_la_description_refuse_aussi_quand_on_lappelle_sans_route(sans_lunettes):
    """Le bouton, le pas à pas, les reçus, les prix et les outils appellent le service directement."""
    from iris.accessibilite import RefusVision

    service = sans_lunettes.app.state.ctx.accessibilite
    with pytest.raises(RefusVision) as refus:
        asyncio.run(service.decrire("lecture", "image", image=None, parler=False))
    assert refus.value.status_code == 428
    assert refus.value.detail["code"] == "lunettes_requises"
    assert refus.value.phrase == MESSAGE_REQUISES


def test_les_alertes_activees_par_les_reglages_attendent_les_lunettes_et_le_disent(sans_lunettes):
    ctx = sans_lunettes.app.state.ctx
    r = sans_lunettes.patch("/api/settings", json={"alertes_actives": True})
    assert r.status_code == 200
    try:
        for _ in range(100):
            if ctx.alertes.raison == MESSAGE_REQUISES:
                break
            time.sleep(0.05)
        assert ctx.alertes.raison == MESSAGE_REQUISES
        assert ctx.alertes.actif is False
    finally:
        sans_lunettes.patch("/api/settings", json={"alertes_actives": False})


def test_loutil_ou_est_objet_du_chat_exige_aussi_les_lunettes(sans_lunettes):
    """La route ou-est est gardée ; l'outil du modèle ne doit pas être une porte dérobée."""
    from iris.tools import ToolContext, make_tool_runner

    ctx = sans_lunettes.app.state.ctx
    outils = make_tool_runner(ToolContext(
        settings=ctx.settings, consent=ctx.consent, capture=ctx.capture, memory=ctx.memory, agent="test",
        confirm=lambda titre, detail: True, accessibilite=ctx.accessibilite, app=ctx,
    ))
    r = sans_lunettes.portal.call(outils, "ou_est_objet", {"question": "où sont mes clés ?"})
    assert MESSAGE_REQUISES in str(r)
