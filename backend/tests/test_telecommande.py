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
