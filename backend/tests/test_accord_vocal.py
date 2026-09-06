"""Accord donné à la voix.

Trou trouvé le 5 septembre 2026 : IRIS demandait « je confirme ? » et on ne pouvait répondre qu'en
CLIQUANT. Rien dans l'écoute vocale n'entendait cette demande. Courriel, SMS et import
d'identifiants étaient donc inutilisables sans écran — un comble pour un produit qu'on pilote à la
voix. Ces tests gardent le pont voix<->chat, sans jamais ouvrir un micro.
"""
from __future__ import annotations

import asyncio

import pytest

from iris.voice.accord import interpreter_accord


# --------------------------------------------------------------------------- oui / non
@pytest.mark.parametrize("phrase", [
    "oui", "ouais", "vas-y", "vas y", "d'accord", "c'est bon", "envoie", "envoie le",
    "parfait", "ok", "confirme", "bien sûr", "tout à fait",
])
def test_les_oui_sont_des_oui(phrase):
    assert interpreter_accord(phrase) is True


@pytest.mark.parametrize("phrase", [
    "non", "nan", "annule", "laisse tomber", "surtout pas", "arrête", "stop",
    "n'envoie pas", "n'envoie rien", "pas maintenant", "attends", "oublie ça",
])
def test_les_non_sont_des_non(phrase):
    assert interpreter_accord(phrase) is False


@pytest.mark.parametrize("phrase", ["euh je sais pas", "peut-être", "", "quelle heure est-il", "mmm"])
def test_lambigu_nest_ni_oui_ni_non(phrase):
    """None veut dire « redemande ». On ne devine pas : un courriel ne part pas sur un peut-être."""
    assert interpreter_accord(phrase) is None


def test_un_refus_lemporte_sur_un_mot_positif():
    """« non, envoie pas » contient « envoie » : le refus doit gagner. Sinon un non deviendrait un oui."""
    assert interpreter_accord("non surtout pas") is False
    assert interpreter_accord("n'envoie pas ça") is False


# --------------------------------------------------------------------------- le pont voix <-> chat
def test_une_confirmation_vocale_est_deposee_dans_le_fil(app):
    """Quand la demande vient de la voix, le chat doit passer la question au fil vocal — pas juste
    l'afficher à l'écran et attendre un clic."""
    chat = app.state.ctx.chat
    voix = app.state.ctx.voice
    # Le vrai pont, tel que main.py le monte.
    chat.set_sink_confirm_vocal(voix.file_confirmation_vocale)

    async def scenario():
        fut = asyncio.get_running_loop().create_task(
            chat._confirm("conv", "Envoyer un courriel", "à alex@exemple.com", source="voice"))
        await asyncio.sleep(0.05)
        # La question a bien atterri dans le fil vocal.
        confirm_id, titre, detail = voix._confirmations_vocales.get_nowait()
        assert "courriel" in titre.lower()
        # On répond « oui » comme le ferait le fil vocal après avoir entendu Miguel.
        assert chat.resolve_confirm(confirm_id, True) is True
        return await fut

    assert asyncio.run(scenario()) is True


def test_par_ecrit_rien_nest_depose_dans_le_fil_vocal(app):
    """Une demande écrite garde le chemin écran : elle ne doit pas parler dans les oreilles de
    quelqu'un qui tape."""
    chat = app.state.ctx.chat
    voix = app.state.ctx.voice
    chat.set_sink_confirm_vocal(voix.file_confirmation_vocale)

    async def scenario():
        fut = asyncio.get_running_loop().create_task(
            chat._confirm("conv", "Écrire un fichier", "rapport.txt", source="text"))
        await asyncio.sleep(0.05)
        vide = voix._confirmations_vocales.empty()
        # on résout par l'écran, comme un clic
        cid = next(iter(chat._confirms))
        chat.resolve_confirm(cid, False)
        await fut
        return vide

    assert asyncio.run(scenario()) is True, "une demande écrite ne doit rien mettre dans le fil vocal"


# --------------------------------------------------------------------------- la boucle reste disponible
def test_lattente_pose_la_question_puis_rend_la_reponse(app, monkeypatch):
    """Le cœur du correctif : pendant que la commande attend un accord, le fil vocal doit poser la
    question et résoudre, puis rendre la réponse de la commande — au lieu de se figer."""
    voix = app.state.ctx.voice
    demandes = []
    monkeypatch.setattr(voix, "_demander_accord_vocal", lambda t, d: demandes.append((t, d)) or True)
    resolus = []
    voix._resoudre_confirmation = lambda cid, ok: resolus.append((cid, ok))

    # Un faux futur : pas encore prêt, puis prêt, comme une commande qui se termine.
    class FauxFutur:
        def __init__(self):
            self.tours = 0

        def result(self, timeout=0):
            self.tours += 1
            if self.tours < 3:
                raise _cf_timeout()
            return {"text": "C'est envoyé."}

    import concurrent.futures as _cf

    def _cf_timeout():
        return _cf.TimeoutError()

    # une demande d'accord est en attente
    voix._confirmations_vocales.put(("c1", "Envoyer un SMS", "à Alex"))
    reply = voix._attendre_commande(FauxFutur())

    assert demandes == [("Envoyer un SMS", "à Alex")], "la question doit avoir été posée"
    assert resolus == [("c1", True)], "et la réponse transmise au chat"
    assert reply == {"text": "C'est envoyé."}, "puis la réponse de la commande est rendue"
