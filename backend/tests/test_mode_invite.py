"""Mode invité (interface I, 2026-09-13) : suspension de la mémoire, minuterie de retour, suppression
des conversations et des messages de la session à la sortie, reprise après redémarrage, phrases vocales
interceptées en priorité 10, routes et événement invite.etat. Aucun micro, aucun réseau.
"""
from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone

import pytest

from iris.memory import MemoireSuspendue
from iris.mode_invite import ModeInvite


def _vieillir(ctx, conv_id: str, minutes: int = 30) -> None:
    """Recule la date d'une conversation et de ses messages : « créés avant le mode invité »."""
    avant = (datetime.now(timezone.utc) - timedelta(minutes=minutes)).isoformat(timespec="seconds")
    ctx.db.execute("UPDATE conversations SET created_at=?, updated_at=? WHERE id=?", (avant, avant, conv_id))
    ctx.db.execute("UPDATE messages SET created_at=? WHERE conversation_id=?", (avant, conv_id))


def test_activer_suspend_la_memoire_et_borne_la_duree(app):
    ctx = app.state.ctx
    mode = ctx.mode_invite
    publies: list[dict] = []
    ctx.hub.publish = lambda type_, **data: publies.append({"type": type_, **data}) or {}
    etat = mode.activer(minutes=100000)
    assert etat["actif"] and ctx.memory.suspendue == "invite"
    duree = datetime.fromisoformat(etat["jusqua"]) - datetime.fromisoformat(etat["depuis"])
    assert duree == timedelta(minutes=720), "au plus 12 heures"
    assert mode.fichier.exists()
    with pytest.raises(MemoireSuspendue):
        ctx.memory.add("le code de l'alarme est 4321")
    assert ctx.memory.capture("Je m'appelle Julie et j'habite à Laval.") == []
    assert publies[-1]["type"] == "invite.etat" and publies[-1]["actif"] is True
    assert mode.activer(minutes=1)["jusqua"]  # 1 minute -> bornée à 5
    fin = datetime.fromisoformat(mode.jusqua) - datetime.now(timezone.utc)
    assert timedelta(minutes=4) < fin <= timedelta(minutes=5)


def test_la_sortie_efface_les_conversations_et_messages_de_la_session_seulement(app):
    ctx = app.state.ctx
    chat = ctx.chat
    ancienne = chat.create_conversation(title="Avant", kind="chat")
    chat._add_message(ancienne["id"], "user", "message du propriétaire, avant le mode")
    vocale = chat.create_conversation(title="Voix", kind="voice")
    chat._add_message(vocale["id"], "user", "commande vocale du propriétaire")
    _vieillir(ctx, ancienne["id"])
    _vieillir(ctx, vocale["id"])

    mode = ctx.mode_invite
    mode.activer(minutes=30)
    invitee = chat.create_conversation(title="Invité", kind="chat")
    chat._add_message(invitee["id"], "user", "question de l'invité")
    mode.noter_conversation(invitee["id"])  # ce que fait le suivi de conversation.created
    chat._add_message(vocale["id"], "user", "l'invité parle dans la conversation vocale existante")

    etat = mode.desactiver()
    assert etat["actif"] is False and ctx.memory.suspendue is None
    assert etat["effacees"] == {"conversations": 1, "messages": 1, "erreurs": 0}
    assert chat.get_conversation(invitee["id"]) is None
    assert chat.get_conversation(ancienne["id"]) is not None
    assert [m["text"] for m in chat.messages(ancienne["id"])] == ["message du propriétaire, avant le mode"]
    assert [m["text"] for m in chat.messages(vocale["id"])] == ["commande vocale du propriétaire"]
    assert not mode.fichier.exists()
    ctx.memory.add("souvenir après le mode invité")  # la mémoire écrit de nouveau


def test_la_minuterie_ramene_a_la_normale(app):
    ctx = app.state.ctx
    mode = ctx.mode_invite
    mode.activer(minutes=5)
    conv = ctx.chat.create_conversation(title="Invité")
    assert mode.verifier_echeance() is False and mode.actif
    assert mode.verifier_echeance(maintenant=time.time() + 6 * 60) is True
    assert not mode.actif and ctx.memory.suspendue is None
    assert ctx.chat.get_conversation(conv["id"]) is None


def test_un_redemarrage_en_plein_mode_invite_ne_rouvre_pas_la_memoire(app):
    ctx = app.state.ctx
    ctx.mode_invite.activer(minutes=60)
    conv = ctx.chat.create_conversation(title="Invité")
    ctx.memory.reprendre("invite")  # simule une mémoire neuve, comme après un redémarrage

    relance = ModeInvite(ctx)
    assert relance.actif and ctx.memory.suspendue == "invite"
    relance._fin = time.time() - 1  # échu pendant que l'ordinateur était éteint
    assert relance.verifier_echeance() is True
    assert ctx.memory.suspendue is None and ctx.chat.get_conversation(conv["id"]) is None


def test_phrases_vocales_interceptees(app):
    mode = app.state.ctx.mode_invite
    assert mode.interception("ouvre youtube") is None
    assert mode.interception("c'est quoi le mode invité") is None, "une question ne déclenche rien"
    assert mode.interception("fin du mode invité") == "Le mode invité n'est pas actif."
    reponse = mode.interception("Active le mode invité")
    assert reponse.startswith("Mode invité activé jusqu'à") and mode.actif
    assert mode.interception("mode invité").startswith("Le mode invité est déjà actif")
    assert mode.interception("Désactive le mode invité, s'il te plaît").startswith("Mode invité terminé")
    assert not mode.actif
    assert mode.interception("mode invité") and mode.actif
    assert mode.interception("fin du mode invité") and not mode.actif


def test_interception_branchee_en_priorite_10_et_suivi_du_hub(client, app):
    ctx = app.state.ctx
    assert any(p == 10 and nom == "confiance-mode-invite" for p, nom, _ in ctx.voice._interceptions)
    # par l'écoute elle-même : la phrase ne va jamais au modèle
    assert ctx.voice._intercepter("passe en mode invité").startswith("Mode invité activé")
    conv = client.post("/api/conversations", json={"title": "Invité"}).json()
    limite = time.monotonic() + 3
    while conv["id"] not in ctx.mode_invite._conversations and time.monotonic() < limite:
        time.sleep(0.02)
    assert conv["id"] in ctx.mode_invite._conversations, "conversation.created suivi sur le hub"
    assert ctx.voice._intercepter("sors du mode invité").startswith("Mode invité terminé")
    assert ctx.chat.get_conversation(conv["id"]) is None


def test_routes_mode_invite(client, app):
    assert client.get("/api/confiance/invite").json()["actif"] is False
    active = client.post("/api/confiance/invite/activer", json={"minutes": 45}).json()
    assert active["actif"] and active["minutes_restantes"] == 45 and "souvenirs existants" in active["limite"]
    assert client.post("/api/memory", json={"text": "à ne pas retenir"}).status_code == 409
    fin = client.post("/api/confiance/invite/desactiver").json()
    assert fin["actif"] is False and "effacees" in fin
    assert client.post("/api/confiance/invite/activer").json()["minutes_restantes"] == app.state.ctx.settings.user.mode_invite_minutes
    client.post("/api/confiance/invite/desactiver")
