"""Reçus (interface G, chantier du 2026-09-13).

Tout est synthétique : textes de reçus écrits à la main (québécois TPS/TVQ, ontarien TVH), images
générées par Pillow, faux OCR (monkeypatch), faux moteur (connecteur simulé), fausse caméra. Aucun
réseau, aucun Bluetooth, aucun modèle.

Ce qui est protégé ici :
- un montant n'est jamais inventé : un champ absent reste vide, le total ne confond ni sous-total, ni
  taxes, ni monnaie rendue, et la confiance dit ce qui a été vérifié ;
- rien ne part sans « Images jointes » ; refus, mode local ou réponse illisible = extraction locale, dite ;
- tout ce qui est gardé est chiffré (données et image) ; mémoire suspendue = rien d'écrit ;
- le CSV est exactement celui qu'Excel ouvre correctement (virgule, UTF-8 avec BOM).
"""
from __future__ import annotations

import base64
import io
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

import iris.chat as chat_module
import iris.recus as recus
from iris.connectors.base import BaseConnector, Chunk
from iris.lunettes_camera import CameraIndisponible, ResultatPhoto

NOMS_INTERDITS = ("claude", "anthropic", "openai", "gpt", "gemini", "google", "elevenlabs", "vosk", "piper",
                  "rapidocr", "openrouter")
AUJOURDHUI = date(2026, 9, 13)

RECU_QUEBEC = """MÉTRO PLUS DU PLATEAU
1234, avenue du Mont-Royal Est
Montréal (Québec) H2J 1X7
Tél. : 514-555-0199
2026-09-12 14:32
LAIT 2% 2 L            5,49
PAIN TRANCHÉ           3,99
CAFÉ MOULU 340 G      12,99 FP
SOUS-TOTAL            22,47
TPS 5 %                0,65
TVQ 9,975 %            1,30
TOTAL                 24,42
VISA                  24,42
TPS/TVH No 123456789 RT0001
TVQ No 1234567890 TQ0001
MERCI DE VOTRE VISITE"""

RECU_ONTARIO = """BEST BUY #123
Toronto ON
Sep 10, 2026
USB-C CABLE          $19.99
MOUSE                $45.00
SUBTOTAL             $64.99
HST 13%               $8.45
TOTAL                $73.44
DEBIT                $73.44"""

RECU_ETIQUETTES_SEULES = """Café Olimpico
13/09/26
Latte 4,75
Croissant 3,25
Sous-total
8,00
TPS 0,40
TVQ 0,80
TOTAL
9,20
COMPTANT 20,00
MONNAIE 10,80"""


# --------------------------------------------------------------------------- une seule application
@pytest.fixture(scope="module")
def _application(tmp_path_factory):
    from fastapi.testclient import TestClient

    from iris.main import create_app

    dossier = tmp_path_factory.mktemp("iris-recus")
    application = create_app(data_dir=dossier, token="test-token", use_keyring=False, enable_tts=False)
    with TestClient(application, headers={"Authorization": "Bearer test-token"}) as c:
        yield application, c
    application.state.ctx.close()


@pytest.fixture()
def app(_application):
    application, _c = _application
    yield application
    ctx = application.state.ctx
    ctx.settings.update({"local_only": False, "privacy_mode": False, "annonce_capture": True, "retention_days": 0,
                         "recus_devise": "CAD", "agents": {"claude": {"active": False}}})
    ctx.secrets.delete_api_key("claude")
    for type_donnee in ("transcript", "audio_raw", "image", "screen", "memory"):
        ctx.consent.set(type_donnee, False)
    for raison in ctx.memory.raisons_suspension():
        ctx.memory.reprendre(raison)
    for row in ctx.db.query("SELECT id FROM recus"):
        ctx.recus.supprimer(row["id"])
    ctx.recus.fabrique_camera = ctx.recus._camera_par_defaut
    ctx.capture.set(camera=False)


@pytest.fixture()
def client(app, _application):
    return _application[1]


@pytest.fixture()
def service(app):
    return app.state.ctx.recus


def jpeg(couleur=(240, 240, 240), taille=(200, 320)) -> bytes:
    from PIL import Image

    tampon = io.BytesIO()
    Image.new("RGB", taille, couleur).save(tampon, format="JPEG", quality=90)
    return tampon.getvalue()


def image_json() -> dict:
    return {"media_type": "image/jpeg", "data": base64.b64encode(jpeg()).decode()}


def accorder(client, *types):
    for t in types:
        assert client.put(f"/api/consent/{t}", json={"granted": True}).status_code == 200


@pytest.fixture()
def faux_ocr(monkeypatch):
    lu = {"texte": RECU_QUEBEC, "appels": 0}

    def lire(octets, largeur_max=1600):
        lu["appels"] += 1
        return lu["texte"]

    monkeypatch.setattr(recus, "ocr_disponible", lambda: True)
    monkeypatch.setattr(recus, "lire_texte", lire)
    return lu


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


JSON_MOTEUR = {
    "date": "2026-09-12", "commercant": "Métro Plus du Plateau", "sous_total": 22.47, "tps": 0.65, "tvq": 1.30,
    "tvh": None, "total": 24.42, "devise": "CAD", "categorie": "Alimentation", "moyen_paiement": "Visa",
    "lignes": [{"libelle": "Lait 2 %", "montant": 5.49}], "confiance": 0.92,
}


@pytest.fixture()
def moteur(monkeypatch, client):
    FauxMoteur.appels = []
    FauxMoteur.reponse = json.dumps(JSON_MOTEUR)
    monkeypatch.setattr(chat_module, "build_connector", lambda name, settings, secrets: FauxMoteur())
    client.put("/api/agents/claude", json={"active": True, "api_key": "sk-test-recus"})
    return FauxMoteur


# --------------------------------------------------------------------------- lecture des montants
@pytest.mark.parametrize("ligne, attendu", [
    ("TOTAL 24,42", [24.42]),
    ("TOTAL $73.44", [73.44]),
    ("Total 24,42 $", [24.42]),
    ("GRAND TOTAL 1,234.56", [1234.56]),
    ("RABAIS 2,00-", [-2.0]),
    ("Coupon -1,50", [-1.5]),
    ("TVQ 9,975 % 1,30", [1.3]),
    ("TPS 5,00 % 0,65", [0.65]),
    ("2026-09-12 14:32", []),
    ("12.09.2026", []),
    ("Tél. 514.555.1234", []),
    ("TPS/TVH No 123456789 RT0001", []),
])
def test_les_montants_sont_lus_sans_confondre_pourcentages_dates_et_numeros(ligne, attendu):
    assert recus.extraire_montants(ligne) == attendu


@pytest.mark.parametrize("texte, attendu", [
    ("2026-09-12 14:32", ("2026-09-12", False)),
    ("Date : 2026/09/12", ("2026-09-12", False)),
    ("13/09/26", ("2026-09-13", False)),
    ("09/13/2026", ("2026-09-13", False)),
    ("03/04/2026", ("2026-04-03", True)),
    ("12 septembre 2026", ("2026-09-12", False)),
    ("Sep 10, 2026", ("2026-09-10", False)),
    ("1er sept. 2026", ("2026-09-01", False)),
    ("2031-01-01", (None, False)),
    ("aucune date", (None, False)),
])
def test_les_dates_de_recu_canadiennes_sont_reconnues(texte, attendu):
    assert recus.lire_date(texte, AUJOURDHUI) == attendu


def test_extraction_locale_dun_recu_quebecois_tps_tvq():
    r = recus.extraire_local(RECU_QUEBEC, aujourd_hui=AUJOURDHUI)
    assert r["commercant"] == "MÉTRO PLUS DU PLATEAU"
    assert r["date"] == "2026-09-12"
    assert (r["sous_total"], r["tps"], r["tvq"], r["tvh"], r["total"]) == (22.47, 0.65, 1.30, None, 24.42)
    assert r["devise"] == "CAD" and r["categorie"] == "Alimentation" and r["moyen_paiement"] == "Visa"
    assert [l["montant"] for l in r["lignes"]] == [5.49, 3.99, 12.99]
    assert r["lignes"][0]["libelle"] == "LAIT 2% 2 L"
    # Panier en partie détaxé : les taxes suivent le rapport TVQ/TPS, ce qui se vérifie malgré tout.
    assert r["controle"]["somme_ok"] is True and r["controle"]["taux_ok"] is True
    assert 0.9 <= r["confiance"] <= recus.CONFIANCE_MAX < 1.0


def test_extraction_locale_dun_recu_ontarien_tvh():
    r = recus.extraire_local(RECU_ONTARIO, aujourd_hui=AUJOURDHUI)
    assert r["commercant"] == "BEST BUY #123" and r["date"] == "2026-09-10"
    assert (r["sous_total"], r["tps"], r["tvq"], r["tvh"], r["total"]) == (64.99, None, None, 8.45, 73.44)
    assert r["categorie"] == "Matériel" and r["moyen_paiement"] == "Débit"
    assert r["controle"]["taux_ok"] is True and r["controle"]["somme_ok"] is True


def test_le_total_nest_ni_le_montant_remis_ni_la_monnaie_meme_sur_la_ligne_suivante():
    r = recus.extraire_local(RECU_ETIQUETTES_SEULES, aujourd_hui=AUJOURDHUI)
    assert r["total"] == 9.20, "COMPTANT 20,00 est le montant remis, pas le total"
    assert r["sous_total"] == 8.00
    assert r["moyen_paiement"] == "Comptant" and r["categorie"] == "Restaurant"
    assert all(l["montant"] not in (20.0, 10.8) for l in r["lignes"])


def test_un_champ_absent_reste_vide_et_la_confiance_baisse():
    texte = "DÉPANNEUR DU COIN\nGOMME 2,50\nTOTAL 2,87\nDEBIT 2,87"
    r = recus.extraire_local(texte, aujourd_hui=AUJOURDHUI)
    assert r["total"] == 2.87
    assert r["sous_total"] is None and r["tps"] is None and r["tvq"] is None, "aucun champ ne doit être calculé"
    assert r["date"] is None and r["confiance"] <= 0.5
    sans_total = recus.extraire_local("RESTO\nSOUS-TOTAL 10,00\nTPS 0,50\nTVQ 1,00", aujourd_hui=AUJOURDHUI)
    assert sans_total["total"] is None, "le total ne doit jamais être additionné à la place du reçu"


def test_total_trouve_seulement_sur_la_ligne_de_paiement():
    r = recus.extraire_local("BOUTIQUE\nARTICLE 10,00\nMASTERCARD 11,50", aujourd_hui=AUJOURDHUI)
    assert r["total"] == 11.50 and r["controle"]["origine_total"] == "paiement"
    assert r["moyen_paiement"] == "Mastercard"


def test_des_taxes_incoherentes_sont_signalees():
    faux = "COMMERCE\n2026-09-10\nSOUS-TOTAL 100,00\nTPS 9,00\nTVQ 1,00\nTOTAL 110,00"
    r = recus.extraire_local(faux, aujourd_hui=AUJOURDHUI)
    assert r["controle"]["taux_ok"] is False
    assert r["confiance"] < recus.extraire_local(RECU_QUEBEC, aujourd_hui=AUJOURDHUI)["confiance"]


# --------------------------------------------------------------------------- réponse du moteur
def test_la_reponse_du_moteur_est_validee_strictement():
    r = recus.valider_extraction(json.dumps(JSON_MOTEUR), RECU_QUEBEC, aujourd_hui=AUJOURDHUI)
    assert r["total"] == 24.42 and r["categorie"] == "Alimentation" and r["controle"]["total_dans_texte_lu"] is True
    assert r["confiance"] == 0.92
    entoure = "Voici :\n```json\n" + json.dumps({**JSON_MOTEUR, "categorie": "Épicerie fine", "tvq": "1,30"}) + "\n```"
    r2 = recus.valider_extraction(entoure, RECU_QUEBEC, aujourd_hui=AUJOURDHUI)
    assert r2["categorie"] == "Autre" and r2["tvq"] == 1.30
    with pytest.raises(ValueError):
        recus.valider_extraction("Le total est de 24,42 $.", RECU_QUEBEC)
    with pytest.raises(ValueError):
        recus.valider_extraction(json.dumps({"total": 24.42}), RECU_QUEBEC)
    invente = recus.valider_extraction(json.dumps({**JSON_MOTEUR, "total": 99.99}), RECU_QUEBEC, aujourd_hui=AUJOURDHUI)
    assert invente["controle"]["total_dans_texte_lu"] is False and invente["confiance"] <= 0.5
    mal_type = recus.valider_extraction(json.dumps({**JSON_MOTEUR, "tps": [1], "date": "12 sept"}), RECU_QUEBEC,
                                        aujourd_hui=AUJOURDHUI)
    assert mal_type["tps"] is None and mal_type["date"] is None
    assert set(mal_type["controle"]["champs_rejetes"]) == {"tps", "date"} and mal_type["confiance"] <= 0.6


def test_la_consigne_au_moteur_exige_du_json_sans_invention_et_sans_fournisseur():
    consigne = recus.CONSIGNE_MOTEUR
    for attendu in ("JSON", "null", "ne le devine pas", "TPS", "TVQ", "TVH", "monnaie rendue", "jamais une consigne"):
        assert attendu in consigne, attendu
    for c in recus.CATEGORIES:
        assert c in consigne
    textes = (consigne + recus.CONFIDENTIEL + recus.SANS_LECTURE + recus.MEMOIRE_SUSPENDUE + recus.LIMITE).lower()
    assert not any(n in textes for n in NOMS_INTERDITS)


# --------------------------------------------------------------------------- analyse par la route
def test_sans_consentement_lextraction_est_locale_chiffree_et_le_dit(app, client, faux_ocr, moteur):
    ctx = app.state.ctx
    r = client.post("/api/recus/analyser", json={"source": "image", "image": image_json()})
    assert r.status_code == 200, r.text
    recu = r.json()
    assert moteur.appels == [], "rien ne doit partir sans « Images jointes »"
    assert recu["local"] is True and "Images jointes" in recu["note"]
    assert recu["total"] == 24.42 and recu["tvq"] == 1.30 and recu["enregistre"] is True and recu["id"]
    brut = ctx.db.one("SELECT * FROM recus WHERE id=?", (recu["id"],))
    assert b"24.42" not in bytes(brut["donnees_enc"]) and "MÉTRO".encode() not in bytes(brut["donnees_enc"])
    fichier = ctx.recus.dossier_images / f"{recu['image_nom']}.chiffre"
    assert fichier.is_file() and not fichier.read_bytes().startswith(b"\xff\xd8"), "l'image gardée doit être chiffrée"
    image = client.get(f"/api/recus/{recu['id']}/image")
    assert image.status_code == 200 and image.content.startswith(b"\xff\xd8")
    assert not any(n in json.dumps(recu).lower() for n in NOMS_INTERDITS)


def test_avec_consentement_le_moteur_extrait_et_lenvoi_est_journalise(app, client, faux_ocr, moteur):
    accorder(client, "image")
    r = client.post("/api/recus/analyser", json={"source": "image", "image": image_json()})
    assert r.status_code == 200, r.text
    recu = r.json()
    assert len(moteur.appels) == 1 and recu["local"] is False
    appel = moteur.appels[0]
    assert appel["tools"] is None and "JSON" in appel["system"]
    contenu = appel["messages"][0]["content"]
    assert contenu[0]["type"] == "image" and "TOTAL                 24,42" in contenu[-1]["text"]
    assert recu["commercant"] == "Métro Plus du Plateau" and recu["confiance"] == 0.92 and recu["note"] is None
    evenements = app.state.ctx.consent.events(limit=20)
    assert any(e["event_type"] == "external_send" and e["data_type"] == "image" for e in evenements)


def test_une_reponse_illisible_du_moteur_retombe_sur_lextraction_locale(client, faux_ocr, moteur):
    accorder(client, "image")
    moteur.reponse = "Je pense que le total est d'environ 24 dollars."
    recu = client.post("/api/recus/analyser", json={"source": "image", "image": image_json()}).json()
    assert recu["local"] is True and "illisible" in recu["note"] and recu["total"] == 24.42


def test_le_mode_100_pour_cent_local_nenvoie_rien(app, client, faux_ocr, moteur):
    accorder(client, "image")
    app.state.ctx.settings.update({"local_only": True})
    recu = client.post("/api/recus/analyser", json={"source": "image", "image": image_json()}).json()
    assert moteur.appels == [] and recu["local"] is True and "100 % local" in recu["note"]


def test_sans_lecture_locale_ni_moteur_le_refus_est_explique(client, monkeypatch):
    monkeypatch.setattr(recus, "ocr_disponible", lambda: False)
    r = client.post("/api/recus/analyser", json={"source": "image", "image": image_json()})
    assert r.status_code == 409
    assert "lecture de texte locale n'est pas disponible" in r.json()["detail"]


def test_image_manquante_ou_source_inconnue(client):
    assert client.post("/api/recus/analyser", json={"source": "image"}).status_code == 422
    assert client.post("/api/recus/analyser", json={"source": "satellite"}).status_code == 422
    r = client.post("/api/recus/analyser", json={"source": "image", "image": {"media_type": "image/jpeg", "data": "pas*du*base64"}})
    assert r.status_code == 422


def test_mode_confidentiel_refuse_lanalyse(app, client, faux_ocr):
    app.state.ctx.settings.update({"privacy_mode": True})
    r = client.post("/api/recus/analyser", json={"source": "image", "image": image_json()})
    assert r.status_code == 409 and "confidentiel" in r.json()["detail"]
    assert faux_ocr["appels"] == 0


def test_memoire_suspendue_le_recu_est_lu_mais_rien_nest_ecrit(app, client, faux_ocr):
    ctx = app.state.ctx
    ctx.memory.suspendre("invite")
    recu = client.post("/api/recus/analyser", json={"source": "image", "image": image_json()}).json()
    assert recu["total"] == 24.42 and recu["enregistre"] is False and recu["id"] is None
    assert "n'a pas été enregistré" in recu["note"]
    assert ctx.db.query("SELECT id FROM recus") == []
    assert list(ctx.recus.dossier_images.glob("*.chiffre")) == []


class FausseCamera:
    def __init__(self, ctx, dossier: Path, erreur: Exception | None = None):
        self.ctx, self.dossier, self.erreur = ctx, dossier, erreur
        self.temoin_pendant = None

    async def prendre_photo(self, reconnaissance: bool = False, timeout: float = 20.0):
        self.temoin_pendant = self.ctx.capture.snapshot()["camera"]
        if self.erreur is not None:
            raise self.erreur
        self.dossier.mkdir(parents=True, exist_ok=True)
        chemin = self.dossier / "lunettes-recu.jpg"
        chemin.write_bytes(jpeg())
        return ResultatPhoto(ok=True, chemin=str(chemin), octets=chemin.stat().st_size, constat="Photo reçue.")


def test_photo_des_lunettes_temoin_annonce_et_copie_en_clair_effacee(app, client, faux_ocr, monkeypatch):
    ctx = app.state.ctx
    camera = FausseCamera(ctx, Path(ctx.settings.data_dir) / "captures")
    ctx.recus.fabrique_camera = lambda: camera
    dites: list[str] = []
    monkeypatch.setattr(ctx.recus, "_dire", dites.append)
    r = client.post("/api/recus/analyser", json={"source": "lunettes"})
    assert r.status_code == 200, r.text
    assert camera.temoin_pendant is True and ctx.capture.snapshot()["camera"] is False
    assert dites == ["Photo."]
    assert not (Path(ctx.settings.data_dir) / "captures" / "lunettes-recu.jpg").exists()
    assert ctx.recus.image(r.json()["id"]).startswith(b"\xff\xd8")


def test_camera_indisponible_rend_le_message_exact(app, client):
    ctx = app.state.ctx
    ctx.recus.fabrique_camera = lambda: FausseCamera(ctx, Path(ctx.settings.data_dir), CameraIndisponible("Ces lunettes n'ont pas de caméra."))
    r = client.post("/api/recus/analyser", json={"source": "lunettes"})
    assert r.status_code == 409 and r.json()["detail"] == "Ces lunettes n'ont pas de caméra."
    assert ctx.capture.snapshot()["camera"] is False


# --------------------------------------------------------------------------- liste, corrections, export
def enregistrer(service, **champs) -> dict:
    base = {"date": "2026-09-12", "commercant": "Commerce", "sous_total": 10.0, "tps": 0.5, "tvq": 1.0, "tvh": None,
            "total": 11.5, "devise": "CAD", "categorie": "Autre", "moyen_paiement": "Visa", "lignes": [],
            "confiance": 0.8, "local": True, "controle": {}, "note": None}
    return service._enregistrer({**base, **champs}, jpeg())


def test_liste_filtree_par_date_avec_totaux_par_devise_et_categorie(client, service):
    enregistrer(service, date="2026-09-01", commercant="IGA", categorie="Alimentation", total=11.5)
    enregistrer(service, date="2026-09-10", commercant="Petro-Canada", categorie="Essence", sous_total=40.0,
                tps=2.0, tvq=3.99, total=45.99)
    enregistrer(service, date="2026-09-11", commercant="Amazon US", devise="USD", total=20.0)
    enregistrer(service, date="2026-09-12", commercant="Illisible", total=None, sous_total=None, tps=None, tvq=None)
    r = client.get("/api/recus", params={"debut": "2026-09-05", "fin": "2026-09-12"})
    assert r.status_code == 200
    corps = r.json()
    assert [x["commercant"] for x in corps["recus"]] == ["Illisible", "Amazon US", "Petro-Canada"]
    totaux = corps["totaux"]
    assert totaux["nombre"] == 2 and totaux["devise"] == "CAD" and totaux["total"] == 45.99
    assert totaux["autres_devises"] == {"USD": 20.0} and totaux["sans_total"] == 1
    assert totaux["par_categorie"] == {"Essence": 45.99}
    assert "pas un avis comptable" in corps["limite"] and corps["retention_jours"] == 0
    assert client.get("/api/recus", params={"debut": "13/09/2026"}).status_code == 422


def test_correction_validee_puis_suppression(app, client, service):
    recu = enregistrer(service, total=99.0)
    assert client.patch(f"/api/recus/{recu['id']}", json={"categorie": "Vêtements"}).status_code == 422
    assert client.patch(f"/api/recus/{recu['id']}", json={"total": "beaucoup"}).status_code == 422
    assert client.patch(f"/api/recus/{recu['id']}", json={"id": "autre"}).status_code == 422
    assert client.patch("/api/recus/inconnu", json={"total": 1}).status_code == 404
    r = client.patch(f"/api/recus/{recu['id']}", json={"total": "11,50", "categorie": "fournitures de bureau",
                                                       "date": "2026-09-11"})
    assert r.status_code == 200, r.text
    corrige = r.json()
    assert corrige["total"] == 11.5 and corrige["categorie"] == "Fournitures de bureau" and corrige["corrige"] is True
    assert corrige["controle"]["somme_ok"] is True and corrige["date"] == "2026-09-11"
    app.state.ctx.memory.suspendre("zone:Clinique")
    assert client.patch(f"/api/recus/{recu['id']}", json={"total": 12}).status_code == 409
    app.state.ctx.memory.reprendre("zone:Clinique")
    fichier = service.dossier_images / f"{recu['image_nom']}.chiffre"
    assert fichier.exists()
    assert client.delete(f"/api/recus/{recu['id']}").json() == {"supprime": True}
    assert not fichier.exists() and client.delete(f"/api/recus/{recu['id']}").status_code == 404


def test_export_csv_exact_pour_excel(client, service):
    enregistrer(service, date="2026-09-12", commercant="Métro, Plateau", categorie="Alimentation", sous_total=22.47,
                tps=0.65, tvq=1.3, total=24.42, moyen_paiement="Visa")
    enregistrer(service, date="2026-09-10", commercant="Best Buy", categorie="Matériel", sous_total=64.99, tps=None,
                tvq=None, tvh=8.45, total=73.44, moyen_paiement=None)
    r = client.get("/api/recus/export", params={"format": "csv", "debut": "2026-09-01", "fin": "2026-09-30"})
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    assert "iris-recus-2026-09-01-2026-09-30.csv" in r.headers["content-disposition"]
    assert r.content.startswith(b"\xef\xbb\xbf"), "BOM UTF-8 obligatoire : sans lui, Excel abîme les accents"
    attendu = (
        "\ufeffdate,commerçant,catégorie,sous-total,TPS,TVQ,TVH,total,devise,moyen de paiement\r\n"
        "2026-09-10,Best Buy,Matériel,64.99,,,8.45,73.44,CAD,\r\n"
        "2026-09-12,\"Métro, Plateau\",Alimentation,22.47,0.65,1.30,,24.42,CAD,Visa\r\n"
    )
    assert r.content.decode("utf-8") == attendu
    assert client.get("/api/recus/export", params={"format": "xlsx"}).status_code == 422


def test_la_retention_efface_recus_et_images(app, service):
    ancien = enregistrer(service)
    app.state.ctx.db.execute("UPDATE recus SET cree_le=? WHERE id=?",
                             ((datetime.now(timezone.utc) - timedelta(days=40)).isoformat(timespec="seconds"), ancien["id"]))
    recent = enregistrer(service)
    app.state.ctx.settings.update({"retention_days": 30})
    assert service.purger() == 1
    assert service.obtenir(ancien["id"]) is None and service.obtenir(recent["id"]) is not None
    assert not (service.dossier_images / f"{ancien['image_nom']}.chiffre").exists()


# --------------------------------------------------------------------------- voix
def test_garde_ce_recu_a_la_voix(app, faux_ocr, monkeypatch):
    import asyncio

    ctx = app.state.ctx
    service = ctx.recus
    assert service.interception("quelle heure est-il") is None
    assert service.interception("lis ce document") is None
    camera = FausseCamera(ctx, Path(ctx.settings.data_dir) / "captures")
    service.fabrique_camera = lambda: camera
    monkeypatch.setattr(service, "_dire", lambda texte: None)
    phrase = asyncio.run(service.interception("Iris, garde ce reçu"))
    assert phrase == ("Reçu enregistré : MÉTRO PLUS DU PLATEAU, total 24,42 $, confiance 95 %. "
                      "Vérifie les montants dans IRIS avant de t'en servir.")
    service.fabrique_camera = lambda: FausseCamera(ctx, Path(ctx.settings.data_dir), CameraIndisponible("pas de caméra"))
    assert asyncio.run(service.interception("scanne ce reçu")) == "La caméra des lunettes n'est pas utilisable pour l'instant."
    noms = {nom: priorite for priorite, nom, _f in ctx.voice._interceptions}
    assert noms.get("quotidien-recus") == 50
