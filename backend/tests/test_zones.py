"""Zones sans mémoire (interface I, 2026-09-13) : distance de haversine, création et suppression dans
les réglages, entrée et sortie de zone -> suspension et reprise de la mémoire, événement zone.etat,
position évaluée puis oubliée, position de l'ordinateur indisponible dite en 409. Aucun GPS, aucun réseau.
"""
from __future__ import annotations

import json
import time

import pytest

from iris.memory import MemoireSuspendue
from iris.zones import RefusZone, distance_m

CLINIQUE = {"nom": "Clinique", "lat": 45.5017, "lon": -73.5673, "rayon_m": 200}
BUREAU = {"nom": "Bureau client", "lat": 46.8139, "lon": -71.2080, "rayon_m": 100}


def _publies(ctx) -> list[dict]:
    publies: list[dict] = []
    original = ctx.hub.publish

    def espion(type_, **data):
        publies.append({"type": type_, **data})
        return original(type_, **data)

    ctx.hub.publish = espion
    return publies


def test_haversine_distances_connues():
    assert distance_m(45.5017, -73.5673, 45.5017, -73.5673) == pytest.approx(0.0, abs=1e-6)
    # Montréal -> Québec : environ 233 km à vol d'oiseau
    assert distance_m(45.5017, -73.5673, 46.8139, -71.2080) == pytest.approx(233_000, rel=0.02)
    # un degré de latitude ≈ 111,2 km
    assert distance_m(0, 0, 1, 0) == pytest.approx(111_195, rel=0.001)


def test_creer_valider_et_supprimer_dans_les_reglages(app):
    zones = app.state.ctx.zones
    zone = zones.creer(**CLINIQUE)
    assert app.state.ctx.settings.user.zones_sans_memoire == [zone]
    for mauvais in ({**CLINIQUE, "nom": " "}, {**CLINIQUE, "lat": 91}, {**CLINIQUE, "lon": "abc"},
                    {**CLINIQUE, "nom": "Autre", "rayon_m": 5}):
        with pytest.raises(RefusZone):
            zones.creer(**mauvais)
    with pytest.raises(RefusZone) as doublon:
        zones.creer(**CLINIQUE)
    assert doublon.value.code == 409
    assert zones.supprimer(zone["id"]) and not zones.supprimer(zone["id"])
    assert app.state.ctx.settings.user.zones_sans_memoire == []


def test_entree_et_sortie_de_zone_suspendent_puis_reprennent_la_memoire(app):
    ctx = app.state.ctx
    publies = _publies(ctx)
    zones = ctx.zones
    clinique = zones.creer(**CLINIQUE)
    bureau = zones.creer(**BUREAU)

    etat = zones.signaler(clinique["id"], "telephone")
    assert etat["zone_active"] == {"id": clinique["id"], "nom": "Clinique"}
    assert ctx.memory.suspendue == "zone:Clinique"
    with pytest.raises(MemoireSuspendue):
        ctx.memory.add("le diagnostic du médecin")
    assert [e for e in publies if e["type"] == "zone.etat"][-1] == {"type": "zone.etat", "dans_zone": True, "zone_nom": "Clinique"}

    zones.signaler(bureau["id"], "telephone")  # d'une zone à l'autre, sans passer par « aucune »
    assert ctx.memory.raisons_suspension() == ["zone:Bureau client"]

    zones.signaler(None, "telephone")
    assert ctx.memory.suspendue is None
    assert [e for e in publies if e["type"] == "zone.etat"][-1]["dans_zone"] is False
    ctx.memory.add("souvenir hors zone")  # la mémoire écrit de nouveau


def test_deux_sources_et_suppression_dune_zone_active(app):
    ctx = app.state.ctx
    zones = ctx.zones
    clinique = zones.creer(**CLINIQUE)
    zones.signaler(clinique["id"], "telephone")
    zones.signaler(None, "pc")  # l'ordinateur resté à la maison ne lève pas la zone du téléphone
    assert ctx.memory.suspendue == "zone:Clinique"
    zones.supprimer(clinique["id"])
    assert ctx.memory.suspendue is None, "une zone supprimée ne garde pas la mémoire suspendue"
    with pytest.raises(RefusZone) as inconnue:
        zones.signaler("inexistante", "telephone")
    assert inconnue.value.code == 404
    with pytest.raises(RefusZone):
        zones.signaler(None, "montre")


def test_la_suspension_de_linvite_et_celle_de_la_zone_sont_independantes(app):
    ctx = app.state.ctx
    clinique = ctx.zones.creer(**CLINIQUE)
    ctx.memory.suspendre("invite")
    ctx.zones.signaler(clinique["id"], "telephone")
    ctx.zones.signaler(None, "telephone")
    assert ctx.memory.suspendue == "invite", "sortir d'une zone ne met pas fin au mode invité"
    ctx.memory.reprendre("invite")


def test_position_evaluee_puis_oubliee_et_precision_prudente(app, data_dir):
    ctx = app.state.ctx
    zones = ctx.zones
    clinique = zones.creer(**CLINIQUE)
    # ~150 m au nord du centre : dedans
    assert zones.evaluer_position(45.5030, -73.5673, 10)["id"] == clinique["id"]
    # ~300 m : dehors avec une bonne précision, « peut-être dedans » avec une précision de 150 m
    assert zones.evaluer_position(45.5044, -73.5673, 10) is None
    assert zones.evaluer_position(45.5044, -73.5673, 150)["id"] == clinique["id"]
    assert zones.evaluer_position(45.5100, -73.5673, 5000) is None, "la tolérance est bornée à un rayon"

    ctx.consent.log("temoin")
    zones.signaler_position(45.5030, -73.5673, 10)
    assert ctx.memory.suspendue == "zone:Clinique"
    # la position n'est écrite nulle part : ni réglages, ni registre, ni fichier du dossier de données
    for fichier in data_dir.rglob("*"):
        if fichier.is_file() and fichier.suffix in (".json", ".bak", ".txt", ".log"):
            assert "45.503" not in fichier.read_text(encoding="utf-8", errors="ignore"), fichier.name
    registre = json.dumps(ctx.consent.events(limit=50))
    assert "45.503" not in registre and "zone" not in registre


def test_routes_zones_position_et_position_pc(client, app):
    ctx = app.state.ctx
    r = client.post("/api/confiance/zones", json=CLINIQUE)
    assert r.status_code == 200
    zone = r.json()
    assert client.post("/api/confiance/zones", json={**CLINIQUE, "nom": ""}).status_code == 422
    liste = client.get("/api/confiance/zones").json()
    assert liste["zones"] == [zone] and liste["zone_active"] is None and "sortie" in liste["limite"]

    dedans = client.post("/api/confiance/position", json={"lat": 45.5030, "lon": -73.5673, "precision_m": 10}).json()
    assert dedans["dans_zone"] is True and dedans["zone_active"]["nom"] == "Clinique"
    assert "lat" not in {k for k in dedans if k != "zones"}, "la position n'est pas renvoyée"
    assert client.post("/api/confiance/zone", json={"zone_id": None, "source": "telephone"}).json()["zone_active"] is None
    assert client.post("/api/confiance/zone", json={"zone_id": "nope", "source": "telephone"}).status_code == 404

    ctx.zones.lire_position_pc = lambda: None
    refus = client.get("/api/confiance/position/pc")
    assert refus.status_code == 409 and "position" in refus.json()["detail"].lower()
    ctx.zones.lire_position_pc = lambda: {"lat": 45.0, "lon": -73.0, "precision_m": 50.0}
    assert client.get("/api/confiance/position/pc").json() == {"lat": 45.0, "lon": -73.0, "precision_m": 50.0}
    ctx.settings.update({"privacy_mode": True})
    assert client.get("/api/confiance/position/pc").status_code == 409

    assert client.delete(f"/api/confiance/zones/{zone['id']}").status_code == 200
    assert client.delete(f"/api/confiance/zones/{zone['id']}").status_code == 404


def test_zones_modifiees_par_patch_des_reglages_sont_reconciliees(client, app):
    ctx = app.state.ctx
    zone = client.post("/api/confiance/zones", json=CLINIQUE).json()
    client.post("/api/confiance/zone", json={"zone_id": zone["id"], "source": "telephone"})
    assert ctx.memory.suspendue == "zone:Clinique"
    # Zones vidées par un autre chemin que nos routes : le suivi de settings.updated doit lever la suspension.
    client.patch("/api/settings", json={"zones_sans_memoire": []})
    limite = time.monotonic() + 3
    while ctx.memory.suspendue is not None and time.monotonic() < limite:
        time.sleep(0.02)
    assert ctx.memory.suspendue is None
