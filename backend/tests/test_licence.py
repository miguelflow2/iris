"""Activation automatique de l'abonnement : IRIS va chercher sa clé, se renouvelle, et expire proprement.

Aucun réseau réel n'est utilisé : le serveur de licences est simulé.
"""
from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import pytest

from iris.config import Settings
from iris.db import Database
from iris.events import EventHub
from iris.licence import LicenceSync
from iris.plans import PlanService, make_key


class FausseReponse:
    def __init__(self, code: int, data: dict | None = None):
        self.status_code = code
        self._data = data or {}

    def json(self) -> dict:
        return self._data

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class FauxClient:
    """Remplace httpx.Client : renvoie la réponse programmée et mémorise l'appel."""

    reponse: FausseReponse | Exception = FausseReponse(404)
    appels: list[dict] = []

    def __init__(self, *a, **k):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def post(self, url, json=None):
        """IRIS interroge d'abord en POST : le courriel voyage dans le corps, pas dans l'adresse."""
        FauxClient.appels.append({"url": url, "json": json, "methode": "POST"})
        if isinstance(FauxClient.reponse, Exception):
            raise FauxClient.reponse
        return FauxClient.reponse

    def get(self, url, params=None):
        FauxClient.appels.append({"url": url, "params": params, "methode": "GET"})
        if isinstance(FauxClient.reponse, Exception):
            raise FauxClient.reponse
        return FauxClient.reponse


@pytest.fixture()
def sync(data_dir: Path, monkeypatch) -> LicenceSync:
    import httpx

    FauxClient.appels = []
    monkeypatch.setattr(httpx, "Client", FauxClient)
    settings = Settings(data_dir)
    settings.update({"licence_server": "https://licences.test", "licence_email": "client@exemple.ca", "licence_auto": True})
    hub = EventHub()
    hub.publish = lambda type_, **data: None
    plans = PlanService(Database(data_dir / "lic.db"), settings, hub)
    return LicenceSync(settings, plans, hub)


def _demain(jours: int = 30) -> str:
    return (date.today() + timedelta(days=jours)).isoformat()


# --------------------------------------------------------------------------- activation
def test_activation_automatique(sync: LicenceSync):
    cle = make_key("pro", _demain(), "client@exemple.ca")
    FauxClient.reponse = FausseReponse(200, {"key": cle})
    r = sync.sync()
    assert r["state"] == "activé"
    assert sync.plans.plan == "pro"
    assert sync.settings.user.license_key == cle
    # le courriel du client est bien celui envoyé au serveur
    dernier = FauxClient.appels[-1]
    assert dernier["methode"] == "POST", "le courriel ne doit pas partir dans l'adresse"
    assert dernier["json"] == {"email": "client@exemple.ca"}


def test_deuxieme_verification_ne_change_rien(sync: LicenceSync):
    cle = make_key("pro", _demain(), "client@exemple.ca")
    FauxClient.reponse = FausseReponse(200, {"key": cle})
    sync.sync()
    r = sync.sync()
    assert r["state"] == "à jour" and sync.plans.plan == "pro"


def test_renouvellement_prolonge_la_date(sync: LicenceSync):
    FauxClient.reponse = FausseReponse(200, {"key": make_key("pro", _demain(3), "client@exemple.ca")})
    sync.sync()
    ancienne = sync.settings.user.plan_expires
    FauxClient.reponse = FausseReponse(200, {"key": make_key("pro", _demain(33), "client@exemple.ca")})
    assert sync.sync()["state"] == "activé"
    assert sync.settings.user.plan_expires > ancienne


# --------------------------------------------------------------------------- refus et pannes
def test_aucun_abonnement(sync: LicenceSync):
    FauxClient.reponse = FausseReponse(404)
    r = sync.sync()
    assert r["state"] == "aucun abonnement" and sync.plans.plan == "gratuit"


def test_cle_invalide_refusee(sync: LicenceSync):
    FauxClient.reponse = FausseReponse(200, {"key": "IRIS-nimportequoi-000"})
    r = sync.sync()
    assert r["state"] == "clé invalide" and sync.plans.plan == "gratuit"


def test_cle_expiree_ne_donne_pas_le_plan(sync: LicenceSync):
    FauxClient.reponse = FausseReponse(200, {"key": make_key("entreprise", _demain(-2), "client@exemple.ca")})
    r = sync.sync()
    assert r["state"] == "expiré" and sync.plans.plan == "gratuit"


def test_serveur_injoignable_conserve_le_plan(sync: LicenceSync):
    FauxClient.reponse = FausseReponse(200, {"key": make_key("pro", _demain(), "client@exemple.ca")})
    sync.sync()
    FauxClient.reponse = RuntimeError("réseau coupé")
    r = sync.sync()
    assert r["state"] == "injoignable"
    assert sync.plans.plan == "pro", "une panne réseau ne doit jamais dégrader un abonnement payé"


def test_mode_local_ne_contacte_personne(sync: LicenceSync):
    sync.settings.update({"local_only": True})
    FauxClient.appels = []
    assert sync.sync()["state"] == "mode local"
    assert FauxClient.appels == [], "le mode 100 % local ne doit produire aucun appel réseau"


def test_non_configure(data_dir: Path):
    settings = Settings(data_dir / "vide")
    hub = EventHub()
    hub.publish = lambda type_, **data: None
    s = LicenceSync(settings, PlanService(Database(data_dir / "l2.db"), settings, hub), hub)
    assert not s.configured and s.sync()["state"] == "non configuré"


def test_desactive_sauf_si_force(sync: LicenceSync):
    sync.settings.update({"licence_auto": False})
    assert sync.sync()["state"] == "désactivé"
    FauxClient.reponse = FausseReponse(200, {"key": make_key("pro", _demain(), "client@exemple.ca")})
    assert sync.sync(force=True)["state"] == "activé"


# --------------------------------------------------------------------------- expiration locale
def test_expiration_retrograde_au_gratuit(sync: LicenceSync):
    FauxClient.reponse = FausseReponse(200, {"key": make_key("pro", _demain(), "client@exemple.ca")})
    sync.sync()
    sync.settings.update({"plan_expires": _demain(-1)})
    sync.check_expiry()
    assert sync.plans.plan == "gratuit" and sync.settings.user.license_key == ""


def test_alerte_avant_echeance(sync: LicenceSync, monkeypatch):
    evenements = []
    sync.hub.publish = lambda type_, **data: evenements.append((type_, data))
    FauxClient.reponse = FausseReponse(200, {"key": make_key("pro", _demain(7), "client@exemple.ca")})
    sync.sync()
    sync.check_expiry()
    assert any(t == "plan.expiring" and d["days"] == 7 for t, d in evenements)


def test_mode_demo_nest_pas_retrograde(sync: LicenceSync):
    sync.plans.set_demo("entreprise")
    sync.settings.update({"plan_expires": _demain(-5)})
    sync.check_expiry()
    assert sync.settings.user.plan_demo, "le mode démonstration ne doit pas être coupé par une échéance"


# --------------------------------------------------------------------------- format de clé
def test_cle_avec_tiret_dans_la_charge_utile():
    """La charge utile est du base64 url-safe : elle peut contenir un « - ».
    Découper par la gauche rejetait silencieusement ces clés pourtant valides."""
    from iris.plans import make_key as mk, verify_key as vk

    cle = mk("pro", _demain(), "a~~@x.ca")
    charge = cle[len("IRIS-") : cle.rindex("-")]
    assert "-" in charge, "ce courriel doit produire un tiret dans la charge utile"
    info = vk(cle)
    assert info and info["plan"] == "pro" and not info["expired"]


def test_cle_falsifiee_refusee():
    from iris.plans import make_key as mk, verify_key as vk

    cle = mk("pro", _demain(), "client@exemple.ca")
    # signature modifiée
    assert vk(cle[:-1] + ("0" if cle[-1] != "0" else "1")) is None
    # charge utile modifiée : la signature ne correspond plus
    coupe = cle.rindex("-")
    charge = cle[len("IRIS-"):coupe]
    altere = charge[:-2] + ("aa" if charge[-2:] != "aa" else "bb")
    assert vk(f"IRIS-{altere}-{cle[coupe + 1:]}") is None
    # préfixe absent
    assert vk(cle[5:]) is None


# --------------------------------------------------------------------------- le courriel dans l'URL
# Trouve par la relecture finale du site : IRIS interrogeait le serveur de licences en GET, avec
# « ?email=... ». Un courriel est une donnee personnelle : dans une URL, il se retrouve dans les
# journaux du serveur, dans ceux de tout intermediaire traverse, et dans les en-tetes de
# provenance. La politique de confidentialite du site affirmait par ailleurs le contraire.
def test_le_courriel_voyage_dans_le_corps_pas_dans_ladresse():
    import inspect

    from iris import licence

    source = inspect.getsource(licence.LicenceSync.sync)
    envoi = source[source.index("client.post"):source.index("client.post") + 200]
    assert 'json={"email"' in envoi, "le courriel doit partir dans le corps"
    avant_post = source[:source.index("client.post")]
    assert "client.get" not in avant_post, "le POST doit etre essaye en premier"


def test_le_serveur_de_licences_accepte_les_deux_formes():
    """Le GET reste servi : les IRIS deja installees l'utilisent encore."""
    from pathlib import Path as _P

    app = _P(__file__).resolve().parents[2] / "server" / "licences" / "app.py"
    source = app.read_text(encoding="utf-8")
    assert '@app.post("/api/licence")' in source
    assert '@app.get("/api/licence")' in source


# --------------------------------------------------------------------------- aucune camera vendue en forfait
# Les lunettes VELA ONT une camera : c'est une fonction MATERIELLE, livree avec le boitier, quel
# que soit l'abonnement. Elle n'appartient donc a aucun palier logiciel. Et surtout, le
# declenchement de la photo par IRIS (trame BLE camera) N'EST PAS ENCORE PROUVE sur le vrai
# materiel — cf. lunettes_camera.py, qui refuse d'ecrire une trame non confirmee. Un forfait qui
# promettrait une fonction camera vendrait donc soit une chose deja incluse ailleurs, soit une
# capacite non demontree. Dans les deux cas c'est a proscrire : aucun palier ne mentionne la camera.
def test_aucun_forfait_ne_promet_de_camera():
    from iris.plans import PLANS

    for nom, plan in PLANS.items():
        for ligne in plan["contents"]:
            assert "caméra" not in ligne.lower() and "camera" not in ligne.lower(),                 "le forfait {} promet une camera : {}".format(nom, ligne)
