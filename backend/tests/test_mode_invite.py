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


def test_phrases_vocales_interceptees(app, monkeypatch):
    ctx = app.state.ctx
    mode = ctx.mode_invite
    # Verrou vocal installé : la commande qui arrive a été admise comme la voix du propriétaire.
    monkeypatch.setattr(ctx.voice, "verificateur_locuteur", lambda pcm: (True, ""), raising=False)
    assert mode.interception("ouvre youtube") is None
    assert mode.interception("c'est quoi le mode invité") is None, "une question ne déclenche rien"
    assert mode.interception("fin du mode invité") == "Le mode invité n'est pas actif."
    reponse = mode.interception("Active le mode invité")
    assert reponse.startswith("Mode invité activé jusqu'à") and mode.actif
    assert "fin du mode invité" in reponse
    assert mode.interception("mode invité").startswith("Le mode invité est déjà actif")
    assert mode.interception("Désactive le mode invité, s'il te plaît").startswith("Mode invité terminé")
    assert not mode.actif
    assert mode.interception("mode invité") and mode.actif
    assert mode.interception("fin du mode invité") and not mode.actif


def test_sans_verrou_vocal_linvite_ne_peut_pas_sortir_du_mode_a_la_voix(app, monkeypatch):
    """Constat du 2026-09-14 : l'invité qui porte les lunettes disait « fin du mode invité », puis demandait
    « qu'est-ce que tu sais sur moi ? » et recevait les souvenirs du propriétaire."""
    ctx = app.state.ctx
    mode = ctx.mode_invite
    monkeypatch.setattr(ctx.voice, "verificateur_locuteur", None, raising=False)
    activation = mode.interception("mode invité")
    assert mode.actif and "utilisez l'application" in activation and "qui me parle" in activation
    refus = mode.interception("fin du mode invité")
    assert "depuis l'application" in refus and mode.jusqua and mode.actif, "le mode reste actif"
    assert ctx.memory.suspendue == "invite"
    assert any(e["event_type"] == "mode_invite_sortie_vocale_refusee" for e in ctx.consent.events(limit=10))
    assert "sans verrou vocal" in mode.etat()["limite"]
    # L'application (route /desactiver) et la minuterie restent les chemins de sortie.
    assert mode.desactiver()["actif"] is False and ctx.memory.suspendue is None
    concis = ctx.settings.update({"verbosite": "concis"})
    assert concis.verbosite == "concis"
    mode.interception("mode invité")
    assert mode.interception("sors du mode invité").startswith("Je ne peux pas savoir qui me parle")
    mode.desactiver()
    ctx.settings.update({"verbosite": "normal"})


def test_interception_branchee_en_priorite_10_et_suivi_du_hub(client, app, monkeypatch):
    ctx = app.state.ctx
    monkeypatch.setattr(ctx.voice, "verificateur_locuteur", lambda pcm: (True, ""), raising=False)
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


def test_en_mode_invite_les_outils_ne_lisent_ni_souvenirs_ni_journal(app):
    """Constat du 2026-09-14 : « où j'ai posé » était gardé, mais la recherche dans les souvenirs et le résumé de
    journée (qui relit le journal d'écoute) restaient ouverts à qui porte les lunettes."""
    import asyncio

    from iris.tools import MODE_INVITE_DONNEES, ToolContext, make_tool_runner

    ctx = app.state.ctx
    ctx.memory.add("Le parapluie rouge est rangé dans le garage", source="user", kind="fact")
    appels: list[str] = []

    class FauxResume:
        async def resumer(self, jour=None):
            appels.append("resumer")
            return {"texte": "journal du propriétaire"}

    ctx.resume_quotidien = FauxResume().resumer
    outil = ToolContext(settings=ctx.settings, consent=ctx.consent, capture=ctx.capture, memory=ctx.memory,
                        agent="test", confirm=None, app=ctx)
    runner = make_tool_runner(outil)
    avant = asyncio.run(runner("search_memory", {"query": "parapluie garage"}))
    assert "garage" in avant, "hors mode invité, la recherche marche"
    ctx.mode_invite.activer(minutes=30)
    try:
        pendant = asyncio.run(runner("search_memory", {"query": "parapluie garage"}))
        assert "garage" not in pendant and MODE_INVITE_DONNEES in pendant
        ctx.presence_lunettes.exiger = lambda fonction: None
        resume = asyncio.run(runner("resume_journee", {}))
        assert MODE_INVITE_DONNEES in str(resume) and appels == []
    finally:
        ctx.mode_invite.desactiver(origine="test")


def _souffle_unique_en_ligne(ctx, monkeypatch, phrase: str, admis: bool):
    """Micro du PC, reconnaissance en ligne : mot d'activation et commande dans le même segment (_wake_cycle)."""
    from iris.lunettes_presence import PresenceLunettes

    monkeypatch.setattr(PresenceLunettes, "exiger", lambda self, fonction: None)
    voix = ctx.voice
    appels: list[int] = []
    voix.verificateur_locuteur = lambda pcm: (appels.append(len(pcm)) or (admis, "" if admis else "voix inconnue"))
    wake = ctx.settings.user.wake_word
    monkeypatch.setattr(voix, "engine", "google", raising=False)
    monkeypatch.setattr(voix, "_capture_segment", lambda *a, **k: b"\x01\x00" * 16000)
    monkeypatch.setattr(voix, "_cloud_recognize", lambda seg: f"{wake} {phrase}")
    monkeypatch.setattr(voix, "_traduire_si_demande", lambda: False)
    dits: list[str] = []
    monkeypatch.setattr(voix, "_say", lambda texte, **k: dits.append(texte))
    voix._wake_cycle()
    return appels, dits


def test_une_voix_refusee_ne_sort_pas_du_mode_invite_dun_seul_souffle_en_ligne(app, monkeypatch):
    """Finition du 2026-09-14 : en reconnaissance en ligne, « Dis-moi Iris fin du mode invité » dit d'un souffle
    allait à _process sans passer par le verrou vocal ; l'origine « micro_pc » faisait croire la voix vérifiée."""
    ctx = app.state.ctx
    ctx.mode_invite.activer(origine="ecran")
    try:
        appels, dits = _souffle_unique_en_ligne(ctx, monkeypatch, "fin du mode invité", admis=False)
        assert appels, "le verrou vocal n'a pas été consulté"
        assert ctx.mode_invite.actif and ctx.memory.suspendue == "invite", "voix refusée, mode invité terminé"
        assert dits == []
    finally:
        ctx.mode_invite.desactiver()


def test_une_commande_dun_seul_souffle_en_ligne_passe_par_le_verrou_vocal(app, monkeypatch):
    ctx = app.state.ctx
    traitees: list[str] = []
    monkeypatch.setattr(ctx.voice, "_process", lambda texte, depth=0: traitees.append(texte))
    appels, _dits = _souffle_unique_en_ligne(ctx, monkeypatch, "ouvre youtube", admis=False)
    assert appels and traitees == [], "une voix refusée a fait exécuter une commande"
    appels, _dits = _souffle_unique_en_ligne(ctx, monkeypatch, "ouvre youtube", admis=True)
    assert appels and traitees == ["ouvre youtube"], "la voix du propriétaire doit passer"
