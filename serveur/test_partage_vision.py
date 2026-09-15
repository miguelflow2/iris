"""Vision partagée, côté relais. Tout est synthétique : jetons d'appareil émis ici, fausses images JPEG
(quelques octets avec l'en-tête JPEG), horloge remplacée pour simuler l'expiration. Aucun réseau.

Ce qui doit tenir, parce qu'une personne malvoyante s'y fie et qu'un inconnu ne doit rien voir :
- seul un appareil VELA authentique crée un partage, et le jeton émetteur n'est gardé qu'en empreinte ;
- les images vont à chaque spectateur, trois au plus, et rien n'est écrit sur le disque ;
- une image trop lourde, qui n'est pas un JPEG ou qui dépasse le débit n'atteint personne ;
- un partage expiré se ferme pour tout le monde, même sans nouvelle image ;
- les messages du spectateur arrivent à l'émetteur, nettoyés ;
- deviner un code est bridé par adresse, sur la page comme sur le WebSocket.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import anyio
import pytest

RACINE = Path(__file__).resolve().parents[1]
for chemin in (str(Path(__file__).parent), str(RACINE / "backend")):
    if chemin not in sys.path:
        sys.path.insert(0, chemin)

JPEG = b"\xff\xd8\xff\xe0" + b"image-synthetique" * 4 + b"\xff\xd9"
NOMS_INTERDITS = ("claude", "anthropic", "openai", "gpt", "gemini", "google", "elevenlabs", "vosk", "piper", "twilio")


@pytest.fixture()
def relais(tmp_path, monkeypatch):
    monkeypatch.setenv("VELA_DONNEES", str(tmp_path))
    monkeypatch.setenv("VELA_OPENROUTER_KEY", "sk-or-factice")
    monkeypatch.delenv("VELA_URL_PUBLIQUE", raising=False)
    for module in [m for m in list(sys.modules) if m in ("relais", "partage_vision")]:
        del sys.modules[module]
    import relais as module

    return module


@pytest.fixture()
def pv(relais):
    import partage_vision

    return partage_vision


@pytest.fixture()
def horloge(pv, monkeypatch):
    """Horloge figée, avancée à la main : l'expiration et le débit se testent sans attendre."""
    etat = {"t": time.time()}
    monkeypatch.setattr(pv, "maintenant", lambda: etat["t"])
    return etat


@pytest.fixture()
def banc(relais, pv):
    """Le routeur du partage seul, dans une application minimale, pour garder la main sur son état.
    `with TestClient` : toutes les connexions partagent la même boucle, comme sous uvicorn."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    application = FastAPI()
    routeur = pv.creer_routeur_partage(relais)
    application.include_router(routeur)
    with TestClient(application) as client:
        yield client, routeur.partage_etat


def jeton_appareil(relais, courriel: str = "proche@exemple.com") -> str:
    return relais.emettre_jeton(courriel, "machine-1")


def creer(client, relais, courriel: str = "proche@exemple.com", ip: str = "198.51.100.7") -> dict:
    r = client.post("/api/partage/creer", json={"jeton_appareil": jeton_appareil(relais, courriel)},
                    headers={"X-Forwarded-For": ip})
    assert r.status_code == 200, r.text
    return r.json()


# --------------------------------------------------------------------------- lecture avec délai
def recevoir(ws, delai: float = 5.0) -> dict:
    """Le prochain message brut du serveur, avec un délai : un test ne doit jamais pendre."""
    async def lire():
        with anyio.fail_after(delai):
            return await ws._send_rx.receive()

    return ws.portal.call(lire)


def recevoir_json(ws, attendu: str | None = None, delai: float = 5.0) -> dict:
    fin = time.monotonic() + delai
    while True:
        message = recevoir(ws, max(0.05, fin - time.monotonic()))
        if message["type"] == "websocket.close":
            raise AssertionError(f"connexion fermée ({message.get('code')}) avant « {attendu} »")
        if message.get("text") is not None:
            contenu = json.loads(message["text"])
            if attendu is None or contenu.get("type") == attendu:
                return contenu


def recevoir_image(ws, delai: float = 5.0) -> bytes:
    fin = time.monotonic() + delai
    while True:
        message = recevoir(ws, max(0.05, fin - time.monotonic()))
        if message["type"] == "websocket.close":
            raise AssertionError(f"connexion fermée ({message.get('code')}) avant l'image")
        if message.get("bytes") is not None:
            return message["bytes"]


def fermeture(ws, delai: float = 5.0) -> int:
    fin = time.monotonic() + delai
    while True:
        message = recevoir(ws, max(0.05, fin - time.monotonic()))
        if message["type"] == "websocket.close":
            return int(message.get("code") or 1000)


# --------------------------------------------------------------------------- création
def test_seul_un_appareil_vela_authentique_cree_un_partage(banc, relais, pv):
    client, etat = banc
    assert client.post("/api/partage/creer", json={}).status_code == 401
    forge = jeton_appareil(relais)[:-3] + "AAA"
    assert client.post("/api/partage/creer", json={"jeton_appareil": forge}).status_code == 401

    session = creer(client, relais)
    assert pv.code_valide(session["code"])
    assert not set(session["code"]) & set("0O1IL")
    assert len(session["jeton_emetteur"]) >= 40
    assert session["url_spectateur"].endswith("/voir/" + session["code"])
    assert session["expire_a"] and session["expire_dans_s"] == 1800
    # Le jeton émetteur n'est gardé qu'en empreinte.
    assert session["jeton_emetteur"] not in etat["par_jeton"]
    assert pv.empreinte(session["jeton_emetteur"]) in etat["par_jeton"]


def test_le_lien_suit_l_adresse_publique_du_mandataire(banc, relais):
    client, _ = banc
    r = client.post("/api/partage/creer", json={"jeton_appareil": jeton_appareil(relais)},
                    headers={"X-Forwarded-Proto": "https", "Host": "relais.velaglass.ca"})
    corps = r.json()
    assert corps["url_spectateur"].startswith("https://relais.velaglass.ca/voir/")
    assert corps["ws_emetteur"] == "wss://relais.velaglass.ca/partage/emetteur"


def test_une_session_abandonnee_est_remplacee_apres_une_minute(banc, relais, horloge):
    client, etat = banc
    premier = creer(client, relais)
    with client.websocket_connect(f"/partage/spectateur/{premier['code']}") as spectateur:
        recevoir_json(spectateur, "etat")
        creer(client, relais)
        horloge["t"] += 61  # aucun émetteur depuis plus d'une minute : la plus vieille peut céder sa place
        creer(client, relais)
        fin = recevoir_json(spectateur, "fin")
        assert fin["raison"] == "remplacee"
        assert fermeture(spectateur) == 4010
    assert premier["code"] not in etat["sessions"] and len(etat["sessions"]) == 2


def test_un_partage_en_service_nest_jamais_ferme_par_une_creation(banc, relais, horloge):
    """Constat du 2026-09-14 : un tiers qui connaît le courriel fermait en boucle, par des créations, le partage
    d'une personne malvoyante en pleine aide à distance. Une session dont l'émetteur est connecté reste."""
    client, etat = banc
    en_service = creer(client, relais)
    with client.websocket_connect(f"/partage/emetteur?jeton={en_service['jeton_emetteur']}") as emetteur:
        recevoir_json(emetteur, "pret")
        creer(client, relais)
        horloge["t"] += 120  # deux minutes plus tard, l'émetteur est toujours là
        # Finition B : la limite de 2 sessions est comptée par (compte, adresse de création) ; on crée donc depuis
        # la même adresse que les deux premières (celle par défaut de creer()).
        seconde = client.post("/api/partage/creer", json={"jeton_appareil": jeton_appareil(relais)},
                              headers={"X-Forwarded-For": "198.51.100.7"})
        assert seconde.status_code == 200, "la session sans émetteur, vieille, cède sa place"
        refus = client.post("/api/partage/creer", json={"jeton_appareil": jeton_appareil(relais)},
                            headers={"X-Forwarded-For": "198.51.100.7"})
        assert refus.status_code == 409 and "déjà en cours" in refus.json()["detail"]
        assert en_service["code"] in etat["sessions"] and not etat["sessions"][en_service["code"]].fermee
        # Depuis une autre adresse, la création passe, sans rien fermer.
        ailleurs = client.post("/api/partage/creer", json={"jeton_appareil": jeton_appareil(relais)},
                               headers={"X-Forwarded-For": "203.0.113.51"})
        assert ailleurs.status_code == 200, ailleurs.text
        assert not etat["sessions"][en_service["code"]].fermee


def test_un_tiers_depuis_une_adresse_ne_bloque_pas_la_victime(banc, relais, horloge):
    """Finition B du 2026-09-14 : depuis UNE adresse, un tiers gardait 2 partages avec émetteurs connectés et la victime
    (compte sans ordinateur lié) recevait 409 « réessayez dans une minute », faux, aussi longtemps qu'il renouvelait."""
    client, etat = banc
    victime = "malvoyant@vela.app"
    tiers = [client.post("/api/partage/creer", json={"jeton_appareil": jeton_appareil(relais, victime)},
                         headers={"X-Forwarded-For": "203.0.113.9"}).json() for _ in range(2)]
    connexions = []
    try:
        for session in tiers:
            cm = client.websocket_connect(f"/partage/emetteur?jeton={session['jeton_emetteur']}")
            ws = cm.__enter__()
            connexions.append(cm)
            recevoir_json(ws, "pret")
        horloge["t"] += 600
        r = client.post("/api/partage/creer", json={"jeton_appareil": jeton_appareil(relais, victime)},
                        headers={"X-Forwarded-For": "198.51.100.1"})
        assert r.status_code == 200, r.text
        # Le tiers, lui, atteint sa limite ; et on ne lui promet pas une minute qui ne libérera rien.
        refus = client.post("/api/partage/creer", json={"jeton_appareil": jeton_appareil(relais, victime)},
                            headers={"X-Forwarded-For": "203.0.113.9"})
        assert refus.status_code == 409
        assert "une minute" not in refus.json()["detail"] and "connectés" in refus.json()["detail"]
        assert all(not etat["sessions"][s["code"]].fermee for s in tiers)
    finally:
        for cm in connexions:
            cm.__exit__(None, None, None)


def test_cinq_creations_au_plus_par_compte(banc, relais):
    """Cinq créations au plus par 15 minutes pour un compte depuis une même adresse. Contre-vérification du
    2026-09-14 : compté par compte seul, ce quota était épuisé par un tiers (cinq adresses) et la victime
    recevait 429 ; le tiers n'entame plus le quota de la victime."""
    client, _ = banc
    statuts = []
    for i in range(6):
        r = client.post("/api/partage/creer", json={"jeton_appareil": jeton_appareil(relais)},
                        headers={"X-Forwarded-For": "203.0.113.7"})
        statuts.append(r.status_code)
        if r.status_code == 200:
            client.post("/api/partage/fermer", json={"jeton_emetteur": r.json()["jeton_emetteur"]})
    assert statuts == [200] * 5 + [429]
    # Un tiers qui a épuisé SON quota pour ce compte ne bloque pas la victime, qui crée depuis son adresse.
    victime = client.post("/api/partage/creer", json={"jeton_appareil": jeton_appareil(relais)},
                          headers={"X-Forwarded-For": "198.51.100.1"})
    assert victime.status_code == 200, victime.text


def _lier(relais, courriel: str, cle: bytes) -> None:
    ident = "liaison-test"
    relais._ecrire(relais.FICHIER_LIAISONS, {courriel: {
        "id": ident, "cle": relais._b64(relais._xor(cle, relais._cle_emballage(courriel, ident))), "machine": "pc",
        "confirme_le": "2026-09-14T08:00:00+00:00", "sel": None, "iterations": None}})


def test_un_ordinateur_lie_doit_prouver_sa_cle_pour_creer(banc, relais):
    import hashlib
    import hmac

    client, _ = banc
    cle = b"k" * 32
    courriel = "proche@exemple.com"
    _lier(relais, courriel, cle)
    sans = client.post("/api/partage/creer", json={"jeton_appareil": jeton_appareil(relais, courriel)})
    assert sans.status_code == 403 and "lié" in sans.json()["detail"]
    instant = int(time.time())

    def preuve(avec: bytes) -> dict:
        message = f"vela-partage-creer|v1|{courriel}|{instant}".encode()
        return {"horodatage": instant, "preuve": relais._b64(hmac.new(avec, message, hashlib.sha256).digest())}

    fausse = client.post("/api/partage/creer", json={"jeton_appareil": jeton_appareil(relais, courriel),
                                                     "preuve_pc": preuve(b"x" * 32)})
    assert fausse.status_code == 403
    bonne = preuve(cle)
    assert client.post("/api/partage/creer", json={"jeton_appareil": jeton_appareil(relais, courriel),
                                                   "preuve_pc": bonne}).status_code == 200
    rejouee = client.post("/api/partage/creer", json={"jeton_appareil": jeton_appareil(relais, courriel),
                                                      "preuve_pc": bonne})
    assert rejouee.status_code == 403, "une preuve ne sert qu'une fois"


# --------------------------------------------------------------------------- images
def test_les_images_vont_a_deux_spectateurs_et_rien_n_est_ecrit(banc, relais, tmp_path):
    client, etat = banc
    session = creer(client, relais)
    with client.websocket_connect(f"/partage/emetteur?jeton={session['jeton_emetteur']}&source=ecran") as emetteur:
        pret = recevoir_json(emetteur, "pret")
        assert pret["code"] == session["code"] and pret["spectateurs"] == 0
        with client.websocket_connect(f"/partage/spectateur/{session['code']}") as s1, \
                client.websocket_connect(f"/partage/spectateur/{session['code'].lower()}") as s2:
            assert recevoir_json(s1, "etat")["source"] == "ecran"
            recevoir_json(s2, "etat")
            assert recevoir_json(emetteur, "spectateurs")["nombre"] == 1
            assert recevoir_json(emetteur, "spectateurs")["nombre"] == 2
            emetteur.send_bytes(JPEG)
            assert recevoir_image(s1) == JPEG
            assert recevoir_image(s2) == JPEG
        assert etat["sessions"][session["code"]].images == 1
    # Aucune image sur le disque du relais.
    assert not [f for f in Path(tmp_path).rglob("*") if f.is_file() and f.read_bytes().startswith(b"\xff\xd8")]


def test_un_quatrieme_spectateur_est_refuse(banc, relais):
    client, _ = banc
    session = creer(client, relais)
    url = f"/partage/spectateur/{session['code']}"
    with client.websocket_connect(url) as a, client.websocket_connect(url) as b, client.websocket_connect(url) as c:
        for ws in (a, b, c):
            recevoir_json(ws, "etat")
        with client.websocket_connect(url) as quatrieme:
            refus = recevoir_json(quatrieme, "refus")
            assert refus["raison"] == "complet" and "Trois personnes" in refus["message"]
            assert fermeture(quatrieme) == 4003


def test_image_trop_lourde_ou_non_jpeg_refusee(banc, relais, pv):
    client, etat = banc
    session = creer(client, relais)
    with client.websocket_connect(f"/partage/emetteur?jeton={session['jeton_emetteur']}") as emetteur, \
            client.websocket_connect(f"/partage/spectateur/{session['code']}") as spectateur:
        recevoir_json(spectateur, "etat")
        emetteur.send_bytes(b"\xff\xd8\xff" + b"\x00" * pv.TAILLE_MAX_IMAGE)
        refus = recevoir_json(emetteur, "refus")
        assert refus["raison"] == "taille" and refus["max_octets"] == 300_000
        emetteur.send_bytes(b"<html>pas une image</html>")
        assert recevoir_json(emetteur, "refus")["raison"] == "format"
        petite = JPEG + b"-2"
        emetteur.send_bytes(petite)
        # Le spectateur ne reçoit que l'image valide, jamais les deux refusées.
        assert recevoir_image(spectateur) == petite
    assert etat["sessions"][session["code"]].images == 1


def test_le_debit_est_borne_a_dix_images_par_seconde(banc, relais, horloge):
    client, etat = banc
    session = creer(client, relais)
    with client.websocket_connect(f"/partage/emetteur?jeton={session['jeton_emetteur']}") as emetteur:
        recevoir_json(emetteur, "pret")
        for _ in range(11):
            emetteur.send_bytes(JPEG)
        refus = recevoir_json(emetteur, "refus")
        assert refus["raison"] == "debit"
        assert etat["sessions"][session["code"]].images == 10
        horloge["t"] += 1.5  # une seconde plus tard, la fenêtre est libre
        emetteur.send_bytes(JPEG)
        emetteur.send_json({"type": "etat"})
        assert recevoir_json(emetteur, "stats")["images"] == 11


# --------------------------------------------------------------------------- expiration
def test_un_partage_expire_se_ferme_pour_tout_le_monde(banc, relais, horloge):
    client, etat = banc
    session = creer(client, relais)
    with client.websocket_connect(f"/partage/emetteur?jeton={session['jeton_emetteur']}") as emetteur, \
            client.websocket_connect(f"/partage/spectateur/{session['code']}") as spectateur:
        recevoir_json(emetteur, "pret")
        recevoir_json(spectateur, "etat")
        horloge["t"] += 31 * 60
        emetteur.send_bytes(JPEG)
        assert recevoir_json(emetteur, "fin")["raison"] == "expiree"
        fin = recevoir_json(spectateur, "fin")
        assert fin["raison"] == "expiree" and "30 minutes" in fin["message"]
        assert fermeture(spectateur) == 4010
    assert session["code"] not in etat["sessions"]
    assert client.get(f"/voir/{session['code']}").status_code == 404


def test_l_expiration_ferme_meme_sans_nouvelle_image(banc, relais, pv, horloge, monkeypatch):
    client, _ = banc
    monkeypatch.setattr(pv, "TIC_S", 0.05)
    session = creer(client, relais)
    with client.websocket_connect(f"/partage/spectateur/{session['code']}") as spectateur:
        recevoir_json(spectateur, "etat")
        horloge["t"] += 30 * 60 + 1
        assert recevoir_json(spectateur, "fin")["raison"] == "expiree"


def test_l_emetteur_prolonge_le_partage(banc, relais, horloge):
    client, etat = banc
    session = creer(client, relais)
    with client.websocket_connect("/partage/emetteur") as emetteur:
        emetteur.send_json({"type": "hello", "jeton": session["jeton_emetteur"], "role": "emetteur", "source": "lunettes"})
        recevoir_json(emetteur, "pret")
        horloge["t"] += 25 * 60
        emetteur.send_json({"type": "renouveler"})
        assert recevoir_json(emetteur, "expiration")["expire_dans_s"] == 1800
        horloge["t"] += 20 * 60  # 45 minutes après la création : toujours vivant
        emetteur.send_bytes(JPEG)
        emetteur.send_json({"type": "etat"})
        stats = recevoir_json(emetteur, "stats")
        assert stats["images"] == 1 and stats["source"] == "lunettes"
    # Par HTTP aussi, avec le jeton émetteur seulement.
    r = client.post("/api/partage/renouveler", json={"jeton_emetteur": session["jeton_emetteur"]})
    assert r.status_code == 200 and r.json()["expire_dans_s"] == 1800
    assert client.post("/api/partage/renouveler", json={"jeton_emetteur": "faux"}).status_code == 404
    assert session["code"] in etat["sessions"]


# --------------------------------------------------------------------------- messages et fin
def test_le_message_du_spectateur_arrive_a_l_emetteur_et_au_controle(banc, relais):
    client, _ = banc
    session = creer(client, relais)
    with client.websocket_connect(f"/partage/emetteur?jeton={session['jeton_emetteur']}") as emetteur, \
            client.websocket_connect(f"/partage/emetteur?jeton={session['jeton_emetteur']}&role=controle") as controle, \
            client.websocket_connect(f"/partage/spectateur/{session['code']}") as spectateur:
        recevoir_json(emetteur, "pret")
        assert recevoir_json(controle, "pret")["role"] == "controle"
        recevoir_json(spectateur, "etat")
        spectateur.send_json({"type": "message", "texte": "  Tourne\x00 à   gauche,\nla porte est là  " + "x" * 600})
        recu = recevoir_json(emetteur, "message")
        assert recu["texte"].startswith("Tourne à gauche, la porte est là x")
        assert len(recu["texte"]) == 500 and "\x00" not in recu["texte"]
        assert recevoir_json(controle, "message")["texte"] == recu["texte"]
        assert recevoir_json(spectateur, "message_envoye")["remis"] is True
        # Un contrôle n'émet pas d'images : ce qu'il envoie en binaire n'atteint personne.
        controle.send_bytes(JPEG)
        emetteur.send_json({"type": "etat"})
        assert recevoir_json(emetteur, "stats")["images"] == 0


def test_trop_de_messages_d_un_coup_sont_bridés(banc, relais, horloge):
    client, _ = banc
    session = creer(client, relais)
    with client.websocket_connect(f"/partage/spectateur/{session['code']}") as spectateur:
        recevoir_json(spectateur, "etat")
        for i in range(6):
            spectateur.send_json({"type": "message", "texte": f"message {i}"})
        remises = [recevoir_json(spectateur, "message_envoye") for _ in range(5)]
        assert all(r["remis"] is False for r in remises)  # personne n'émet encore
        assert recevoir_json(spectateur, "refus")["raison"] == "messages"


def test_l_emetteur_arrete_le_partage(banc, relais):
    client, etat = banc
    session = creer(client, relais)
    with client.websocket_connect(f"/partage/spectateur/{session['code']}") as spectateur:
        recevoir_json(spectateur, "etat")
        r = client.post("/api/partage/fermer", json={"jeton_emetteur": session["jeton_emetteur"]})
        assert r.json() == {"ok": True}
        assert recevoir_json(spectateur, "fin")["raison"] == "arrete"
    assert not etat["sessions"] and not etat["par_jeton"]
    assert client.post("/api/partage/fermer", json={"jeton_emetteur": session["jeton_emetteur"]}).status_code == 404


def test_un_nouvel_emetteur_remplace_l_ancien(banc, relais):
    client, _ = banc
    session = creer(client, relais)
    url = f"/partage/emetteur?jeton={session['jeton_emetteur']}"
    with client.websocket_connect(url) as ancien:
        recevoir_json(ancien, "pret")
        with client.websocket_connect(url + "&source=telephone") as nouveau:
            recevoir_json(nouveau, "pret")
            assert recevoir_json(ancien, "fin")["raison"] == "remplace"
            assert fermeture(ancien) == 4000


def test_un_jeton_emetteur_inconnu_est_refuse(banc):
    client, _ = banc
    with client.websocket_connect("/partage/emetteur?jeton=inconnu") as ws:
        assert recevoir_json(ws, "refus")["raison"] == "inconnu"
        assert fermeture(ws) == 4004


# --------------------------------------------------------------------------- tentatives
def test_deviner_un_code_est_bride_par_adresse(banc, relais):
    client, etat = banc
    session = creer(client, relais)
    entetes = {"X-Forwarded-For": "203.0.113.9"}
    for _ in range(10):
        assert client.get("/voir/ABCDEFGH", headers=entetes).status_code == 404
    # Même le bon code est refusé depuis cette adresse, sur la page comme sur le WebSocket.
    bloque = client.get(f"/voir/{session['code']}", headers=entetes)
    assert bloque.status_code == 429 and "Trop de tentatives" in bloque.text
    with client.websocket_connect(f"/partage/spectateur/{session['code']}", headers=entetes) as ws:
        assert recevoir_json(ws, "refus")["raison"] == "trop_de_tentatives"
        assert fermeture(ws) == 4029
    # Une autre adresse n'est pas touchée.
    assert client.get(f"/voir/{session['code']}", headers={"X-Forwarded-For": "203.0.113.10"}).status_code == 200


def test_le_websocket_spectateur_compte_aussi_les_echecs(banc):
    client, _ = banc
    entetes = {"X-Forwarded-For": "203.0.113.20"}
    for _ in range(10):
        with client.websocket_connect("/partage/spectateur/ZZZZZZZZ", headers=entetes) as ws:
            assert recevoir_json(ws, "refus")["raison"] == "inconnu"
    assert client.get("/voir/ZZZZZZZZ", headers=entetes).status_code == 429


# --------------------------------------------------------------------------- page du spectateur
def test_la_page_du_spectateur_est_autonome_accessible_et_en_francais(banc, relais):
    client, _ = banc
    session = creer(client, relais)
    r = client.get(f"/voir/{session['code']}")
    assert r.status_code == 200
    page = r.text
    assert '<html lang="fr-CA">' in page
    # Autonome : aucune ressource externe.
    for motif in ('src="http', "src='http", 'href="http', "@import", "url(http"):
        assert motif not in page
    # Accessible : état annoncé, image avec texte alternatif mis à jour, champ étiqueté, bouton « Parler ».
    assert 'role="status"' in page and 'aria-live="polite"' in page
    assert 'id="image" alt=' in page and "image.alt =" in page
    assert '<label for="message">' in page and ">Parler</button>" in page
    assert "SpeechRecognition" in page and "fr-CA" in page
    assert "images par seconde" in page
    # Honnête : ni vidéo, ni enregistrement, ni guidage de traversée.
    assert "Rien n'est enregistré" in page and "Ce n'est pas une vidéo" in page and "traversée de rue" in page
    minuscules = page.lower()
    for nom in NOMS_INTERDITS:
        assert nom not in minuscules, nom
    assert r.headers["referrer-policy"] == "no-referrer" and r.headers["cache-control"] == "no-store"
    assert "default-src 'none'" in r.headers["content-security-policy"]


def test_le_module_est_branche_dans_le_relais(relais):
    from fastapi.testclient import TestClient

    with TestClient(relais.app) as client:
        assert client.get("/voir/ABCDEFGH").status_code == 404
        r = client.post("/api/partage/creer", json={"jeton_appareil": jeton_appareil(relais)})
        assert r.status_code == 200
        assert client.get(f"/voir/{r.json()['code']}").status_code == 200
