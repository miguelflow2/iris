"""La vraie ligne téléphonique d'IRIS chez Twilio : SMS et appels, sortants et entrants.

Décision de Miguel, 7 septembre 2026. Ces tests protègent les mêmes promesses que test_telephonie.py
— rien ne part sans un accord donné juste avant pour CE message-là, un service incomplet le dit en
français, une erreur ne vide pas un crédit — et en ajoutent pour ce qui est neuf : l'authentification
par clé d'API, l'appel sortant qui dit un message, et surtout les webhooks ENTRANTS, qui ne traitent
JAMAIS une requête dont la signature Twilio n'est pas prouvée.

Aucun test ne touche le réseau (client HTTP injecté), n'envoie de vrai SMS, ne passe de vrai appel,
ni ne lit l'environnement réel (configuration de ligne injectée).
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import logging
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from iris import twilio_ligne
from iris.security.crypto import Crypto, load_master_key
from iris.security.secrets import SecretStore
from iris.telephonie import (
    Autorisation,
    AutorisationInvalide,
    EnvoiEchoue,
    ModeLocalActif,
    NumeroInvalide,
    Telephoniste,
    TelephonieNonConfiguree,
)

NUMERO = "+18195242804"
ACCOUNT_SID = "AC" + "0123456789abcdef" * 2  # AC + 32 = 34, comme un vrai Account SID
API_KEY_SID = "SK" + "fedcba9876543210" * 2  # SK + 32 = 34, forme d'un vrai SID de clé d'API (valeur fictive)
API_KEY_SECRET = "secret_de_la_cle_api_0123456789abcdef"
NUMERO_LIGNE = "+15145550100"
AUTH_TOKEN = "auth_token_du_compte_0123456789abcdef"


# --------------------------------------------------------------------------- doublures
class FausseReponse:
    def __init__(self, statut: int, corps: dict):
        self.status_code = statut
        self._corps = corps

    def json(self) -> dict:
        return self._corps


class FauxHTTP:
    """Faux opérateur : aucun octet ne quitte la machine pendant les tests."""

    def __init__(self, statut: int = 201, corps: dict | None = None, erreur: Exception | None = None):
        self.statut = statut
        self.corps = corps if corps is not None else {"sid": "SM00000000000000000000000000000000", "status": "queued"}
        self.erreur = erreur
        self.appels: list[dict] = []

    def __call__(self, url: str, donnees: dict, auth: tuple[str, str], delai: int) -> FausseReponse:
        self.appels.append({"url": url, "donnees": donnees, "auth": auth, "delai": delai})
        if self.erreur:
            raise self.erreur
        return FausseReponse(self.statut, self.corps)


def reseau_interdit(*_a, **_k):
    raise AssertionError("un appel réseau a été tenté alors qu'aucun accord n'avait été donné")


class Horloge:
    def __init__(self, depart: float = 10_000.0):
        self.t = depart

    def __call__(self) -> float:
        return self.t

    def avancer(self, secondes: float) -> None:
        self.t += secondes


class FauxRegistre:
    def __init__(self) -> None:
        self.entrees: list[tuple[str, str, str]] = []

    def log(self, event_type: str, data_type: str | None = None, agent: str | None = None, detail: str = "") -> None:
        self.entrees.append((event_type, agent or "", detail))

    @property
    def evenements(self) -> list[str]:
        return [e[0] for e in self.entrees]


class FauxHub:
    def __init__(self) -> None:
        self.publications: list[tuple[str, dict]] = []

    def publish(self, type_: str, **donnees: Any) -> None:
        self.publications.append((type_, donnees))


@dataclass
class ReglagesBruts:
    fournisseur: str = "twilio_ligne"
    numero_par_defaut: str = ""
    indicatif_pays: str = "+1"


@dataclass
class FauxUtilisateur:
    local_only: bool = False
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
def horloge() -> Horloge:
    return Horloge()


def config(**kw) -> twilio_ligne.ConfigLigne:
    base = dict(account_sid=ACCOUNT_SID, api_key_sid=API_KEY_SID, api_key_secret=API_KEY_SECRET, numero=NUMERO_LIGNE)
    base.update(kw)
    return twilio_ligne.ConfigLigne(**base)


def ligne(coffre, horloge, http, *, config_ligne: twilio_ligne.ConfigLigne | None = None,
          local_only: bool = False, registre: FauxRegistre | None = None) -> Telephoniste:
    settings = FauxSettings(local_only=local_only, telephonie=ReglagesBruts(fournisseur="twilio_ligne"))
    return Telephoniste(settings, coffre, client_http=http, horloge=horloge,
                        registre=registre if registre is not None else FauxRegistre(),
                        config_ligne=config_ligne if config_ligne is not None else config())


def accord_oui(iris: Telephoniste, brouillon) -> Autorisation:
    async def confirmer(_titre: str, _detail: str) -> bool:
        return True

    return asyncio.run(iris.demander_accord(brouillon, confirmer))


# --------------------------------------------------------------------------- configuration (env)
def test_la_config_se_lit_dans_lenvironnement_sans_secret_en_dur():
    env = {
        "TWILIO_ACCOUNT_SID": ACCOUNT_SID,
        "TWILIO_API_KEY_SID": API_KEY_SID,
        "TWILIO_API_KEY_SECRET": API_KEY_SECRET,
        "TWILIO_NUMBER": NUMERO_LIGNE,
        "TWILIO_AUTH_TOKEN": AUTH_TOKEN,
        "TWILIO_PUBLIC_BASE": "https://iris.exemple.app/",
    }
    c = twilio_ligne.ConfigLigne.depuis_environnement(env)
    assert c.sortant_pret is True and c.entrant_pret is True
    assert c.auth() == (API_KEY_SID, API_KEY_SECRET)
    assert c.base_publique == "https://iris.exemple.app"  # le / final est retiré
    # L'URL porte l'Account SID du compte (AC…), jamais le SID de la clé d'API (SK…).
    assert ACCOUNT_SID in c.url_messages() and API_KEY_SID not in c.url_messages()
    assert c.url_messages().endswith("/Messages.json")
    assert ACCOUNT_SID in c.url_calls() and c.url_calls().endswith("/Calls.json")


def test_auth_repli_sur_account_sid_et_auth_token():
    """Cas réel de Miguel : pas de secret de clé d'API, mais Account SID + Auth Token (comme le
    curl fourni). Twilio accepte ce couple en Basic auth : la ligne doit être prête."""
    c = twilio_ligne.ConfigLigne(account_sid=ACCOUNT_SID, numero=NUMERO_LIGNE, auth_token=AUTH_TOKEN)
    assert c.sortant_pret is True
    assert c.auth() == (ACCOUNT_SID, AUTH_TOKEN)
    assert c.manquant_sortant() == []  # rien ne manque : cette voie d'auth est complète


def test_la_cle_dapi_reste_prioritaire_quand_les_deux_existent():
    """Si le secret de clé d'API ET l'Auth Token sont là, la clé d'API prime (bonne pratique)."""
    c = twilio_ligne.ConfigLigne(account_sid=ACCOUNT_SID, api_key_sid=API_KEY_SID,
                                 api_key_secret=API_KEY_SECRET, numero=NUMERO_LIGNE, auth_token=AUTH_TOKEN)
    assert c.auth() == (API_KEY_SID, API_KEY_SECRET)


def test_une_config_incomplete_nomme_precisement_ce_qui_manque():
    c = twilio_ligne.ConfigLigne(api_key_sid=API_KEY_SID)  # seule pièce fournie, comme le 7 septembre
    assert c.sortant_pret is False and c.entrant_pret is False
    manque = " ".join(c.manquant_sortant())
    assert "Account SID" in manque and "secret" in manque and "numéro" in manque
    assert "SID de la clé" not in manque, "le SID de la clé est fourni, il ne doit pas figurer dans ce qui manque"


# --------------------------------------------------------------------------- signature entrante
def _signer(auth_token: str, url: str, params: dict) -> str:
    base = url + "".join(cle + str(params[cle]) for cle in sorted(params))
    return base64.b64encode(hmac.new(auth_token.encode(), base.encode(), hashlib.sha1).digest()).decode()


def test_une_signature_valide_est_acceptee_et_toute_autre_est_refusee():
    url = "https://iris.exemple.app/twilio/entrant/sms"
    params = {"From": NUMERO, "To": NUMERO_LIGNE, "Body": "Salut"}
    bonne = _signer(AUTH_TOKEN, url, params)
    assert twilio_ligne.valider_signature(AUTH_TOKEN, url, params, bonne) is True
    # Un paramètre modifié après signature invalide tout : c'est ce qui empêche de rejouer un corps trafiqué.
    assert twilio_ligne.valider_signature(AUTH_TOKEN, url, {**params, "Body": "Autre"}, bonne) is False
    assert twilio_ligne.valider_signature(AUTH_TOKEN, url, params, "n'importe quoi") is False
    # Sans Auth Token ou sans signature, jamais « vrai par défaut ».
    assert twilio_ligne.valider_signature("", url, params, bonne) is False
    assert twilio_ligne.valider_signature(AUTH_TOKEN, url, params, "") is False


# --------------------------------------------------------------------------- TwiML
def test_le_twiml_echappe_le_xml_et_ne_repond_jamais_seul_a_un_sms():
    # Un « & » ou un « < » dans un message casserait le XML — et pourrait injecter des balises.
    dit = twilio_ligne.twiml_dire("Rappelle Léa & Tom <vite>")
    assert "&amp;" in dit and "&lt;vite&gt;" in dit and "<Say" in dit
    # La réponse à un SMS entrant est VIDE : répondre tout seul serait un envoi sans accord.
    assert twilio_ligne.twiml_vide() == '<?xml version="1.0" encoding="UTF-8"?><Response></Response>'
    accueil = twilio_ligne.twiml_accueil_entrant()
    assert "<Hangup/>" in accueil and "<Record" not in accueil, "pas d'enregistrement de la voix par défaut"


# --------------------------------------------------------------------------- SMS sortant réel
def test_un_sms_part_avec_lauth_par_cle_dapi_et_le_texte_approuve(coffre, horloge):
    http = FauxHTTP()
    iris = ligne(coffre, horloge, http)
    assert iris.configure is True
    resultat = iris.executer(accord_oui(iris, iris.preparer_sms("819 524-2804", "À demain.")))
    assert len(http.appels) == 1
    envoi = http.appels[0]
    assert envoi["auth"] == (API_KEY_SID, API_KEY_SECRET), "l'authentification est la clé d'API, pas l'Auth Token"
    assert ACCOUNT_SID in envoi["url"] and envoi["url"].endswith("/Messages.json")
    assert envoi["donnees"] == {"To": NUMERO, "From": NUMERO_LIGNE, "Body": "À demain."}
    assert resultat["envoye"] is True and resultat["ok"] is True and "IRIS" in resultat["message"]


def test_sans_accord_aucun_sms_ne_part(coffre, horloge):
    """La serrure de telephonie.py s'applique telle quelle : executer() n'accepte qu'une Autorisation."""
    iris = ligne(coffre, horloge, reseau_interdit)
    brouillon = iris.preparer_sms(NUMERO, "Un mot.")
    with pytest.raises(AutorisationInvalide):
        iris.executer(brouillon)  # type: ignore[arg-type]


def test_un_refus_de_lopérateur_ne_laisse_pas_croire_que_cest_parti(coffre, horloge):
    http = FauxHTTP(statut=400, corps={"code": 21610, "message": "unsubscribed recipient"})
    iris = ligne(coffre, horloge, http)
    with pytest.raises(EnvoiEchoue) as capture:
        iris.executer(accord_oui(iris, iris.preparer_sms(NUMERO, "Un mot.")))
    assert "STOP" in str(capture.value) and "Rien n'est parti" in str(capture.value)


def test_le_secret_de_la_cle_ne_fuit_ni_dans_lerreur_ni_dans_le_journal(coffre, horloge, caplog):
    caplog.set_level(logging.DEBUG, logger="iris.telephonie")
    http = FauxHTTP(erreur=RuntimeError(f"échec TLS pour Authorization: Basic {API_KEY_SID}:{API_KEY_SECRET}"))
    iris = ligne(coffre, horloge, http)
    with pytest.raises(EnvoiEchoue) as capture:
        iris.executer(accord_oui(iris, iris.preparer_sms(NUMERO, "Un mot.")))
    assert API_KEY_SECRET not in str(capture.value) and "•••" in str(capture.value)
    assert API_KEY_SECRET not in caplog.text


# --------------------------------------------------------------------------- appel sortant réel
def test_un_appel_part_par_lapi_calls_et_dit_le_message_approuve(coffre, horloge):
    http = FauxHTTP(corps={"sid": "CA00000000000000000000000000000000", "status": "queued"})
    iris = ligne(coffre, horloge, http)
    resultat = asyncio.run(iris.appeler_apres_accord("819 524-2804", _oui, message="Rappelle-moi & vite <stp>"))
    assert len(http.appels) == 1
    envoi = http.appels[0]
    assert ACCOUNT_SID in envoi["url"] and envoi["url"].endswith("/Calls.json")
    assert envoi["donnees"]["To"] == NUMERO and envoi["donnees"]["From"] == NUMERO_LIGNE
    assert "Twiml" in envoi["donnees"] and "<Say" in envoi["donnees"]["Twiml"]
    assert "&amp;" in envoi["donnees"]["Twiml"] and "&lt;stp&gt;" in envoi["donnees"]["Twiml"]
    assert resultat["envoye"] is True and resultat["genre"] == "appel"


def test_un_appel_sans_message_dit_une_phrase_par_defaut(coffre, horloge):
    http = FauxHTTP(corps={"sid": "CA0", "status": "queued"})
    iris = ligne(coffre, horloge, http)
    iris.executer(accord_oui(iris, iris.preparer_appel(NUMERO)))
    assert twilio_ligne.MESSAGE_APPEL_DEFAUT in http.appels[0]["donnees"]["Twiml"]


def test_la_confirmation_dun_appel_montre_le_texte_qui_sera_dit(coffre, horloge):
    """On approuve ce qu'IRIS dira, pas seulement un numéro : le texte doit être sous les yeux."""
    iris = ligne(coffre, horloge, reseau_interdit)
    vus: dict = {}

    async def confirmer(titre: str, detail: str) -> bool:
        vus["titre"], vus["detail"] = titre, detail
        return False

    asyncio.run(iris.appeler_apres_accord(NUMERO, confirmer, message="Le rendez-vous est déplacé à 15 h."))
    assert "819 524-2804" in vus["titre"]
    assert "Le rendez-vous est déplacé à 15 h." in vus["detail"]


@pytest.mark.parametrize("interdit", ["911", "1-900-555-1212", "+8701234567"])
def test_les_numeros_durgence_et_surtaxes_restent_refuses_sur_la_ligne(coffre, horloge, interdit):
    iris = ligne(coffre, horloge, reseau_interdit)
    with pytest.raises(NumeroInvalide):
        iris.preparer_appel(interdit, "peu importe")


# --------------------------------------------------------------------------- dégradation propre
def test_une_ligne_incomplete_le_dit_en_francais_sans_planter(coffre, horloge):
    iris = ligne(coffre, horloge, reseau_interdit, config_ligne=twilio_ligne.ConfigLigne(api_key_sid=API_KEY_SID))
    assert iris.configure is False
    with pytest.raises(TelephonieNonConfiguree) as capture:
        iris.preparer_sms(NUMERO, "Un mot.")
    texte = str(capture.value)
    assert "manque" in texte and "Account SID" in texte and "numéro" in texte
    assert "sur ton téléphone" in texte, "un refus doit proposer ce qui marche encore"
    etat = iris.etat()
    assert etat["configure"] is False and etat["manquant"] and etat["secret"] == ""


def test_le_mode_local_interdit_la_ligne_twilio(coffre, horloge):
    iris = ligne(coffre, horloge, reseau_interdit, local_only=True)
    assert iris.configure is False
    with pytest.raises(ModeLocalActif, match="mode local"):
        iris.preparer_sms(NUMERO, "Un mot.")


def test_letat_de_la_ligne_ne_contient_jamais_le_secret(coffre, horloge):
    iris = ligne(coffre, horloge, FauxHTTP())
    etat = iris.etat()
    assert API_KEY_SECRET not in str(etat) and AUTH_TOKEN not in str(etat)
    assert etat["configure"] is True and etat["peut_appeler"] is True
    assert etat["numero_ligne"] == NUMERO_LIGNE and etat["secret"] == "présent"


# --------------------------------------------------------------------------- câblage des outils
def test_les_outils_sms_et_appel_sont_bien_dans_tool_specs():
    """Leçon chère du projet : un outil non offert au modèle ne sert à rien. On le vérifie."""
    from iris.tools import ToolContext, tool_specs

    ctx = ToolContext(
        settings=SimpleNamespace(user=SimpleNamespace(confirm_commands="dangerous", computer_use=True)),
        consent=None, capture=None, memory=None, agent="test",
        confirm=lambda _t, _d: asyncio.sleep(0, result=True),
    )
    noms = [s.name for s in tool_specs(ctx)]
    assert "envoyer_sms" in noms and "passer_un_appel" in noms


# --------------------------------------------------------------------------- webhooks entrants
async def _oui(_titre: str, _detail: str) -> bool:  # utilisé par appeler_apres_accord
    return True


def _app_webhooks(coffre, *, config_ligne: twilio_ligne.ConfigLigne) -> tuple[TestClient, FauxRegistre, FauxHub]:
    from iris.routes_twilio import creer_routeur_twilio

    registre, hub = FauxRegistre(), FauxHub()
    tele = Telephoniste(FauxSettings(telephonie=ReglagesBruts()), coffre, client_http=reseau_interdit,
                        registre=registre, hub=hub, config_ligne=config_ligne)
    ctx = SimpleNamespace(telephonie=tele, consent=registre, hub=hub)
    app = FastAPI()
    app.include_router(creer_routeur_twilio(ctx))
    return TestClient(app), registre, hub


def test_un_sms_entrant_signe_est_recu_prevenu_et_jamais_repondu_seul(coffre):
    c = config(auth_token=AUTH_TOKEN, base_publique="http://testserver")
    client, registre, hub = _app_webhooks(coffre, config_ligne=c)
    url = "http://testserver/twilio/entrant/sms"
    params = {"From": NUMERO, "To": NUMERO_LIGNE, "Body": "Mon code est 4712", "MessageSid": "SM123"}
    reponse = client.post("/twilio/entrant/sms", data=params, headers={"X-Twilio-Signature": _signer(AUTH_TOKEN, url, params)})
    assert reponse.status_code == 200
    assert reponse.text == twilio_ligne.twiml_vide(), "aucune réponse automatique : ce serait un envoi sans accord"
    # Le contenu va au bureau (hub) pour être LU, jamais au registre de transparence.
    assert hub.publications and hub.publications[0][0] == "telephone.sms_entrant"
    assert hub.publications[0][1]["corps"] == "Mon code est 4712"
    assert registre.evenements == ["telephonie_sms_recu"]
    assert "4712" not in registre.entrees[0][2], "le contenu d'un SMS n'a rien à faire dans le registre"


def test_une_signature_absente_ou_fausse_est_refusee(coffre):
    c = config(auth_token=AUTH_TOKEN, base_publique="http://testserver")
    client, _registre, _hub = _app_webhooks(coffre, config_ligne=c)
    params = {"From": NUMERO, "To": NUMERO_LIGNE, "Body": "Salut"}
    assert client.post("/twilio/entrant/sms", data=params).status_code == 403
    assert client.post("/twilio/entrant/sms", data=params,
                       headers={"X-Twilio-Signature": "faux"}).status_code == 403


def test_sans_auth_token_lentrant_echoue_ferme_plutot_que_de_faire_confiance(coffre):
    c = config(base_publique="http://testserver")  # pas d'auth_token
    client, _registre, _hub = _app_webhooks(coffre, config_ligne=c)
    params = {"From": NUMERO, "To": NUMERO_LIGNE, "Body": "Salut"}
    reponse = client.post("/twilio/entrant/sms", data=params, headers={"X-Twilio-Signature": "peu importe"})
    assert reponse.status_code == 503 and "TWILIO_AUTH_TOKEN" in reponse.json()["detail"]


def test_un_appel_entrant_signe_recoit_un_accueil_et_raccroche(coffre):
    c = config(auth_token=AUTH_TOKEN, base_publique="http://testserver")
    client, _registre, hub = _app_webhooks(coffre, config_ligne=c)
    url = "http://testserver/twilio/entrant/appel"
    params = {"From": NUMERO, "To": NUMERO_LIGNE, "CallSid": "CA123"}
    reponse = client.post("/twilio/entrant/appel", data=params, headers={"X-Twilio-Signature": _signer(AUTH_TOKEN, url, params)})
    assert reponse.status_code == 200 and "<Say" in reponse.text and "<Hangup/>" in reponse.text
    assert hub.publications[0][0] == "telephone.appel_entrant"
