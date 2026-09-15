"""Verrouillage à distance côté relais (serveur/verrou_distant.py, 2026-09-13 ; protocole à preuve du 2026-09-14).

Ce que ces tests protègent : (1) la page /verrou est autonome, en français, sans ressource externe, et dit ce
qui est vrai (le code ne quitte pas le navigateur, un succès n'est affiché que confirmé) ; (2) le code n'est
JAMAIS transmis : la page envoie une preuve à usage unique, et le calcul du navigateur (WebCrypto) donne
exactement celui de l'ordinateur ; (3) seul l'ordinateur LIÉ au courriel, qui a prouvé sa clé, reçoit la
commande ; une autre machine du même courriel est refusée et ne peut pas le remplacer ; (4) réponses uniformes :
un courriel inconnu reçoit un sel factice stable et la même réponse « transmise » ; (5) 5 tentatives par
15 minutes, par courriel ET par adresse IP ; (6) ordinateur hors ligne : la commande attend en mémoire (une par
adresse ; file pleine : la plus ancienne d'une autre adresse cède) et part à la reconnexion ; (7) sans réponse en 15 s, le relais le dit. Aucun réseau réel : faux
ordinateur sur le WebSocket /appareil/ws.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import re
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[1]
for chemin in (str(Path(__file__).parent), str(RACINE / "backend")):
    if chemin not in sys.path:
        sys.path.insert(0, chemin)

CODE = "secours-2468-code"
PAIRING = "code-appairage"
COURRIEL = "proprio@vela.ca"
CLE_PC = bytes(range(32))
SEL = bytes(range(100, 116))
ITERATIONS = 100_000


@pytest.fixture()
def relais(tmp_path, monkeypatch):
    monkeypatch.setenv("VELA_DONNEES", str(tmp_path))
    monkeypatch.setenv("VELA_OPENROUTER_KEY", "sk-or-factice")
    import verrou_distant

    monkeypatch.setattr(verrou_distant, "INTERVALLE_LIVRAISON_S", 0.05)
    for module in [m for m in list(sys.modules) if m == "relais"]:
        del sys.modules[module]
    import relais as module

    return module


@pytest.fixture()
def client(relais):
    from fastapi.testclient import TestClient

    with TestClient(relais.app) as c:  # une seule boucle : la livraison en attente y tourne
        yield c


def _etat(relais) -> dict:
    import verrou_distant

    return verrou_distant.etat_memoire(relais)


def _b64(relais, octets: bytes) -> str:
    return relais._b64(octets)


def _lier(relais, courriel: str = COURRIEL, cle: bytes = CLE_PC) -> None:
    """Liaison déjà confirmée par courriel (le parcours de confirmation a ses propres tests)."""
    ident = "liaison-test"
    liaisons = relais._lire_liaisons()
    liaisons[courriel] = {"id": ident, "cle": relais._b64(relais._xor(cle, relais._cle_emballage(courriel, ident))),
                          "machine": "pc", "confirme_le": "2026-09-14T08:00:00+00:00", "sel": None, "iterations": None}
    relais._ecrire(relais.FICHIER_LIAISONS, liaisons)


def _ordinateur_lie(client, relais, courriel: str = COURRIEL, cle: bytes = CLE_PC):
    """Connexion de l'ordinateur lié : hello → défi → preuve (+ sel du code) → prêt."""
    ws = client.websocket_connect("/appareil/ws")
    pc = ws.__enter__()
    pc.send_json({"type": "hello", "jeton": relais.emettre_jeton(courriel, "machine-test"), "pairing": PAIRING,
                  "preuve": 1})
    defi = pc.receive_json()
    assert defi["type"] == "defi" and len(defi["nonce"]) >= 40
    message = f"vela-appareil-ws|v1|{courriel}|{defi['nonce']}".encode()
    pc.send_json({"type": "preuve", "preuve": relais._b64(hmac.new(cle, message, hashlib.sha256).digest()),
                  "verrou": {"sel": relais._b64(SEL), "iterations": ITERATIONS}})
    pret = pc.receive_json()
    assert pret == {"type": "pret", "prouve": True, "liaison": "confirmee"}, pret
    return ws, pc


def _cle_code(code: str = CODE, sel: bytes = SEL, iterations: int = ITERATIONS) -> bytes:
    return hashlib.pbkdf2_hmac("sha256", code.encode("utf-8"), sel, iterations, dklen=32)


def _preparer(client, relais, courriel=COURRIEL, action="verrouiller", code=CODE, ip="203.0.113.7") -> dict:
    """Ce que fait la page : défi, clé dérivée du code, preuve. Renvoie le corps à poster (sans le code)."""
    defi = client.post("/api/verrou/defi", json={"courriel": courriel}, headers={"X-Forwarded-For": ip})
    assert defi.status_code == 200, defi.text
    d = defi.json()
    cle = _cle_code(code, relais._debase64(d["sel"]), d["iterations"])
    preuve = relais._b64(hmac.new(cle, f"vela-verrou|v1|{action}|{d['nonce']}".encode(), hashlib.sha256).digest())
    return {"courriel": courriel, "action": action, "nonce": d["nonce"], "preuve": preuve,
            "defi_page": relais._b64(b"p" * 16), "_cle": cle}


def _poster(client, corps: dict, ip: str = "203.0.113.7"):
    return client.post("/api/verrou", json={k: v for k, v in corps.items() if not k.startswith("_")},
                       headers={"X-Forwarded-For": ip})


def _attendre_suivi(client, suivi: str, delai: float = 5.0) -> dict:
    limite = time.monotonic() + delai
    while True:
        etat = client.get(f"/api/verrou/suivi/{suivi}").json()
        if etat["etat"] != "en_attente" or time.monotonic() > limite:
            return etat
        time.sleep(0.05)


def _confirmation(cle: bytes, etat: str, corps: dict) -> str:
    message = f"vela-verrou-resultat|v1|{etat}|{corps['nonce']}|{corps['defi_page']}".encode()
    return hmac.new(cle, message, hashlib.sha256).digest()


# --------------------------------------------------------------------------- page
def test_la_page_est_autonome_en_francais_et_dit_vrai(client):
    r = client.get("/verrou")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/html")
    page = r.text
    assert '<html lang="fr-CA">' in page and "Verrouiller IRIS à distance" in page
    assert "src=\"http" not in page and "href=\"http" not in page and "@import" not in page, "aucune ressource externe"
    assert 'role="status"' in page and 'aria-live="polite"' in page and '<label for="code">' in page
    assert "perdue" in page, "la limite de la mise en attente est dite"
    assert "ne quitte pas ce navigateur" in page and "Réponse confirmée par votre ordinateur" in page
    assert "bloquer cette page 15 minutes" in page, "le revers de la limitation est dit"
    assert "ne vérifie pas votre code" not in page, "l'ancienne promesse fausse a disparu"
    assert "code: code" not in page and "JSON.stringify({ courriel: courriel, code" not in page, "le code ne part jamais"
    for fournisseur in ("Claude", "Anthropic", "OpenAI", "Google", "Render", "OpenRouter"):
        assert fournisseur not in page
    assert r.headers.get("cache-control") == "no-store"
    csp = r.headers.get("content-security-policy", "")
    for directive in ("default-src 'none'", "connect-src 'self'", "form-action 'none'", "frame-ancestors 'none'",
                      "base-uri 'none'"):
        assert directive in csp, directive
    assert r.headers.get("x-content-type-options") == "nosniff" and r.headers.get("x-robots-tag") == "noindex"
    assert "<script src" not in page and "<link" not in page


@pytest.mark.skipif(shutil.which("node") is None, reason="Node absent de cette machine")
def test_la_preuve_du_navigateur_est_celle_de_lordinateur(client, relais, tmp_path):
    """Le calcul WebCrypto de la page (bloc VerrouPreuve) donne exactement la preuve et la confirmation que
    vérifie et produit l'ordinateur (backend/iris/verrou.py)."""
    from iris import verrou as verrou_pc

    page = client.get("/verrou").text
    bloc = re.search(r"var VerrouPreuve = \(function \(\) \{.*?\}\)\(\);", page, re.S)
    assert bloc, "bloc VerrouPreuve introuvable"
    nonce = f"{int(time.time())}.{'n' * 32}"
    defi_page = relais._b64(b"q" * 16)
    script = tmp_path / "preuve.mjs"
    script.write_text(bloc.group(0) + f"""
const cle = await VerrouPreuve.deriver({json.dumps(CODE)}, {json.dumps(relais._b64(SEL))}, {ITERATIONS});
const preuve = await VerrouPreuve.signer(cle, 'vela-verrou|v1|effacer|' + {json.dumps(nonce)});
const confirmation = process.argv[2];
const bonne = await VerrouPreuve.verifier(cle, 'vela-verrou-resultat|v1|efface|' + {json.dumps(nonce)} + '|' + {json.dumps(defi_page)}, confirmation);
const mauvaise = await VerrouPreuve.verifier(cle, 'vela-verrou-resultat|v1|efface|' + {json.dumps(nonce)} + '|autre', confirmation);
process.stdout.write(JSON.stringify({{ preuve, bonne, mauvaise }}));
""", encoding="utf-8")
    cle = verrou_pc.deriver_cle_preuve(CODE, SEL, ITERATIONS)
    confirmation = verrou_pc.confirmation_resultat(cle, "efface", nonce, defi_page)
    sortie = subprocess.run(["node", str(script), confirmation], capture_output=True, text=True, timeout=60)
    assert sortie.returncode == 0, sortie.stderr
    res = json.loads(sortie.stdout)
    assert res["preuve"] == verrou_pc.preuve_commande(cle, "effacer", nonce)
    assert res["bonne"] is True and res["mauvaise"] is False


# --------------------------------------------------------------------------- défi et uniformité
def test_le_defi_est_uniforme_pour_un_courriel_inconnu(client, relais):
    a = client.post("/api/verrou/defi", json={"courriel": "inconnu@vela.ca"}).json()
    b = client.post("/api/verrou/defi", json={"courriel": "inconnu@vela.ca"}).json()
    assert set(a) == {"sel", "iterations", "nonce", "expire_dans_s"}
    assert a["sel"] == b["sel"] and a["nonce"] != b["nonce"], "sel factice stable, nonce neuf à chaque fois"
    assert a["iterations"] == 240_000
    # Un courriel dont l'ordinateur est lié et a publié son sel reçoit le vrai sel : même forme de réponse.
    _lier(relais)
    ws, _pc = _ordinateur_lie(client, relais)
    try:
        lie = client.post("/api/verrou/defi", json={"courriel": COURRIEL}).json()
        assert set(lie) == set(a) and lie["sel"] == relais._b64(SEL) and lie["iterations"] == ITERATIONS
    finally:
        ws.__exit__(None, None, None)
    inconnu = _poster(client, _preparer(client, relais, courriel="inconnu@vela.ca"))
    assert inconnu.status_code == 202 and inconnu.json()["etat"] == "en_attente", "même réponse qu'un ordinateur lié"


def test_un_nonce_ne_sert_quune_fois_et_pour_son_courriel(client, relais):
    corps = _preparer(client, relais, courriel="a@vela.ca")
    assert _poster(client, corps).status_code == 202
    rejoue = _poster(client, corps, ip="203.0.113.8")
    assert rejoue.status_code == 422 and rejoue.json()["etat"] == "defi_expire"
    autre = _preparer(client, relais, courriel="a@vela.ca", ip="203.0.113.9")
    autre["courriel"] = "b@vela.ca"
    assert _poster(client, autre, ip="203.0.113.9").json()["etat"] == "defi_expire"


def test_entrees_invalides_et_ancienne_page_sans_echo(client, relais):
    corps = _preparer(client, relais)
    r = client.post("/api/verrou", json={**{k: v for k, v in corps.items() if k != "_cle"}, "courriel": "pas-un-courriel"})
    assert r.status_code == 422
    assert _poster(client, {**corps, "action": "formater"}).status_code == 422
    assert _poster(client, {**corps, "preuve": "pas une preuve !"}).status_code == 422
    ancienne = client.post("/api/verrou", json={"courriel": COURRIEL, "code": CODE, "action": "verrouiller"})
    assert ancienne.status_code == 422 and ancienne.json()["etat"] == "page_perimee" and CODE not in ancienne.text
    assert client.post("/api/verrou", content=b"pas du json", headers={"content-type": "application/json"}).status_code == 422


# --------------------------------------------------------------------------- limitation
def test_cinq_tentatives_par_courriel_toutes_adresses_confondues(client, relais):
    statuts, etats = [], []
    for i in range(6):
        corps = _preparer(client, relais, code=f"mauvais-code-{i}", ip=f"198.51.100.{i}")
        r = _poster(client, corps, ip=f"198.51.100.{i}")
        statuts.append(r.status_code)
        etats.append(r.json()["etat"])
    # 5 commandes mises en file (une par adresse ; plus de « file_pleine » qui trahirait l'état de l'ordinateur),
    # puis la limitation par courriel.
    assert statuts[:5] == [202] * 5 and etats[:5] == ["en_attente"] * 5
    assert statuts[5] == 429 and etats[5] == "trop_de_tentatives"


def test_cinq_tentatives_par_adresse_ip_tous_courriels_confondus(client, relais):
    statuts = []
    for i in range(6):
        corps = _preparer(client, relais, courriel=f"cible{i}@vela.ca", ip="6.6.6.6, 192.0.2.10")
        statuts.append(_poster(client, corps, ip="6.6.6.6, 192.0.2.10").status_code)
    assert statuts[5] == 429
    # la première entrée de X-Forwarded-For est forgeable : changer celle-là ne contourne pas la limite
    corps = _preparer(client, relais, courriel="autre@vela.ca", ip="1.1.1.1, 192.0.2.10")
    assert _poster(client, corps, ip="1.1.1.1, 192.0.2.10").status_code == 429


# --------------------------------------------------------------------------- l'ordinateur lié, et lui seul
def test_la_preuve_part_a_lordinateur_lie_et_sa_confirmation_revient(client, relais, caplog):
    caplog.set_level(logging.DEBUG)
    _lier(relais)
    ws, pc = _ordinateur_lie(client, relais)
    try:
        corps = _preparer(client, relais)
        r = _poster(client, corps)
        assert r.status_code == 202 and CODE not in r.text
        recu = pc.receive_json()
        assert recu["type"] == "verrou" and recu["action"] == "verrouiller" and "code" not in recu
        assert recu["preuve"] == corps["preuve"] and recu["nonce"] == corps["nonce"]
        assert recu["defi_page"] == corps["defi_page"] and recu["req_id"] in relais._req_en_cours
        confirmation = relais._b64(_confirmation(corps["_cle"], "verrouille", corps))
        pc.send_json({"type": "resultat", "req_id": recu["req_id"], "verrou": True, "ok": True, "etat": "verrouille",
                      "message": "L'ordinateur est verrouillé.", "confirmation": confirmation})
        final = _attendre_suivi(client, r.json()["suivi"])
        assert final == {"etat": "verrouille", "message": "L'ordinateur est verrouillé.", "confirmation": confirmation}
        assert recu["req_id"] not in relais._req_en_cours
    finally:
        ws.__exit__(None, None, None)
    assert CODE not in caplog.text and corps["preuve"] not in caplog.text


def test_une_autre_machine_du_meme_courriel_ne_recoit_rien_et_ne_remplace_pas(client, relais):
    """Constat bloquant du 2026-09-14 : n'importe qui obtenait un jeton pour le courriel de la victime, prenait la
    place de son ordinateur et recevait son code de secours."""
    from starlette.websockets import WebSocketDisconnect

    _lier(relais)
    ws, pc = _ordinateur_lie(client, relais)
    try:
        # 1. Sans preuve : refusé, et le vrai ordinateur reste en place.
        with client.websocket_connect("/appareil/ws") as intrus:
            intrus.send_json({"type": "hello", "jeton": relais.emettre_jeton(COURRIEL, "pirate"), "pairing": "x"})
            refus = intrus.receive_json()
            assert refus["type"] == "refus" and "Un autre ordinateur" in refus["message"]
            with pytest.raises(WebSocketDisconnect):
                intrus.receive_json()
        # 2. Avec une fausse clé : refusé aussi.
        with client.websocket_connect("/appareil/ws") as intrus:
            intrus.send_json({"type": "hello", "jeton": relais.emettre_jeton(COURRIEL, "pirate"), "pairing": "x",
                              "preuve": 1})
            defi = intrus.receive_json()
            faux = hmac.new(b"z" * 32, f"vela-appareil-ws|v1|{COURRIEL}|{defi['nonce']}".encode(), hashlib.sha256)
            intrus.send_json({"type": "preuve", "preuve": relais._b64(faux.digest()),
                              "verrou": {"sel": relais._b64(b"f" * 16), "iterations": ITERATIONS}})
            assert intrus.receive_json()["type"] == "refus"
        assert relais._pc_par_courriel[COURRIEL]["prouve"] is True
        assert relais.liaison_confirmee(COURRIEL)["sel"] == relais._b64(SEL), "l'intrus n'a pas changé le sel publié"
        # 3. La commande arrive toujours au vrai ordinateur.
        _poster(client, _preparer(client, relais))
        assert pc.receive_json()["type"] == "verrou"
    finally:
        ws.__exit__(None, None, None)


def test_un_ordinateur_non_lie_ne_recoit_jamais_de_verrou(client, relais):
    """Sans liaison confirmée, l'ancien canal (télécommande) reste, mais aucune commande de verrou n'y part."""
    with client.websocket_connect("/appareil/ws") as pc:
        pc.send_json({"type": "hello", "jeton": relais.emettre_jeton(COURRIEL, "machine"), "pairing": PAIRING})
        assert pc.receive_json() == {"type": "pret"}
        r = _poster(client, _preparer(client, relais))
        assert r.status_code == 202
        time.sleep(0.3)
        assert _etat(relais)["attentes"][COURRIEL], "la commande attend un ordinateur lié"
        assert client.get(f"/api/verrou/suivi/{r.json()['suivi']}").json()["etat"] == "en_attente"


def test_sans_reponse_du_pc_le_relais_le_dit(client, relais, monkeypatch):
    import verrou_distant

    monkeypatch.setattr(verrou_distant, "DELAI_REPONSE_S", 0.3)
    monkeypatch.setattr(verrou_distant, "DELAI_UNIFORME_S", 0.5)
    _lier(relais)
    ws, pc = _ordinateur_lie(client, relais)
    try:
        r = _poster(client, _preparer(client, relais))
        assert pc.receive_json()["type"] == "verrou"  # reçu, mais l'ordinateur ne répond pas
        final = _attendre_suivi(client, r.json()["suivi"])
        # Contre-vérification du 2026-09-14 : « sans réponse » se lit comme tout résultat non confirmé.
        assert final["etat"] == "non_confirmee" and "impossible de confirmer" in final["message"]
        assert _etat(relais)["suivis"][r.json()["suivi"]]["etat"] == "sans_reponse", "l'état réel reste connu du relais"
        assert not relais._req_en_cours
    finally:
        ws.__exit__(None, None, None)


# --------------------------------------------------------------------------- mise en attente
def test_ordinateur_hors_ligne_commande_en_attente_puis_livree_a_la_reconnexion(client, relais):
    _lier(relais)
    corps = _preparer(client, relais, action="effacer")
    r = _poster(client, corps)
    assert r.status_code == 202
    reponse = r.json()
    assert reponse["etat"] == "en_attente" and "perdue" in reponse["message"]
    suivi = reponse["suivi"]
    attente = _etat(relais)["attentes"][COURRIEL][0]
    assert "code" not in attente and attente["preuve"] == corps["preuve"], "en mémoire : une preuve, jamais le code"

    ws, pc = _ordinateur_lie(client, relais)  # l'ordinateur se reconnecte
    try:
        recu = pc.receive_json()
        assert recu["type"] == "verrou" and recu["action"] == "effacer" and recu["differee"] is True
        pc.send_json({"type": "resultat", "req_id": recu["req_id"], "ok": True, "etat": "efface",
                      "message": "Les données d'IRIS ont été effacées sur l'ordinateur et il est verrouillé."})
        final = _attendre_suivi(client, suivi)
        assert final["etat"] == "efface" and "effacées" in final["message"] and "confirmation" not in final
        assert _etat(relais)["attentes"] == {}
    finally:
        ws.__exit__(None, None, None)
    assert client.get("/api/verrou/suivi/inexistant").status_code == 404


def test_des_preuves_bidon_n_empechent_pas_la_commande_du_proprietaire(client, relais):
    """Finition B du 2026-09-14 : 3 preuves bidon (file de 3 par courriel, sans éviction) faisaient répondre 429
    « file_pleine » au propriétaire qui voulait effacer son ordinateur volé hors ligne, jusqu'à 72 h. La commande du
    propriétaire est maintenant mise en file, et aucune commande déjà en file n'est retirée par elle."""
    _lier(relais)
    bidons = [_poster(client, _preparer(client, relais, code=f"bidon-{i}-xyz", ip=f"192.0.2.{10 + i}"),
                      ip=f"192.0.2.{10 + i}") for i in range(4)]
    assert [r.status_code for r in bidons] == [202] * 4
    proprio = _poster(client, _preparer(client, relais, action="effacer", ip="198.51.100.5"), ip="198.51.100.5")
    assert proprio.status_code == 202 and proprio.json()["etat"] == "en_attente"
    file = _etat(relais)["attentes"][COURRIEL]
    assert len(file) == 5 and file[-1]["suivi"] == proprio.json()["suivi"] and file[-1]["action"] == "effacer"
    assert all("198.51.100.5" not in json.dumps(c) for c in file), "l'adresse n'est pas gardée en clair"


def test_une_commande_par_adresse_et_la_plus_ancienne_d_une_autre_adresse_cede(client, relais, monkeypatch):
    import verrou_distant

    monkeypatch.setattr(verrou_distant, "ATTENTES_PAR_COURRIEL", 3)
    monkeypatch.setattr(verrou_distant, "MAX_TENTATIVES", 50)
    premiere = _poster(client, _preparer(client, relais, code="faute-de-frappe", ip="192.0.2.1"), ip="192.0.2.1")
    corrigee = _poster(client, _preparer(client, relais, action="effacer", ip="192.0.2.1"), ip="192.0.2.1")
    file = _etat(relais)["attentes"][COURRIEL]
    assert [c["suivi"] for c in file] == [corrigee.json()["suivi"]], "la même adresse remplace sa commande"
    autres = [_poster(client, _preparer(client, relais, code=f"bidon-{i}", ip=f"203.0.113.{i}"), ip=f"203.0.113.{i}")
              for i in range(3)]
    assert [r.status_code for r in autres] == [202] * 3
    file = _etat(relais)["attentes"][COURRIEL]
    assert len(file) == 3 and corrigee.json()["suivi"] not in [c["suivi"] for c in file]
    # Remplacée ou cédée : la réponse et le suivi ne se distinguent pas d'une commande gardée.
    assert premiere.json().keys() == autres[-1].json().keys()
    assert client.get(f"/api/verrou/suivi/{premiere.json()['suivi']}").json()["etat"] == "en_attente"


def test_la_reponse_ne_revele_pas_si_l_ordinateur_lie_est_en_ligne(client, relais):
    """La sonde envoyait 4 preuves bidon : [202, 202, 202, 429] hors ligne contre [202] * 4 en ligne."""
    _lier(relais)
    hors = [_poster(client, _preparer(client, relais, code=f"bidon-{i}", ip=f"192.0.2.{40 + i}"), ip=f"192.0.2.{40 + i}")
            for i in range(4)]
    autre = "enligne@vela.ca"
    _lier(relais, courriel=autre)
    ws, pc = _ordinateur_lie(client, relais, courriel=autre)
    en = []
    try:
        for i in range(4):
            r = _poster(client, _preparer(client, relais, courriel=autre, code=f"bidon-{i}", ip=f"192.0.2.{60 + i}"),
                        ip=f"192.0.2.{60 + i}")
            en.append(r)
            recu = pc.receive_json()
            pc.send_json({"type": "resultat", "req_id": recu["req_id"], "ok": False, "etat": "code_refuse",
                          "message": "Code de secours incorrect."})
    finally:
        ws.__exit__(None, None, None)
    assert [r.status_code for r in hors] == [r.status_code for r in en] == [202] * 4
    assert {r.json()["etat"] for r in hors + en} == {"en_attente"}
    assert {r.json()["message"] for r in hors} == {r.json()["message"] for r in en}


def test_une_deconnexion_pendant_la_livraison_ne_perd_aucune_commande(client, relais):
    premiere = _poster(client, _preparer(client, relais, ip="192.0.2.1"), ip="192.0.2.1").json()["suivi"]
    seconde = _poster(client, _preparer(client, relais, action="effacer", ip="192.0.2.2"), ip="192.0.2.2").json()["suivi"]
    envois: list[dict] = []

    class PcQuiTombe:
        async def send_json(self, message):
            envois.append(message)
            raise ConnectionError("l'ordinateur vient de se déconnecter")

    relais._pc_par_courriel[COURRIEL] = {"ws": PcQuiTombe(), "pairing": PAIRING, "prouve": True}
    try:
        limite = time.monotonic() + 5
        while len(envois) < 2 and time.monotonic() < limite:
            time.sleep(0.02)
    finally:
        relais._pc_par_courriel.pop(COURRIEL, None)
    time.sleep(0.15)
    assert len(envois) >= 2, "la livraison a été tentée (puis retentée)"
    assert envois[0]["differee"] is True and envois[0]["reste"] == 1 and envois[0]["lot"]
    file = _etat(relais)["attentes"][COURRIEL]
    assert [c["suivi"] for c in file] == [premiere, seconde], "les deux commandes restent, dans leur ordre"
    for suivi in (premiere, seconde):
        assert client.get(f"/api/verrou/suivi/{suivi}").json()["etat"] == "en_attente"


def test_la_reponse_dun_verrou_ne_vient_que_de_lordinateur_lie(client, relais):
    """relais.py ignore une réponse de verrou venue d'une connexion non prouvée."""
    recus: list = []

    class Destinataire:
        async def send_json(self, message):
            recus.append(message)

    relais._req_en_cours["verrou-test"] = {"tel": Destinataire(), "courriel": "legacy@vela.ca", "verrou": True}
    try:
        with client.websocket_connect("/appareil/ws") as pc:
            pc.send_json({"type": "hello", "jeton": relais.emettre_jeton("legacy@vela.ca", "m"), "pairing": PAIRING})
            assert pc.receive_json() == {"type": "pret"}
            pc.send_json({"type": "resultat", "req_id": "verrou-test", "ok": True, "etat": "verrouille"})
            time.sleep(0.2)
        assert recus == []
    finally:
        relais._req_en_cours.pop("verrou-test", None)


def test_le_suivi_ne_revele_pas_si_lordinateur_lie_est_en_ligne(client, relais, monkeypatch):
    """Contre-vérification du 2026-09-14 : une preuve bidon rendait « code_refuse » en quelques secondes si l'ordinateur
    lié était en ligne, « en_attente » sinon. Les deux se lisent maintenant de la même façon."""
    import verrou_distant

    monkeypatch.setattr(verrou_distant, "DELAI_UNIFORME_S", 0.6)
    _lier(relais)
    hors_ligne = _poster(client, _preparer(client, relais, code="bidon-hors-ligne", ip="192.0.2.30"), ip="192.0.2.30")
    ws, pc = _ordinateur_lie(client, relais)
    try:
        recu = pc.receive_json()  # la commande en file part à la reconnexion : l'ordinateur la refuse
        pc.send_json({"type": "resultat", "req_id": recu["req_id"], "ok": False, "etat": "code_refuse",
                      "message": "Code de secours incorrect."})
        en_ligne = _poster(client, _preparer(client, relais, code="bidon-en-ligne", ip="192.0.2.31"), ip="192.0.2.31")
        recu = pc.receive_json()
        pc.send_json({"type": "resultat", "req_id": recu["req_id"], "ok": False, "etat": "code_refuse",
                      "message": "Code de secours incorrect."})
        time.sleep(0.2)
        tot = client.get(f"/api/verrou/suivi/{en_ligne.json()['suivi']}").json()
        assert tot["etat"] == "en_attente", "un refus n'est pas dit en quelques secondes"
        time.sleep(0.6)
        a = client.get(f"/api/verrou/suivi/{en_ligne.json()['suivi']}").json()
        b = client.get(f"/api/verrou/suivi/{hors_ligne.json()['suivi']}").json()
        assert a == b and a["etat"] == "non_confirmee" and "Code de secours incorrect" not in a["message"]
    finally:
        ws.__exit__(None, None, None)
    # Un ordinateur jamais connecté : exactement la même lecture.
    inconnu = _poster(client, _preparer(client, relais, courriel="jamais@vela.ca", ip="192.0.2.32"), ip="192.0.2.32")
    time.sleep(0.7)
    assert client.get(f"/api/verrou/suivi/{inconnu.json()['suivi']}").json() == a


def test_la_page_dit_que_le_blocage_se_renouvelle_et_lit_letat_de_liaison(client):
    page = client.get("/verrou").text
    assert "recommencer tant qu’il insiste" in page
    assert "liaison-indisponible" in page and "fetch('sante'" in page
