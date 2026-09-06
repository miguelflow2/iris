"""Les routes du courriel et de la téléphonie : ce qui manquait pour que le SMS arrive vraiment.

Le 6 septembre 2026, le journal montrait IRIS dire « le texto est prêt sur ton téléphone » alors
que rien n'apparaissait sur l'iPhone : le brouillon attendait dans `Telephoniste._attente` et
aucune route ne permettait de le lire. Ces tests protègent trois choses : le téléphone peut voir,
fermer et annuler un brouillon ; le courriel se configure sans que le mot de passe ressorte
jamais ; et chaque route refuse un appel sans jeton, comme toutes les autres.

Aucun test ne touche le réseau : le serveur SMTP est une doublure, et la voie iPhone n'ouvre
aucune connexion de toute façon.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.testclient import TestClient

from iris.courriel import Postier
from iris.routes_communications import PUCES, creer_routeur, sans_secrets
from iris.security.crypto import Crypto, load_master_key
from iris.security.secrets import SecretStore
from iris.telephonie import Telephoniste

ADRESSE = "miguel@gmail.com"
# Seize lettres, comme Google les affiche : quatre groupes de quatre, séparés par des espaces.
MOTDEPASSE_AFFICHE = "abcd efgh ijkl mnop"
MOTDEPASSE = "abcdefghijklmnop"
NUMERO = "+18195242804"
SID = "AC" + "0123456789abcdef" * 2
TOKEN = "f1e2d3c4b5a697887766554433221100"
EXPEDITEUR = "+15145550100"
JETON = "jeton-de-test"


# --------------------------------------------------------------------------- doublures
class FauxSMTP:
    """Faux serveur d'envoi : il note ce qu'on lui demande et ne fait rien partir."""

    def __init__(self, journal: list, echec: Exception | None = None):
        self.journal = journal
        self.echec = echec

    def __enter__(self) -> "FauxSMTP":
        return self

    def __exit__(self, *_exc) -> bool:
        return False

    def starttls(self) -> None:
        self.journal.append("starttls")

    def login(self, utilisateur: str, mot_de_passe: str) -> None:
        self.journal.append(("login", utilisateur, mot_de_passe))
        if self.echec:
            raise self.echec


def fabrique(journal: list, echec: Exception | None = None):
    def ouvrir(hote: str, port: int, ssl: bool):
        journal.append(("connexion", hote, port, ssl))
        return FauxSMTP(journal, echec)

    return ouvrir


def reseau_interdit(*_a, **_k):
    raise AssertionError("la voie iPhone a tenté un appel réseau")


class FauxRegistre:
    def __init__(self) -> None:
        self.entrees: list[tuple[str, str]] = []

    def log(self, event_type: str, data_type: str | None = None, agent: str | None = None, detail: str = "") -> None:
        self.entrees.append((event_type, detail))

    @property
    def evenements(self) -> list[str]:
        return [e[0] for e in self.entrees]


class FauxHub:
    def __init__(self) -> None:
        self.publications: list[tuple[str, dict]] = []

    def publish(self, type_: str, **donnees: Any) -> None:
        self.publications.append((type_, donnees))


@dataclass
class FauxUtilisateur:
    local_only: bool = False
    courriel: Any = None
    telephonie: Any = None


class FauxSettings:
    def __init__(self, **kwargs):
        self.user = FauxUtilisateur(**kwargs)


# --------------------------------------------------------------------------- fixtures
@pytest.fixture()
def coffre(tmp_path) -> SecretStore:
    cle, _source = load_master_key(tmp_path, use_keyring=False)
    return SecretStore(Crypto(cle), tmp_path, use_keyring=False)


@pytest.fixture()
def journal() -> list:
    return []


@pytest.fixture()
def ctx(coffre, journal) -> SimpleNamespace:
    """Un contexte factice qui ne porte que ce que le routeur lit : postier, téléphoniste, registre."""
    registre = FauxRegistre()
    hub = FauxHub()
    return SimpleNamespace(
        courriel=Postier(FauxSettings(), coffre, fabrique_smtp=fabrique(journal)),
        telephonie=Telephoniste(FauxSettings(), coffre, client_http=reseau_interdit, registre=registre, hub=hub),
        consent=registre,
        hub=hub,
    )


def garde(request: Request) -> None:
    """La même règle que main.py : un jeton, en en-tête ou dans l'adresse, sinon 401."""
    entete = request.headers.get("authorization", "")
    fourni = entete[7:] if entete.lower().startswith("bearer ") else request.query_params.get("token", "")
    if fourni != JETON:
        raise HTTPException(status_code=401, detail="jeton de session invalide")


@pytest.fixture()
def application(ctx) -> FastAPI:
    """Le routeur inclus EXACTEMENT comme main.py le fera : avec la garde en dépendance."""
    app = FastAPI()
    app.include_router(creer_routeur(ctx), dependencies=[Depends(garde)])
    return app


@pytest.fixture()
def client(application) -> TestClient:
    return TestClient(application, headers={"Authorization": f"Bearer {JETON}"})


@pytest.fixture()
def anonyme(application) -> TestClient:
    return TestClient(application)


def deposer(telephoniste: Telephoniste, message: str = "J'arrive dans dix minutes.") -> dict:
    """Passe par le seul chemin qui dépose un brouillon : la confirmation, puis l'exécution."""

    async def oui(_titre: str, _detail: str) -> bool:
        return True

    resultat = asyncio.run(telephoniste.envoyer_sms_apres_accord(NUMERO, message, oui))
    assert resultat["en_attente"] is True and resultat["envoye"] is False
    return resultat


ROUTES = [
    ("GET", "/api/courriel/etat"),
    ("POST", "/api/courriel/configurer"),
    ("POST", "/api/courriel/tester"),
    ("DELETE", "/api/courriel"),
    ("GET", "/api/telephonie/etat"),
    ("POST", "/api/telephonie/configurer"),
    ("DELETE", "/api/telephonie"),
    ("GET", "/api/telephonie/en_attente"),
    ("POST", "/api/telephonie/abc123/envoye"),
    ("POST", "/api/telephonie/abc123/annule"),
]


# --------------------------------------------------------------------------- protection
@pytest.mark.parametrize("methode,chemin", ROUTES)
def test_chaque_route_refuse_un_appel_sans_jeton(anonyme: TestClient, methode: str, chemin: str):
    """Ces routes lisent des textos et rangent des mots de passe : sans jeton, elles ne répondent rien."""
    r = anonyme.request(methode, chemin, json={})
    assert r.status_code == 401, f"{methode} {chemin} a répondu {r.status_code} sans jeton"


def test_le_jeton_dans_ladresse_suffit_comme_ailleurs(anonyme: TestClient):
    """Le téléphone passe par l'en-tête, mais main.py accepte aussi ?token= : la garde est la même."""
    assert anonyme.get(f"/api/telephonie/en_attente?token={JETON}").status_code == 200


def test_la_garde_est_celle_de_lapplication_reelle(app):
    """Inclus dans l'application réelle avec sa vraie garde, le routeur refuse sans jeton et
    accepte le jeton de l'application — c'est la ligne que main.py doit porter."""
    if not any(getattr(r, "path", "") == "/api/telephonie/en_attente" for r in app.routes):
        # main.py n'inclut pas encore le routeur : on le fait ici, avec la garde réelle, récupérée
        # sur une route qu'elle protège déjà. Le jour où main.py l'inclut, ce bloc ne sert plus.
        statut = next(r for r in app.routes if getattr(r, "path", "") == "/api/status")
        app.include_router(creer_routeur(app.state.ctx), dependencies=list(statut.dependencies))
    # Un seul client : refermer le premier éteindrait l'application, base de données comprise.
    with TestClient(app) as c:
        assert c.get("/api/telephonie/en_attente").status_code == 401
        assert c.get("/api/courriel/etat").status_code == 401
        ok = {"Authorization": "Bearer test-token"}
        assert c.get("/api/telephonie/en_attente", headers=ok).json()["brouillons"] == []
        assert c.get("/api/courriel/etat", headers=ok).json()["configure"] is False


# --------------------------------------------------------------------------- le SMS fantôme
def test_le_telephone_voit_le_brouillon_que_iris_a_depose(client: TestClient, ctx):
    """LE bogue du 6 septembre : IRIS disait « touche Envoyer » et le téléphone ne voyait rien."""
    depose = deposer(ctx.telephonie, "On se voit à 14 h ?")
    d = client.get("/api/telephonie/en_attente").json()
    assert d["voie"] == "iphone"
    assert len(d["brouillons"]) == 1
    b = d["brouillons"][0]
    assert b["id"] == depose["id"]
    assert b["texte"] == "On se voit à 14 h ?" and b["numero"] == NUMERO
    assert b["numero_lisible"] == "819 524-2804", "le téléphone affiche un numéro lisible, pas E.164"
    assert b["genre"] == "sms" and b["depose_a"]


def test_les_liens_ouvrent_messages_deja_rempli(client: TestClient, ctx):
    """iOS attend « &body= », Android « ?body= » ; se tromper donne un SMS vide sans erreur."""
    deposer(ctx.telephonie, "Salut & à plus")
    b = client.get("/api/telephonie/en_attente").json()["brouillons"][0]
    assert b["lien_ios"].startswith(f"sms:{NUMERO}&body=")
    assert b["lien_android"].startswith(f"sms:{NUMERO}?body=")
    assert "Salut%20%26%20%C3%A0%20plus" in b["lien_ios"], "le texte doit être encodé, l'esperluette comprise"


def test_un_appel_donne_un_lien_tel(client: TestClient, ctx):
    async def oui(_t: str, _d: str) -> bool:
        return True

    asyncio.run(ctx.telephonie.appeler_apres_accord("819 524 2804", oui))
    b = client.get("/api/telephonie/en_attente").json()["brouillons"][0]
    assert b["genre"] == "appel" and b["lien_ios"] == f"tel:{NUMERO}" and b["lien_android"] == f"tel:{NUMERO}"


def test_touche_envoye_ferme_le_brouillon_et_le_registre_le_note(client: TestClient, ctx):
    depose = deposer(ctx.telephonie)
    r = client.post(f"/api/telephonie/{depose['id']}/envoye")
    assert r.status_code == 200 and r.json()["ok"] is True
    assert "parti de ton téléphone" in r.json()["message"]
    assert client.get("/api/telephonie/en_attente").json()["brouillons"] == []
    assert "telephonie_envoye" in ctx.consent.evenements
    assert ("telephone.brouillon_ferme", {"id": depose["id"], "etat": "envoye"}) in ctx.hub.publications


def test_annuler_ferme_le_brouillon_sans_pretendre_quil_est_parti(client: TestClient, ctx):
    depose = deposer(ctx.telephonie)
    r = client.post(f"/api/telephonie/{depose['id']}/annule")
    assert r.status_code == 200 and "oublie" in r.json()["message"]
    assert client.get("/api/telephonie/en_attente").json()["brouillons"] == []
    assert "telephonie_annule" in ctx.consent.evenements
    assert "telephonie_envoye" not in ctx.consent.evenements


def test_un_brouillon_deja_traite_repond_404_en_francais(client: TestClient, ctx):
    """Deux pouces sur « C'est envoyé » : le second doit expliquer, pas planter."""
    depose = deposer(ctx.telephonie)
    client.post(f"/api/telephonie/{depose['id']}/envoye")
    r = client.post(f"/api/telephonie/{depose['id']}/envoye")
    assert r.status_code == 404 and "n'existe plus" in r.json()["detail"]
    assert client.post("/api/telephonie/inconnu/annule").status_code == 404


def test_les_brouillons_sortent_du_plus_ancien_au_plus_recent(client: TestClient, ctx):
    deposer(ctx.telephonie, "premier")
    deposer(ctx.telephonie, "deuxième")
    textes = [b["texte"] for b in client.get("/api/telephonie/en_attente").json()["brouillons"]]
    assert textes == ["premier", "deuxième"]


# --------------------------------------------------------------------------- la page /m
def test_la_page_mobile_sonde_et_affiche_les_brouillons():
    """Sans ce code dans la page, la route existe et le téléphone ne montre toujours rien."""
    from iris.mobile import PAGE

    for attendu in (
        "/api/telephonie/en_attente",
        "'envoye'",
        "'annule'",
        'id="brouillons"',
        "lien_ios",
        "lien_android",
        "Ouvrir dans Messages",
        "Annuler",
        "visibilitychange",
    ):
        assert attendu in PAGE, f"manque dans la page téléphone : {attendu}"


def test_la_page_mobile_naccepte_que_sms_et_tel():
    """Un lien venu de l'API ne doit jamais devenir autre chose qu'un sms: ou un tel:."""
    from iris.mobile import PAGE

    assert "indexOf('sms:') === 0" in PAGE and "indexOf('tel:') === 0" in PAGE


# --------------------------------------------------------------------------- le courriel
def test_letat_du_courriel_dit_quil_manque_un_compte_et_ou_le_prendre(client: TestClient):
    d = client.get("/api/courriel/etat").json()
    assert d["configure"] is False and d["adresse"] == "" and d["secret"] == ""
    assert "apppasswords" in d["mode_emploi"] and "deux étapes" in d["mode_emploi"]
    assert d["lien_mots_de_passe_application"] == "https://myaccount.google.com/apppasswords"


def test_configurer_le_courriel_range_le_compte_dans_le_coffre(client: TestClient, ctx, coffre):
    r = client.post("/api/courriel/configurer", json={"adresse": ADRESSE, "mot_de_passe_application": MOTDEPASSE_AFFICHE})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["configure"] is True and d["adresse"] == ADRESSE
    assert d["smtp_hote"] == "smtp.gmail.com", "Gmail est reconnu à l'adresse, sans rien demander d'autre"
    assert d["avertissement"] == "", "seize lettres : rien à signaler"
    compte = coffre.get_site("courriel")
    assert compte["username"] == ADRESSE
    assert compte["password"] == MOTDEPASSE, "les espaces affichés par Google sont retirés avant de ranger"
    assert ("courriel_configure", ADRESSE) in ctx.consent.entrees


def test_un_mot_de_passe_habituel_est_signale_mais_range(client: TestClient):
    """Un mot de passe Google ordinaire sera refusé par Gmail : on prévient avant le premier envoi."""
    d = client.post("/api/courriel/configurer", json={"adresse": ADRESSE, "mot_de_passe_application": "MonMotDePasse2026"}).json()
    assert d["configure"] is True and "16 lettres" in d["avertissement"]


def test_une_adresse_invalide_ou_un_secret_vide_repondent_400_en_francais(client: TestClient):
    r = client.post("/api/courriel/configurer", json={"adresse": "pas une adresse", "mot_de_passe_application": MOTDEPASSE})
    assert r.status_code == 400 and r.json()["detail"]
    r = client.post("/api/courriel/configurer", json={"adresse": ADRESSE, "mot_de_passe_application": "   "})
    assert r.status_code == 400 and "manquant" in r.json()["detail"]


def test_tester_ouvre_une_connexion_et_sidentifie_sans_rien_envoyer(client: TestClient, journal):
    client.post("/api/courriel/configurer", json={"adresse": ADRESSE, "mot_de_passe_application": MOTDEPASSE_AFFICHE})
    r = client.post("/api/courriel/tester")
    assert r.status_code == 200, r.text
    assert r.json()["ok"] is True and "smtp.gmail.com" in r.json()["message"]
    assert ("connexion", "smtp.gmail.com", 587, False) in journal
    assert ("login", ADRESSE, MOTDEPASSE) in journal
    assert not any(g == "send_message" for g in journal), "tester n'envoie jamais rien"


def test_tester_sans_compte_explique_quoi_faire(client: TestClient):
    r = client.post("/api/courriel/tester")
    assert r.status_code == 400 and "apppasswords" in r.json()["detail"]


def test_tester_avec_un_mauvais_secret_dit_ce_que_gmail_attend(coffre):
    import smtplib

    journal: list = []
    erreur = smtplib.SMTPAuthenticationError(535, b"5.7.8 Username and Password not accepted")
    contexte = SimpleNamespace(
        courriel=Postier(FauxSettings(), coffre, fabrique_smtp=fabrique(journal, echec=erreur)),
        telephonie=None, consent=None,
    )
    app = FastAPI()
    app.include_router(creer_routeur(contexte), dependencies=[Depends(garde)])
    c = TestClient(app, headers={"Authorization": f"Bearer {JETON}"})
    c.post("/api/courriel/configurer", json={"adresse": ADRESSE, "mot_de_passe_application": MOTDEPASSE_AFFICHE})
    r = c.post("/api/courriel/tester")
    assert r.status_code == 400
    assert "application" in r.json()["detail"].lower(), "la réponse doit orienter vers le mot de passe d'application"
    assert MOTDEPASSE not in r.text


def test_oublier_efface_le_compte(client: TestClient, ctx, coffre):
    client.post("/api/courriel/configurer", json={"adresse": ADRESSE, "mot_de_passe_application": MOTDEPASSE_AFFICHE})
    d = client.delete("/api/courriel").json()
    assert d["configure"] is False and d["adresse"] == ""
    assert coffre.get_site("courriel") is None
    assert "courriel_oublie" in ctx.consent.evenements


def test_le_mot_de_passe_ne_ressort_jamais_meme_en_morceaux(client: TestClient):
    """SecretStore.mask montre quatre lettres au début et quatre à la fin : sur seize, c'est la moitié."""
    reponses = [
        client.post("/api/courriel/configurer", json={"adresse": ADRESSE, "mot_de_passe_application": MOTDEPASSE_AFFICHE}),
        client.get("/api/courriel/etat"),
        client.post("/api/courriel/tester"),
        client.delete("/api/courriel"),
    ]
    for r in reponses:
        assert MOTDEPASSE not in r.text and MOTDEPASSE_AFFICHE not in r.text
        assert MOTDEPASSE[:4] not in r.text and MOTDEPASSE[-4:] not in r.text
    assert reponses[0].json()["secret"] == PUCES, "l'interface voit qu'un secret existe, rien de plus"


# --------------------------------------------------------------------------- Twilio, optionnel
def test_letat_de_la_telephonie_decrit_la_voie_iphone(client: TestClient):
    d = client.get("/api/telephonie/etat").json()
    assert d["fournisseur"] == "iphone" and d["configure"] is True
    assert d["peut_envoyer_seule"] is False and d["voie"] == "brouillon sur le téléphone"
    assert "Envoyer" in d["explication"]


def test_configurer_twilio_range_le_compte_sans_le_rendre(client: TestClient, ctx, coffre):
    r = client.post("/api/telephonie/configurer", json={"account_sid": SID, "auth_token": TOKEN, "numero": "514-555-0100"})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["numero_expediteur"] == EXPEDITEUR
    assert d["secret"] == PUCES and TOKEN not in r.text
    assert coffre.get_site("telephonie") == {"username": SID, "password": TOKEN}
    assert ("telephonie_configuree", EXPEDITEUR) in ctx.consent.entrees


def test_lauth_token_ne_ressort_jamais_meme_en_morceaux(client: TestClient):
    """Le masque du coffre rendrait « f1e2…1100 » : un quart d'un secret de 32 caractères."""
    reponses = [
        client.post("/api/telephonie/configurer", json={"account_sid": SID, "auth_token": TOKEN, "numero": EXPEDITEUR}),
        client.get("/api/telephonie/etat"),
        client.get("/api/telephonie/en_attente"),
        client.delete("/api/telephonie"),
    ]
    for r in reponses:
        assert TOKEN not in r.text and TOKEN[:4] not in r.text and TOKEN[-4:] not in r.text


def test_un_sid_qui_nest_pas_un_account_sid_est_refuse_avec_explication(client: TestClient, coffre):
    r = client.post("/api/telephonie/configurer", json={"account_sid": "SK" + "0" * 32, "auth_token": TOKEN, "numero": EXPEDITEUR})
    assert r.status_code == 400 and "AC" in r.json()["detail"]
    assert coffre.get_site("telephonie") is None, "rien ne doit être rangé sur un refus"


def test_oublier_twilio_vide_le_coffre(client: TestClient, coffre):
    client.post("/api/telephonie/configurer", json={"account_sid": SID, "auth_token": TOKEN, "numero": EXPEDITEUR})
    d = client.delete("/api/telephonie").json()
    assert d["identifiant"] == "" and d["secret"] == "" and d["numero_expediteur"] == ""
    assert coffre.get_site("telephonie") is None and coffre.get_site("telephonie-numero") is None


# --------------------------------------------------------------------------- sans service
def test_sans_service_le_routeur_repond_503_en_francais_au_lieu_de_planter():
    contexte = SimpleNamespace(courriel=None, telephonie=None)
    app = FastAPI()
    app.include_router(creer_routeur(contexte), dependencies=[Depends(garde)])
    c = TestClient(app, headers={"Authorization": f"Bearer {JETON}"})
    assert c.get("/api/courriel/etat").status_code == 503
    assert "courriel" in c.get("/api/courriel/etat").json()["detail"]
    assert c.get("/api/telephonie/en_attente").status_code == 503


def test_sans_secrets_reduit_les_champs_secrets_a_des_puces():
    assert sans_secrets({"secret": "f1e2…1100", "auth_token": "x", "adresse": "a@b.c"}) == {
        "secret": PUCES, "auth_token": PUCES, "adresse": "a@b.c",
    }
    assert sans_secrets({"secret": ""})["secret"] == ""
    assert sans_secrets({}) == {} and sans_secrets(None) == {}
