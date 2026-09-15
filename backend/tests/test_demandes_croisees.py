"""Demandes croisées des correcteurs du 2026-09-14 : ce qu'une équipe ne pouvait pas modifier elle-même.

Chaque test échouerait sans le correctif qu'il accompagne :
- commande vocale dite dans les lunettes reliées au téléphone (POST /api/voix/commande, demande iOS) ;
- lecture partielle d'une conversation (?depuis=, ?limit=, demande iOS) ;
- textes du mode invité alignés sur le refus réel de la sortie vocale (demande service-b) ;
- ancien site téléphone sans widget vocal tiers ni identifiant d'agent (demande mobile) ;
- texte atténué du renderer aligné sur la palette validée de l'iPhone (demande iOS) ;
- refus caméra des lunettes structuré, sans jargon, et caméra annoncée par la présence (demande renderer).
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

import iris.chat as chat_module
from iris.connectors.base import BaseConnector, Chunk

RACINE = Path(__file__).resolve().parents[2]


class FauxMoteur(BaseConnector):
    name = "claude"
    supports_tools = True
    appels: list[dict] = []

    def __init__(self, api_key=None, model="faux", base_url=None):
        super().__init__(api_key, model, base_url)

    async def stream(self, messages, system, tools=None, run_tool=None, options=None):
        FauxMoteur.appels.append({"system": system, "messages": messages})
        yield Chunk("text", text="Voici une histoire.")
        yield Chunk("done")

    async def test(self):
        return {"ok": True, "message": "ok", "model": self.model, "latency_ms": 1}


@pytest.fixture()
def moteur(monkeypatch):
    FauxMoteur.appels = []
    monkeypatch.setattr(chat_module, "build_connector", lambda name, settings, secrets: FauxMoteur())
    return FauxMoteur


def _lunettes_du_telephone(client, app, monkeypatch):
    """Lunettes connues de l'ordinateur, absentes de lui, attestées par l'app du téléphone."""
    ctx = app.state.ctx
    ctx.settings.update({"require_glasses": True, "demo_sans_lunettes": False,
                         "glasses": {"name": "M01 Pro_F444", "address": "65:A2:9F:5C:F4:44", "auto_connect": False}})
    monkeypatch.setattr(ctx.voice, "lunettes_presentes", lambda: False)
    r = client.post("/api/lunettes/attestation", json={"nom": "M01 Pro_F444", "identifiant": "ios-1", "source": "iphone"})
    assert r.status_code == 200, r.text
    assert ctx.presence_lunettes.source() == "telephone"
    return ctx


# --------------------------------------------------------------------------- POST /api/voix/commande
def test_commande_vocale_du_telephone_interceptions_puis_chat_regle_de_la_voix(client, app, monkeypatch, moteur):
    ctx = _lunettes_du_telephone(client, app, monkeypatch)
    ctx.voice.ajouter_interception("essai", lambda t: "Pas à pas : étape suivante." if "suivant" in t else None, 5)
    try:
        r = client.post("/api/voix/commande", json={"texte": "passe au suivant", "source": "iphone"})
        assert r.status_code == 200, r.text
        assert r.json()["intercepte"] is True and r.json()["texte"] == "Pas à pas : étape suivante."
        assert moteur.appels == [], "une phrase interceptée ne va pas au modèle"
    finally:
        ctx.voice.retirer_interception("essai")

    client.put("/api/agents/claude", json={"active": True, "api_key": "cle-factice-test"})
    client.put("/api/consent/transcript", json={"granted": True})
    parle: list[str] = []
    monkeypatch.setattr(ctx.tts, "speak", lambda *a, **k: parle.append(a[0] if a else ""))
    r = client.post("/api/voix/commande", json={"texte": "raconte-moi une histoire courte", "source": "iphone"})
    assert r.status_code == 200, r.text
    corps = r.json()
    assert corps["intercepte"] is False and corps["texte"] == "Voici une histoire." and corps["message_id"]
    assert "dictée à la voix" in moteur.appels[-1]["system"], "réponse orale courte, comme la voix du PC"
    messages = client.get(f"/api/conversations/{corps['conversation_id']}").json()["messages"]
    assert messages[-2]["meta"]["source"] == "voix_telephone"
    assert parle == [], "l'ordinateur resté à la maison ne lit pas la réponse : le téléphone s'en charge"


def test_commande_vocale_du_telephone_exige_les_lunettes_et_nouvre_pas_le_micro_de_la_maison(client, app, monkeypatch):
    ctx = app.state.ctx
    client.delete("/api/lunettes/attestation")
    ctx.settings.update({"require_glasses": True, "demo_sans_lunettes": False})
    monkeypatch.setattr(ctx.voice, "lunettes_presentes", lambda: False)
    r = client.post("/api/voix/commande", json={"texte": "quelle heure est-il"})
    assert r.status_code == 428 and r.json()["detail"]["code"] == "lunettes_requises"

    _lunettes_du_telephone(client, app, monkeypatch)
    demarrages: list[bool] = []
    monkeypatch.setattr(ctx.voice, "start", lambda *a, **k: demarrages.append(True))
    r = client.post("/api/voix/commande", json={"texte": "mode interprète anglais"})
    assert r.status_code == 200 and r.json()["refus"] == "micro_de_la_maison"
    assert "micro de l'ordinateur" in r.json()["texte"]
    assert demarrages == [] and not getattr(ctx, "interprete").actif
    assert client.post("/api/voix/commande", json={"texte": "   "}).status_code == 422


# --------------------------------------------------------------------------- GET /api/conversations/{id}?depuis=
def test_conversation_lue_depuis_un_message_ou_par_la_fin(client, app):
    chat = app.state.ctx.chat
    conv = chat.create_conversation(title="Longue", agent="auto")
    ids = [chat._add_message(conv["id"], "user" if i % 2 == 0 else "assistant", f"message {i}")["id"] for i in range(6)]
    complet = client.get(f"/api/conversations/{conv['id']}").json()
    assert [m["id"] for m in complet["messages"]] == ids and "depuis_trouve" not in complet
    apres = client.get(f"/api/conversations/{conv['id']}", params={"depuis": ids[3]}).json()
    assert [m["id"] for m in apres["messages"]] == ids[4:] and apres["depuis_trouve"] is True
    fin = client.get(f"/api/conversations/{conv['id']}", params={"limit": 2}).json()
    assert [m["id"] for m in fin["messages"]] == ids[4:]
    inconnu = client.get(f"/api/conversations/{conv['id']}", params={"depuis": "efface", "limit": 3}).json()
    assert inconnu["depuis_trouve"] is False and [m["id"] for m in inconnu["messages"]] == ids[3:]
    assert client.get(f"/api/conversations/{conv['id']}", params={"depuis": ids[5]}).json()["messages"] == []


# --------------------------------------------------------------------------- textes du mode invité
def test_les_textes_du_mode_invite_ne_promettent_pas_la_sortie_a_la_voix():
    """« fin du mode invité » à la voix est refusée sans verrou vocal (mode_invite.SORTIE_VOCALE_REFUSEE)."""
    ecran = (RACINE / "renderer/src/screens/ModeInviteScreen.tsx").read_text(encoding="utf-8")
    assert "la fin du mode efface la session sans demander de confirmation" not in ecran
    assert "verrou vocal" in ecran
    page = (RACINE / "backend/iris/mobile_static/js/invite.js").read_text(encoding="utf-8")
    assert "verrou vocal" in page


# --------------------------------------------------------------------------- ancien site téléphone
def test_lancien_site_telephone_na_plus_de_widget_vocal_tiers():
    dossier = RACINE / "mobile-web"
    for fichier in ("index.html", "assets/app.js", "assets/app.css", "sw.js", "_headers"):
        texte = (dossier / fichier).read_text(encoding="utf-8").lower()
        assert "agent_2501" not in texte and "elevenlabs" not in texte and "convai" not in texte, fichier
    page = (dossier / "index.html").read_text(encoding="utf-8")
    assert not re.search(r'<script[^>]+src="https?://', page), "aucun script d'un autre domaine"


def test_lancien_site_telephone_ne_promet_plus_ce_quil_ne_fait_pas():
    """Contre-vérification mobile du 2026-09-14 : le manifeste promettait encore « Parlez à Iris, l'assistante
    vocale », et la télécommande (non revérifiée) promettait un accord « avant tout envoi ou toute action
    irréversible », un code « affiché par ton ordinateur » (il ne l'est pas), un lien « Revenir à la voix »
    et une adresse de tunnel éphémère."""
    dossier = RACINE / "mobile-web"
    manifeste = json.loads((dossier / "manifest.webmanifest").read_text(encoding="utf-8"))
    assert "assistante vocale" not in manifeste["description"].lower()
    assert "parlez" not in manifeste["description"].lower()
    assert "plus utilisée" in manifeste["description"]

    page = (dossier / "telecommande.html").read_text(encoding="utf-8")
    script = (dossier / "telecommande.js").read_text(encoding="utf-8")
    for interdit in ("tout envoi", "toute action", "Revenir à la voix", "trycloudflare", "affiché par ton ordinateur",
                     "Pilote ton ordinateur"):
        assert interdit not in page, interdit
    assert '<meta name="robots" content="noindex, nofollow"' in page
    assert "lunettes VELA" in page and "n'est pas garanti" in page
    # Finition du 2026-09-14 : seuls courriel, texto et appel sont TOUJOURS confirmés (tools.OUTILS_TOUJOURS_CONFIRMES) ;
    # une suppression passe par une commande, confirmée selon confirm_commands (« never » : jamais).
    from iris.tools import OUTILS_TOUJOURS_CONFIRMES, needs_confirmation

    assert OUTILS_TOUJOURS_CONFIRMES == {"envoyer_courriel", "envoyer_sms", "passer_un_appel"}
    assert needs_confirmation("never", "rm -rf ~/Documents") is False
    for texte, nom in ((page, "telecommande.html"),
                       ((RACINE / "renderer/src/screens/ModeDehorsScreen.tsx").read_text(encoding="utf-8"), "ModeDehorsScreen.tsx")):
        assert "appel, suppression) attendent" not in texte, f"{nom} promet une confirmation des suppressions"
        assert "Jamais" in texte and "rien n" in texte, f"{nom} doit dire qu'avec « Jamais », rien n'est demandé"
    assert "n'est pas encore affiché dans l'application IRIS" in page, "le code d'appairage : dire où il est vraiment"
    assert "Relais injoignable" in script and "r.status" in script and "detail" in script
    for fichier in dossier.rglob("*"):
        if fichier.suffix in (".html", ".js", ".webmanifest", ".css"):
            texte = fichier.read_text(encoding="utf-8").lower()
            for nom in ("elevenlabs", "openai", "anthropic", "claude", "gemini", "trycloudflare"):
                assert nom not in texte, (fichier.name, nom)


# --------------------------------------------------------------------------- contraste du texte atténué
def _luminance(hexa: str) -> float:
    canaux = [int(hexa[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    lineaire = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in canaux]
    return 0.2126 * lineaire[0] + 0.7152 * lineaire[1] + 0.0722 * lineaire[2]


def test_le_texte_attenue_du_renderer_atteint_le_contraste_aa():
    """Demande iOS : aligner --muted sur #A1A1A6. #8E8E93 ne donnait que ~4,3:1 sur --surface (#2C2C2E),
    sous le seuil AA de 4,5:1 pour un texte lu par des personnes malvoyantes."""
    feuille = (RACINE / "renderer/src/styles.css").read_text(encoding="utf-8")
    racine = feuille[feuille.index(":root {"):feuille.index("}", feuille.index(":root {"))]
    jetons = dict(re.findall(r"--([a-z0-9-]+):\s*(#[0-9a-fA-F]{6})", racine))
    attenue = _luminance(jetons["muted"])
    for fond in ("bg", "bg-2", "surface"):
        ratio = (attenue + 0.05) / (_luminance(jetons[fond]) + 0.05)
        assert ratio >= 4.5, (fond, round(ratio, 2))


# --------------------------------------------------------------------------- refus caméra des lunettes
def test_le_refus_camera_des_lunettes_est_structure_et_sans_jargon(client, app, monkeypatch):
    """Demande renderer : ProtocoleNonConfirme -> {code: camera_non_confirmee, message} ; le texte technique (charge
    utile, chemin de document, nom du réglage d'exploration) reste au journal ; la présence dit si la caméra est active."""
    from iris import lunettes_camera
    from iris.lunettes_camera import ProtocoleNonConfirme, ResultatPhoto

    class CameraRefusee:
        def __init__(self, glasses):
            self.glasses = glasses

        async def prendre_photo(self, reconnaissance=False):
            raise ProtocoleNonConfirme("charge utile 010400, voir docs/LUNETTES-CAMERA-PROTOCOLE.md, "
                                       "activez « lunettes_exploration »")

    monkeypatch.setattr(lunettes_camera, "CameraLunettes", CameraRefusee)
    monkeypatch.setattr(app.state.ctx.presence_lunettes, "exiger_capture_pc", lambda fonction: None)
    r = client.post("/api/glasses/photo", json={})
    assert r.status_code == 409, r.text
    detail = r.json()["detail"]
    assert detail["code"] == "camera_non_confirmee"
    assert not any(m in detail["message"] for m in ("lunettes_exploration", "docs/", "010400", "trame"))
    assert detail["message"] == lunettes_camera.MESSAGE_CAMERA_NON_CONFIRMEE
    assert ResultatPhoto  # le module garde son résultat honnête pour les photos réellement tentées

    assert client.get("/api/lunettes/presence").json()["camera_lunettes_active"] is False
    app.state.ctx.settings.update({"lunettes_exploration": True})
    try:
        assert client.get("/api/lunettes/presence").json()["camera_lunettes_active"] is True
    finally:
        app.state.ctx.settings.update({"lunettes_exploration": False})


# --------------------------------------------------------------------------- limite légale des sous-titres
def test_la_limite_legale_des_sous_titres_est_dite_sur_le_telephone_et_liphone():
    """Constat 13 de la revue transversale, « non couvert : page téléphone et app iPhone »."""
    page = (RACINE / "backend/iris/mobile_static/js/coeur.js").read_text(encoding="utf-8")
    assert "conversation à laquelle vous ne participez pas est illégal" in page
    ios = (RACINE / "mobile-ios/IRIS/Ecrans/Accessibilite/EcranSousTitres.swift").read_text(encoding="utf-8")
    assert "conversation à laquelle tu ne participes pas est illégal" in ios


# --------------------------------------------------------------------------- journal technique et effacement local
def test_tout_effacer_vide_aussi_le_journal_technique(client, tmp_path, monkeypatch):
    """Revue transversale, NON LIVRÉ : le journal technique n'était vidé qu'à l'effacement à distance et par la
    rétention. « Effacer toute la mémoire » et « effacer tout le journal » le vident aussi."""
    monkeypatch.setenv("IRIS_JOURNAL_TECHNIQUE", str(tmp_path))
    courant = tmp_path / "backend.log"
    courant.write_text("ancienne ligne : 'rendez-vous chez le médecin'", encoding="utf-8")
    (tmp_path / "backend-2026-09-01.log").write_text("vieux", encoding="utf-8")
    r = client.delete("/api/memory")
    assert r.status_code == 200 and r.json()["journal_technique"] == 2
    assert courant.exists() and courant.read_text(encoding="utf-8") == ""
    assert not (tmp_path / "backend-2026-09-01.log").exists()
    courant.write_text("autre", encoding="utf-8")
    assert client.delete("/api/journal", params={"debut": "2020-01-01", "fin": "2020-01-02"}).json().get("journal_technique") is None
    assert courant.read_text(encoding="utf-8") == "autre", "une plage ne vide pas le journal technique"
    assert client.delete("/api/journal", params={"tout": "true"}).json()["journal_technique"] == 1
    assert courant.read_text(encoding="utf-8") == ""


# --------------------------------------------------------------------------- retrait d'attestation nominatif
def test_aucun_client_ne_retire_lattestation_sans_nommer_son_appareil():
    """Contre-vérification mobile du 2026-09-14 : la page téléphone nommait son appareil au retrait, mais l'app
    iPhone appelait encore DELETE /api/lunettes/attestation SANS identifiant ; le service garde alors le
    comportement d'origine et l'iPhone effaçait l'attestation qu'un Android relié aux lunettes venait de donner.
    Tout client (page /m, app iPhone, renderer, Electron) doit passer ?identifiant=."""
    appels: list[tuple[str, str]] = []
    motifs = {
        ".swift": re.compile(r'\.delete\(\s*"/api/lunettes/attestation"(.{0,400}?)\)\s*$', re.S | re.M),
        ".js": re.compile(r"(?:\.delete|fetch)\(\s*'/api/lunettes/attestation'([^;]{0,400})", re.S),
        ".ts": re.compile(r"\.delete\(\s*['\"`]/api/lunettes/attestation([^;]{0,400})", re.S),
        ".tsx": re.compile(r"\.delete\(\s*['\"`]/api/lunettes/attestation([^;]{0,400})", re.S),
    }
    for dossier in ("mobile-ios/IRIS", "backend/iris/mobile_static", "renderer/src", "electron"):
        for fichier in (RACINE / dossier).rglob("*"):
            motif = motifs.get(fichier.suffix)
            if motif is None or not fichier.is_file():
                continue
            texte = fichier.read_text(encoding="utf-8", errors="replace")
            for m in motif.finditer(texte):
                appels.append((fichier.relative_to(RACINE).as_posix(), m.group(0)))
    assert any(f.endswith("AttestationLunettes.swift") for f, _ in appels), "retrait de l'app iPhone introuvable"
    for fichier, appel in appels:
        assert "identifiant" in appel.lower() or "parametresRetrait" in appel, (fichier, appel)

    ios = (RACINE / "mobile-ios/IRIS/Pont/AttestationLunettes.swift").read_text(encoding="utf-8")
    assert 'URLQueryItem(name: "identifiant"' in ios
    # L'état Bluetooth n'a plus d'identifiant après « oublier » : c'est celui de l'attestation acceptée qui sert.
    assert "identifiantAtteste = corps.identifiant" in ios
    # La page téléphone : un seul chemin de retrait, qui nomme l'appareil (DELETE et pagehide).
    page = (RACINE / "backend/iris/mobile_static/js/lunettes.js").read_text(encoding="utf-8")
    assert "'?identifiant=' + encodeURIComponent(id)" in page


def test_le_retrait_de_liphone_nefface_pas_lattestation_dun_autre_telephone(client, app, monkeypatch):
    """Scénario de la sonde : l'iPhone atteste, puis un Android associé atteste à son tour ; l'iPhone perd ses
    lunettes et retire SON attestation en se nommant : l'Android reste attesté."""
    ctx = _lunettes_du_telephone(client, app, monkeypatch)  # « ios-1 », premier appareil associé
    ctx.presence_lunettes._ecrire_association({**ctx.presence_lunettes._lire_association(),
                                               "identifiants": ["ios-1", "android-1"]})
    try:
        r = client.post("/api/lunettes/attestation", json={"nom": "M01 Pro_F444", "identifiant": "android-1",
                                                           "source": "android"})
        assert r.status_code == 200, r.text
        assert client.delete("/api/lunettes/attestation", params={"identifiant": "ios-1"}).json()["presentes"] is True
        assert client.delete("/api/lunettes/attestation",
                             params={"identifiant": "android-1"}).json()["presentes"] is False
    finally:
        client.delete("/api/lunettes/attestation")
