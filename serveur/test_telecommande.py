"""Le canal inverse (télécommande) : le relais courtier route les commandes du téléphone vers
l'ordinateur du MÊME courriel ET du MÊME code d'appairage, relaie les demandes de confirmation, et
refuse tout le reste.

Ce que ces tests protègent : (1) un jeton invalide ou un hello sans code d'appairage n'ouvre rien ;
(2) un aller-retour complet marche, confirmation comprise ; (3) un téléphone d'un autre compte
n'atteint jamais l'ordinateur d'autrui ; (4) le BON courriel mais un MAUVAIS code d'appairage
n'atteint pas l'ordinateur non plus (connaître le courriel ne suffit pas). Aucun réseau réel.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from starlette.websockets import WebSocketDisconnect

RACINE = Path(__file__).resolve().parents[1]
for chemin in (str(Path(__file__).parent), str(RACINE / "backend")):
    if chemin not in sys.path:
        sys.path.insert(0, chemin)

CODE = "code-appairage-secret"  # affiché par l'ordinateur, saisi dans le téléphone


@pytest.fixture()
def relais(tmp_path, monkeypatch):
    monkeypatch.setenv("VELA_DONNEES", str(tmp_path))
    monkeypatch.setenv("VELA_OPENROUTER_KEY", "sk-or-factice")
    for module in [m for m in list(sys.modules) if m == "relais"]:
        del sys.modules[module]
    import relais as module

    return module


@pytest.fixture()
def client(relais):
    from fastapi.testclient import TestClient

    return TestClient(relais.app)


def _jeton(relais, courriel):
    return relais.emettre_jeton(courriel, "machine-test")


def _hello(jeton, pairing=CODE):
    return {"type": "hello", "jeton": jeton, "pairing": pairing}


def test_refuse_un_jeton_invalide(client):
    with client.websocket_connect("/appareil/ws") as ws:
        ws.send_json(_hello("pas-un-vrai-jeton"))
        with pytest.raises(WebSocketDisconnect):
            ws.receive_json()  # fermée (4001), aucun {pret}


def test_ordinateur_refuse_sans_code_dappairage(client, relais):
    with client.websocket_connect("/appareil/ws") as ws:
        ws.send_json({"type": "hello", "jeton": _jeton(relais, "a@vela.app")})  # pairing manquant
        with pytest.raises(WebSocketDisconnect):
            ws.receive_json()


def test_ordinateur_valide_est_pret(client, relais):
    with client.websocket_connect("/appareil/ws") as ws:
        ws.send_json(_hello(_jeton(relais, "a@vela.app")))
        assert ws.receive_json() == {"type": "pret"}


def test_sans_ordinateur_le_dit(client, relais):
    with client.websocket_connect("/telecommande/ws") as tel:
        tel.send_json(_hello(_jeton(relais, "seul@vela.app")))
        assert tel.receive_json()["ordinateur"] is False
        tel.send_json({"type": "commande", "req_id": "x", "texte": "ouvre une application"})
        assert tel.receive_json()["erreur"] == "ordinateur_absent"


def test_aller_retour_complet(client, relais):
    tok = _jeton(relais, "duo@vela.app")  # même compte, même code des deux côtés
    with client.websocket_connect("/appareil/ws") as pc:
        pc.send_json(_hello(tok))
        assert pc.receive_json() == {"type": "pret"}
        with client.websocket_connect("/telecommande/ws") as tel:
            tel.send_json(_hello(tok))
            pret = tel.receive_json()
            assert pret["type"] == "pret" and pret["ordinateur"] is True
            tel.send_json({"type": "commande", "req_id": "r1", "texte": "ouvre le bloc-notes"})
            assert pc.receive_json() == {"type": "commande", "req_id": "r1", "texte": "ouvre le bloc-notes"}
            pc.send_json({"type": "confirm", "req_id": "r1", "confirm_id": "c1", "title": "Ouvrir ?", "detail": "Bloc-notes"})
            conf = tel.receive_json()
            assert conf["type"] == "confirm" and conf["confirm_id"] == "c1"
            tel.send_json({"type": "confirm_reponse", "req_id": "r1", "confirm_id": "c1", "approved": True})
            assert pc.receive_json()["approved"] is True
            pc.send_json({"type": "resultat", "req_id": "r1", "reponse": "C'est fait."})
            assert tel.receive_json() == {"type": "resultat", "req_id": "r1", "reponse": "C'est fait."}


def test_cloisonnee_par_compte(client, relais):
    """Un téléphone d'un AUTRE courriel n'atteint pas l'ordinateur de quelqu'un d'autre."""
    with client.websocket_connect("/appareil/ws") as pc:
        pc.send_json(_hello(_jeton(relais, "proprietaire@vela.app")))
        assert pc.receive_json() == {"type": "pret"}
        with client.websocket_connect("/telecommande/ws") as tel:
            tel.send_json(_hello(_jeton(relais, "voisin@vela.app")))  # autre compte
            assert tel.receive_json()["ordinateur"] is False
            tel.send_json({"type": "commande", "req_id": "z", "texte": "ouvre une application"})
            assert tel.receive_json()["erreur"] == "ordinateur_absent"


def test_bon_courriel_mais_mauvais_code_est_refuse(client, relais):
    """Connaître le courriel ne suffit pas : sans le bon code d'appairage, l'ordinateur reste hors d'atteinte."""
    tok = _jeton(relais, "cible@vela.app")
    with client.websocket_connect("/appareil/ws") as pc:
        pc.send_json(_hello(tok, pairing="le-vrai-code"))
        assert pc.receive_json() == {"type": "pret"}
        with client.websocket_connect("/telecommande/ws") as tel:
            tel.send_json(_hello(tok, pairing="mauvais-code"))  # même courriel, code faux
            assert tel.receive_json()["ordinateur"] is False
            tel.send_json({"type": "commande", "req_id": "z", "texte": "ouvre une application"})
            assert tel.receive_json()["erreur"] == "ordinateur_absent"


# --------------------------------------------------------------------------- liaison ordinateur ↔ courriel (2026-09-14)
def _cle_b64(relais, octet: int = 7) -> str:
    return relais._b64(bytes([octet]) * 32)


def test_sans_serveur_de_courriel_aucune_liaison_et_on_le_dit(client, relais, monkeypatch):
    monkeypatch.delenv("VELA_SMTP_HOTE", raising=False)
    r = client.post("/api/appareil/liaison", json={"jeton": _jeton(relais, "a@vela.app"), "cle": _cle_b64(relais)})
    assert r.status_code == 503 and r.json()["etat"] == "confirmation_indisponible"
    assert "ne peut pas encore être lié" in r.json()["message"]
    assert relais.liaison_confirmee("a@vela.app") is None


def test_la_liaison_nexiste_quapres_la_confirmation_par_courriel(client, relais, monkeypatch):
    courriels: list[tuple[str, str, str]] = []
    monkeypatch.setenv("VELA_SMTP_HOTE", "smtp.exemple")
    monkeypatch.setattr(relais, "envoyer_courriel", lambda a, sujet, corps: courriels.append((a, sujet, corps)) or True)
    jeton = _jeton(relais, "Proprio@Vela.app")
    assert client.post("/api/appareil/liaison", json={"jeton": "faux", "cle": _cle_b64(relais)}).status_code == 401
    assert client.post("/api/appareil/liaison", json={"jeton": jeton, "cle": "trop-court"}).status_code == 422
    r = client.post("/api/appareil/liaison", json={"jeton": jeton, "cle": _cle_b64(relais), "machine": "Portable"})
    assert r.status_code == 202 and r.json()["etat"] == "en_attente"
    assert relais.liaison_confirmee("proprio@vela.app") is None, "rien n'est lié avant la confirmation"
    # La même demande, tout de suite : pas de second courriel.
    assert client.post("/api/appareil/liaison", json={"jeton": jeton, "cle": _cle_b64(relais)}).status_code == 202
    assert len(courriels) == 1
    destinataire, _, corps = courriels[0]
    assert destinataire == "proprio@vela.app" and "Portable" in corps
    lien = next(mot for mot in corps.split() if "/appareil/confirmer/" in mot)
    chemin = "/appareil/confirmer/" + lien.rsplit("/", 1)[-1]
    page = client.get(chemin)
    assert page.status_code == 200 and "Confirmer cet ordinateur" in page.text
    assert relais.liaison_confirmee("proprio@vela.app") is None, "ouvrir le lien ne confirme rien tout seul"
    # Contre-vérification du 2026-09-14 : le lien seul ne confirme pas ; il faut recopier le code affiché dans IRIS.
    assert r.json()["empreinte"] == relais.empreinte_cle(bytes([7]) * 32)
    sans_code = client.post("/api/appareil/confirmer", json={"jeton": chemin.rsplit("/", 1)[-1]})
    assert sans_code.status_code == 403 and relais.liaison_confirmee("proprio@vela.app") is None
    ok = client.post("/api/appareil/confirmer", json={"jeton": chemin.rsplit("/", 1)[-1],
                                                       "empreinte": r.json()["empreinte"].lower()})
    assert ok.status_code == 200 and ok.json()["ok"] is True
    assert relais.liaison_confirmee("proprio@vela.app") is not None
    assert client.post("/api/appareil/confirmer", json={"jeton": chemin.rsplit("/", 1)[-1]}).status_code == 410, "usage unique"
    assert client.get(chemin).status_code == 410
    deja = client.post("/api/appareil/liaison", json={"jeton": jeton, "cle": _cle_b64(relais)})
    assert deja.status_code == 200 and deja.json()["etat"] == "confirmee"
    # Une autre clé pour le même courriel : un nouveau courriel, et la liaison actuelle ne bouge pas avant confirmation.
    autre = client.post("/api/appareil/liaison", json={"jeton": jeton, "cle": _cle_b64(relais, 9), "machine": "Voleur"})
    assert autre.status_code == 202 and len(courriels) == 2 and "remplacera" in courriels[1][2]
    cle_actuelle = relais._cle_de("proprio@vela.app", relais.liaison_confirmee("proprio@vela.app"))
    assert cle_actuelle == bytes([7]) * 32
    fichier = (relais.DONNEES / relais.FICHIER_LIAISONS).read_text(encoding="utf-8")
    assert _cle_b64(relais) not in fichier, "la clé n'est pas gardée en clair"


def test_un_ordinateur_non_prouve_est_refuse_quand_une_liaison_existe(client, relais, monkeypatch):
    from starlette.websockets import WebSocketDisconnect

    monkeypatch.setenv("VELA_SMTP_HOTE", "smtp.exemple")
    liens: list[str] = []
    monkeypatch.setattr(relais, "envoyer_courriel", lambda a, s, corps: liens.append(corps) or True)
    tok = _jeton(relais, "lie@vela.app")
    empreinte = client.post("/api/appareil/liaison", json={"jeton": tok, "cle": _cle_b64(relais)}).json()["empreinte"]
    jeton_confirmation = next(m for m in liens[0].split() if "/appareil/confirmer/" in m).rsplit("/", 1)[-1]
    with client.websocket_connect("/appareil/ws") as ancien:
        ancien.send_json(_hello(tok))
        assert ancien.receive_json() == {"type": "pret"}
        # La confirmation déconnecte la connexion non prouvée : l'ordinateur lié va se reconnecter et prouver.
        assert client.post("/api/appareil/confirmer",
                           json={"jeton": jeton_confirmation, "empreinte": empreinte}).status_code == 200
        with pytest.raises(WebSocketDisconnect):
            ancien.receive_json()
    with client.websocket_connect("/appareil/ws") as sans_preuve:
        sans_preuve.send_json(_hello(tok))
        assert sans_preuve.receive_json()["type"] == "refus"
    with client.websocket_connect("/telecommande/ws") as tel:  # le téléphone n'atteint pas un intrus
        tel.send_json(_hello(tok))
        assert tel.receive_json()["ordinateur"] is False


def test_api_appareil_est_limitee_en_debit(client, relais):
    statuts = [client.post("/api/appareil", json={"machine": "m", "email": "cible@vela.app"},
                           headers={"X-Forwarded-For": f"198.51.100.{i}"}).status_code for i in range(11)]
    assert statuts[:10] == [200] * 10 and statuts[10] == 429


def test_le_lien_de_confirmation_ne_suit_pas_un_hote_impose_par_lappelant(client, relais, monkeypatch):
    """Le lien part chez le propriétaire du courriel : l'appelant ne doit pas pouvoir y mettre son propre site
    (X-Forwarded-Host), qui recevrait le jeton de confirmation dès l'ouverture du lien."""
    courriels: list[str] = []
    monkeypatch.setenv("VELA_SMTP_HOTE", "smtp.exemple")
    monkeypatch.delenv("VELA_URL_PUBLIQUE", raising=False)
    monkeypatch.setattr(relais, "envoyer_courriel", lambda a, s, corps: courriels.append(corps) or True)
    r = client.post("/api/appareil/liaison", json={"jeton": _jeton(relais, "hote@vela.app"), "cle": _cle_b64(relais)},
                    headers={"X-Forwarded-Host": "pirate.exemple", "X-Forwarded-Proto": "http"})
    assert r.status_code == 202
    lien = next(m for m in courriels[0].split() if "/appareil/confirmer/" in m)
    assert "pirate.exemple" not in lien and lien.startswith("http://testserver/appareil/confirmer/")
    monkeypatch.setenv("VELA_URL_PUBLIQUE", "https://relais.velaglass.ca/")
    client.post("/api/appareil/liaison", json={"jeton": _jeton(relais, "hote2@vela.app"), "cle": _cle_b64(relais)},
                headers={"X-Forwarded-Host": "pirate.exemple"})
    assert "https://relais.velaglass.ca/appareil/confirmer/" in courriels[1]


def test_un_tiers_ne_bloque_ni_ne_detourne_la_liaison_du_vrai_ordinateur(client, relais, monkeypatch):
    """Contre-vérification du 2026-09-14 (sonde 1) : un tiers muni d'un jeton pour le courriel de la victime envoyait
    5 demandes de liaison ; le vrai PC recevait 429 pendant 24 h et le seul lien encore valable liait la clé du tiers."""
    courriels: list[str] = []
    monkeypatch.setenv("VELA_SMTP_HOTE", "smtp.exemple")
    monkeypatch.setattr(relais, "envoyer_courriel", lambda a, s, corps: courriels.append(corps) or True)
    victime = "victime@vela.app"
    jeton_tiers = client.post("/api/appareil", json={"machine": "DESKTOP-MIGUEL", "email": victime},
                              headers={"X-Forwarded-For": "203.0.113.9"}).json()["jeton"]
    for i in range(5):
        r = client.post("/api/appareil/liaison", json={"jeton": jeton_tiers, "cle": _cle_b64(relais, 100 + i),
                                                        "machine": "DESKTOP-MIGUEL"},
                        headers={"X-Forwarded-For": f"203.0.113.{i}"})
        assert r.status_code == 202
    liens_tiers = [next(m for m in c.split() if "/appareil/confirmer/" in m).rsplit("/", 1)[-1] for c in courriels]
    assert "DESKTOP-MIGUEL" in courriels[0] and relais.empreinte_cle(bytes([100]) * 32) not in courriels[0],         "le courriel ne donne pas le code : il faut le lire dans IRIS"
    # Le vrai PC n'est pas bloqué.
    r_victime = client.post("/api/appareil/liaison", json={"jeton": relais.emettre_jeton(victime, "vrai-pc"),
                                                            "cle": _cle_b64(relais, 7), "machine": "DESKTOP-MIGUEL"},
                            headers={"X-Forwarded-For": "198.51.100.77"})
    assert r_victime.status_code == 202, r_victime.text
    code_iris = r_victime.json()["empreinte"]
    lien_victime = next(m for m in courriels[-1].split() if "/appareil/confirmer/" in m).rsplit("/", 1)[-1]
    # Tous les liens restent valables (plus d'écrasement).
    assert all(client.get(f"/appareil/confirmer/{j}").status_code == 200 for j in liens_tiers + [lien_victime])
    # Ouvrir le lien d'un tiers et confirmer « à l'aveugle » ne lie rien ; y recopier le code d'IRIS lie le vrai PC.
    assert client.post("/api/appareil/confirmer", json={"jeton": liens_tiers[-1], "empreinte": "AAAAAA"}).status_code == 403
    assert relais.liaison_confirmee(victime) is None
    ok = client.post("/api/appareil/confirmer", json={"jeton": liens_tiers[-1], "empreinte": code_iris})
    assert ok.status_code == 200
    assert relais._cle_de(victime, relais.liaison_confirmee(victime)) == bytes([7]) * 32


def test_cinq_codes_errones_epuisent_le_lien(client, relais, monkeypatch):
    courriels: list[str] = []
    monkeypatch.setenv("VELA_SMTP_HOTE", "smtp.exemple")
    monkeypatch.setattr(relais, "envoyer_courriel", lambda a, s, corps: courriels.append(corps) or True)
    r = client.post("/api/appareil/liaison", json={"jeton": _jeton(relais, "essais@vela.app"), "cle": _cle_b64(relais)})
    lien = next(m for m in courriels[0].split() if "/appareil/confirmer/" in m).rsplit("/", 1)[-1]
    for _ in range(5):
        assert client.post("/api/appareil/confirmer", json={"jeton": lien, "empreinte": "ZZZZZZ"}).status_code == 403
    assert client.post("/api/appareil/confirmer", json={"jeton": lien, "empreinte": r.json()["empreinte"]}).status_code == 410


def test_sante_dit_si_une_liaison_est_possible(client, relais, monkeypatch):
    monkeypatch.delenv("VELA_SMTP_HOTE", raising=False)
    assert client.get("/sante").json()["liaison_possible"] is False
    monkeypatch.setenv("VELA_SMTP_HOTE", "smtp.exemple")
    assert client.get("/sante").json()["liaison_possible"] is True


def test_lempreinte_affichee_par_iris_est_celle_du_relais(relais):
    """IRIS (backend/iris/telecommande.py) et le relais calculent le même code : sinon la confirmation échouerait."""
    from iris.telecommande import empreinte_cle

    for octet in (0, 7, 255):
        assert empreinte_cle(bytes([octet]) * 32) == relais.empreinte_cle(bytes([octet]) * 32)


# --------------------------------------------------------------------------- finition B du 2026-09-14
def _lien_de(corps: str) -> str:
    return next(m for m in corps.split() if "/appareil/confirmer/" in m).rsplit("/", 1)[-1]


def test_les_relances_d_iris_gardent_le_premier_lien_valable_et_ne_donnent_pas_429(client, relais, monkeypatch):
    """IRIS redemande la liaison à chaque reconnexion, au plus toutes les 10 minutes. Avant ce correctif, chaque relance
    renvoyait un courriel, invalidait le lien précédent (410) et, à la 6e, IRIS affichait « Trop de demandes » alors
    qu'un lien valable attendait dans la boîte."""
    import time as module_time

    courriels: list[str] = []
    monkeypatch.setenv("VELA_SMTP_HOTE", "smtp.exemple")
    monkeypatch.setattr(relais, "envoyer_courriel", lambda a, s, corps: courriels.append(corps) or True)
    horloge = {"t": module_time.time()}
    monkeypatch.setattr(relais.time, "time", lambda: horloge["t"])
    jeton = _jeton(relais, "relances@vela.app")
    reponses = []
    for _ in range(7):
        r = client.post("/api/appareil/liaison", json={"jeton": jeton, "cle": _cle_b64(relais), "machine": "PC"},
                        headers={"X-Forwarded-For": "198.51.100.10"})
        reponses.append(r)
        horloge["t"] += 601
    assert [r.status_code for r in reponses] == [202] * 7
    assert len(courriels) == 1, "aucun nouveau courriel tant que le lien envoyé reste valable"
    assert "déjà été envoyé" in reponses[-1].json()["message"]
    assert "Trop de demandes" not in reponses[-1].json()["message"]
    premier = _lien_de(courriels[0])
    assert client.get(f"/appareil/confirmer/{premier}").status_code == 200
    ok = client.post("/api/appareil/confirmer", json={"jeton": premier, "empreinte": reponses[0].json()["empreinte"]})
    assert ok.status_code == 200
    # Passé 24 h, un nouveau courriel peut partir (l'attente a expiré).
    horloge["t"] += relais.DUREE_CONFIRMATION_S + 1
    autre = client.post("/api/appareil/liaison", json={"jeton": _jeton(relais, "expire@vela.app"), "cle": _cle_b64(relais, 3)})
    assert autre.status_code == 202 and len(courriels) == 2


def test_une_rafale_de_cles_n_evince_pas_l_attente_du_proprietaire(client, relais, monkeypatch):
    """21 clés depuis 5 adresses évinçaient l'attente du propriétaire (son lien -> 410, son code -> 403)."""
    courriels: list[str] = []
    monkeypatch.setenv("VELA_SMTP_HOTE", "smtp.exemple")
    monkeypatch.setattr(relais, "envoyer_courriel", lambda a, s, corps: courriels.append(corps) or True)
    victime = "rafale@vela.app"
    r = client.post("/api/appareil/liaison", json={"jeton": relais.emettre_jeton(victime, "pc"),
                                                    "cle": _cle_b64(relais, 7), "machine": "PC"},
                    headers={"X-Forwarded-For": "198.51.100.77"})
    code, lien_proprio = r.json()["empreinte"], _lien_de(courriels[-1])
    jeton_tiers = relais.emettre_jeton(victime, "tiers")
    for i in range(21):
        rr = client.post("/api/appareil/liaison", json={"jeton": jeton_tiers, "cle": _cle_b64(relais, 100 + i),
                                                         "machine": "PC"},
                         headers={"X-Forwarded-For": f"203.0.113.{i // 5}"})
        assert rr.status_code in (202, 429)
    assert client.get(f"/appareil/confirmer/{lien_proprio}").status_code == 200
    ok = client.post("/api/appareil/confirmer", json={"jeton": _lien_de(courriels[-1]), "empreinte": code})
    assert ok.status_code == 200, ok.text
    assert relais._cle_de(victime, relais.liaison_confirmee(victime)) == bytes([7]) * 32


def test_table_pleine_d_attentes_seules_refuse_sans_evincer(client, relais, monkeypatch):
    """Quand toutes les attentes viennent d'adresses distinctes (une chacune), la nouvelle demande est refusée : l'attente
    seule de son adresse — celle du propriétaire — ne cède jamais."""
    courriels: list[str] = []
    monkeypatch.setenv("VELA_SMTP_HOTE", "smtp.exemple")
    monkeypatch.setattr(relais, "envoyer_courriel", lambda a, s, corps: courriels.append(corps) or True)
    monkeypatch.setattr(relais, "LIAISONS_PAR_IP", 1000)
    victime = "pleine@vela.app"
    r = client.post("/api/appareil/liaison", json={"jeton": relais.emettre_jeton(victime, "pc"), "cle": _cle_b64(relais, 7)},
                    headers={"X-Forwarded-For": "198.51.100.77"})
    code, lien_proprio = r.json()["empreinte"], _lien_de(courriels[-1])
    jeton_tiers = relais.emettre_jeton(victime, "tiers")
    statuts = [client.post("/api/appareil/liaison", json={"jeton": jeton_tiers, "cle": _cle_b64(relais, 100 + i)},
                           headers={"X-Forwarded-For": f"192.0.2.{i}"}).status_code
               for i in range(relais.ATTENTES_PAR_COURRIEL + 3)]
    assert statuts.count(202) == relais.ATTENTES_PAR_COURRIEL - 1 and statuts[-1] == 429
    ok = client.post("/api/appareil/confirmer", json={"jeton": lien_proprio, "empreinte": code})
    assert ok.status_code == 200, ok.text
