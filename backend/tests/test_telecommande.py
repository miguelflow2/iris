"""La télécommande côté ordinateur : exécute une commande distante par toute la boucle d'IRIS,
renvoie le résultat, et fait remonter les demandes d'accord au téléphone.

On teste la LOGIQUE sans réseau : le WebSocket est remplacé par un enregistreur d'envois, et le
ChatService par une doublure. Ce qui compte : une commande produit un résultat ; une demande de
confirmation est relayée ; la réponse d'accord est bien résolue ; et l'opt-in (désactivé par
défaut) tient.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

from iris.telecommande import Telecommande


class FauxChat:
    def __init__(self, reponse="C'est fait.", declenche_confirm=False):
        self.reponse = reponse
        self.declenche_confirm = declenche_confirm
        self.sink = None
        self.resolus: list[tuple[str, bool]] = []
        self._n = 0

    def set_sink_confirm_distant(self, cb):
        self.sink = cb

    def create_conversation(self, title=None, agent="auto", kind="chat"):
        self._n += 1
        return {"id": f"conv{self._n}"}

    async def run_and_wait(self, conv_id, texte, agent="auto", source="text", speak=None):
        assert source == "distant", "une commande distante doit passer par la source 'distant'"
        if self.declenche_confirm and self.sink:
            self.sink(conv_id, "cid-1", "Envoyer le courriel ?", "À: a@b.c")  # simule un acte sensible
        return {"message": {"text": self.reponse}}

    def resolve_confirm(self, confirm_id, approved):
        self.resolus.append((confirm_id, approved))


def _settings(relay="https://relais.exemple/", local_only=False, telecommande=True, data_dir="/dossier/inexistant"):
    s = SimpleNamespace(user=SimpleNamespace(
        relay_server=relay, local_only=local_only, telecommande=telecommande,
    ))
    s.data_dir = data_dir
    return s


def _tc(chat, settings=None, jeton="jeton-appareil"):
    return Telecommande(chat, settings or _settings(), obtenir_jeton=lambda: jeton)


def test_url_http_devient_ws():
    tc = _tc(FauxChat())
    assert tc.url() == "wss://relais.exemple/appareil/ws"
    tc2 = _tc(FauxChat(), _settings(relay="http://127.0.0.1:8100"))
    assert tc2.url() == "ws://127.0.0.1:8100/appareil/ws"
    assert _tc(FauxChat(), _settings(relay="")).url() == ""


def test_opt_in_desactive_par_defaut():
    assert _tc(FauxChat(), _settings(telecommande=False)).actif() is False   # coupé par défaut
    assert _tc(FauxChat(), _settings(local_only=True)).actif() is False       # mode 100 % local
    assert _tc(FauxChat(), jeton="").actif() is False                         # pas de jeton
    assert _tc(FauxChat(), _settings(relay="")).actif() is False              # pas de relais
    assert _tc(FauxChat()).actif() is True                                    # tout réuni


def test_une_commande_renvoie_un_resultat():
    envois = []

    async def scenario():
        tc = _tc(FauxChat(reponse="Bloc-notes ouvert."))

        async def rec(m):
            envois.append(m)

        tc._envoyer = rec
        await tc._executer("r1", "ouvre le bloc-notes")

    asyncio.run(scenario())
    res = [m for m in envois if m["type"] == "resultat"]
    assert res and res[0]["req_id"] == "r1" and res[0]["reponse"] == "Bloc-notes ouvert."


def test_une_confirmation_remonte_au_telephone():
    envois = []

    async def scenario():
        tc = _tc(FauxChat(declenche_confirm=True))

        async def rec(m):
            envois.append(m)

        tc._envoyer = rec
        await tc._executer("r2", "envoie un courriel à a@b.c")
        await asyncio.sleep(0)  # laisser la tâche d'envoi du confirm s'exécuter

    asyncio.run(scenario())
    types = [m["type"] for m in envois]
    assert "confirm" in types, "l'acte sensible doit demander l'accord au téléphone"
    assert "resultat" in types
    conf = [m for m in envois if m["type"] == "confirm"][0]
    assert conf["req_id"] == "r2" and conf["confirm_id"] == "cid-1"


def test_reponse_daccord_est_resolue():
    chat = FauxChat()
    tc = _tc(chat)
    asyncio.run(tc._traiter({"type": "confirm_reponse", "confirm_id": "cid-1", "approved": True}))
    assert chat.resolus == [("cid-1", True)]


def test_confirm_sans_requete_connue_ne_plante_pas():
    # un confirm pour une conversation qu'on ne suit pas : ignoré silencieusement, aucun envoi
    tc = _tc(FauxChat())
    tc._on_confirm("conv-inconnue", "c", "t", "d")  # ne doit pas lever


def test_code_dappairage_stable_et_persistant(tmp_path):
    s = _settings(data_dir=str(tmp_path))
    tc = Telecommande(FauxChat(), s, obtenir_jeton=lambda: "jeton")
    code = tc.pairing()
    assert code and tc.pairing() == code  # stable dans la même instance
    assert (tmp_path / "telecommande-pairing").read_text(encoding="utf-8").strip() == code  # écrit sur le disque
    # une nouvelle instance (redémarrage) relit le MÊME code
    tc2 = Telecommande(FauxChat(), s, obtenir_jeton=lambda: "jeton")
    assert tc2.pairing() == code


# --------------------------------------------------------------------------- liaison et preuve (constat du 2026-09-14)
def _jeton_de(courriel: str) -> str:
    """Même forme que les jetons du relais : courriel.machine.échéance.signature (base64 URL)."""
    import base64

    b64 = base64.urlsafe_b64encode(courriel.encode()).decode().rstrip("=")
    return f"{b64}.bWFjaGluZQ.9999999999.signature"


class FauxWs:
    def __init__(self, reponses: list[dict]):
        self.reponses = list(reponses)
        self.envoyes: list[dict] = []

    async def send(self, texte):
        import json

        self.envoyes.append(json.loads(texte))

    async def recv(self):
        import json

        return json.dumps(self.reponses.pop(0))


def test_la_poignee_de_main_prouve_la_cle_et_publie_le_sel(tmp_path):
    import hashlib
    import hmac

    from iris.telecommande import _b64

    tc = _tc(FauxChat(), _settings(data_dir=str(tmp_path)), jeton=_jeton_de("Proprio@Vela.ca"))
    tc.verrou = SimpleNamespace(infos_preuve=lambda: {"sel": "c2VsLWR1LWNvZGUtZGUtc2Vjb3Vycw", "iterations": 240000})
    ws = FauxWs([{"type": "defi", "nonce": "nonce-du-relais"}, {"type": "pret", "prouve": True, "liaison": "confirmee"}])
    asyncio.run(tc._poignee_de_main(ws, "jeton", "appairage"))
    hello, preuve = ws.envoyes
    assert hello == {"type": "hello", "jeton": "jeton", "pairing": "appairage", "preuve": 1}
    attendue = hmac.new(tc.cle(), b"vela-appareil-ws|v1|proprio@vela.ca|nonce-du-relais", hashlib.sha256).digest()
    assert preuve["type"] == "preuve" and preuve["preuve"] == _b64(attendue), "courriel du jeton, en minuscules"
    assert preuve["verrou"]["iterations"] == 240000 and "code" not in str(preuve)
    assert tc.liaison["etat"] == "confirmee"
    # La clé est créée une fois et relue : la liaison survit au redémarrage.
    assert (tmp_path / "telecommande-cle").is_file()
    assert _tc(FauxChat(), _settings(data_dir=str(tmp_path))).cle() == tc.cle()


def test_un_refus_de_liaison_est_dit_et_espace_les_essais(tmp_path):
    import pytest

    from iris.telecommande import RefusLiaison

    tc = _tc(FauxChat(), _settings(data_dir=str(tmp_path)))
    ws = FauxWs([{"type": "defi", "nonce": "n"}, {"type": "refus", "message": "Un autre ordinateur est lié à ce compte."}])
    with pytest.raises(RefusLiaison):
        asyncio.run(tc._poignee_de_main(ws, "jeton", "appairage"))
    assert tc.liaison == {"etat": "autre_ordinateur", "message": "Un autre ordinateur est lié à ce compte."}
    # Un ancien relais qui répond « pret » directement reste accepté (télécommande seulement).
    ancien = FauxWs([{"type": "pret"}])
    assert asyncio.run(tc._poignee_de_main(ancien, "jeton", "appairage")) == {"type": "pret"}


def test_preuve_horodatee_pour_le_partage(tmp_path):
    import hashlib
    import hmac

    from iris.telecommande import _b64

    tc = _tc(FauxChat(), _settings(data_dir=str(tmp_path)), jeton=_jeton_de("a@vela.ca"))
    p = tc.preuve_horodatee("vela-partage-creer")
    message = f"vela-partage-creer|v1|a@vela.ca|{p['horodatage']}".encode()
    assert p["preuve"] == _b64(hmac.new(tc.cle(), message, hashlib.sha256).digest())


def test_mode_local_garde_seulement_le_canal_du_verrouillage():
    """Constat du 2026-09-14 : passer en 100 % local coupait le verrouillage à distance. Le canal reste, pour
    le verrou seulement ; aucune commande du téléphone n'est acceptée."""
    reglages = _settings(local_only=True, telecommande=True)
    tc = _tc(FauxChat(), reglages)
    assert tc.actif() is False, "sans verrouillage à distance, le mode local ferme tout"
    tc.verrou = SimpleNamespace(distant_actif=True, verrouille=False)
    assert tc.actif() is True and tc.pilotage_permis() is False
    envois: list[dict] = []

    async def enregistrer(message):
        envois.append(message)

    tc._envoyer = enregistrer

    async def scenario():
        await tc._traiter({"type": "commande", "req_id": "c1", "texte": "ouvre le navigateur"})
        await asyncio.sleep(0.02)

    asyncio.run(scenario())
    assert "désactivée" in envois[0]["reponse"]


def test_la_demande_de_liaison_est_envoyee_puis_espacee(tmp_path, monkeypatch):
    import httpx

    appels: list[dict] = []

    class Reponse:
        status_code = 202
        headers = {"content-type": "application/json"}

        def json(self):
            return {"etat": "en_attente", "message": "Un courriel de confirmation a été envoyé."}

    class Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, json=None):
            appels.append({"url": url, **json})
            return Reponse()

    monkeypatch.setattr(httpx, "AsyncClient", Client)
    tc = _tc(FauxChat(), _settings(data_dir=str(tmp_path)))
    etat = asyncio.run(tc.demander_liaison())
    assert etat["etat"] == "en_attente" and "courriel" in etat["message"]
    assert appels[0]["url"] == "https://relais.exemple/api/appareil/liaison" and len(appels[0]["cle"]) == 43
    # Le code à recopier sur la page de confirmation est calculé ici, depuis la clé de cet ordinateur.
    import base64 as _base64
    import hashlib as _hashlib

    attendu = _base64.b32encode(_hashlib.sha256(tc.cle()).digest()).decode()[:6]
    assert tc.empreinte() == attendu
    asyncio.run(tc.demander_liaison())
    assert len(appels) == 1, "pas une demande (donc un courriel) toutes les 5 secondes"
