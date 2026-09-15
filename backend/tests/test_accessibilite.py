"""Vision d'accessibilité (interface A, chantier du 2026-09-13).

Tout est synthétique : images générées par Pillow, fausse caméra, faux moteur (connecteur simulé),
faux OCR (monkeypatch). Aucun réseau, aucun Bluetooth, aucun modèle.

Ce qui est protégé ici, pour une personne qui ne peut pas vérifier ce qu'IRIS lui dit :
- rien ne part sans consentement, et un refus arrive AVANT de photographier quand le mode n'a pas
  de chemin local ;
- la lecture passe d'abord par l'OCR local, et une « remise en ordre » qui résume est rejetée ;
- le mode 100 % local, le mode confidentiel et la mémoire suspendue sont respectés et le disent ;
- la caméra des lunettes allume son témoin, dit « Photo. », et ses refus sont rendus mot pour mot ;
- les consignes au moteur exigent l'ordre spatial, les montants exacts et l'absence d'identification.
"""
from __future__ import annotations

import base64
import io
from pathlib import Path

import pytest

import iris.accessibilite as acc
import iris.chat as chat_module
from iris.connectors.base import BaseConnector, Chunk
from iris.lunettes_camera import CameraIndisponible, ProtocoleNonConfirme, ResultatPhoto

# Lunettes d'abord (2026-09-13) : ces tests portent sur la fonction elle-même, lunettes présentes.
# La garde est vérifiée à part, avec et sans lunettes, dans test_garde_lunettes.py.
pytestmark = pytest.mark.usefixtures("lunettes_presentes")

NOMS_INTERDITS = ("claude", "anthropic", "openai", "gpt", "gemini", "google", "elevenlabs", "vosk", "piper",
                  "rapidocr", "openrouter")


# --------------------------------------------------------------------------- une seule application
# Créer l'application et son cycle de vie coûte près de deux secondes : une par test dépasserait
# largement la limite de 20 s du fichier. Une seule instance pour le module, remise à zéro entre
# chaque test (réglages, consentements, moteur, mémoire, journal, caméra).
@pytest.fixture(scope="module")
def _application(tmp_path_factory):
    from fastapi.testclient import TestClient

    from iris.main import create_app

    dossier = tmp_path_factory.mktemp("iris-vision")
    application = create_app(data_dir=dossier, token="test-token", use_keyring=False, enable_tts=False)
    with TestClient(application, headers={"Authorization": "Bearer test-token"}) as c:
        yield application, c
    application.state.ctx.close()


@pytest.fixture()
def app(_application):
    application, _c = _application
    yield application
    ctx = application.state.ctx
    ctx.settings.update({"local_only": False, "privacy_mode": False, "verbosite": "normal", "annonce_capture": True,
                         "vision_model": "", "agents": {"claude": {"active": False}}})
    ctx.secrets.delete_api_key("claude")
    for type_donnee in ("transcript", "audio_raw", "image", "screen", "memory"):
        ctx.consent.set(type_donnee, False)
    ctx.memory.clear()
    for raison in ctx.memory.raisons_suspension():
        ctx.memory.reprendre(raison)
    if hasattr(ctx, "journal"):
        del ctx.journal
    ctx.accessibilite.fabrique_camera = lambda: acc.CameraLunettes(ctx.glasses)
    ctx.capture.set(camera=False)


@pytest.fixture()
def client(app, _application):
    return _application[1]


@pytest.fixture()
def data_dir(app):
    return app.state.ctx.settings.data_dir


# --------------------------------------------------------------------------- outils de test
def jpeg(couleur=(200, 200, 200), taille=(160, 120)) -> bytes:
    from PIL import Image

    tampon = io.BytesIO()
    Image.new("RGB", taille, couleur).save(tampon, format="JPEG", quality=90)
    return tampon.getvalue()


def image_json(couleur=(200, 200, 200)) -> dict:
    return {"media_type": "image/jpeg", "data": base64.b64encode(jpeg(couleur)).decode()}


class FauxMoteur(BaseConnector):
    """Connecteur simulé : enregistre ce qu'il reçoit et rend un texte choisi par le test."""

    name = "claude"
    supports_tools = True
    supports_images = True
    appels: list[dict] = []
    reponse = "Une table en bois au centre, une chaise à gauche."
    attente = 0.0  # un moteur qui tarde à répondre (délai maximal)

    def __init__(self):
        super().__init__("cle", "faux-modele")

    async def stream(self, messages, system, tools=None, run_tool=None, options=None):
        FauxMoteur.appels.append({"messages": messages, "system": system, "tools": tools, "options": options})
        if FauxMoteur.attente:
            import asyncio

            await asyncio.sleep(FauxMoteur.attente)
        yield Chunk("text", text=FauxMoteur.reponse)
        yield Chunk("done")

    async def test(self):  # pragma: no cover
        return {"ok": True}


@pytest.fixture()
def moteur(monkeypatch, client):
    """Un moteur externe prêt (clé présente), sans aucun consentement accordé."""
    FauxMoteur.appels = []
    FauxMoteur.reponse = "Une table en bois au centre, une chaise à gauche."
    FauxMoteur.attente = 0.0
    monkeypatch.setattr(chat_module, "build_connector", lambda name, settings, secrets: FauxMoteur())
    client.put("/api/agents/claude", json={"active": True, "api_key": "sk-test-vision"})
    return FauxMoteur


def accorder(client, *types):
    for t in types:
        assert client.put(f"/api/consent/{t}", json={"granted": True}).status_code == 200


class FausseCamera:
    def __init__(self, ctx, dossier: Path, erreur: Exception | None = None, couleur=(30, 60, 200)):
        self.ctx = ctx
        self.dossier = dossier
        self.erreur = erreur
        self.couleur = couleur
        self.prises = 0
        self.temoin_pendant: bool | None = None

    async def prendre_photo(self, reconnaissance: bool = False, timeout: float = 20.0):
        self.prises += 1
        self.temoin_pendant = self.ctx.capture.snapshot()["camera"]
        if self.erreur is not None:
            raise self.erreur
        self.dossier.mkdir(parents=True, exist_ok=True)
        chemin = self.dossier / f"lunettes-test-{self.prises}.jpg"
        chemin.write_bytes(jpeg(self.couleur))
        return ResultatPhoto(ok=True, chemin=str(chemin), octets=chemin.stat().st_size, constat="Photo reçue.")


@pytest.fixture()
def service(app, client):
    return app.state.ctx.accessibilite


@pytest.fixture()
def camera(app, service, data_dir):
    cam = FausseCamera(app.state.ctx, data_dir / "captures")
    service.fabrique_camera = lambda: cam
    return cam


@pytest.fixture()
def paroles(service, monkeypatch):
    dites: list[str] = []

    async def dire(texte: str) -> None:
        dites.append(texte)

    monkeypatch.setattr(service, "_dire", dire)
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


FAUX_OCR = [
    {"text": "Miguel", "confidence": 0.99, "left": 100, "top": 12, "right": 180, "bottom": 32},
    {"text": "Bonjour", "confidence": 0.99, "left": 10, "top": 10, "right": 90, "bottom": 30},
    {"text": "Rendez-vous mardi à 14 h au 200 rue Principale.", "confidence": 0.97, "left": 10, "top": 60, "right": 400, "bottom": 82},
]
TEXTE_OCR = "Bonjour Miguel\nRendez-vous mardi à 14 h au 200 rue Principale."


@pytest.fixture()
def faux_ocr(monkeypatch):
    monkeypatch.setattr(acc, "ocr_disponible", lambda: True)
    monkeypatch.setattr(acc, "_ocr_items", lambda octets, largeur_max=1600: list(FAUX_OCR))


# --------------------------------------------------------------------------- modes et consignes
def test_la_liste_des_modes_est_complete_honnete_et_sans_fournisseur(client):
    r = client.get("/api/accessibilite/modes")
    assert r.status_code == 200
    modes = r.json()["modes"]
    assert [m["id"] for m in modes] == ["scene", "lecture", "objet", "couleur", "billets", "personnes", "affichage", "ecran"]
    for m in modes:
        assert m["nom"] and m["description"] and m["limite"] and isinstance(m["local"], bool)
        texte = (m["nom"] + m["description"] + m["limite"]).lower()
        assert not any(n in texte for n in NOMS_INTERDITS), m
        assert "toujours" not in texte and "parfait" not in texte and "instantan" not in texte
    par_id = {m["id"]: m for m in modes}
    assert par_id["lecture"]["local"] and not par_id["billets"]["local"]
    assert "direct" in par_id["scene"]["limite"], "la scène doit dire que ce n'est pas une vision en direct"
    assert "reconnaît personne" in par_id["personnes"]["limite"]


def test_les_consignes_exigent_exactitude_ordre_et_verbosite():
    billets = acc.consigne_systeme("billets", "lunettes", "normal")
    for attendu in ("5 $", "10 $", "20 $", "50 $", "100 $", "5 ¢", "2 $", "total", "certitude", "gauche à droite",
                    "je ne suis pas sûre", "mot pour mot"):
        assert attendu in billets, attendu
    personnes = acc.consigne_systeme("personnes", "image", "normal")
    assert "jamais les identifier" in personnes and "INTERDIT" in personnes and "l'âge" in personnes
    lecture = acc.consigne_systeme("lecture", "lunettes", "concis")
    assert "Ne résume pas" in lecture and "lis tout" in lecture
    assert "une ou deux phrases" in acc.consigne_systeme("scene", "lunettes", "concis")
    assert "riche et complète" in acc.consigne_systeme("scene", "lunettes", "descriptif")
    for mode in acc.MODES:
        consigne = acc.consigne_systeme(mode, "ecran", "normal").lower()
        # « ni quelle entreprise » est permis ; aucun nom de fournisseur ne doit y figurer
        assert not any(n in consigne for n in NOMS_INTERDITS), mode


def test_la_verbosite_entre_dans_le_prompt_du_chat(app):
    chat = app.state.ctx.chat
    settings = app.state.ctx.settings
    normal = chat._system_prompt("openrouter", has_tools=False, memory_ctx="", source="voice")
    assert "une ou deux phrases orales" in normal and "VERBOSITÉ CHOISIE" not in normal
    settings.update({"verbosite": "descriptif"})
    descriptif = chat._system_prompt("openrouter", has_tools=False, memory_ctx="", source="voice")
    assert "VERBOSITÉ CHOISIE PAR L'UTILISATEUR : descriptive" in descriptif
    assert "une ou deux phrases orales" not in descriptif and "une ou deux phrases parlées" not in descriptif
    assert "RÈGLE ABSOLUE DE LANGUE" in descriptif and "IDENTITÉ" in descriptif
    settings.update({"verbosite": "concis"})
    concis = chat._system_prompt("openrouter", has_tools=False, memory_ctx="", source="text")
    assert "VERBOSITÉ CHOISIE PAR L'UTILISATEUR : concise" in concis


# --------------------------------------------------------------------------- demander_image
def test_demander_image_envoie_une_question_unique_sans_outils_au_modele_vision(app, client, moteur):
    ctx = app.state.ctx
    ctx.settings.update({"vision_model": "modele-vision"})
    accorder(client, "image")
    import asyncio

    texte = asyncio.run(ctx.chat.demander_image("Consigne", "Décris.", [{"media_type": "image/jpeg", "data": "QUJD"}]))
    assert texte == moteur.reponse
    appel = moteur.appels[-1]
    assert appel["tools"] is None and appel["system"] == "Consigne"
    assert appel["options"].model_override == "modele-vision" and appel["options"].max_rounds == 1
    assert not appel["options"].force_tools
    contenu = appel["messages"][0]["content"]
    assert contenu[0] == {"type": "image", "media_type": "image/jpeg", "data": "QUJD"}
    assert contenu[-1] == {"type": "text", "text": "Décris."}
    envois = [e for e in ctx.consent.events() if e["event_type"] == "external_send" and e["data_type"] == "image"]
    assert envois, "tout envoi d'image doit être journalisé"


def test_demander_image_refuse_sans_consentement(app, client, moteur):
    import asyncio

    from iris.consent import ConsentRequired

    with pytest.raises(ConsentRequired):
        asyncio.run(app.state.ctx.chat.demander_image("C", "M", [{"media_type": "image/jpeg", "data": "QUJD"}]))
    assert moteur.appels == [], "rien ne doit partir sans consentement"


# --------------------------------------------------------------------------- décrire : image fournie
def test_decrire_une_image_fournie_memorise_et_publie(app, client, moteur, evenements):
    accorder(client, "image")
    ctx = app.state.ctx
    avant = ctx.memory.count()
    r = client.post("/api/accessibilite/decrire",
                    json={"mode": "scene", "source": "image", "image": image_json(), "parler": False})
    assert r.status_code == 200, r.text
    corps = r.json()
    assert corps["ok"] and corps["mode"] == "scene" and corps["source"] == "image"
    assert corps["texte"] == moteur.reponse and corps["local"] is False and corps["chemin"] is None
    assert isinstance(corps["duree_ms"], int)
    appel = moteur.appels[-1]
    assert "gauche à droite" in appel["system"] and "photo fournie" in appel["system"]
    assert appel["messages"][0]["content"][0]["type"] == "image"
    assert ctx.memory.count() == avant + 1
    souvenir = ctx.memory.list(limit=1)[0]
    assert souvenir["text"].startswith("[Photo ") and souvenir["source"] == "photo" and souvenir["kind"] == "vision"
    resultats = [e for e in evenements if e["type"] == "vision.resultat"]
    assert resultats and resultats[-1]["texte"] == moteur.reponse and resultats[-1]["local"] is False


def test_la_question_exige_aussi_le_consentement_texte(app, client, moteur):
    accorder(client, "image")
    r = client.post("/api/accessibilite/decrire", json={
        "mode": "objet", "source": "image", "image": image_json(), "question": "C'est quelle date de péremption ?",
        "parler": False})
    assert r.status_code == 403
    assert r.json()["detail"]["data_type"] == "transcript" and moteur.appels == []
    accorder(client, "transcript")
    r = client.post("/api/accessibilite/decrire", json={
        "mode": "objet", "source": "image", "image": image_json(), "question": "C'est quelle date de péremption ?",
        "parler": False})
    assert r.status_code == 200
    assert "date de péremption" in moteur.appels[-1]["messages"][0]["content"][-1]["text"]


def test_parler_lit_la_description(client, moteur, paroles):
    accorder(client, "image")
    r = client.post("/api/accessibilite/decrire", json={"mode": "objet", "source": "image", "image": image_json()})
    assert r.status_code == 200 and paroles == [moteur.reponse]


@pytest.mark.parametrize("corps, attendu", [
    ({"mode": "radar", "source": "image", "image": image_json()}, "Mode de description inconnu"),
    ({"mode": "scene", "source": "image"}, "Image manquante"),
    ({"mode": "scene", "source": "image", "image": {"media_type": "image/jpeg", "data": "pas du base64 !!"}}, "base64"),
    ({"mode": "scene", "source": "satellite"}, "Source inconnue"),
])
def test_les_demandes_invalides_repondent_422_en_francais(client, corps, attendu):
    r = client.post("/api/accessibilite/decrire", json={**corps, "parler": False})
    assert r.status_code == 422 and attendu in r.json()["detail"]


# --------------------------------------------------------------------------- consentement, local, confidentiel
def test_consentement_refuse_403_avant_de_photographier(app, client, moteur, camera, paroles):
    r = client.post("/api/accessibilite/decrire", json={"mode": "scene", "source": "lunettes", "parler": False})
    assert r.status_code == 403
    detail = r.json()["detail"]
    assert detail["code"] == "consentement" and detail["data_type"] == "image" and detail["label"]
    assert camera.prises == 0, "on ne photographie pas une scène qu'on ne pourra pas décrire"
    assert paroles == [] and moteur.appels == []


def test_local_only_409_pour_un_mode_qui_exige_le_moteur(app, client, camera):
    app.state.ctx.settings.update({"local_only": True})
    r = client.post("/api/accessibilite/decrire", json={"mode": "billets", "source": "lunettes", "parler": False})
    assert r.status_code == 409 and "100 % local" in r.json()["detail"]
    assert camera.prises == 0


def test_mode_confidentiel_refuse_tout(app, client, camera):
    app.state.ctx.settings.update({"privacy_mode": True})
    r = client.post("/api/accessibilite/decrire", json={"mode": "lecture", "source": "lunettes", "parler": False})
    assert r.status_code == 409 and "confidentiel" in r.json()["detail"]
    assert camera.prises == 0


# --------------------------------------------------------------------------- lecture : OCR local d'abord
def test_lecture_en_mode_local_rend_le_texte_ocr_verbatim(app, client, moteur, faux_ocr):
    app.state.ctx.settings.update({"local_only": True})
    r = client.post("/api/accessibilite/decrire", json={"mode": "lecture", "source": "image", "image": image_json(), "parler": False})
    assert r.status_code == 200, r.text
    corps = r.json()
    assert corps["texte"] == TEXTE_OCR and corps["local"] is True
    assert "100 % local" in corps["note"]
    assert moteur.appels == [], "en mode local, aucun moteur externe"


def test_lecture_sans_consentement_rend_le_texte_ocr_brut(client, moteur, faux_ocr):
    r = client.post("/api/accessibilite/decrire", json={"mode": "lecture", "source": "image", "image": image_json(), "parler": False})
    assert r.status_code == 200
    corps = r.json()
    assert corps["texte"] == TEXTE_OCR and corps["local"] is True and "Confidentialité" in corps["note"]
    assert moteur.appels == []


def test_lecture_remise_en_ordre_par_le_moteur_quand_autorise(client, moteur, faux_ocr):
    accorder(client, "image")
    moteur.reponse = "Bonjour Miguel. Rendez-vous mardi à 14 h au 200 rue Principale."
    r = client.post("/api/accessibilite/decrire", json={"mode": "lecture", "source": "image", "image": image_json(), "parler": False})
    corps = r.json()
    assert corps["texte"] == moteur.reponse and corps["local"] is False
    envoye = moteur.appels[-1]["messages"][0]["content"][-1]["text"]
    assert TEXTE_OCR in envoye, "le moteur reçoit la lecture locale à remettre en ordre"


def test_une_remise_en_ordre_qui_resume_est_rejetee(client, moteur, faux_ocr):
    accorder(client, "image")
    moteur.reponse = "C'est une invitation à un rendez-vous."
    r = client.post("/api/accessibilite/decrire", json={"mode": "lecture", "source": "image", "image": image_json(), "parler": False})
    assert r.json()["texte"] == TEXTE_OCR, "un résumé présenté comme une lecture est refusé"


def test_lecture_sans_ocr_ni_moteur_dit_les_deux_limites(app, client, monkeypatch):
    monkeypatch.setattr(acc, "ocr_disponible", lambda: False)
    app.state.ctx.settings.update({"local_only": True})
    r = client.post("/api/accessibilite/decrire", json={"mode": "lecture", "source": "image", "image": image_json(), "parler": False})
    assert r.status_code == 409
    assert "100 % local" in r.json()["detail"] and "lecture locale du texte" in r.json()["detail"]


def test_affichage_sans_moteur_rend_le_texte_brut_et_le_dit(app, client, faux_ocr):
    app.state.ctx.settings.update({"local_only": True})
    r = client.post("/api/accessibilite/decrire", json={"mode": "affichage", "source": "image", "image": image_json(), "parler": False})
    corps = r.json()
    assert corps["local"] and corps["texte"].startswith("Lecture locale du texte visible, sans interprétation")


def test_lecture_fidele():
    assert acc.lecture_fidele(TEXTE_OCR, "Bonjour Miguel. Rendez-vous mardi à 14 h au 200, rue Principale.")
    assert not acc.lecture_fidele(TEXTE_OCR, "Un rendez-vous.")
    assert not acc.lecture_fidele(TEXTE_OCR, TEXTE_OCR + " " + "mots inventés " * 20)


def test_ocr_sur_image_reutilise_le_rangement_de_la_lecture_decran(monkeypatch):
    class FauxMoteurOcr:
        def __call__(self, tableau):
            assert tableau.shape[2] == 3
            return ([[[[100, 12], [180, 12], [180, 32], [100, 32]], "Miguel", 0.99],
                     [[[10, 10], [90, 10], [90, 30], [10, 30]], "Bonjour", 0.99]], 0.1)

    monkeypatch.setattr(acc.actions, "_ocr_engine", FauxMoteurOcr())
    assert acc.lire_texte_image(jpeg()) == "Bonjour Miguel"


# --------------------------------------------------------------------------- couleur locale
@pytest.mark.parametrize("rvb, attendu", [
    ((230, 20, 20), "rouge"), ((20, 40, 230), "bleu"), ((20, 190, 40), "vert"), ((250, 250, 250), "blanc"),
    ((5, 5, 5), "noir"), ((120, 70, 20), "brun"), ((240, 220, 20), "jaune"),
])
def test_couleur_dominante_locale(rvb, attendu):
    assert acc.couleur_dominante(jpeg(rvb)).startswith(attendu)


def test_couleur_sans_moteur_est_une_estimation_annoncee(app, client):
    app.state.ctx.settings.update({"local_only": True})
    r = client.post("/api/accessibilite/decrire", json={"mode": "couleur", "source": "image", "image": image_json((230, 20, 20)), "parler": False})
    corps = r.json()
    assert r.status_code == 200 and corps["local"]
    assert "rouge" in corps["texte"] and "Estimation locale" in corps["texte"] and "éclairage" in corps["texte"]


# --------------------------------------------------------------------------- lunettes
def test_photo_des_lunettes_temoin_annonce_et_album(app, client, moteur, camera, paroles, evenements):
    accorder(client, "image")
    ctx = app.state.ctx
    ctx.settings.update({"vision_garder_photos": True})  # réglage explicite : sans lui, la photo n'est pas gardée
    r = client.post("/api/accessibilite/decrire", json={"mode": "scene", "source": "lunettes", "parler": False})
    assert r.status_code == 200, r.text
    corps = r.json()
    assert camera.prises == 1 and camera.temoin_pendant is True
    assert ctx.capture.snapshot()["camera"] is False, "le témoin de caméra s'éteint après la photo"
    assert paroles == ["Photo."]
    assert corps["chemin"] and Path(corps["chemin"]).exists()
    assert "caméra des lunettes" in moteur.appels[-1]["system"]
    nom = Path(corps["chemin"]).name
    # origine « description » : l'album ne recopie pas ces photos vers le dossier Images.
    assert any(e["type"] == "album.nouveau" and e["nom"] == nom and e["genre"] == "photo"
               and e.get("origine") == "description" for e in evenements)
    assert ctx.memory.list(limit=1)[0]["source_text"] == nom
    assert "non chiffrée" in corps["note"], "garder la photo se dit, avec ce qu'elle devient"


def test_sans_le_reglage_la_photo_decrite_nest_pas_gardee(app, client, moteur, camera, paroles, evenements):
    """Demande de la revue service-a : aucune image conservée sans réglage explicite (défaut : désactivé).
    La description, elle, est retenue ; la note dit que la photo ne l'est pas."""
    accorder(client, "image")
    ctx = app.state.ctx
    from iris.config import UserSettings

    assert UserSettings().vision_garder_photos is False, "désactivé par défaut"
    ctx.settings.update({"vision_garder_photos": False})
    r = client.post("/api/accessibilite/decrire", json={"mode": "scene", "source": "lunettes", "parler": False})
    assert r.status_code == 200, r.text
    corps = r.json()
    assert corps["chemin"] is None and not any(camera.dossier.glob("*.jpg"))
    assert not any(e["type"] in ("album.nouveau", "glasses.photo") for e in evenements)
    assert ctx.memory.count() == 1, "la description reste retenue"
    assert "n'a pas été gardée" in corps["note"]


def test_memoriser_faux_efface_la_photo_des_lunettes(app, client, moteur, camera, paroles, evenements):
    """Demander une description n'est pas demander de garder la photo (d'une lettre, de billets, de passants)."""
    accorder(client, "image")
    r = client.post("/api/accessibilite/decrire", json={"mode": "billets", "source": "lunettes", "parler": False,
                                                        "memoriser": False})
    corps = r.json()
    assert r.status_code == 200 and corps["texte"] == moteur.reponse and camera.prises == 1
    assert corps["chemin"] is None and not any(camera.dossier.glob("*.jpg")), "la photo est effacée tout de suite"
    assert not any(e["type"] in ("album.nouveau", "glasses.photo") for e in evenements)
    assert not (corps["note"] or "").count("gardée")


def test_une_description_ratee_ne_garde_pas_la_photo(app, client, moteur, camera, paroles):
    accorder(client, "image")
    moteur.reponse = ""
    corps = client.post("/api/accessibilite/decrire", json={"mode": "scene", "source": "lunettes", "parler": False}).json()
    assert corps["texte"] == acc.DESCRIPTION_RATEE and corps["chemin"] is None
    assert not any(camera.dossier.glob("*.jpg"))


# --------------------------------------------------------------------------- délai maximal du moteur
def test_un_moteur_trop_lent_repond_504_et_ne_garde_pas_la_photo(app, client, moteur, camera, paroles, monkeypatch):
    accorder(client, "image")
    monkeypatch.setattr(acc, "DELAI_MOTEUR_S", 0.3)
    moteur.attente = 3.0
    import time as _time

    debut = _time.monotonic()
    r = client.post("/api/accessibilite/decrire", json={"mode": "scene", "source": "lunettes", "parler": False})
    assert r.status_code == 504 and r.json()["detail"] == acc.MOTEUR_LENT
    assert _time.monotonic() - debut < 2.5, "la requête n'attend pas le moteur au-delà du délai"
    assert not any(camera.dossier.glob("*.jpg"))
    # À la voix : une phrase courte, pas un gel de 90 s suivi d'un second envoi par le modèle.
    assert app.state.ctx.voice._intercepter("qu'est-ce qu'il y a devant moi") == acc.MOTEUR_LENT_PHRASE


def test_lecture_retombe_sur_le_texte_local_quand_le_moteur_est_trop_lent(client, moteur, faux_ocr, monkeypatch):
    accorder(client, "image")
    monkeypatch.setattr(acc, "DELAI_MOTEUR_S", 0.3)
    moteur.attente = 3.0
    r = client.post("/api/accessibilite/decrire", json={"mode": "lecture", "source": "image", "image": image_json(),
                                                        "parler": False})
    assert r.status_code == 200 and r.json()["texte"] == TEXTE_OCR


def test_sans_annonce_de_capture_pas_de_photo_dite(app, client, moteur, camera, paroles):
    accorder(client, "image")
    app.state.ctx.settings.update({"annonce_capture": False})
    assert client.post("/api/accessibilite/decrire", json={"mode": "objet", "source": "lunettes", "parler": False}).status_code == 200
    assert paroles == []


def test_le_temoin_reste_allume_si_un_autre_service_utilise_la_camera(app, client, moteur, camera, paroles):
    accorder(client, "image")
    app.state.ctx.capture.set(camera=True)
    client.post("/api/accessibilite/decrire", json={"mode": "scene", "source": "lunettes", "parler": False})
    assert app.state.ctx.capture.snapshot()["camera"] is True


@pytest.mark.parametrize("erreur", [
    CameraIndisponible("Les lunettes ne sont pas connectées."),
    ProtocoleNonConfirme("La commande photo est identifiée, mais l'en-tête exact de la trame n'est pas encore confirmé."),
])
def test_camera_indisponible_409_avec_le_message_exact(app, client, moteur, camera, paroles, erreur):
    accorder(client, "image")
    camera.erreur = erreur
    r = client.post("/api/accessibilite/decrire", json={"mode": "scene", "source": "lunettes", "parler": False})
    # {code, message} depuis le 2026-09-14 : la phrase client, jamais le texte technique du module caméra.
    from iris.lunettes_camera import refus_camera_client

    assert r.status_code == 409 and r.json()["detail"] == refus_camera_client(erreur)
    assert "trame" not in r.json()["detail"]["message"]
    assert app.state.ctx.capture.snapshot()["camera"] is False
    assert moteur.appels == []


def test_la_vraie_camera_sans_lunettes_refuse_sans_annoncer_de_photo(app, client, moteur, paroles):
    accorder(client, "image")
    # fabrique par défaut : la vraie CameraLunettes sur le GlassesService, non connecté en test
    r = client.post("/api/accessibilite/decrire", json={"mode": "scene", "source": "lunettes", "parler": False})
    assert r.status_code == 409 and "pas connectées" in r.json()["detail"]
    assert paroles == [], "annoncer « Photo. » sans photo serait mentir aux personnes autour"


# --------------------------------------------------------------------------- mémoire suspendue et journal
class FauxJournal:
    def __init__(self, entrees=None):
        self.ajouts: list[tuple[str, str]] = []
        self.entrees = entrees or []

    def ajouter(self, texte, source):
        self.ajouts.append((texte, source))

    def chercher(self, question, debut=None, fin=None, limit=20):
        return [e for e in self.entrees if any(m in e["texte"].lower() for m in question.lower().split())]


def test_la_description_va_aussi_au_journal(app, client, moteur, camera, paroles):
    accorder(client, "image")
    journal = FauxJournal()
    app.state.ctx.journal = journal
    client.post("/api/accessibilite/decrire", json={"mode": "scene", "source": "lunettes", "parler": False})
    assert journal.ajouts == [(moteur.reponse, "photo")]


def test_memoire_suspendue_rien_nest_ecrit_et_la_photo_est_effacee(app, client, moteur, camera, paroles):
    accorder(client, "image")
    ctx = app.state.ctx
    journal = FauxJournal()
    ctx.journal = journal
    avant = ctx.memory.count()
    ctx.memory.suspendre("invite")
    try:
        r = client.post("/api/accessibilite/decrire", json={"mode": "scene", "source": "lunettes", "parler": False})
    finally:
        ctx.memory.reprendre("invite")
    corps = r.json()
    assert r.status_code == 200 and corps["texte"] == moteur.reponse
    assert corps["chemin"] is None and "Mémoire suspendue" in corps["note"]
    assert not any(camera.dossier.glob("*.jpg")), "la photo décrite n'est pas gardée en mode invité"
    assert ctx.memory.count() == avant and journal.ajouts == []


def test_memoriser_faux_ne_retient_rien(app, client, moteur):
    accorder(client, "image")
    avant = app.state.ctx.memory.count()
    client.post("/api/accessibilite/decrire", json={"mode": "scene", "source": "image", "image": image_json(),
                                                    "parler": False, "memoriser": False})
    assert app.state.ctx.memory.count() == avant


# --------------------------------------------------------------------------- écran
def test_ecran_exige_le_consentement_captures_et_retombe_sur_le_texte(app, client, moteur, faux_ocr, monkeypatch):
    from iris.pc import actions

    monkeypatch.setattr(actions, "take_screenshot", lambda *a, **k: {
        "media_type": "image/jpeg", "data": base64.b64encode(jpeg()).decode(), "width": 160, "height": 120})
    accorder(client, "image")  # le consentement « images » ne vaut pas pour l'écran
    r = client.post("/api/accessibilite/decrire", json={"mode": "ecran", "source": "lunettes", "parler": False})
    corps = r.json()
    assert r.status_code == 200 and corps["source"] == "ecran" and corps["local"] is True
    assert corps["texte"].startswith("Sans le moteur VELA") and "Bonjour Miguel" in corps["texte"]
    assert moteur.appels == []
    accorder(client, "screen")
    r = client.post("/api/accessibilite/decrire", json={"mode": "ecran", "source": "ecran", "parler": False})
    assert r.json()["local"] is False and "capture de l'écran" in moteur.appels[-1]["system"]
    assert any(e["data_type"] == "screen" for e in app.state.ctx.consent.events() if e["event_type"] == "external_send")


# --------------------------------------------------------------------------- où ai-je posé…
def test_ou_est_rend_le_souvenir_photo_tel_quel_sans_consentement(app, client, moteur):
    memoire = app.state.ctx.memory
    memoire.add("J'aime les clés de sol en musique.", source="conversation", kind="fact")
    memoire.add("[Photo 14:02] Un trousseau de clés sur la table de la cuisine, à gauche du bol.", source="photo", kind="vision")
    r = client.post("/api/accessibilite/ou-est", json={"question": "Où j'ai posé mes clés ?"})
    assert r.status_code == 200
    corps = r.json()
    assert corps["local"] is True and moteur.appels == []
    assert "table de la cuisine" in corps["reponse"] and "déplacé" in corps["reponse"]
    assert corps["souvenirs"][0]["texte"].startswith("[Photo 14:02]"), "les souvenirs photo passent d'abord"
    assert set(corps["souvenirs"][0]) == {"id", "texte", "date"}


def test_ou_est_formule_par_le_moteur_avec_consentement(app, client, moteur):
    accorder(client, "transcript", "memory")
    app.state.ctx.memory.add("[Photo 09:15] Des lunettes de soleil sur le comptoir.", source="photo", kind="vision")
    moteur.reponse = "D'après ta photo de 9 h 15, tes lunettes de soleil étaient sur le comptoir."
    r = client.post("/api/accessibilite/ou-est", json={"question": "où sont passées mes lunettes de soleil"})
    corps = r.json()
    assert corps["reponse"] == moteur.reponse and corps["local"] is False
    assert "comptoir" in moteur.appels[-1]["messages"][0]["content"], "question texte : contenu simple"


def test_ou_est_sans_souvenir_le_dit(client, moteur):
    r = client.post("/api/accessibilite/ou-est", json={"question": "où j'ai mis mon parapluie"})
    assert "aucun souvenir" in r.json()["reponse"] and r.json()["souvenirs"] == []


def test_ou_est_consulte_le_journal(app, client):
    app.state.ctx.journal = FauxJournal([{"id": "j1", "ts": "2026-09-13T15:00:00+00:00", "texte": "J'ai laissé mon portefeuille dans l'auto.", "source": "sous_titres"}])
    r = client.post("/api/accessibilite/ou-est", json={"question": "où est mon portefeuille"})
    assert "auto" in r.json()["reponse"]


def test_mode_invite_ne_livre_ni_souvenirs_ni_journal(app, client, paroles):
    """Un invité n'obtient pas, par « où ai-je posé… », les souvenirs ou les conversations du propriétaire."""
    ctx = app.state.ctx
    ctx.memory.add("[Photo 10:00] Des clés posées sur la table de la cuisine.", source="photo", kind="vision")
    ctx.journal = FauxJournal([{"id": "j1", "ts": "2026-09-13T15:00:00+00:00",
                                "texte": "J'ai caché mes clés dans le tiroir du bureau.", "source": "sous_titres"}])
    ctx.memory.suspendre("invite")
    try:
        r = client.post("/api/accessibilite/ou-est", json={"question": "Où j'ai posé mes clés ?"})
        assert r.status_code == 200
        assert r.json() == {"reponse": acc.MODE_INVITE_SOUVENIRS, "souvenirs": [], "local": True}
        assert ctx.voice._intercepter("où j'ai posé mes clés") == acc.MODE_INVITE_SOUVENIRS
        assert ctx.voice._intercepter("où sont mes clés") is None, "phrase générique : la garde du chat s'applique"
        corps = r.text
        assert "cuisine" not in corps and "tiroir" not in corps
    finally:
        ctx.memory.reprendre("invite")
    # Une zone sans mémoire, elle, ne cache pas ses propres souvenirs au propriétaire.
    ctx.memory.suspendre("zone:Clinique")
    try:
        assert "cuisine" in client.post("/api/accessibilite/ou-est", json={"question": "Où j'ai posé mes clés ?"}).json()["reponse"]
    finally:
        ctx.memory.reprendre("zone:Clinique")


# --------------------------------------------------------------------------- voix
@pytest.mark.parametrize("phrase, attendu", [
    ("qu'est-ce qu'il y a devant moi", ("scene", "lunettes")),
    ("Décris ce que je vois", ("scene", "lunettes")),
    ("lis-moi ça", ("lecture", "lunettes")),
    ("lis ce texte", ("lecture", "lunettes")),
    ("c'est quel billet", ("billets", "lunettes")),
    ("combien d'argent", ("billets", "lunettes")),
    ("c'est quoi cet objet", ("objet", "lunettes")),
    ("c'est quelle couleur", ("couleur", "lunettes")),
    ("qui est devant moi", ("personnes", "lunettes")),
    ("c'est quel bus", ("affichage", "lunettes")),
    ("lis le panneau", ("affichage", "lunettes")),
    ("décris l'écran", ("ecran", "ecran")),
    ("où j'ai posé mes clés", ("ou-est", "lunettes")),
    ("où est mon portefeuille", ("ou-est-generique", "lunettes")),
    ("Iris, c'est quel billet ça ?", ("billets", "lunettes")),
    ("quelle pièce", ("billets", "lunettes")),
    ("quel bus arrive", ("affichage", "lunettes")),
    ("c'est quoi le numéro du bus", ("affichage", "lunettes")),
    ("c'est quelle marque", ("objet", "lunettes")),
    ("lis-moi le menu", ("lecture", "lunettes")),
    # Demandes typiques d'une personne non voyante, avec une queue qui désigne ce qu'elle a sous les yeux :
    # l'ancrage « $ » seul les faisait partir au modèle (contre-vérification du 2026-09-14).
    ("c'est quel bus qui arrive", ("affichage", "lunettes")),
    ("quel bus arrive là-bas", ("affichage", "lunettes")),
    ("c'est quel autobus qui s'en vient", ("affichage", "lunettes")),
    ("c'est quelle pièce de monnaie", ("billets", "lunettes")),
    ("c'est quel billet que je tiens", ("billets", "lunettes")),
    ("quel billet je tiens", ("billets", "lunettes")),
    ("lis-moi le menu du restaurant", ("lecture", "lunettes")),
    ("lis le menu s'il te plaît", ("lecture", "lunettes")),
    ("qu'est-ce que je tiens dans la main", ("objet", "lunettes")),
    ("c'est quelle marque ce téléphone", ("objet", "lunettes")),
    ("c'est quelle couleur ce chandail", ("couleur", "lunettes")),
    ("qu'est-ce que je regarde là", ("scene", "lunettes")),
    ("de quelle couleur est ce chandail", ("couleur", "lunettes")),
    ("de quelle couleur sont mes chaussettes", ("couleur", "lunettes")),
    ("quelle est la couleur de mon chandail", ("couleur", "lunettes")),
    ("décris la pièce où je suis", ("scene", "lunettes")),
    ("décris l'endroit", ("scene", "lunettes")),
    ("décris les gens autour de moi", ("personnes", "lunettes")),
    ("décris la personne devant moi", ("personnes", "lunettes")),
    ("c'est quoi ce produit", ("objet", "lunettes")),
    ("quel est ce produit que je tiens", ("objet", "lunettes")),
    ("compte les billets", ("billets", "lunettes")),
    ("combien vaut ce billet", ("billets", "lunettes")),
    ("lis ce document", ("lecture", "lunettes")),
    ("lis ce document à l'écran", ("lecture", "ecran")),
    # Reconnues avant l'ancrage « $ », perdues par lui (finition du 2026-09-14) : queues « j'ai », « en ce
    # moment » et objet de deux mots « ma chemise de nuit » ; objet désigné par un article pour la lecture.
    ("quel billet j'ai dans la main", ("billets", "lunettes")),
    ("qu'est-ce que je regarde en ce moment", ("scene", "lunettes")),
    ("c'est de quelle couleur ma chemise de nuit", ("couleur", "lunettes")),
    ("qu'est-ce que j'ai dans la main droite", ("objet", "lunettes")),
    ("lis l'étiquette de la bouteille", ("lecture", "lunettes")),
    ("lis-moi l'étiquette de ce pot", ("lecture", "lunettes")),
    ("lis-moi le texte de ce document", ("lecture", "lunettes")),
    ("lis-moi le panneau du quai", ("affichage", "lunettes")),
    ("que dit le panneau en face de moi", ("affichage", "lunettes")),
    ("compte mon argent dans ma main", ("billets", "lunettes")),
])
def test_les_phrases_vocales_sont_reconnues(phrase, attendu):
    assert acc.reconnaitre_demande(phrase) == attendu


@pytest.mark.parametrize("phrase", [
    "ouvre youtube", "combien d'argent faut-il pour un voyage", "quel bus prendre pour aller au centre-ville",
    "quelle heure est-il", "lis mes courriels", "mets de la musique",
    # Faux positifs relevés à la revue : des questions ordinaires qui déclenchaient une photo.
    "quel billet d'avion est le moins cher", "dans quelle pièce est le chat",
    "c'est quoi le numéro du bus pour aller à Laval", "c'est quelle marque de voiture la plus fiable",
    "c'est dans quelle pièce", "pour aller à Laval c'est quel bus", "qu'est-ce que je regarde ce soir à la télé",
    "c'est quelle couleur le drapeau du Canada", "lis le menu démarrer",
    # Questions de connaissance que les motifs non ancrés interceptaient encore (contre-vérification du 2026-09-14).
    "décris la pièce de théâtre Tartuffe", "décris l'endroit où Napoléon est mort",
    "décris la personne idéale pour ce poste", "décris les gens de la Renaissance",
    "de quelle couleur est ce drapeau du Japon", "quelle couleur c'est le drapeau du Canada",
    "de quelle couleur est ma voiture préférée selon toi", "de quelle couleur est le ciel",
    "c'est quoi ce produit dont tout le monde parle", "quel est ce produit que tu m'as recommandé hier",
    "compte les billets vendus pour le concert", "lis ce document Word sur le bureau",
    "combien d'argent j'ai dans la main gauche selon toi", "lis-moi ça plus tard",
    "qu'est-ce que je regarde ce soir", "quel bus ce matin",
    # Motifs « verbe + objet » qui étaient reconnus n'importe où dans la phrase (finition du 2026-09-14) :
    # textos, courriels, fichiers, web, loi, compte bancaire, jeu de cartes.
    "lis-moi le texte de Marc", "lis-moi le texte que Julie m'a envoyé", "lis ce texte sur Wikipédia",
    "lis-moi cette lettre de la banque dans mes courriels", "lis-moi ça, le dernier courriel",
    "lis moi l'étiquette du fichier", "compte mon argent dans mon compte bancaire",
    "compte ces billets de Taylor Swift", "combien d'argent j'ai dans la main de poker",
    "que dit le panneau de la loi", "lis le panneau de configuration", "de quelle couleur est ce drapeau",
    "de quelle couleur sont mes yeux", "lis-moi le texte de la chanson", "quel billet du concert",
])
def test_les_autres_phrases_passent_leur_chemin(service, phrase):
    assert service.interception(phrase) is None


def test_ou_est_generique_exige_un_souvenir_qui_parle_de_lobjet(app, client):
    """« Où est ma commande Amazon ? » ne s'arrête pas sur une phrase entendue qui contient « commande »."""
    ctx = app.state.ctx
    ctx.journal = FauxJournal([
        {"id": "j1", "ts": "2026-09-13T15:00:00+00:00", "texte": "On a reçu la commande de papier hier.", "source": "sous_titres"},
        {"id": "j2", "ts": "2026-09-13T16:00:00+00:00", "texte": "J'ai laissé mes clés sur le comptoir.", "source": "sous_titres"},
    ])
    assert ctx.voice._intercepter("où est ma commande Amazon") is None
    reponse = ctx.voice._intercepter("où sont mes clés")
    assert reponse is not None and "comptoir" in reponse
    assert acc.couverture_objet("ma commande Amazon", "On a reçu la commande de papier hier.") == 0.5
    assert acc.couverture_objet("mes clés", "une clé USB") == 1.0


def test_linterception_est_branchee_en_priorite_40(app, client):
    interceptions = {nom: prio for prio, nom, _f in app.state.ctx.voice._interceptions}
    assert interceptions.get("vision") == 40


def test_la_voix_decrit_de_bout_en_bout(app, client, moteur, camera, paroles):
    accorder(client, "image")
    voice = app.state.ctx.voice
    assert voice.loop is not None
    assert voice._intercepter("qu'est-ce qu'il y a devant moi") == moteur.reponse
    assert camera.prises == 1 and paroles == ["Photo."], "la description est dite par l'écoute, pas deux fois"


def test_la_voix_dit_un_refus_court_et_clair(app, client, moteur, camera):
    accorder(client, "image")
    camera.erreur = ProtocoleNonConfirme("long message technique (voir docs/LUNETTES-CAMERA-PROTOCOLE.md §6)")
    phrase = app.state.ctx.voice._intercepter("c'est quel billet")
    assert "docs/" not in phrase and "pas encore activée" in phrase


def test_ou_est_generique_sans_objet_vu_laisse_le_modele_repondre(app, client):
    assert app.state.ctx.voice._intercepter("où est ma commande Amazon") is None


# --------------------------------------------------------------------------- outils du chat
def test_les_outils_sont_declares_et_relaient_le_service(app, client, moteur):
    import asyncio

    from iris.tools import ToolContext, make_tool_runner, tool_specs

    ctx = app.state.ctx
    noms = {s.name for s in tool_specs(ToolContext(settings=ctx.settings, consent=ctx.consent, capture=ctx.capture,
                                                   memory=ctx.memory, agent="test", confirm=None))}
    assert {"decrire_vue", "ou_est_objet"} <= noms
    accorder(client, "image")
    ctx.settings.update({"annonce_capture": False})
    outil = ToolContext(settings=ctx.settings, consent=ctx.consent, capture=ctx.capture, memory=ctx.memory,
                        agent="test", confirm=None, accessibilite=None)
    resultat = asyncio.run(make_tool_runner(outil)("decrire_vue", {"mode": "scene"}))
    assert resultat["is_error"] and "pas branché" in resultat["content"]
    ctx.memory.add("[Photo 08:00] Des clés sur le banc de l'entrée.", source="photo", kind="vision")
    outil.accessibilite = ctx.accessibilite
    reponse = asyncio.run(make_tool_runner(outil)("ou_est_objet", {"question": "où j'ai posé mes clés"}))
    assert "banc de l'entrée" in reponse


def test_loutil_rend_le_refus_du_service(app, client, moteur):
    import asyncio

    from iris.tools import ToolContext, make_tool_runner

    ctx = app.state.ctx
    outil = ToolContext(settings=ctx.settings, consent=ctx.consent, capture=ctx.capture, memory=ctx.memory,
                        agent="test", confirm=None, accessibilite=ctx.accessibilite)
    resultat = asyncio.run(make_tool_runner(outil)("decrire_vue", {"mode": "billets", "source": "lunettes"}))
    assert resultat["is_error"] and "Confidentialité" in resultat["content"]


def test_en_mode_local_loutil_ne_propose_que_les_modes_possibles(app, client):
    from iris.tools import ToolContext, tool_specs

    ctx = app.state.ctx
    ctx.settings.update({"local_only": True})
    outil = ToolContext(settings=ctx.settings, consent=ctx.consent, capture=ctx.capture, memory=ctx.memory,
                        agent="test", confirm=None, accessibilite=ctx.accessibilite)
    spec = next(s for s in tool_specs(outil) if s.name == "decrire_vue")
    assert spec.input_schema["properties"]["mode"]["enum"] == ["lecture", "couleur", "affichage", "ecran"]
    from iris.tools import TOOL_SPECS

    original = next(s for s in TOOL_SPECS if s.name == "decrire_vue")
    assert "scene" in original.input_schema["properties"]["mode"]["enum"], "la déclaration d'origine n'est pas modifiée"
