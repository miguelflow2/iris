"""Verrouillage d'IRIS et effacement à distance (interface I, 2026-09-13).

Ce que ces tests protègent : un verrou refuse TOUTES les routes protégées (via ctx.verrou et
main.raison_de_refus) sauf celles qui servent à déverrouiller ; il survit à un redémarrage ; il coupe
l'écoute et les lunettes et les empêche de revenir ; seul le mot de passe du propriétaire déverrouille ;
le code de secours est haché, limité en tentatives (persistées), et seule sa PREUVE à usage unique est
acceptée par la commande distante (jamais rejouée, confirmée en retour) ; l'effacement
supprime tout ce qu'il annonce et laisse le compte ; la télécommande n'accepte que le verrou quand seul
le verrouillage à distance est activé. Fausses lunettes, faux micro, faux WebSocket : aucun réseau.
"""
from __future__ import annotations

import asyncio
import json
import time
import uuid
from types import SimpleNamespace

import pytest
from starlette.websockets import WebSocketDisconnect

from iris.verrou import (
    RefusVerrou,
    VerrouIRIS,
    _b64,
    _debase64,
    code_conforme,
    confirmation_resultat,
    deriver_cle_preuve,
    hacher_code,
    preuve_commande,
)

MOT_DE_PASSE = "motdepasse-proprietaire"
CODE = "secours-2468"


class FausseEcoute:
    def __init__(self, running: bool = True):
        self.running = running
        self.arrets: list[bool] = []
        self.robinet = SimpleNamespace(abonnes=lambda: [])
        self.muted = False
        self.verificateur_locuteur = None

    def stop(self, by_user: bool = True):
        self.arrets.append(by_user)
        self.running = False

    def start(self):
        self.running = True


class FaussesLunettes:
    def __init__(self):
        self.connected = True
        self.deconnexions = 0
        self.oubliees = False

    async def disconnect(self):
        self.deconnexions += 1
        self.connected = False

    def forget(self):
        self.oubliees = True

    async def auto_connect_on_start(self):
        return None


@pytest.fixture(autouse=True)
def hachage_rapide(monkeypatch):
    """Mêmes algorithmes (PBKDF2, scrypt), coût réduit : les tests vérifient la logique, pas la lenteur."""
    monkeypatch.setattr("iris.comptes.ITERATIONS", 2_000)
    monkeypatch.setattr("iris.verrou.SCRYPT", {"n": 2 ** 10, "r": 8, "p": 1})
    monkeypatch.setattr("iris.verrou.PREUVE_ITERATIONS", 2_000)


DEFI_PAGE = "defi-de-la-page-0123456789"


def _nonce(age_s: float = 0) -> str:
    return f"{int(time.time() - age_s)}.{uuid.uuid4().hex}"


def _preuve(verrou, action: str = "verrouiller", code: str = CODE, nonce: str | None = None) -> dict:
    """Ce que calcule la page /verrou : clé PBKDF2 du code avec le sel publié, puis HMAC sur le nonce du relais."""
    nonce = nonce or _nonce()
    infos = verrou.infos_preuve()
    if infos is None:  # pas de clé de preuve (aucun code) : une preuve quelconque
        return {"preuve": "x" * 43, "nonce": nonce, "defi_page": DEFI_PAGE}
    cle = deriver_cle_preuve(code, _debase64(infos["sel"]), infos["iterations"])
    return {"preuve": preuve_commande(cle, action, nonce), "nonce": nonce, "defi_page": DEFI_PAGE}


def _proprietaire(ctx) -> None:
    ctx.comptes.creer(MOT_DE_PASSE, "Miguel")


# --------------------------------------------------------------------------- verrouiller / déverrouiller
def test_sans_mot_de_passe_on_refuse_de_verrouiller(client):
    r = client.post("/api/confiance/verrouiller")
    assert r.status_code == 409 and "mot de passe" in r.json()["detail"]
    assert client.get("/api/settings").status_code == 200


def test_verrouillee_tout_est_refuse_sauf_le_deverrouillage(client, app):
    ctx = app.state.ctx
    _proprietaire(ctx)
    etat = client.post("/api/confiance/verrouiller").json()
    assert etat["verrouille"] is True and etat["raison"] == "local" and etat["depuis"]
    for methode, chemin in (("get", "/api/settings"), ("get", "/api/status"), ("get", "/api/memory"),
                            ("get", "/api/confiance/zones"), ("post", "/api/confiance/invite/activer")):
        refus = getattr(client, methode)(chemin)
        assert refus.status_code == 401 and "verrouillée" in refus.json()["detail"], chemin
    assert client.get("/api/health").status_code == 200
    assert client.get("/api/confiance/verrou/etat").json()["verrouille"] is True
    # le code de secours ne se change pas pendant le verrou, même si le chemin reste joignable
    assert client.post("/api/confiance/verrou/code", json={"code": CODE}).status_code == 423
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/ws?token=test-token") as ws:
            ws.receive_json()

    assert client.post("/api/confiance/deverrouiller", json={"mot_de_passe": "mauvais"}).status_code == 403
    ouvert = client.post("/api/confiance/deverrouiller", json={"mot_de_passe": MOT_DE_PASSE})
    assert ouvert.status_code == 200 and ouvert.json()["verrouille"] is False
    assert client.get("/api/settings").status_code == 200
    evenements = [e["event_type"] for e in ctx.consent.events(limit=20)]
    assert {"verrouillage", "deverrouillage_refuse", "deverrouillage"} <= set(evenements)


def test_trop_de_mots_de_passe_errones_ralentit(client, app):
    _proprietaire(app.state.ctx)
    client.post("/api/confiance/verrouiller")
    codes = [client.post("/api/confiance/deverrouiller", json={"mot_de_passe": "faux"}).status_code for _ in range(9)]
    assert codes[:8] == [403] * 8 and codes[8] == 429
    assert client.post("/api/confiance/deverrouiller", json={"mot_de_passe": MOT_DE_PASSE}).status_code == 429


def test_le_verrou_survit_au_redemarrage(app, data_dir):
    from fastapi.testclient import TestClient

    from iris.main import create_app

    ctx = app.state.ctx
    _proprietaire(ctx)
    asyncio.run(ctx.verrou.verrouiller("distance"))
    relance = create_app(data_dir=data_dir, token="t2", use_keyring=False, enable_tts=False)
    try:
        with TestClient(relance, headers={"Authorization": "Bearer t2"}) as c:
            assert relance.state.ctx.verrou.verrouille is True
            assert c.get("/api/settings").status_code == 401
            assert c.get("/api/confiance/verrou/etat").json()["raison"] == "distance"
    finally:
        relance.state.ctx.close()


def test_verrouiller_coupe_ecoute_lunettes_et_services_puis_les_empeche_de_revenir(app, monkeypatch):
    ctx = app.state.ctx
    _proprietaire(ctx)
    ecoute, lunettes = FausseEcoute(), FaussesLunettes()
    arrets: list[str] = []
    monkeypatch.setattr(ctx, "voice", ecoute)
    monkeypatch.setattr(ctx, "glasses", lunettes)
    monkeypatch.setattr(ctx, "sous_titres", SimpleNamespace(arreter_tout=lambda: arrets.append("sous-titres")), raising=False)
    monkeypatch.setattr(ctx, "alertes", SimpleNamespace(actif=True, arreter=lambda raison=None: arrets.append(f"alertes:{raison}")), raising=False)
    monkeypatch.setattr(ctx, "enregistreur", SimpleNamespace(actif=True, arreter=lambda: arrets.append("enregistrement")), raising=False)
    # Pas à pas et entraînement : leurs minuteurs parleraient encore sur un ordinateur verrouillé.
    monkeypatch.setattr(ctx, "pas_a_pas", SimpleNamespace(interrompre=lambda raison: arrets.append(f"pas_a_pas:{raison}")), raising=False)

    def entrainement_en_panne(raison):
        arrets.append(f"entrainement:{raison}")
        raise RuntimeError("séance illisible")  # une panne n'empêche pas les arrêts suivants

    monkeypatch.setattr(ctx, "entrainement", SimpleNamespace(interrompre=entrainement_en_panne), raising=False)

    async def scenario():
        await ctx.verrou.verrouiller("local")
        assert ecoute.arrets == [True] and lunettes.deconnexions == 1
        assert arrets == ["sous-titres", "alertes:verrouillage", "pas_a_pas:verrouillage",
                          "entrainement:verrouillage", "enregistrement"]
        garde = asyncio.create_task(ctx.verrou.surveiller(intervalle=0.01))
        ecoute.running = True  # le chien de garde vocal relance l'écoute...
        lunettes.connected = True  # ... et les lunettes se reconnectent toutes seules
        # Attente bornée plutôt qu'un 0,2 s fixe : l'arrêt de l'écoute passe par asyncio.to_thread, et sous une
        # suite complète chargée le fil tardait assez pour que les lunettes soient vérifiées trop tôt (2026-09-14).
        limite = time.monotonic() + 5
        while (ecoute.running or lunettes.connected) and time.monotonic() < limite:
            await asyncio.sleep(0.02)
        garde.cancel()
        assert not ecoute.running and not lunettes.connected, "rien ne se rallume pendant le verrou"

    asyncio.run(scenario())


def test_demander_le_mot_de_passe_a_louverture(client, app, data_dir):
    """Constat du 2026-09-14 : l'application de l'ordinateur s'ouvre sans mot de passe. Choisi, IRIS redémarre
    verrouillée ; l'activer exige qu'un mot de passe existe, le retirer exige ce mot de passe."""
    from fastapi.testclient import TestClient

    from iris.main import create_app

    assert client.post("/api/confiance/verrou/ouverture", json={"actif": True}).status_code == 409
    _proprietaire(app.state.ctx)
    assert client.post("/api/confiance/verrou/ouverture", json={"actif": True}).json()["ouverture_verrouillee"] is True
    relance = create_app(data_dir=data_dir, token="t3", use_keyring=False, enable_tts=False)
    try:
        with TestClient(relance, headers={"Authorization": "Bearer t3"}) as c:
            etat = c.get("/api/confiance/verrou/etat").json()
            assert etat["verrouille"] is True and etat["raison"] == "ouverture"
            assert c.get("/api/settings").status_code == 401
            assert c.post("/api/confiance/deverrouiller", json={"mot_de_passe": MOT_DE_PASSE}).status_code == 200
            refus = c.post("/api/confiance/verrou/ouverture", json={"actif": False})
            assert refus.status_code == 403 and "mot de passe" in refus.json()["detail"]
            ok = c.post("/api/confiance/verrou/ouverture", json={"actif": False, "mot_de_passe": MOT_DE_PASSE})
            assert ok.status_code == 200 and ok.json()["ouverture_verrouillee"] is False
    finally:
        relance.state.ctx.close()


# --------------------------------------------------------------------------- code de secours
def test_code_de_secours_hache_limite_et_protege(app):
    ctx = app.state.ctx
    verrou = ctx.verrou
    with pytest.raises(RefusVerrou):
        verrou.definir_code("123")
    verrou.definir_code(CODE)
    brut = verrou.fichier.read_text(encoding="utf-8")
    assert CODE not in brut and json.loads(brut)["code"]["algo"] in ("scrypt", "pbkdf2")
    assert verrou.verifier_code(CODE) == "ok"
    assert [verrou.verifier_code("mauvais-code") for _ in range(5)] == ["refuse"] * 5
    assert verrou.verifier_code(CODE) == "trop_de_tentatives", "même le bon code attend la fin de la fenêtre"
    stocke = json.loads(verrou.fichier.read_text(encoding="utf-8"))
    assert stocke["preuve"]["chiffree"] is True and stocke["preuve"]["sel"] and CODE not in json.dumps(stocke)
    cle = deriver_cle_preuve(CODE, _debase64(stocke["preuve"]["sel"]), stocke["preuve"]["iterations"])
    assert _b64(cle) not in json.dumps(stocke), "la clé de preuve n'est pas gardée en clair"
    # Constat du 2026-09-14 : les échecs vivaient en mémoire, un redémarrage rendait 5 nouveaux essais.
    assert len(stocke["echecs_code"]) == 5
    assert VerrouIRIS(ctx).verifier_code(CODE) == "trop_de_tentatives", "la fenêtre d'essais survit au redémarrage"
    # remplacer un code existant exige le mot de passe dès qu'un compte existe
    _proprietaire(ctx)
    with pytest.raises(RefusVerrou) as refus:
        verrou.definir_code("nouveau-code-99")
    assert refus.value.code == 403
    assert verrou.definir_code("nouveau-code-99", MOT_DE_PASSE)["code_defini"] is True
    empreinte = hacher_code("abcdef")
    assert code_conforme(empreinte, "abcdef") and not code_conforme(empreinte, "abcdeg")


def test_commande_distante_exige_activation_code_et_mot_de_passe(app):
    ctx = app.state.ctx
    verrou = ctx.verrou

    def commande(action="verrouiller", code=CODE, **preuve):
        return asyncio.run(verrou.commande_distante(action, **(preuve or _preuve(verrou, action, code))))

    assert commande()["etat"] == "desactive"
    verrou.definir_distant(True)
    assert commande()["etat"] == "sans_code"
    verrou.definir_code(CODE)
    assert commande(code="pas-le-bon")["etat"] == "code_refuse"
    assert commande(action="formater")["etat"] == "action_inconnue"
    assert commande()["etat"] == "sans_mot_de_passe" and not verrou.verrouille
    _proprietaire(ctx)
    preuve = _preuve(verrou)
    resultat = commande(**preuve)
    cle = deriver_cle_preuve(CODE, _debase64(verrou.infos_preuve()["sel"]), verrou.infos_preuve()["iterations"])
    assert resultat == {"ok": True, "etat": "verrouille", "message": "L'ordinateur est verrouillé.",
                        "confirmation": confirmation_resultat(cle, "verrouille", preuve["nonce"], DEFI_PAGE)}
    assert verrou.verrouille and verrou.raison == "distance"
    assert CODE not in json.dumps(ctx.consent.events(limit=50)), "le code n'est jamais journalisé"


def test_une_preuve_ne_se_rejoue_pas_et_un_nonce_trop_vieux_est_refuse(app):
    """Constat bloquant du 2026-09-14 : le code transitait en clair et pouvait être rejoué plus tard (effacement)."""
    ctx = app.state.ctx
    verrou = ctx.verrou
    _proprietaire(ctx)
    verrou.definir_distant(True)
    verrou.definir_code(CODE)
    preuve = _preuve(verrou)
    assert asyncio.run(verrou.commande_distante("verrouiller", **preuve))["etat"] == "verrouille"
    verrou.deverrouiller(MOT_DE_PASSE)
    rejouee = asyncio.run(verrou.commande_distante("verrouiller", **preuve))
    assert rejouee["etat"] == "rejouee" and not verrou.verrouille and "confirmation" not in rejouee
    assert VerrouIRIS(ctx).verifier_preuve("verrouiller", preuve["nonce"], preuve["preuve"]) == "rejouee", \
        "les nonces vus survivent au redémarrage"
    # La preuve d'un « verrouiller » ne vaut pas pour « effacer ».
    detournee = {**_preuve(verrou), "defi_page": DEFI_PAGE}
    assert asyncio.run(verrou.commande_distante("effacer", **detournee))["etat"] == "code_refuse"
    vieille = _preuve(verrou, nonce=_nonce(age_s=81 * 3600))
    assert asyncio.run(verrou.commande_distante("verrouiller", **vieille))["etat"] == "code_refuse"
    assert not verrou.verrouille


def test_un_code_defini_avant_la_preuve_doit_etre_redefini(app):
    ctx = app.state.ctx
    verrou = ctx.verrou
    verrou.definir_distant(True)
    verrou._code = hacher_code(CODE)
    verrou._preuve = None
    verrou._ecrire()
    relu = VerrouIRIS(ctx)
    assert relu.code_defini and relu.code_a_redefinir and relu.infos_preuve() is None
    assert relu.etat()["code_a_redefinir"] is True
    reponse = asyncio.run(relu.commande_distante("verrouiller", preuve="x" * 43, nonce=_nonce(), defi_page=DEFI_PAGE))
    assert reponse["etat"] == "code_a_redefinir" and "de nouveau" in reponse["message"]


def test_desactiver_le_verrouillage_a_distance_exige_le_mot_de_passe(client, app):
    """Constat du 2026-09-14 : le voleur d'un portable resté ouvert coupait le verrouillage à distance d'un
    PATCH /api/settings, alors que remplacer le code de secours exigeait déjà le mot de passe."""
    import time

    ctx = app.state.ctx
    _proprietaire(ctx)
    ctx.verrou.definir_code(CODE)
    assert client.post("/api/confiance/verrou/distant", json={"actif": True}).json()["actif_distance"] is True
    assert ctx.settings.user.verrou_distant_actif is True, "le réglage reflète l'état réel"
    assert json.loads(ctx.verrou.fichier.read_text(encoding="utf-8"))["distant_actif"] is True

    refus = client.post("/api/confiance/verrou/distant", json={"actif": False})
    assert refus.status_code == 403 and "mot de passe" in refus.json()["detail"]
    assert client.post("/api/confiance/verrou/distant", json={"actif": False, "mot_de_passe": "faux"}).status_code == 403
    assert ctx.verrou.distant_actif is True

    # PATCH /api/settings sans mot de passe : 403 dit tel quel (un 200 suivi d'un rétablissement silencieux faisait
    # afficher « désactivé » à l'écran alors que rien ne l'était).
    for corps in ({"verrou_distant_actif": False}, {"verrou_distant_actif": False, "mot_de_passe": "faux"}):
        refus_reglage = client.patch("/api/settings", json=corps)
        assert refus_reglage.status_code == 403 and "mot de passe" in refus_reglage.json()["detail"], corps
    assert ctx.verrou.distant_actif is True and ctx.settings.user.verrou_distant_actif is True
    # Un changement interne du réglage (sans passer par la route) : l'état réel ne bouge pas, le reflet est rétabli.
    ctx.settings.update({"verrou_distant_actif": False})
    ctx.hub.publish("settings.updated", settings=ctx.settings.user.model_dump())
    limite = time.monotonic() + 5
    while not ctx.settings.user.verrou_distant_actif and time.monotonic() < limite:
        time.sleep(0.02)
    assert ctx.verrou.distant_actif is True and ctx.settings.user.verrou_distant_actif is True
    ctx.telecommande.verrou = ctx.verrou
    assert ctx.telecommande.verrou_distant_permis() is True
    assert asyncio.run(ctx.verrou.commande_distante("verrouiller", **_preuve(ctx.verrou, code="pas-le-bon")))["etat"] == "code_refuse"

    ouvert = client.post("/api/confiance/verrou/distant", json={"actif": False, "mot_de_passe": MOT_DE_PASSE})
    assert ouvert.status_code == 200 and ouvert.json()["actif_distance"] is False
    assert ctx.telecommande.verrou_distant_permis() is False and ctx.settings.user.verrou_distant_actif is False
    assert asyncio.run(ctx.verrou.commande_distante("verrouiller", **_preuve(ctx.verrou)))["etat"] == "desactive"
    # Rallumer par le réglage (écrans existants) reste possible : c'est une protection de plus.
    client.patch("/api/settings", json={"verrou_distant_actif": True})
    limite = time.monotonic() + 5
    while not ctx.verrou.distant_actif and time.monotonic() < limite:
        time.sleep(0.02)
    assert ctx.verrou.distant_actif is True
    evenements = {e["event_type"] for e in ctx.consent.events(limit=50)}
    assert {"verrou_distant_active", "verrou_distant_desactivation_refusee", "verrou_distant_desactive"} <= evenements


def test_couper_le_canal_du_verrou_par_les_reglages_exige_le_mot_de_passe(client, app):
    """Constat du 2026-09-14 : un voleur (session Windows ouverte, jeton local) coupait le verrouillage à distance en
    changeant l'adresse du relais ou le courriel du compte. Le mode 100 % local, lui, garde le canal du verrou."""
    ctx = app.state.ctx
    _proprietaire(ctx)
    ctx.settings.update({"relay_server": "https://relais.velaglass.ca", "licence_email": "proprio@vela.ca"})
    ctx.verrou.definir_distant(True)
    for patch in ({"relay_server": ""}, {"relay_server": "https://pirate.exemple"}, {"licence_email": "autre@vela.ca"}):
        refus = client.patch("/api/settings", json=patch)
        assert refus.status_code == 403 and "mot de passe" in refus.json()["detail"], patch
    assert ctx.settings.user.relay_server == "https://relais.velaglass.ca"
    assert client.patch("/api/settings", json={"licence_email": "autre@vela.ca", "mot_de_passe": "faux"}).status_code == 403
    ok = client.patch("/api/settings", json={"licence_email": "autre@vela.ca", "mot_de_passe": MOT_DE_PASSE})
    assert ok.status_code == 200 and ok.json()["licence_email"] == "autre@vela.ca" and "mot_de_passe" not in ok.json()
    # Le même courriel renvoyé (écran qui enregistre tout) ne demande rien.
    assert client.patch("/api/settings", json={"licence_email": "autre@vela.ca"}).status_code == 200
    # Mode 100 % local : permis, et le canal reste ouvert pour le verrouillage seulement.
    assert client.patch("/api/settings", json={"local_only": True}).status_code == 200
    ctx.telecommande.verrou = ctx.verrou
    monkey_jeton = ctx.telecommande._obtenir_jeton
    ctx.telecommande._obtenir_jeton = lambda: "jeton"
    try:
        assert ctx.telecommande.actif() is True and ctx.telecommande.pilotage_permis() is False
    finally:
        ctx.telecommande._obtenir_jeton = monkey_jeton
        client.patch("/api/settings", json={"local_only": False})
    evenements = {e["event_type"] for e in ctx.consent.events(limit=50)}
    assert "reglage_protege_refuse" in evenements


def test_des_codes_bidon_en_file_ne_consomment_pas_les_essais_quand_le_bon_code_est_dans_le_lot(app):
    """Constat du 2026-09-14 : quiconque connaît le courriel glisse des codes bidon dans la file du relais ;
    à la reconnexion, ils épuisaient les 5 essais de l'ordinateur avant le bon code du propriétaire."""
    ctx = app.state.ctx
    verrou = ctx.verrou
    _proprietaire(ctx)
    verrou.definir_distant(True)
    verrou.definir_code(CODE)

    def commande(code, **lot):
        return asyncio.run(verrou.commande_distante("verrouiller", **_preuve(verrou, code=code), **lot))

    # Deux échecs en direct (comptés), puis un lot de trois codes bidon et du bon code.
    assert [commande("direct-faux-1")["etat"], commande("direct-faux-2")["etat"]] == ["code_refuse"] * 2
    lot = {"differee": True, "lot": "lot-1"}
    etats = [commande(f"bidon-{i}-xyz", reste=3 - i, **lot)["etat"] for i in range(3)]
    assert etats == ["code_refuse"] * 3
    assert commande(CODE, reste=0, **lot)["etat"] == "verrouille", "5 échecs auraient bloqué le bon code"
    verrou.deverrouiller(MOT_DE_PASSE)
    assert verrou._echecs_code == [] and verrou._lots == {}

    # Un lot sans aucun bon code : ses échecs sont comptés à sa clôture.
    for i in range(3):
        commande(f"bidon-{i}-abc", differee=True, lot="lot-2", reste=2 - i)
    assert len(verrou._echecs_code) == 3 and verrou._lots == {}
    # Une commande différée mal formée (sans lot) est traitée comme une commande directe : comptée.
    commande("bidon-sans-lot", differee=True)
    assert len(verrou._echecs_code) == 4


# --------------------------------------------------------------------------- effacement
def _inserer(db, table: str, **valeurs) -> None:
    """Insère une ligne factice dans une table d'une autre équipe, sans connaître son schéma exact."""
    colonnes = db.query(f"PRAGMA table_info({table})")
    ligne: dict = {}
    for col in colonnes:
        nom, genre = col["name"], (col["type"] or "").upper()
        if nom in valeurs:
            ligne[nom] = valeurs[nom]
        elif col["pk"] and "INT" not in genre:
            ligne[nom] = uuid.uuid4().hex
        elif col["notnull"] and col["dflt_value"] is None:
            ligne[nom] = b"x" if "BLOB" in genre else (0 if ("INT" in genre or "REAL" in genre) else "x")
    db.execute(f"INSERT INTO {table}({', '.join(ligne)}) VALUES({', '.join('?' * len(ligne))})", list(ligne.values()))


def test_effacement_complet_garde_le_compte_et_le_jeton_dappareil(app, data_dir, monkeypatch):
    ctx = app.state.ctx
    _proprietaire(ctx)
    session = ctx.comptes.ouvrir_session()
    ctx.verrou.definir_distant(True)
    ctx.verrou.definir_code(CODE)

    ctx.memory.add("mon code de porte est 1234")
    conv = ctx.chat.create_conversation(title="Privée")
    ctx.chat._add_message(conv["id"], "user", "message privé")
    # Le registre de confidentialité garde des extraits de messages (chat.py : detail=text[:120]).
    ctx.consent.log("external_send", data_type="transcript", agent="vela", detail="rendez-vous secret chez Julie")
    tables = {r["name"] for r in ctx.db.query("SELECT name FROM sqlite_master WHERE type='table'")}
    for table in ("journal_ecoute", "cours", "recus", "rappels_contexte", "reminders", "tasks", "entrainement_seances"):
        if table in tables:
            _inserer(ctx.db, table, id="ligne-" + table)
    _inserer(ctx.db, "routines", id="routine-matin", name="Matin")
    _inserer(ctx.db, "presence", key="last_interaction", value="2026-09-13T08:00:00+00:00")
    assert {"entrainement_seances", "routines", "presence"} <= tables
    if "cours_lignes" in tables:
        _inserer(ctx.db, "cours_lignes", cours_id="ligne-cours")
    (data_dir / "captures" / "audio").mkdir(parents=True, exist_ok=True)
    (data_dir / "captures" / "photo.jpg").write_bytes(b"\xff\xd8")
    (data_dir / "captures" / "audio" / "enregistrement-1.wav").write_bytes(b"RIFF")
    (data_dir / "recus").mkdir(exist_ok=True)
    (data_dir / "recus" / "recu.jpg").write_bytes(b"\xff\xd8")
    (data_dir / "telecommande-pairing").write_text("abcd1234", encoding="utf-8")
    import iris.verrou_vocal as verrou_vocal_module

    monkeypatch.setattr(verrou_vocal_module, "DECLARATION_CAI", "2026-07-01")  # fonction offerte pour ce test
    ctx.verrou_vocal.definir_consentement(True)
    ctx.verrou_vocal.fichier.write_bytes(ctx.crypto.encrypt('{"echantillons": []}'))
    ctx.zones.creer("Clinique", 45.5, -73.6, 200)
    ctx.secrets.set_api_key("vela", "jeton-appareil")
    agent = next(a for a in ctx.settings.user.agents if a != "vela")
    ctx.secrets.set_api_key(agent, "cle-byok")
    ctx.secrets.set_site("courriel", "moi@exemple.ca", "mot-de-passe-courriel")
    ctx.settings.update({"glasses": {"address": "AA:BB", "name": "VELA K900", "auto_connect": True}})

    resultat = asyncio.run(ctx.verrou.commande_distante("effacer", **_preuve(ctx.verrou, "effacer")))
    assert resultat["ok"] is True and resultat["etat"] in ("efface", "efface_partiel")
    assert resultat["verrouille"] is True and ctx.verrou.verrouille

    for table in ("memories", "messages", "conversations", "journal_ecoute", "cours", "cours_lignes", "recus",
                  "rappels_contexte", "reminders", "tasks", "entrainement_seances", "routines", "presence"):
        if table in tables:
            assert ctx.db.one(f"SELECT COUNT(*) AS n FROM {table}")["n"] == 0, table
    registre = ctx.db.query("SELECT event_type, detail FROM privacy_events ORDER BY id ASC")
    assert registre[0]["event_type"] == "effacement_a_distance", "le registre repart de l'effacement"
    assert not any("Julie" in (e["detail"] or "") for e in registre)
    assert ctx.consent.verify()["ok"] is True, "la chaîne du registre remis à zéro reste vérifiable"
    assert not any(p.is_file() for p in (data_dir / "captures").rglob("*"))
    assert not any((data_dir / "recus").iterdir())
    assert not ctx.verrou_vocal.fichier.exists() and ctx.verrou_vocal.consentement() is None
    assert ctx.settings.user.zones_sans_memoire == []
    assert not (data_dir / "telecommande-pairing").exists()
    assert ctx.comptes.session_valide(session) is False, "les téléphones doivent se reconnecter"
    assert ctx.secrets.get_api_key(agent) is None and ctx.secrets.get_site("courriel") is None
    assert ctx.secrets.get_api_key("vela") == "jeton-appareil", "l'ordinateur reste verrouillable à distance"
    assert ctx.settings.user.glasses.address == "" and ctx.settings.user.glasses.auto_connect is False
    # le compte et le mot de passe restent : on peut déverrouiller
    assert ctx.comptes.configure and ctx.verrou.deverrouiller(MOT_DE_PASSE)["verrouille"] is False
    assert ctx.verrou.code_defini, "le code de secours reste pour un prochain verrouillage"


def test_effacement_ne_laisse_aucune_table_utilisateur_ni_fichier_personnel(app, data_dir, tmp_path, monkeypatch):
    """Constat du 2026-09-14 : l'effacement oubliait settings.json.bak, mode-invite.json, la clé de voix du .env,
    le journal technique, et toute table ajoutée après sa liste. Désormais : toute table sauf la liste blanche."""
    from iris import verrou as module_verrou

    ctx = app.state.ctx
    _proprietaire(ctx)
    tables = {r["name"] for r in ctx.db.query("SELECT name FROM sqlite_master WHERE type='table'")}
    ctx.db.execute("CREATE TABLE IF NOT EXISTS table_future_equipe (id TEXT PRIMARY KEY, secret TEXT NOT NULL)")
    tables.add("table_future_equipe")
    remplies = []
    for table in sorted(tables):
        if table.startswith("sqlite_") or table in ("conversations", "cours"):
            continue
        try:
            if table == "messages":
                conv = ctx.chat.create_conversation(title="Privée")
                ctx.chat._add_message(conv["id"], "user", "message privé")
            elif table == "cours_lignes":
                _inserer(ctx.db, "cours", id="c-1")
                _inserer(ctx.db, "cours_lignes", cours_id="c-1")
            else:
                _inserer(ctx.db, table)
            remplies.append(table)
        except Exception as exc:  # une table au schéma exotique : on le dit plutôt que de l'ignorer en silence
            pytest.fail(f"insertion factice impossible dans {table} : {exc}")
    for nom in ("settings.json.bak", "mode-invite.json", "lunettes-association.json", "settings.corrupt.json"):
        (data_dir / nom).write_text('{"zones_sans_memoire": [{"lat": 45.5}]}', encoding="utf-8")
    (data_dir / ".env").write_text("# commentaire\nELEVENLABS_API_KEY=cle-perso\nIRIS_LOG_LEVEL=info\n", encoding="utf-8")
    journaux = tmp_path / "logs"
    journaux.mkdir()
    (journaux / "backend.log").write_text("mémoire : souvenir privé\n", encoding="utf-8")
    (journaux / "backend-2026-09-01.log").write_text("ancienne transcription\n", encoding="utf-8")
    monkeypatch.setenv("IRIS_JOURNAL_TECHNIQUE", str(journaux))

    rapport = ctx.verrou.effacer_donnees()

    for table in remplies:
        if table in module_verrou.TABLES_CONSERVEES:
            continue
        assert ctx.db.one(f'SELECT COUNT(*) AS n FROM "{table}"')["n"] == 0, table
    registre = ctx.db.query("SELECT event_type FROM privacy_events")
    assert [e["event_type"] for e in registre] == ["effacement_a_distance"], "une seule ligne : l'effacement"
    for nom in ("settings.json.bak", "mode-invite.json", "lunettes-association.json", "settings.corrupt.json"):
        assert not (data_dir / nom).exists(), nom
    env = (data_dir / ".env").read_text(encoding="utf-8")
    assert "cle-perso" not in env and "IRIS_LOG_LEVEL=info" in env
    assert (journaux / "backend.log").read_text(encoding="utf-8") == ""
    assert not (journaux / "backend-2026-09-01.log").exists()
    assert rapport["journal_technique"] == 2 and rapport["secrets_env"] == 1


def test_retention_du_journal_technique(tmp_path):
    import os
    import time as horloge

    from iris.verrou import purger_journal_technique

    (tmp_path / "backend.log").write_text("aujourd'hui\n", encoding="utf-8")
    vieux = tmp_path / "backend-2026-08-01.log"
    vieux.write_text("vieux\n", encoding="utf-8")
    il_y_a_10_jours = horloge.time() - 10 * 86400
    os.utime(vieux, (il_y_a_10_jours, il_y_a_10_jours))
    assert purger_journal_technique(0, tmp_path) == 0, "rétention illimitée : rien n'est vidé"
    assert purger_journal_technique(7, tmp_path) == 1
    assert not vieux.exists() and (tmp_path / "backend.log").read_text(encoding="utf-8") == "aujourd'hui\n"
    assert purger_journal_technique(None, tmp_path / "absent") == 0


# --------------------------------------------------------------------------- télécommande
class FauxChat:
    def set_sink_confirm_distant(self, cb):
        self.sink = cb


def _telecommande(telecommande: bool, distant: bool, verrou=None):
    from iris.telecommande import Telecommande

    reglages = SimpleNamespace(user=SimpleNamespace(relay_server="https://relais.exemple", local_only=False,
                                                    telecommande=telecommande, verrou_distant_actif=distant),
                               data_dir="/dossier/inexistant")
    tc = Telecommande(FauxChat(), reglages, obtenir_jeton=lambda: "jeton")
    tc.verrou = verrou
    envois: list[dict] = []

    async def enregistrer(message):
        envois.append(message)

    tc._envoyer = enregistrer
    return tc, envois


def test_telecommande_nouvre_le_canal_que_pour_ce_qui_est_active():
    assert _telecommande(False, False)[0].actif() is False
    assert _telecommande(False, True)[0].actif() is True, "le verrouillage à distance seul ouvre le canal"


def test_seul_le_verrou_passe_quand_la_telecommande_est_coupee():
    class FauxVerrou:
        verrouille = False

        async def commande_distante(self, action, preuve, nonce, defi_page):
            bonne = preuve == "bonne-preuve"
            return {"ok": bonne, "etat": "verrouille" if bonne else "code_refuse", "message": "m"}

    tc, envois = _telecommande(False, True, FauxVerrou())

    async def scenario():
        await tc._traiter({"type": "commande", "req_id": "c1", "texte": "ouvre le navigateur"})
        await tc._traiter({"type": "verrou", "req_id": "v1", "action": "verrouiller", "preuve": "bonne-preuve",
                           "nonce": _nonce(), "defi_page": DEFI_PAGE})
        # Un message de l'ancien format (code en clair) n'est jamais traité.
        await tc._traiter({"type": "verrou", "req_id": "v0", "action": "verrouiller", "code": CODE})
        await asyncio.sleep(0.05)

    asyncio.run(scenario())
    commande = next(m for m in envois if m["req_id"] == "c1")
    assert commande["type"] == "resultat" and "désactivée" in commande["reponse"]
    verrou = next(m for m in envois if m["req_id"] == "v1")
    assert verrou == {"type": "resultat", "req_id": "v1", "verrou": True, "ok": True, "etat": "verrouille", "message": "m"}
    ancien = next(m for m in envois if m["req_id"] == "v0")
    assert ancien["etat"] == "protocole_perime" and ancien["ok"] is False


def test_aucune_commande_distante_pendant_le_verrou():
    tc, envois = _telecommande(True, True, SimpleNamespace(verrouille=True))
    executees: list[str] = []

    async def executer(req_id, texte):
        executees.append(texte)

    tc._executer = executer

    async def scenario():
        await tc._traiter({"type": "commande", "req_id": "c2", "texte": "supprime mes fichiers"})
        await asyncio.sleep(0.05)

    asyncio.run(scenario())
    assert executees == [] and "verrouillée" in envois[0]["reponse"]


def test_verrou_distant_refuse_si_reglage_coupe():
    tc, envois = _telecommande(True, False, VerrouIRIS.__new__(VerrouIRIS))
    asyncio.run(tc._verrou_distant("v2", "verrouiller", "preuve", _nonce(), DEFI_PAGE))
    assert envois[0]["etat"] == "desactive" and envois[0]["verrou"] is True


def test_la_telecommande_suit_letat_du_verrou_et_transmet_le_lot():
    """L'activation fait foi dans verrou.json : le réglage allumé ne suffit pas si le verrou dit non."""
    recues: list[tuple] = []

    class Verrou:
        verrouille = False
        distant_actif = False

        async def commande_distante(self, action, preuve, nonce, defi_page, **lot):
            recues.append((action, lot))
            return {"ok": False, "etat": "code_refuse", "message": "m"}

    verrou = Verrou()
    tc, envois = _telecommande(False, True, verrou)
    assert tc.verrou_distant_permis() is False and tc.actif() is False
    verrou.distant_actif = True
    assert tc.verrou_distant_permis() is True

    async def scenario():
        await tc._traiter({"type": "verrou", "req_id": "v3", "action": "effacer", "preuve": "p", "nonce": _nonce(),
                           "defi_page": DEFI_PAGE, "differee": True, "lot": "abc", "reste": 1})
        await tc._traiter({"type": "verrou", "req_id": "v4", "action": "verrouiller", "preuve": "p", "nonce": _nonce(),
                           "defi_page": DEFI_PAGE, "differee": True, "lot": "abc", "reste": "pas un nombre"})
        await asyncio.sleep(0.05)

    asyncio.run(scenario())
    assert recues == [("effacer", {"differee": True, "lot": "abc", "reste": 1}), ("verrouiller", {})]


def test_effacement_retire_les_identifiants_importes_du_navigateur(app, monkeypatch):
    """Contre-vérification du 2026-09-14 : les mots de passe importés du navigateur (rangés sous « site:<domaine> »
    sans passer par le réglage `sites`) survivaient à l'effacement, que la page /verrou annonce pourtant."""
    from iris import identifiants_navigateur as idn

    ctx = app.state.ctx
    _proprietaire(ctx)

    class Ident:
        domaine, utilisateur, _secret = "github.com", "miguel", "mdp-github-importe"

    monkeypatch.setattr(idn, "_identifiants", lambda motif, dpapi=None, aes_gcm=None: [Ident()])
    assert idn.importer_dans_le_coffre("github", ctx.secrets)["importes"] == 1
    assert ctx.secrets.sites_enregistres() == ["github.com"]
    rapport = ctx.verrou.effacer_donnees()
    assert ctx.secrets.get_site("github.com") is None
    assert rapport["identifiants_supprimes"] >= 1


def test_le_coffre_systeme_tient_lindex_des_sites_sans_les_mots_de_passe(data_dir, monkeypatch):
    """Dans le coffre système (qui ne sait pas énumérer), l'index ne garde que les noms."""
    import sys
    import types

    from iris.security.crypto import Crypto
    from iris.security.secrets import SERVICE, SecretStore

    magasin: dict[tuple[str, str], str] = {}
    faux = types.ModuleType("keyring")
    faux.set_password = lambda s, n, v: magasin.__setitem__((s, n), v)
    faux.get_password = lambda s, n: magasin.get((s, n))

    def supprimer(s, n):
        if (s, n) not in magasin:
            raise KeyError(n)
        del magasin[(s, n)]

    faux.delete_password = supprimer
    monkeypatch.setitem(sys.modules, "keyring", faux)
    coffre = SecretStore(Crypto(b"k" * 32), data_dir, use_keyring=True)
    assert coffre.backend == "keyring"
    coffre.set_site("omnivox.ca", "moi", "secret-omnivox")
    coffre.set_site("github.com", "moi", "secret-github")
    assert coffre.sites_enregistres() == ["github.com", "omnivox.ca"]
    assert "secret" not in (magasin.get((SERVICE, "site-index")) or "")
    coffre.delete_site("omnivox.ca")
    assert coffre.sites_enregistres() == ["github.com"]


def test_letat_du_verrou_donne_le_code_a_recopier_pour_la_liaison(client, app):
    """Contre-vérification du 2026-09-14 : la page de confirmation du relais demande le code de la clé de CET
    ordinateur ; l'écran Verrouillage à distance le lit ici."""
    import base64
    import hashlib

    tc = app.state.ctx.telecommande
    etat = client.get("/api/confiance/verrou/etat").json()
    assert etat["empreinte_liaison"] == base64.b32encode(hashlib.sha256(tc.cle()).digest()).decode()[:6]
