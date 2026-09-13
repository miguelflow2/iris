"""Album local et traduction de l'écran (interface E) : images synthétiques, dossiers temporaires, faux
OCR, faux moteur. Aucun réseau, aucune capture réelle, aucun écran lu.

Prouvé ici : liste (types, tri, durée lue dans l'en-tête WAV), lecture binaire au bon type, suppression
(et refus d'un WAV en cours d'écriture), refus des traversées de chemin sur TOUTES les routes, « Lumière
BD » (taille maximale, aplats limités, traits sur les bords et pas sur les zones plates), exportation
(copie exacte, filigrane en bas à droite seulement, jamais d'écrasement), enregistrement automatique
branché sur le vrai bus d'événements (une seule copie par photo, images seulement, rien en mémoire
suspendue), rétention des images, traduction de l'écran (consentements vérifiés AVANT la capture, mode
local, confidentiel, texte vide, panne du moteur sans nom de fournisseur, délai, troncature).
"""
from __future__ import annotations

import asyncio
import io
import os
import struct
import time
import wave
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from iris import album as album_mod
from iris.connectors.base import ConnectorError
from iris.router import NoAgentAvailable


# =============================================================================== outils
def attendre(condition, delai: float = 5.0) -> bool:
    fin = time.monotonic() + delai
    while time.monotonic() < fin:
        if condition():
            return True
        time.sleep(0.02)
    return condition()


def image_octets(largeur: int = 320, hauteur: int = 240, couleur=(200, 120, 40), format_: str = "JPEG") -> bytes:
    tampon = io.BytesIO()
    Image.new("RGB", (largeur, hauteur), couleur).save(tampon, format=format_)
    return tampon.getvalue()


def ecrire_wav(chemin: Path, secondes: float, taux: int = 16000) -> None:
    chemin.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(chemin), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(taux)
        w.writeframes(np.zeros(int(secondes * taux), dtype=np.int16).tobytes())


def captures(app) -> Path:
    dossier = Path(app.state.ctx.settings.data_dir) / "captures"
    dossier.mkdir(parents=True, exist_ok=True)
    return dossier


def vieillir(chemin: Path, secondes: float) -> None:
    t = time.time() - secondes
    os.utime(chemin, (t, t))


@pytest.fixture()
def export(app, tmp_path):
    dossier = tmp_path / "export"
    app.state.ctx.settings.update({"album_dossier_export": str(dossier)})
    return dossier


# =============================================================================== liste et lecture
def test_le_service_est_branche_et_protege(app, client_sans_jeton):
    assert isinstance(getattr(app.state.ctx, "album", None), album_mod.ServiceAlbum)
    assert client_sans_jeton.get("/api/album").status_code == 401
    assert client_sans_jeton.get("/api/album/fichier/a.jpg").status_code == 401


def test_liste_types_tri_et_duree(client, app):
    assert client.get("/api/album").json()["elements"] == []  # aucun dossier : liste vide, pas d'erreur
    dossier = captures(app)
    (dossier / "lunettes-1.jpg").write_bytes(image_octets())
    (dossier / "lunettes-1-bd.jpg").write_bytes(image_octets())
    (dossier / "ecran.png").write_bytes(image_octets(format_="PNG"))
    (dossier / "notes.txt").write_text("pas une image", encoding="utf-8")
    ecrire_wav(dossier / "audio" / "enregistrement-20260913-100000.wav", 1.5)
    (dossier / "audio" / "egaree.jpg").write_bytes(image_octets())  # image hors de sa place : ignorée
    vieillir(dossier / "lunettes-1.jpg", 300)
    vieillir(dossier / "lunettes-1-bd.jpg", 200)
    vieillir(dossier / "ecran.png", 100)

    corps = client.get("/api/album").json()
    elements = corps["elements"]
    assert [e["nom"] for e in elements] == [
        "enregistrement-20260913-100000.wav", "ecran.png", "lunettes-1-bd.jpg", "lunettes-1.jpg"]
    par_nom = {e["nom"]: e for e in elements}
    assert par_nom["lunettes-1.jpg"]["type"] == "photo" and par_nom["lunettes-1.jpg"]["duree_s"] is None
    assert par_nom["lunettes-1-bd.jpg"]["type"] == "bd"
    assert par_nom["enregistrement-20260913-100000.wav"] == {
        **par_nom["enregistrement-20260913-100000.wav"], "type": "audio", "duree_s": 1.5}
    assert all(set(e) == {"nom", "type", "octets", "modifie", "duree_s"} for e in elements)
    assert par_nom["ecran.png"]["octets"] == (dossier / "ecran.png").stat().st_size
    assert "dossier_export" in corps and corps["memoire_suspendue"] is None

    assert [e["nom"] for e in client.get("/api/album?type=photo").json()["elements"]] == ["ecran.png", "lunettes-1.jpg"]
    assert [e["nom"] for e in client.get("/api/album?type=bd").json()["elements"]] == ["lunettes-1-bd.jpg"]
    assert [e["type"] for e in client.get("/api/album?type=audio").json()["elements"]] == ["audio"]
    assert client.get("/api/album?type=video").status_code == 422


def test_duree_wav_en_cours_d_ecriture_et_fichiers_pieges(tmp_path):
    complet = tmp_path / "complet.wav"
    ecrire_wav(complet, 2.0)
    assert album_mod.duree_wav(complet) == 2.0

    # En-tête dont la taille « data » vaut encore 0 (fichier qu'on écrit) : mesurée sur les octets présents.
    en_cours = tmp_path / "en-cours.wav"
    brut = bytearray(complet.read_bytes())
    position = brut.find(b"data")
    brut[position + 4:position + 8] = struct.pack("<I", 0)
    en_cours.write_bytes(bytes(brut))
    assert album_mod.duree_wav(en_cours) == 2.0

    # Taille déclarée plus grande que le fichier (coupure brutale) : pas de durée inventée.
    tronque = tmp_path / "tronque.wav"
    brut[position + 4:position + 8] = struct.pack("<I", 10_000_000)
    tronque.write_bytes(bytes(brut[: position + 8 + 16000]))
    assert album_mod.duree_wav(tronque) == 0.5

    faux = tmp_path / "faux.wav"
    faux.write_bytes(b"ceci n'est pas un wav" * 10)
    assert album_mod.duree_wav(faux) is None
    assert album_mod.duree_wav(tmp_path / "absent.wav") is None


def test_lecture_binaire_avec_le_type_exact(client, app):
    dossier = captures(app)
    jpeg, png = image_octets(), image_octets(format_="PNG")
    (dossier / "a.jpg").write_bytes(jpeg)
    (dossier / "b.png").write_bytes(png)
    ecrire_wav(dossier / "audio" / "cours-1.wav", 0.25)

    r = client.get("/api/album/fichier/a.jpg")
    assert r.status_code == 200 and r.headers["content-type"] == "image/jpeg" and r.content == jpeg
    r = client.get("/api/album/fichier/b.png")
    assert r.headers["content-type"] == "image/png" and r.content == png
    r = client.get("/api/album/fichier/cours-1.wav")
    assert r.headers["content-type"] == "audio/wav"
    assert r.content == (dossier / "audio" / "cours-1.wav").read_bytes()
    assert client.get("/api/album/fichier/absent.jpg").status_code == 404


# =============================================================================== traversées
def test_toute_traversee_de_chemin_est_refusee(client, app):
    ctx = app.state.ctx
    dossier = captures(app)
    secret = Path(ctx.settings.data_dir) / "secret.jpg"
    secret.write_bytes(b"SECRET")
    (dossier / "audio").mkdir(exist_ok=True)
    (dossier / "audio" / "secret2.jpg").write_bytes(b"SECRET")  # une image SOUS audio/ n'est pas servie

    for nom in ("..%5Csecret.jpg", "..%5C..%5Csecret.jpg", "C:%5Csecret.jpg", "secret.jpg:flux", "settings.json",
                "..jpg", ".cache.jpg", "%20a.jpg"):
        r = client.get(f"/api/album/fichier/{nom}")
        assert r.status_code in (400, 404), nom
        assert b"SECRET" not in r.content
        assert client.delete(f"/api/album/{nom}").status_code in (400, 404, 405), nom
    # Séparateur encodé : soit la route ne correspond pas, soit le nom est refusé. Jamais le fichier.
    for nom in ("..%2Fsecret.jpg", "audio%2Fsecret2.jpg", "%2E%2E%2Fsecret.jpg"):
        r = client.get(f"/api/album/fichier/{nom}")
        assert r.status_code in (400, 404) and b"SECRET" not in r.content
    for route in ("/api/album/bd", "/api/album/exporter"):
        for nom in ("../secret.jpg", "..\\secret.jpg", "/etc/passwd.jpg", "C:\\secret.jpg", "audio/secret2.jpg"):
            assert client.post(route, json={"nom": nom}).status_code == 400, (route, nom)
    # Nom de périphérique Windows : jamais une erreur 500, jamais une lecture.
    assert client.get("/api/album/fichier/nul.jpg").status_code == 404
    assert secret.read_bytes() == b"SECRET"

    with pytest.raises(album_mod.RefusAlbum) as exc:
        ctx.album.chemin_de("../secret.jpg")
    assert exc.value.status_code == 400

    lien = dossier / "lien.jpg"
    try:
        os.symlink(secret, lien)
    except (OSError, NotImplementedError):
        return  # Windows sans le privilège des liens symboliques : le contrôle du parent reste prouvé plus haut
    r = client.get("/api/album/fichier/lien.jpg")
    assert r.status_code == 404 and b"SECRET" not in r.content


# =============================================================================== suppression
def test_suppression_et_wav_en_cours(client, app, monkeypatch):
    ctx = app.state.ctx
    dossier = captures(app)
    (dossier / "a.jpg").write_bytes(image_octets())
    ecrire_wav(dossier / "audio" / "enregistrement-1.wav", 0.5)

    assert client.delete("/api/album/a.jpg").json() == {"supprime": True, "nom": "a.jpg"}
    assert not (dossier / "a.jpg").exists()
    assert client.delete("/api/album/a.jpg").status_code == 404

    enregistreur = getattr(ctx, "enregistreur", None)
    if enregistreur is None:  # module d'écoute absent : on simule le service voisin
        class Faux:
            def fichiers_en_cours(self):
                return set()

        ctx.enregistreur = enregistreur = Faux()
    monkeypatch.setattr(enregistreur, "fichiers_en_cours", lambda: {"enregistrement-1.wav"})
    r = client.delete("/api/album/enregistrement-1.wav")
    assert r.status_code == 409 and "en cours" in r.json()["detail"]
    assert (dossier / "audio" / "enregistrement-1.wav").exists()
    monkeypatch.setattr(enregistreur, "fichiers_en_cours", lambda: set())
    assert client.delete("/api/album/enregistrement-1.wav").status_code == 200


# =============================================================================== Lumière BD
def scene_deux_aplats(largeur: int, hauteur: int, bruit: float = 4.0) -> Image.Image:
    rng = np.random.default_rng(3)
    tableau = np.zeros((hauteur, largeur, 3), dtype=np.float32)
    tableau[:, : largeur // 2] = (40, 90, 200)
    tableau[:, largeur // 2:] = (230, 140, 40)
    tableau += rng.normal(0, bruit, tableau.shape)
    return Image.fromarray(np.clip(tableau, 0, 255).astype(np.uint8))


def encre(tableau: np.ndarray) -> np.ndarray:
    return tableau.astype(np.int32).sum(axis=2) < 160


def nb_couleurs(pixels: np.ndarray) -> int:
    # Couleurs empaquetées en un entier : np.unique(axis=0) sur un million de lignes coûte une seconde.
    v = pixels.reshape(-1, 3).astype(np.int32)
    return len(np.unique((v[:, 0] << 16) | (v[:, 1] << 8) | v[:, 2]))


def test_lumiere_bd_taille_aplats_et_traits():
    debut = time.monotonic()
    sortie = album_mod.styliser_bd(scene_deux_aplats(3000, 1000))
    assert sortie.size == (2048, 683) and sortie.mode == "RGB"
    t = np.asarray(sortie)
    frontiere = 1024
    # Un trait d'encre suit la frontière entre les deux aplats, sur toute la hauteur…
    bande = encre(t[20:-20, frontiere - 8: frontiere + 8])
    assert bande.any(axis=1).mean() > 0.95
    # … et aucune zone plate ne reçoit d'encre (le bruit du capteur ne devient pas des gribouillis).
    assert not encre(t[:, 100: frontiere - 60]).any()
    assert not encre(t[:, frontiere + 60: -100]).any()
    # Aplats : loin du trait, au plus NIVEAUX_COULEUR teintes (la photo bruitée en avait des milliers).
    interieur = np.concatenate([t[:, 50: frontiere - 60].reshape(-1, 3), t[:, frontiere + 60: -50].reshape(-1, 3)])
    assert nb_couleurs(interieur) <= album_mod.NIVEAUX_COULEUR
    assert time.monotonic() - debut < 15


def test_lumiere_bd_image_uniforme_sans_trait_et_degrade_posterise():
    uniforme = Image.fromarray(np.clip(
        np.random.default_rng(1).normal(128, 3, (400, 600, 3)), 0, 255).astype(np.uint8))
    assert not encre(np.asarray(album_mod.styliser_bd(uniforme))).any()

    x = np.linspace(0, 255, 512, dtype=np.float32)
    degrade = np.stack([np.tile(x, (256, 1)), np.tile(x[::-1], (256, 1)), np.full((256, 512), 90.0)], axis=2)
    image = Image.fromarray(degrade.astype(np.uint8))
    assert nb_couleurs(np.asarray(image)) > 200
    aplats = np.asarray(album_mod.posteriser(image))
    assert nb_couleurs(aplats) <= album_mod.NIVEAUX_COULEUR


def test_route_bd_noms_refus_et_occupation(client, app):
    ctx = app.state.ctx
    dossier = captures(app)
    tampon = io.BytesIO()
    scene_deux_aplats(900, 500).save(tampon, format="JPEG", quality=92)
    (dossier / "lunettes-2.jpg").write_bytes(tampon.getvalue())
    (dossier / "abimee.jpg").write_bytes(b"\xff\xd8 pas vraiment une image")
    ecrire_wav(dossier / "audio" / "cours-1.wav", 0.25)

    r = client.post("/api/album/bd", json={"nom": "lunettes-2.jpg"})
    assert r.status_code == 200, r.text
    corps = r.json()
    assert corps["nom"] == "lunettes-2-bd.jpg" and corps["octets"] == (dossier / "lunettes-2-bd.jpg").stat().st_size
    with Image.open(dossier / "lunettes-2-bd.jpg") as produite:
        assert produite.format == "JPEG" and produite.size == (900, 500)  # la réduction à 2048 px est prouvée plus haut
    assert not [p for p in dossier.iterdir() if p.name.endswith(".partiel")]
    assert client.post("/api/album/bd", json={"nom": "lunettes-2.jpg"}).json()["nom"] == "lunettes-2-2-bd.jpg"
    assert {e["nom"] for e in client.get("/api/album?type=bd").json()["elements"]} == {
        "lunettes-2-bd.jpg", "lunettes-2-2-bd.jpg"}

    assert client.post("/api/album/bd", json={"nom": "lunettes-2-bd.jpg"}).status_code == 422
    assert client.post("/api/album/bd", json={"nom": "cours-1.wav"}).status_code == 422
    assert client.post("/api/album/bd", json={"nom": "abimee.jpg"}).status_code == 422
    assert client.post("/api/album/bd", json={"nom": "absente.jpg"}).status_code == 404

    assert ctx.album._verrou_bd.acquire(blocking=False)
    try:
        r = client.post("/api/album/bd", json={"nom": "lunettes-2.jpg"})
        assert r.status_code == 409 and "déjà en cours" in r.json()["detail"]
    finally:
        ctx.album._verrou_bd.release()

    ctx.memory.suspendre("invite")
    try:
        r = client.post("/api/album/bd", json={"nom": "lunettes-2.jpg"})
        assert r.status_code == 409 and "Mémoire suspendue" in r.json()["detail"]
    finally:
        ctx.memory.reprendre("invite")


# =============================================================================== exportation
def test_export_copie_exacte_sans_ecrasement_et_filigrane(client, app, export):
    ctx = app.state.ctx
    dossier = captures(app)
    png = image_octets(800, 600, (255, 255, 255), "PNG")
    (dossier / "ecran.png").write_bytes(png)
    ecrire_wav(dossier / "audio" / "enregistrement-2.wav", 0.25)

    r = client.post("/api/album/exporter", json={"nom": "ecran.png", "filigrane": False})
    assert r.status_code == 200, r.text
    premier = Path(r.json()["chemin"])
    assert premier == export / "ecran.png" and premier.read_bytes() == png and r.json()["filigrane"] is False
    second = Path(client.post("/api/album/exporter", json={"nom": "ecran.png", "filigrane": False}).json()["chemin"])
    assert second == export / "ecran-2.png" and premier.read_bytes() == png  # l'existant n'est jamais écrasé

    r = client.post("/api/album/exporter", json={"nom": "ecran.png", "filigrane": True})
    marque = Path(r.json()["chemin"])
    assert marque.name == "ecran-3.png" and r.json()["filigrane"] is True
    with Image.open(marque) as ouverte:
        pixels = np.asarray(ouverte.convert("RGB")).astype(np.int32)
    assert (pixels[:300, :400] == 255).all()  # rien ailleurs qu'en bas à droite
    coin = pixels[-80:, -300:]
    assert (coin != 255).any(), "le filigrane doit être visible dans le coin"
    assert coin.min() > 60, "discret : ombre légère, pas de texte noir plein"

    # filigrane null : le réglage décide.
    ctx.settings.update({"album_filigrane": True})
    assert client.post("/api/album/exporter", json={"nom": "ecran.png"}).json()["filigrane"] is True
    ctx.settings.update({"album_filigrane": False})
    assert client.post("/api/album/exporter", json={"nom": "ecran.png"}).json()["filigrane"] is False

    # L'audio se copie tel quel : un filigrane ne se dessine pas sur du son.
    r = client.post("/api/album/exporter", json={"nom": "enregistrement-2.wav", "filigrane": True})
    assert r.json()["filigrane"] is False
    assert Path(r.json()["chemin"]).read_bytes() == (dossier / "audio" / "enregistrement-2.wav").read_bytes()

    assert any(e["event_type"] == "album_exporte" for e in ctx.consent.events())
    ctx.settings.update({"album_dossier_export": "dossier/relatif"})
    assert client.post("/api/album/exporter", json={"nom": "ecran.png"}).status_code == 422


def test_export_dossier_par_defaut_cree_au_besoin(client, app, tmp_path, monkeypatch):
    defaut = tmp_path / "Images" / "IRIS"
    monkeypatch.setattr(album_mod, "dossier_images_par_defaut", lambda: defaut)
    app.state.ctx.settings.update({"album_dossier_export": ""})
    (captures(app) / "a.jpg").write_bytes(image_octets())
    r = client.post("/api/album/exporter", json={"nom": "a.jpg"})
    assert r.status_code == 200 and Path(r.json()["chemin"]) == defaut / "a.jpg" and (defaut / "a.jpg").is_file()


def test_filigrane_jpeg_garde_le_format(tmp_path):
    source = tmp_path / "photo.jpg"
    source.write_bytes(image_octets(640, 480, (30, 30, 30)))
    donnees = album_mod.image_filigranee(source)
    with Image.open(io.BytesIO(donnees)) as ouverte:
        assert ouverte.format == "JPEG" and ouverte.size == (640, 480)
        coin = np.asarray(ouverte.convert("L"))[-40:, -200:]
    assert coin.max() > 90  # texte clair visible sur fond sombre


# =============================================================================== enregistrement automatique
def test_enregistrement_automatique_sur_le_vrai_bus(client, app, export):
    ctx = app.state.ctx
    assert ctx.album._taches, "iris_demarrage doit avoir branché l'écoute du bus"
    dossier = captures(app)
    for nom in ("p1.jpg", "p2.jpg", "p3.jpg", "p4.jpg", "p5.jpg"):
        (dossier / nom).write_bytes(image_octets())
    ecrire_wav(dossier / "audio" / "enregistrement-3.wav", 0.25)
    dehors = Path(ctx.settings.data_dir) / "ailleurs.jpg"
    dehors.write_bytes(image_octets())

    traites: list[dict] = []
    original = ctx.album.traiter_evenement

    async def temoin(evenement):
        try:
            return await original(evenement)
        finally:
            traites.append(evenement)

    ctx.album.traiter_evenement = temoin
    # Le réglage est lu au moment du traitement : on attend que p1 soit traité AVANT de l'activer.
    ctx.hub.publish("glasses.photo", chemin=str(dossier / "p1.jpg"), octets=10)  # réglage coupé : rien
    assert attendre(lambda: any(str(e.get("chemin", "")).endswith("p1.jpg") for e in traites))
    ctx.settings.update({"album_enregistrement_auto": True})
    ctx.hub.publish("glasses.photo", chemin=str(dossier / "p2.jpg"), octets=10)
    ctx.hub.publish("album.nouveau", nom="p2.jpg", genre="photo", octets=10)  # même photo : pas de 2e copie
    ctx.hub.publish("album.nouveau", nom="enregistrement-3.wav", genre="audio", octets=10)  # audio : jamais
    ctx.hub.publish("glasses.photo", chemin=str(dehors), octets=10)  # hors de l'album : ignoré
    ctx.hub.publish("album.nouveau", nom="../ailleurs.jpg", genre="photo", octets=10)
    ctx.hub.publish("album.nouveau", nom="p3.jpg", genre="photo", octets=10)
    # Les copies partent en tâches parallèles : on attend que les sept événements soient traités.
    assert attendre(lambda: len(traites) == 7)
    assert sorted(p.name for p in export.iterdir()) == ["p2.jpg", "p3.jpg"]

    ctx.memory.suspendre("zone:Clinique")
    try:
        ctx.hub.publish("glasses.photo", chemin=str(dossier / "p4.jpg"), octets=10)
        assert attendre(lambda: len(traites) == 8)
    finally:
        ctx.memory.reprendre("zone:Clinique")
    ctx.hub.publish("album.nouveau", nom="p5.jpg", genre="photo", octets=10)
    assert attendre(lambda: (export / "p5.jpg").exists())
    assert not (export / "p4.jpg").exists(), "mémoire suspendue : aucune copie automatique"
    assert not (export / "enregistrement-3.wav").exists() and not (export / "ailleurs.jpg").exists()


def test_copie_automatique_ignoree_dit_pourquoi(app, export):
    ctx = app.state.ctx
    publies: list[tuple[str, dict]] = []
    ctx.hub.publish = lambda type_, **donnees: publies.append((type_, donnees)) or {}
    (captures(app) / "p.jpg").write_bytes(image_octets())
    ctx.settings.update({"album_enregistrement_auto": True, "privacy_mode": True})
    resultat = asyncio.run(ctx.album.traiter_evenement({"type": "album.nouveau", "nom": "p.jpg", "genre": "photo"}))
    assert resultat is None and not export.exists()
    assert publies and publies[-1][0] == "album.auto_ignore" and "confidentiel" in publies[-1][1]["raison"]


# =============================================================================== rétention
def test_retention_des_images(app):
    ctx = app.state.ctx
    dossier = captures(app)
    for nom in ("vieille.jpg", "vieille-bd.jpg", "recente.jpg"):
        (dossier / nom).write_bytes(image_octets())
    ecrire_wav(dossier / "audio" / "enregistrement-4.wav", 0.25)
    for chemin in (dossier / "vieille.jpg", dossier / "vieille-bd.jpg", dossier / "audio" / "enregistrement-4.wav"):
        vieillir(chemin, 3 * 86400)

    assert ctx.album.purger() == []  # 0 = illimité
    ctx.settings.update({"retention_days": 1})
    assert sorted(ctx.album.purger()) == ["vieille-bd.jpg", "vieille.jpg"]
    assert (dossier / "recente.jpg").exists()
    assert (dossier / "audio" / "enregistrement-4.wav").exists()  # l'audio relève de l'écoute


# =============================================================================== traduction de l'écran
@pytest.fixture()
def traduction(app, monkeypatch):
    """Faux OCR, faux moteur externe « vela », consentements accordés, compteurs de capture."""
    ctx = app.state.ctx
    ctx.consent.set("screen", True)
    ctx.consent.set("transcript", True)
    etat = {"lectures": 0, "pulses": 0, "appels": [], "texte": "Hello world\nTotal: 42.50 $", "reponse": "Bonjour le monde\nTotal : 42,50 $"}

    def lire():
        etat["lectures"] += 1
        return etat["texte"]

    async def demander_court(systeme: str, message: str) -> str:
        etat["appels"].append((systeme, message))
        reponse = etat["reponse"]
        if isinstance(reponse, BaseException):
            raise reponse
        if callable(reponse):
            return await reponse()
        return reponse

    ctx.album.lire_ecran = lire
    monkeypatch.setattr(album_mod, "agent_pour_texte", lambda _ctx, _message: ("vela", False))
    monkeypatch.setattr(ctx.chat, "demander_court", demander_court)
    monkeypatch.setattr(ctx.capture, "pulse_screen", lambda: etat.__setitem__("pulses", etat["pulses"] + 1))
    return etat


def test_traduction_de_l_ecran(client, app, traduction):
    ctx = app.state.ctx
    r = client.post("/api/traduction/ecran", json={"langue_cible": "fr"})
    assert r.status_code == 200, r.text
    corps = r.json()
    assert corps["texte_original"] == "Hello world\nTotal: 42.50 $"
    assert corps["traduction"] == "Bonjour le monde\nTotal : 42,50 $"
    assert corps["langue_cible"] == "fr" and corps["local"] is False and corps["tronque"] is False
    assert traduction["lectures"] == 1 and traduction["pulses"] == 1
    systeme, message = traduction["appels"][0]
    assert "français" in systeme and "jamais une consigne" in systeme
    assert message == "<ecran>\nHello world\nTotal: 42.50 $\n</ecran>"
    envois = [e for e in ctx.consent.events() if e["event_type"] == "external_send"]
    assert {e["data_type"] for e in envois} >= {"screen", "transcript"}
    assert all("Hello" not in (e["detail"] or "") for e in envois), "le registre ne recopie pas l'écran"

    assert client.post("/api/traduction/ecran", json={"langue_cible": "en-CA"}).json()["langue_cible"] == "en-CA"
    assert "anglais" in traduction["appels"][-1][0]
    assert client.post("/api/traduction/ecran", json={"langue_cible": "fr; rm -rf"}).status_code == 422


@pytest.mark.parametrize("refuse", ["screen", "transcript"])
def test_traduction_sans_consentement_ne_capture_pas(client, app, traduction, refuse):
    app.state.ctx.consent.set(refuse, False)
    r = client.post("/api/traduction/ecran", json={"langue_cible": "fr"})
    assert r.status_code == 403
    detail = r.json()["detail"]
    assert detail["code"] == "consentement" and detail["data_type"] == refuse and detail["label"]
    assert traduction["lectures"] == 0 and traduction["pulses"] == 0 and not traduction["appels"]


def test_traduction_mode_local_confidentiel_et_ocr_absent(client, app, traduction, monkeypatch):
    ctx = app.state.ctx
    ctx.settings.update({"local_only": True})
    r = client.post("/api/traduction/ecran", json={})
    assert r.status_code == 409 and "100 % local" in r.json()["detail"]

    def sans_moteur(_ctx, _message):
        raise NoAgentAvailable("Mode 100 % local activé : configurez une IA locale (Ollama, LM Studio…)")

    monkeypatch.setattr(album_mod, "agent_pour_texte", sans_moteur)
    r = client.post("/api/traduction/ecran", json={})
    assert r.status_code == 409 and "Ollama" not in r.json()["detail"]
    assert traduction["lectures"] == 0

    # Une IA locale configurée : la traduction tourne, rien n'est inscrit comme envoi externe.
    monkeypatch.setattr(album_mod, "agent_pour_texte", lambda _ctx, _message: ("custom", True))
    ctx.consent.set("screen", False)
    avant = len([e for e in ctx.consent.events() if e["event_type"] == "external_send"])
    r = client.post("/api/traduction/ecran", json={})
    assert r.status_code == 200 and r.json()["local"] is True
    assert len([e for e in ctx.consent.events() if e["event_type"] == "external_send"]) == avant
    ctx.settings.update({"local_only": False})
    ctx.consent.set("screen", True)
    monkeypatch.setattr(album_mod, "agent_pour_texte", lambda _ctx, _message: ("vela", False))

    lectures = traduction["lectures"]
    ctx.settings.update({"privacy_mode": True})
    r = client.post("/api/traduction/ecran", json={})
    assert r.status_code == 409 and "confidentiel" in r.json()["detail"]
    ctx.settings.update({"privacy_mode": False})
    assert traduction["lectures"] == lectures

    def ocr_absent():
        raise album_mod.OcrIndisponible(album_mod.OCR_ABSENT)

    ctx.album.lire_ecran = ocr_absent
    pulses = traduction["pulses"]
    r = client.post("/api/traduction/ecran", json={})
    assert r.status_code == 409 and "lecture locale" in r.json()["detail"]
    assert traduction["pulses"] == pulses, "aucune capture n'a eu lieu : le témoin ne s'allume pas"

    def ocr_plante():
        raise RuntimeError("C:\\Users\\x\\AppData\\détail interne")

    ctx.album.lire_ecran = ocr_plante
    r = client.post("/api/traduction/ecran", json={})
    assert r.status_code == 500 and "AppData" not in r.text
    assert traduction["pulses"] == pulses + 1


def test_traduction_texte_vide_panne_delai_et_troncature(client, app, traduction, monkeypatch):
    traduction["texte"] = "   \n  "
    r = client.post("/api/traduction/ecran", json={})
    assert r.status_code == 422 and not traduction["appels"]

    traduction["texte"] = "Error 402"
    traduction["reponse"] = ConnectorError("Anthropic API: overloaded_error (clé sk-ant-…)")
    r = client.post("/api/traduction/ecran", json={})
    assert r.status_code == 502
    assert "Anthropic" not in r.text and "sk-ant" not in r.text and "VELA" in r.json()["detail"]

    traduction["reponse"] = "   "
    assert client.post("/api/traduction/ecran", json={}).status_code == 502

    async def lent():
        await asyncio.sleep(2)
        return "trop tard"

    traduction["reponse"] = lent
    monkeypatch.setattr(album_mod, "DELAI_MOTEUR_S", 0.05)
    r = client.post("/api/traduction/ecran", json={})
    assert r.status_code == 504 and "à temps" in r.json()["detail"]

    traduction["reponse"] = "traduit"
    traduction["texte"] = "\n".join(f"Ligne numéro {i} du document affiché" for i in range(400))
    corps = client.post("/api/traduction/ecran", json={}).json()
    assert corps["tronque"] is True
    assert len(corps["texte_original"]) <= album_mod.TEXTE_MAX_TRADUCTION
    assert corps["texte_original"].endswith("du document affiché")  # coupé entre deux lignes
