"""Vision partagée en direct, côté service (interface J, chantier du 2026-09-13).

Tout est synthétique : faux relais (mêmes méthodes que partage.ClientRelais), fausse capture d'écran,
fausse caméra des lunettes, images générées par Pillow. Aucun réseau, aucun Bluetooth. Un dernier test
branche le service sur le VRAI module du relais (serveur/partage_vision.py), joint par son client de
test : il prouve que les deux côtés parlent le même protocole.

Ce qui est protégé ici, parce qu'une personne malvoyante s'y fie et qu'un écran ou une caméra ne doit
jamais partir chez quelqu'un par erreur :
- rien ne démarre sans consentement, en mode confidentiel ou en mode 100 % local ; et un partage en
  cours s'arrête dès que l'un d'eux change ;
- le refus de la caméra des lunettes remonte mot pour mot, AVANT qu'un lien existe sur le relais ;
- le témoin de capture s'allume pendant le partage et s'éteint après ;
- les photos des lunettes ne restent pas sur le disque ; le jeton émetteur ne sort que vers le téléphone ;
- les messages du proche sont lus à voix haute (sur l'ordinateur, pas quand le téléphone émet) ;
- la fin décidée par le relais (expiration) est dite, et la session perdue n'est pas réessayée en boucle.
"""
from __future__ import annotations

import asyncio
import io
import json
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlsplit

import pytest

import iris.partage as partage
from iris.lunettes_camera import CameraIndisponible, ProtocoleNonConfirme, ResultatPhoto
from iris.partage import ErreurRelais

NOMS_INTERDITS = ("claude", "anthropic", "openai", "gpt", "gemini", "google", "elevenlabs", "vosk", "piper",
                  "twilio", "openrouter")
JETON_APPAREIL = "jeton-appareil-test"
JETON_EMETTEUR = "jeton-emetteur-secret"


# --------------------------------------------------------------------------- une seule application
# Créer l'application et son cycle de vie coûte près de deux secondes : une instance pour le module,
# remise à zéro entre chaque test (réglages, consentements, faux relais, caméra, témoins).
@pytest.fixture(scope="module")
def _application(tmp_path_factory):
    from fastapi.testclient import TestClient

    from iris.main import create_app

    dossier = tmp_path_factory.mktemp("iris-partage")
    application = create_app(data_dir=dossier, token="test-token", use_keyring=False, enable_tts=False)
    with TestClient(application, headers={"Authorization": "Bearer test-token"}) as c:
        yield application, c
    application.state.ctx.close()


def jpeg(couleur=(120, 160, 200), taille=(320, 240)) -> bytes:
    from PIL import Image

    tampon = io.BytesIO()
    Image.new("RGB", taille, couleur).save(tampon, format="JPEG", quality=85)
    return tampon.getvalue()


class FausseConnexion:
    """Une connexion WebSocket simulée : répond « pret » au hello, garde ce que le service envoie."""

    def __init__(self, relais: "FauxRelais", url: str):
        self.relais = relais
        self.url = url
        self.boucle = asyncio.get_running_loop()
        self.file: asyncio.Queue = asyncio.Queue()
        self.textes: list[dict] = []
        self.images: list[bytes] = []
        self.fermee = False
        self.code_fermeture: int | None = None

    async def envoyer_texte(self, texte: str) -> None:
        if self.fermee:
            raise ConnectionError("fermée")
        message = json.loads(texte)
        self.textes.append(message)
        if message.get("type") == "hello":
            self.relais.hellos.append(message)
            if self.relais.session_inconnue:
                self.code_fermeture = 4004
                await self.file.put(json.dumps({"type": "refus", "raison": "inconnu", "message": "inconnu"}))
                await self.file.put(None)
            else:
                await self.file.put(json.dumps({"type": "pret", "role": message.get("role"), "code": "ABCDEFGH",
                                                "expire_a": "2026-09-13T20:30:00+00:00", "expire_dans_s": 1800,
                                                "spectateurs": 0}))
        elif message.get("type") == "fin":
            self.relais.fins += 1

    async def envoyer_octets(self, donnees: bytes) -> None:
        if self.fermee:
            raise ConnectionError("fermée")
        self.images.append(donnees)
        self.relais.images.append(donnees)

    async def recevoir(self):
        return await self.file.get()

    async def fermer(self) -> None:
        if not self.fermee:
            self.fermee = True
            self.file.put_nowait(None)

    # Depuis le fil du test (le service tourne dans la boucle du client de test).
    def pousser(self, message: dict) -> None:
        self.boucle.call_soon_threadsafe(self.file.put_nowait, json.dumps(message))

    def couper(self, code: int = 1006) -> None:
        def _couper():
            self.code_fermeture = code
            self.fermee = True
            self.file.put_nowait(None)

        self.boucle.call_soon_threadsafe(_couper)


class FauxRelais:
    def __init__(self):
        self.creations: list[tuple[str, str]] = []
        self.connexions: list[FausseConnexion] = []
        self.hellos: list[dict] = []
        self.images: list[bytes] = []
        self.fins = 0
        self.fermetures_http = 0
        self.renouvellements = 0
        self.jetons_demandes: list[tuple[str, str]] = []
        self.erreur_creation: Exception | None = None
        self.session_inconnue = False
        self.refuser_premier_jeton = False

    async def obtenir_jeton(self, base: str, courriel: str, machine: str) -> str:
        self.jetons_demandes.append((base, courriel))
        return "jeton-neuf"

    async def creer(self, base: str, jeton: str) -> dict:
        self.creations.append((base, jeton))
        if self.refuser_premier_jeton and len(self.creations) == 1:
            raise ErreurRelais(401, "Jeton d'appareil invalide ou expiré.")
        if self.erreur_creation is not None:
            raise self.erreur_creation
        return {"code": "ABCDEFGH", "jeton_emetteur": JETON_EMETTEUR, "expire_a": "2026-09-13T20:30:00+00:00",
                "expire_dans_s": 1800, "url_spectateur": f"{base}/voir/ABCDEFGH",
                "ws_emetteur": "wss://relais.velaglass.ca/partage/emetteur"}

    async def renouveler(self, base: str, jeton: str) -> dict:
        self.renouvellements += 1
        return {"expire_a": "2026-09-13T21:00:00+00:00", "expire_dans_s": 1800}

    async def fermer(self, base: str, jeton: str) -> None:
        self.fermetures_http += 1

    async def connecter(self, url: str) -> FausseConnexion:
        cx = FausseConnexion(self, url)
        self.connexions.append(cx)
        return cx


class FausseCamera:
    """Photo « prise » en écrivant un vrai JPEG sur le disque, comme le module caméra."""

    def __init__(self, ctx, dossier: Path, connectees: bool = True, erreur: Exception | None = None,
                 exploration: bool = True):
        self.ctx = ctx
        self.glasses = SimpleNamespace(connected=connectees)
        self.dossier = dossier
        self.erreur = erreur
        self.exploration = exploration
        self.appels = 0
        self.chemins: list[Path] = []
        self.verrou_tenu: list[bool] = []

    def _exploration_autorisee(self) -> bool:
        return self.exploration

    async def prendre_photo(self, reconnaissance: bool = False):
        self.appels += 1
        self.verrou_tenu.append(self.ctx.accessibilite._verrou_camera.locked())
        if self.erreur is not None:
            raise self.erreur
        await asyncio.sleep(0.05)
        chemin = self.dossier / f"lunettes-test-{self.appels}.jpg"
        chemin.write_bytes(jpeg((30, 60 + self.appels, 90), (2400, 1800)))
        self.chemins.append(chemin)
        return ResultatPhoto(ok=True, chemin=str(chemin), octets=chemin.stat().st_size, constat="Photo reçue.")


@pytest.fixture()
def app(_application, monkeypatch):
    application, client = _application
    ctx = application.state.ctx
    monkeypatch.setattr(partage, "SURVEILLANCE_S", 0.05)
    relais = FauxRelais()
    ctx.partage.client_relais = relais
    ctx.partage.capture_ecran = lambda: jpeg()
    ctx.partage.fabrique_camera = ctx.partage._camera_par_defaut
    ctx.secrets.set_api_key("vela", JETON_APPAREIL)
    paroles: list[str] = []
    evenements: list[dict] = []
    publier = ctx.hub.publish

    def espion(type_, **donnees):
        evenements.append({"type": type_, **donnees})
        return publier(type_, **donnees)

    monkeypatch.setattr(ctx.tts, "speak", lambda texte, force=False: paroles.append(texte) or True)
    monkeypatch.setattr(ctx.hub, "publish", espion)
    application.state.test = SimpleNamespace(relais=relais, paroles=paroles, evenements=evenements, client=client)
    yield application
    client.post("/api/partage/arreter")
    ctx.settings.update({"local_only": False, "privacy_mode": False, "annonce_capture": True,
                         "relay_server": "https://relais.velaglass.ca"})
    for type_donnee in ("image", "screen"):
        ctx.consent.set(type_donnee, False)
    ctx.capture.set(camera=False, screen=False)


@pytest.fixture()
def client(app):
    return app.state.test.client


@pytest.fixture()
def ctx(app):
    return app.state.ctx


@pytest.fixture()
def relais(app) -> FauxRelais:
    return app.state.test.relais


def attendre(condition, delai: float = 5.0, message: str = "condition non atteinte") -> None:
    fin = time.monotonic() + delai
    while time.monotonic() < fin:
        if condition():
            return
        time.sleep(0.02)
    raise AssertionError(message)


def dans_la_boucle(ctx, coroutine, delai: float = 10.0):
    return asyncio.run_coroutine_threadsafe(coroutine, ctx.voice.loop).result(delai)


# --------------------------------------------------------------------------- refus avant tout envoi
def test_sans_consentement_rien_ne_part(client, relais):
    r = client.post("/api/partage/demarrer", json={"source": "ecran"})
    assert r.status_code == 403
    detail = r.json()["detail"]
    assert detail["code"] == "consentement" and detail["data_type"] == "screen" and detail["label"]
    assert "Confidentialité" in detail["message"]
    r = client.post("/api/partage/demarrer", json={"source": "lunettes"})
    assert r.status_code == 403 and r.json()["detail"]["data_type"] == "image"
    assert relais.creations == [] and relais.images == []


def test_mode_confidentiel_local_seulement_et_sans_relais_refusent(client, ctx, relais):
    ctx.consent.set("screen", True)
    ctx.settings.update({"privacy_mode": True})
    r = client.post("/api/partage/demarrer", json={"source": "ecran"})
    assert r.status_code == 409 and "confidentiel" in r.json()["detail"]
    ctx.settings.update({"privacy_mode": False, "local_only": True})
    r = client.post("/api/partage/demarrer", json={"source": "ecran"})
    assert r.status_code == 409 and "100 % local" in r.json()["detail"]
    ctx.settings.update({"local_only": False, "relay_server": ""})
    r = client.post("/api/partage/demarrer", json={"source": "ecran"})
    assert r.status_code == 409 and "relais" in r.json()["detail"]
    assert client.post("/api/partage/demarrer", json={"source": "video"}).status_code == 422
    assert relais.creations == []
    assert ctx.capture.snapshot()["screen"] is False


def test_relais_injoignable_message_neutre_et_temoin_eteint(client, ctx, relais):
    ctx.consent.set("screen", True)
    relais.erreur_creation = ErreurRelais(None, "ConnectError")
    r = client.post("/api/partage/demarrer", json={"source": "ecran"})
    assert r.status_code == 502
    assert r.json()["detail"] == partage.RELAIS_INJOIGNABLE
    assert ctx.capture.snapshot()["screen"] is False
    assert client.get("/api/partage/etat").json()["actif"] is False
    relais.erreur_creation = ErreurRelais(429, "Trop de partages créés en peu de temps. Réessayez dans 3 minutes.")
    r = client.post("/api/partage/demarrer", json={"source": "ecran"})
    assert r.status_code == 429 and "Réessayez dans 3 minutes" in r.json()["detail"]


def test_jeton_d_appareil_obtenu_ou_renouvele_aupres_du_relais(client, ctx, relais):
    ctx.consent.set("screen", True)
    ctx.secrets.delete_api_key("vela")
    assert client.post("/api/partage/demarrer", json={"source": "ecran"}).status_code == 200
    assert relais.jetons_demandes and relais.creations[0][1] == "jeton-neuf"
    assert ctx.secrets.get_api_key("vela") == "jeton-neuf"
    client.post("/api/partage/arreter")
    # Un jeton refusé (expiré) est redemandé une fois, puis la création réussit.
    ctx.secrets.set_api_key("vela", JETON_APPAREIL)
    relais.creations.clear()
    relais.refuser_premier_jeton = True
    assert client.post("/api/partage/demarrer", json={"source": "ecran"}).status_code == 200
    assert [j for _b, j in relais.creations] == [JETON_APPAREIL, "jeton-neuf"]


# --------------------------------------------------------------------------- écran
def test_partage_d_ecran_envoie_mesure_et_s_arrete_proprement(client, ctx, relais, app):
    ctx.consent.set("screen", True)
    r = client.post("/api/partage/demarrer", json={"source": "ecran", "intervalle_s": 0.01})
    assert r.status_code == 200, r.text
    corps = r.json()
    assert corps["code"] == "ABCDEFGH" and corps["url_spectateur"].endswith("/voir/ABCDEFGH")
    assert corps["source"] == "ecran" and corps["expire_a"]
    # Le jeton émetteur ne sort pas vers l'écran du PC ; l'intervalle est borné à 5 images par seconde.
    assert corps["jeton_emetteur"] is None and corps["ws_emetteur"] is None
    assert corps["intervalle_s"] == partage.INTERVALLE_ECRAN_MIN_S
    assert "notifications" in corps["note"] and corps["limites"]
    # Le jeton émetteur passe dans le premier message, jamais dans l'adresse.
    hello = relais.hellos[0]
    assert hello == {"type": "hello", "jeton": JETON_EMETTEUR, "role": "emetteur", "source": "ecran"}
    assert JETON_EMETTEUR not in relais.connexions[0].url
    assert relais.connexions[0].url == "wss://relais.velaglass.ca/partage/emetteur"
    attendre(lambda: len(relais.images) >= 4, message="images de l'écran non envoyées")
    assert all(i.startswith(b"\xff\xd8\xff") and len(i) <= 300_000 for i in relais.images)
    assert ctx.capture.snapshot()["screen"] is True

    etat = client.get("/api/partage/etat").json()
    assert etat["actif"] is True and etat["source"] == "ecran" and etat["code"] == "ABCDEFGH"
    assert etat["images_envoyees"] >= 4 and etat["fps_reel"] > 0
    assert etat["fps_reel"] <= 5.5  # borne de 5 images par seconde, mesurée
    assert "mesuré" in etat["cadence_texte"]
    assert "jeton_emetteur" not in etat
    assert ctx.partage.derniere_image() is not None

    arret = client.post("/api/partage/arreter").json()
    assert arret["actif"] is False and arret["raison"] == partage.ARRETE
    assert relais.fins == 1 and relais.connexions[0].fermee
    assert ctx.capture.snapshot()["screen"] is False
    envoyees = len(relais.images)
    time.sleep(0.3)
    assert len(relais.images) == envoyees  # plus rien ne part après l'arrêt
    assert ctx.partage.derniere_image() is None
    registre = [e["event_type"] for e in ctx.consent.events(20)]
    assert "partage_vision_demarre" in registre and "partage_vision_arrete" in registre
    for e in ctx.consent.events(20):
        assert "ABCDEFGH" not in (e["detail"] or "") and JETON_EMETTEUR not in (e["detail"] or "")
    types = [e["type"] for e in app.state.test.evenements]
    assert "partage.etat" in types
    assert all(JETON_EMETTEUR not in json.dumps(e, default=str) for e in app.state.test.evenements)


def test_deja_actif_refuse(client, ctx):
    ctx.consent.set("screen", True)
    assert client.post("/api/partage/demarrer", json={"source": "ecran"}).status_code == 200
    r = client.post("/api/partage/demarrer", json={"source": "ecran"})
    assert r.status_code == 409 and r.json()["detail"] == partage.DEJA_ACTIF


def test_mode_confidentiel_ou_consentement_retire_arrete_le_partage(client, ctx, relais, app):
    ctx.consent.set("screen", True)
    assert client.post("/api/partage/demarrer", json={"source": "ecran", "intervalle_s": 0.2}).status_code == 200
    attendre(lambda: len(relais.images) >= 1)
    assert client.patch("/api/settings", json={"privacy_mode": True}).status_code == 200
    attendre(lambda: not ctx.partage.actif, message="le mode confidentiel n'a pas arrêté le partage")
    etat = client.get("/api/partage/etat").json()
    assert etat["actif"] is False and etat["raison"] == partage.CONFIDENTIEL_ARRET
    assert relais.fins == 1
    assert partage.CONFIDENTIEL_ARRET not in app.state.test.paroles  # en mode confidentiel, IRIS se tait
    envoyees = len(relais.images)
    time.sleep(0.4)
    assert len(relais.images) == envoyees

    client.patch("/api/settings", json={"privacy_mode": False})
    assert client.post("/api/partage/demarrer", json={"source": "ecran"}).status_code == 200
    ctx.consent.set("screen", False)
    attendre(lambda: not ctx.partage.actif, message="le retrait du consentement n'a pas arrêté le partage")
    assert "Consentement" in client.get("/api/partage/etat").json()["raison"]


def test_verrouillage_a_distance_arrete_le_partage(client, ctx, relais):
    ctx.consent.set("screen", True)
    assert client.post("/api/partage/demarrer", json={"source": "ecran"}).status_code == 200
    verrou = getattr(ctx, "verrou", None)
    ancien = getattr(verrou, "verrouille", False)
    if verrou is None:
        ctx.verrou = SimpleNamespace(verrouille=True)
    else:
        verrou.verrouille = True
    try:
        attendre(lambda: not ctx.partage.actif, message="le verrouillage n'a pas arrêté le partage")
        assert ctx.partage.etat()["raison"] == partage.VERROU_ARRET
    finally:
        if verrou is None:
            del ctx.verrou
        else:
            verrou.verrouille = ancien


# --------------------------------------------------------------------------- messages et fin
def test_message_du_proche_lu_a_voix_haute_et_publie(client, ctx, relais, app):
    ctx.consent.set("screen", True)
    assert client.post("/api/partage/demarrer", json={"source": "ecran"}).status_code == 200
    cx = relais.connexions[0]
    cx.pousser({"type": "spectateurs", "nombre": 1})
    cx.pousser({"type": "message", "texte": "  Tourne\x00 à gauche,\nla porte est là  ", "ts": "2026-09-13T20:01:00+00:00"})
    paroles = app.state.test.paroles
    attendre(lambda: any(p.startswith("Message de votre proche") for p in paroles))
    assert "Message de votre proche : Tourne à gauche, la porte est là" in paroles
    assert "Une personne regarde maintenant votre partage." in paroles
    evenement = next(e for e in app.state.test.evenements if e["type"] == "partage.message")
    assert evenement["texte"] == "Tourne à gauche, la porte est là" and evenement["lu_a_voix_haute"] is True
    etat = client.get("/api/partage/etat").json()
    assert etat["spectateurs"] == 1 and etat["messages"][0]["texte"] == "Tourne à gauche, la porte est là"
    client.post("/api/partage/arreter")
    assert client.get("/api/partage/etat").json()["messages"] == []  # rien n'est gardé après l'arrêt


def test_fin_decidee_par_le_relais_est_dite(client, ctx, relais, app):
    ctx.consent.set("screen", True)
    assert client.post("/api/partage/demarrer", json={"source": "ecran"}).status_code == 200
    relais.connexions[0].pousser({"type": "fin", "raison": "expiree", "message": "Le partage a expiré."})
    attendre(lambda: not ctx.partage.actif)
    assert ctx.partage.etat()["raison"] == partage.EXPIRE
    attendre(lambda: partage.EXPIRE in app.state.test.paroles)
    assert ctx.capture.snapshot()["screen"] is False
    assert relais.fins == 0  # le relais a déjà fermé : on ne lui renvoie pas « fin »


def test_coupure_reseau_reconnexion_puis_session_perdue(client, ctx, relais, monkeypatch):
    monkeypatch.setattr(partage, "ATTENTE_RECONNEXION_MAX_S", 0.05)
    ctx.consent.set("screen", True)
    assert client.post("/api/partage/demarrer", json={"source": "ecran", "intervalle_s": 0.2}).status_code == 200
    relais.connexions[0].couper(1006)
    attendre(lambda: len(relais.hellos) >= 2, message="pas de reconnexion après une coupure")
    attendre(lambda: ctx.partage.etat()["emetteur_connecte"])
    # Le relais a redémarré : la session n'existe plus, inutile de réessayer en boucle.
    relais.session_inconnue = True
    relais.connexions[-1].couper(1006)
    attendre(lambda: not ctx.partage.actif, message="session perdue non détectée")
    assert ctx.partage.etat()["raison"] == partage.SESSION_PERDUE
    assert len(relais.hellos) == 3


def test_prolonger_le_partage(client, ctx, relais):
    assert client.post("/api/partage/prolonger").status_code == 409
    ctx.consent.set("screen", True)
    assert client.post("/api/partage/demarrer", json={"source": "ecran"}).status_code == 200
    etat = client.post("/api/partage/prolonger").json()
    assert relais.renouvellements == 1 and etat["actif"] and 1790 <= etat["expire_dans_s"] <= 1800
    assert "partage_vision_prolonge" in [e["event_type"] for e in ctx.consent.events(10)]


# --------------------------------------------------------------------------- téléphone
def test_source_telephone_renvoie_le_jeton_et_ne_capture_rien(client, ctx, relais, app):
    ctx.consent.set("image", True)
    r = client.post("/api/partage/demarrer", json={"source": "telephone"})
    assert r.status_code == 200, r.text
    corps = r.json()
    assert corps["jeton_emetteur"] == JETON_EMETTEUR
    assert corps["ws_emetteur"] == "wss://relais.velaglass.ca/partage/emetteur"
    assert corps["intervalle_s"] is None
    attendre(lambda: relais.hellos, message="pas de connexion de suivi")
    assert relais.hellos[0]["role"] == "controle"
    assert ctx.capture.snapshot()["camera"] is False and ctx.capture.snapshot()["screen"] is False
    cx = relais.connexions[0]
    cx.pousser({"type": "stats", "images": 7, "fps_reel": 0.8, "spectateurs": 2, "emetteur_connecte": True,
                "expire_dans_s": 1700, "expire_a": "2026-09-13T20:28:00+00:00"})
    attendre(lambda: ctx.partage.etat()["images_envoyees"] == 7)
    etat = client.get("/api/partage/etat").json()
    assert etat["spectateurs"] == 2 and etat["fps_reel"] == 0.8 and etat["emetteur_connecte"] is True
    assert "1 image toutes les" in etat["cadence_texte"]
    # Dehors, c'est le téléphone qui lit le message : l'ordinateur resté à la maison se tait.
    cx.pousser({"type": "message", "texte": "Je vois le panneau"})
    attendre(lambda: any(e["type"] == "partage.message" for e in app.state.test.evenements))
    evenement = next(e for e in app.state.test.evenements if e["type"] == "partage.message")
    assert evenement["lu_a_voix_haute"] is False and evenement["source"] == "telephone"
    assert not any("Je vois le panneau" in p for p in app.state.test.paroles)
    assert relais.images == []
    client.post("/api/partage/arreter")
    assert relais.fins == 1


# --------------------------------------------------------------------------- lunettes
def test_lunettes_protocole_non_confirme_refus_mot_pour_mot_sans_lien(client, ctx, relais, app, tmp_path):
    ctx.consent.set("image", True)
    refus = ProtocoleNonConfirme("La commande photo est identifiée, mais l'en-tête exact de la trame n'est pas confirmé.")
    camera = FausseCamera(ctx, tmp_path, erreur=refus, exploration=False)
    ctx.partage.fabrique_camera = lambda: camera
    r = client.post("/api/partage/demarrer", json={"source": "lunettes"})
    assert r.status_code == 409 and r.json()["detail"] == str(refus)
    assert relais.creations == []  # aucun lien créé pour une caméra qui ne peut pas photographier
    assert ctx.capture.snapshot()["camera"] is False
    assert "Photo." not in app.state.test.paroles  # pas d'annonce d'une photo qui n'aura pas lieu

    camera = FausseCamera(ctx, tmp_path, erreur=CameraIndisponible("Ces lunettes n'exposent pas l'interface caméra."))
    ctx.partage.fabrique_camera = lambda: camera
    r = client.post("/api/partage/demarrer", json={"source": "lunettes"})
    assert r.status_code == 409 and r.json()["detail"] == "Ces lunettes n'exposent pas l'interface caméra."

    camera = FausseCamera(ctx, tmp_path, connectees=False)
    ctx.partage.fabrique_camera = lambda: camera
    r = client.post("/api/partage/demarrer", json={"source": "lunettes"})
    assert r.status_code == 409 and r.json()["detail"] == partage.LUNETTES_NON_CONNECTEES
    assert camera.appels == 0 and relais.creations == []


def test_lunettes_photo_en_boucle_effacee_et_verrou_commun(client, ctx, relais, app, tmp_path):
    ctx.consent.set("image", True)
    camera = FausseCamera(ctx, tmp_path)
    ctx.partage.fabrique_camera = lambda: camera
    r = client.post("/api/partage/demarrer", json={"source": "lunettes", "intervalle_s": 0})
    assert r.status_code == 200, r.text
    assert "pas de vidéo" in r.json()["note"]
    assert app.state.test.paroles[0] == "Photo."
    attendre(lambda: len(relais.images) >= 3, message="photos non envoyées")
    assert all(camera.verrou_tenu)  # chaque photo prise sous le verrou commun de la caméra
    assert ctx.capture.snapshot()["camera"] is True
    # La vision d'accessibilité voit que la caméra sert au partage (pour ne pas éteindre son témoin).
    assert ctx.accessibilite._camera_utilisee_ailleurs() is True
    # Les photos 2400 × 1800 sont réduites à 1280 px et restent sous 300 Ko.
    from PIL import Image

    image = Image.open(io.BytesIO(relais.images[0]))
    assert max(image.size) == 1280 and len(relais.images[0]) <= 300_000
    client.post("/api/partage/arreter")
    attendre(lambda: ctx.capture.snapshot()["camera"] is False)
    # Aucune photo du partage ne reste sur le disque, même celle qui finissait au moment de l'arrêt.
    attendre(lambda: camera.chemins and not any(c.exists() for c in camera.chemins),
             message="une photo du partage est restée sur le disque")
    assert ctx.accessibilite._camera_utilisee_ailleurs() is False


def test_lunettes_deconnectees_en_cours_arretent_et_le_disent(client, ctx, relais, app, tmp_path):
    ctx.consent.set("image", True)
    camera = FausseCamera(ctx, tmp_path)
    ctx.partage.fabrique_camera = lambda: camera
    assert client.post("/api/partage/demarrer", json={"source": "lunettes", "intervalle_s": 0}).status_code == 200
    attendre(lambda: len(relais.images) >= 1)
    camera.glasses.connected = False
    attendre(lambda: not ctx.partage.actif)
    assert ctx.partage.etat()["raison"] == partage.LUNETTES_DECONNECTEES
    attendre(lambda: partage.LUNETTES_DECONNECTEES in app.state.test.paroles)
    assert ctx.capture.snapshot()["camera"] is False


# --------------------------------------------------------------------------- voix
def test_voix_arreter_prolonger_et_etat(client, ctx, relais):
    service = ctx.partage
    # Sans partage en cours et sans « vision », la phrase n'est pas pour nous.
    assert service.interception("arrête le partage de connexion") is None
    assert service.interception("arrête de regarder la télé") is None
    assert service.interception("quelle heure est-il") is None
    assert dans_la_boucle(ctx, service.interception("arrête la vision partagée")) == partage.AUCUN_PARTAGE

    ctx.consent.set("screen", True)
    assert client.post("/api/partage/demarrer", json={"source": "ecran"}).status_code == 200
    assert "Personne ne regarde" in dans_la_boucle(ctx, service.interception("qui regarde mon partage ?"))
    assert dans_la_boucle(ctx, service.interception("Prolonge le partage")).startswith("Partage prolongé")
    assert relais.renouvellements == 1
    assert dans_la_boucle(ctx, service.interception("Arrête le partage")) == partage.ARRETE
    assert service.actif is False and relais.fins == 1
    # L'interception est bien branchée dans l'écoute, en priorité 60.
    assert ("partage", 60) in [(nom, priorite) for priorite, nom, _f in ctx.voice._interceptions]


# --------------------------------------------------------------------------- utilitaires
def test_compression_sous_la_borne_du_relais():
    import numpy as np
    from PIL import Image

    bruit = np.random.default_rng(7).integers(0, 255, size=(1800, 3200, 3), dtype=np.uint8)
    donnees = partage.compresser_jpeg(Image.fromarray(bruit, "RGB"))
    assert donnees.startswith(b"\xff\xd8\xff") and len(donnees) <= partage.TAILLE_MAX_IMAGE
    assert max(Image.open(io.BytesIO(donnees)).size) <= 1280
    assert partage.cadence_texte(0) is None
    assert partage.cadence_texte(3) == "3,0 images par seconde (mesuré)"
    assert partage.cadence_texte(0.25) == "1 image toutes les 4,0 secondes (mesuré)"


def test_textes_visibles_sans_nom_de_fournisseur_ni_promesse_absolue():
    textes = [v for k, v in vars(partage).items() if k.isupper() and isinstance(v, str)]
    textes += list(partage.NOTES.values()) + list(partage.LIMITES) + list(partage.MESSAGES_FIN_RELAIS.values())
    for texte in textes:
        minuscules = texte.lower()
        for nom in NOMS_INTERDITS:
            assert nom not in minuscules, (nom, texte)
        for absolu in ("instantané", "toujours", "parfait", "entièrement", "en temps réel"):
            assert absolu not in minuscules, (absolu, texte)


# --------------------------------------------------------------------------- avec le vrai relais
class _ConnexionTestClient:
    """Une connexion du client de test du relais, vue par le service comme une connexion WebSocket."""

    def __init__(self, session, ws):
        self._session = session
        self._ws = ws
        self.code_fermeture: int | None = None
        self._fermee = False

    async def envoyer_texte(self, texte: str) -> None:
        await asyncio.to_thread(self._ws.send_text, texte)

    async def envoyer_octets(self, donnees: bytes) -> None:
        await asyncio.to_thread(self._ws.send_bytes, donnees)

    async def recevoir(self):
        try:
            message = await asyncio.to_thread(self._ws.receive)
        except Exception:
            return None
        if message.get("type") == "websocket.close":
            self.code_fermeture = message.get("code")
            return None
        return message["text"] if message.get("text") is not None else message.get("bytes")

    async def fermer(self) -> None:
        if self._fermee:
            return
        self._fermee = True

        def sortir():
            try:
                self._session.__exit__(None, None, None)
            except Exception:
                pass

        await asyncio.to_thread(sortir)


class _RelaisEnMemoire:
    def __init__(self, client):
        self.client = client

    async def _post(self, chemin: str, corps: dict) -> dict:
        r = await asyncio.to_thread(self.client.post, chemin, json=corps)
        if r.status_code >= 400:
            raise ErreurRelais(r.status_code, str(r.json().get("detail") or ""))
        return r.json()

    async def obtenir_jeton(self, base, courriel, machine):  # pragma: no cover - jeton fourni par le test
        raise ErreurRelais(503, "")

    async def creer(self, base, jeton):
        return await self._post("/api/partage/creer", {"jeton_appareil": jeton})

    async def renouveler(self, base, jeton):
        return await self._post("/api/partage/renouveler", {"jeton_emetteur": jeton})

    async def fermer(self, base, jeton):
        await self._post("/api/partage/fermer", {"jeton_emetteur": jeton})

    async def connecter(self, url):
        session = self.client.websocket_connect(urlsplit(url).path)
        ws = await asyncio.to_thread(session.__enter__)
        return _ConnexionTestClient(session, ws)


def recevoir_ws(ws, delai: float = 5.0) -> dict:
    """Le prochain message d'une connexion du client de test, avec un délai : un test ne doit jamais pendre."""
    import anyio

    async def lire():
        with anyio.fail_after(delai):
            return await ws._send_rx.receive()

    return ws.portal.call(lire)


def test_le_service_parle_le_protocole_du_vrai_relais(client, ctx, app, tmp_path, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    serveur = Path(__file__).resolve().parents[2] / "serveur"
    monkeypatch.setenv("VELA_DONNEES", str(tmp_path / "relais"))
    monkeypatch.setenv("VELA_OPENROUTER_KEY", "sk-factice")
    monkeypatch.syspath_prepend(str(serveur))
    for module in ("relais", "partage_vision"):
        sys.modules.pop(module, None)
    import partage_vision
    import relais as module_relais

    application_relais = FastAPI()
    application_relais.include_router(partage_vision.creer_routeur_partage(module_relais))
    ctx.consent.set("screen", True)
    ctx.secrets.set_api_key("vela", module_relais.emettre_jeton("proche@exemple.com", "machine-test"))
    try:
        with TestClient(application_relais) as client_relais:
            ctx.partage.client_relais = _RelaisEnMemoire(client_relais)
            try:
                r = client.post("/api/partage/demarrer", json={"source": "ecran", "intervalle_s": 0.2})
                assert r.status_code == 200, r.text
                code = r.json()["code"]
                assert partage_vision.code_valide(code)
                with client_relais.websocket_connect(f"/partage/spectateur/{code}") as spectateur:
                    # Le spectateur reçoit de vraies images JPEG émises par le service.
                    fin = time.monotonic() + 8
                    image = None
                    while image is None:
                        message = recevoir_ws(spectateur, max(0.1, fin - time.monotonic()))
                        if message.get("bytes"):
                            image = message["bytes"]
                    assert image.startswith(b"\xff\xd8\xff") and len(image) <= 300_000
                    spectateur.send_json({"type": "message", "texte": "Je vois ton écran"})
                    attendre(lambda: "Message de votre proche : Je vois ton écran" in app.state.test.paroles, delai=8)
                    attendre(lambda: ctx.partage.etat()["spectateurs"] == 1, delai=8)
                    client.post("/api/partage/arreter")
                    fin_recue = None
                    limite = time.monotonic() + 8
                    while fin_recue is None:
                        message = recevoir_ws(spectateur, max(0.1, limite - time.monotonic()))
                        if message.get("type") == "websocket.close":
                            break
                        if message.get("text"):
                            contenu = json.loads(message["text"])
                            if contenu.get("type") == "fin":
                                fin_recue = contenu
                    assert fin_recue is not None and fin_recue["raison"] == "arrete"
            finally:
                client.post("/api/partage/arreter")
    finally:
        for module in ("relais", "partage_vision"):
            sys.modules.pop(module, None)
