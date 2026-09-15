"""Réparations du 2026-09-14 (groupe service-b), reprises des sondes du contre-vérificateur.

1. Le jeton d'appareil « vela » garde ouvert le canal du verrouillage à distance (Telecommande.actif) : le retirer
   ou le remplacer sans mot de passe coupait ce canal pendant que l'écran l'annonçait toujours actif.
2. Une phrase transcrite par le téléphone (POST /api/voix/commande) n'a aucun audio : le verrou vocal ne l'a jamais
   vérifiée. Elle ne doit pas terminer le mode invité, même quand un vérificateur de locuteur est installé.
"""
import asyncio

import pytest

MDP = "motdepasse-proprietaire"
JETON = "p@vela.ca.machine.9999999999.sig"


@pytest.fixture(autouse=True)
def rapide(monkeypatch):
    monkeypatch.setattr("iris.comptes.ITERATIONS", 2_000)
    monkeypatch.setattr("iris.verrou.SCRYPT", {"n": 2 ** 10, "r": 8, "p": 1})
    monkeypatch.setattr("iris.verrou.PREUVE_ITERATIONS", 2_000)


def _monter_verrou_distant(ctx, actif: bool = True) -> None:
    ctx.comptes.creer(MDP, "Miguel")
    ctx.settings.update({"relay_server": "https://relais.velaglass.ca", "licence_email": "p@vela.ca"})
    ctx.secrets.set_api_key("vela", JETON)
    if actif:
        ctx.verrou.definir_distant(True)
        assert ctx.telecommande.actif() is True, "montage : canal du verrou ouvert"


# ---------------------------------------------------------------------- 1. jeton d'appareil « vela »
@pytest.mark.parametrize("voie", ["delete", "put_vide", "put_autre"])
def test_retirer_ou_remplacer_le_jeton_vela_exige_le_mot_de_passe(client, app, voie):
    ctx = app.state.ctx
    _monter_verrou_distant(ctx)

    def appeler(mot_de_passe=None):
        corps = {} if mot_de_passe is None else {"mot_de_passe": mot_de_passe}
        if voie == "delete":
            return client.request("DELETE", "/api/agents/vela/key", json=corps or None)
        cle = "" if voie == "put_vide" else "autre.jeton.bidon"
        return client.put("/api/agents/vela", json={"api_key": cle, **corps})

    for essai in (None, "mauvais-mot-de-passe"):
        r = appeler(essai)
        assert r.status_code == 403, r.text
        assert "verrouillage à distance est actif" in r.json()["detail"]
        assert ctx.secrets.get_api_key("vela") == JETON, "le jeton reste en place"
        assert ctx.verrou.distant_actif and ctx.telecommande.actif() is True, "le canal du verrou reste ouvert"
    assert any(e["event_type"] == "reglage_protege_refuse" for e in ctx.consent.events(limit=20))

    r = appeler(MDP)
    assert r.status_code == 200, r.text
    assert r.json()["name"] == "vela" and "mot_de_passe" not in r.json()
    attendu = None if voie != "put_autre" else "autre.jeton.bidon"
    assert ctx.secrets.get_api_key("vela") == attendu


def test_mode_local_puis_retrait_du_jeton_reste_refuse(client, app):
    """La suite « PATCH local_only » puis « DELETE jeton » coupait le verrou durablement (assurer_acces_vela sort en
    mode local et ne réobtient jamais le jeton)."""
    ctx = app.state.ctx
    _monter_verrou_distant(ctx)
    assert client.patch("/api/settings", json={"local_only": True}).status_code == 200
    assert ctx.telecommande.actif() is True, "mode local : canal « verrouillage seulement » ouvert"
    assert client.delete("/api/agents/vela/key").status_code == 403
    assert client.put("/api/agents/vela", json={"api_key": ""}).status_code == 403
    assert ctx.secrets.get_api_key("vela") == JETON and ctx.telecommande.actif() is True


def test_jeton_vela_libre_quand_rien_ne_le_protege(client, app):
    ctx = app.state.ctx
    _monter_verrou_distant(ctx, actif=False)
    # Même valeur réécrite, autres réglages du moteur : rien n'est coupé.
    ctx.verrou.definir_distant(True)
    assert client.put("/api/agents/vela", json={"api_key": JETON}).status_code == 200
    assert client.put("/api/agents/vela", json={"active": True}).status_code == 200
    # Les autres moteurs ne portent pas le canal du verrou.
    ctx.secrets.set_api_key("openrouter", "sk-test-1234567890")
    assert client.delete("/api/agents/openrouter/key").status_code == 200
    # Verrouillage à distance éteint (avec le mot de passe) : le jeton se retire librement.
    ctx.verrou.definir_distant(False, MDP)
    assert client.delete("/api/agents/vela/key").status_code == 200
    assert ctx.secrets.get_api_key("vela") is None


# ---------------------------------------------------------------------- 2. mode invité et voix du téléphone
@pytest.fixture()
def sans_lunettes_exigees(monkeypatch):
    from iris.lunettes_presence import PresenceLunettes

    monkeypatch.setattr(PresenceLunettes, "exiger", lambda self, fonction: None)


def test_fin_du_mode_invite_par_le_telephone_refusee_meme_avec_verrou_vocal(client, app, sans_lunettes_exigees):
    ctx = app.state.ctx
    ctx.mode_invite.activer(origine="ecran")
    r = client.post("/api/voix/commande", json={"texte": "fin du mode invité", "source": "iphone"})
    assert r.status_code == 200 and r.json()["texte"].startswith("Je ne peux pas savoir qui me parle")
    assert ctx.mode_invite.actif

    appels = []
    ctx.voice.verificateur_locuteur = lambda pcm: (appels.append(len(pcm)) or (False, "voix inconnue"))
    try:
        for phrase in ("fin du mode invité", "Iris, sors du mode invité s'il te plaît"):
            r = client.post("/api/voix/commande", json={"texte": phrase, "source": "iphone"})
            assert r.status_code == 200, r.text
            assert r.json()["texte"].startswith("Je ne peux pas savoir qui me parle"), r.json()
            assert r.json()["intercepte"] is True
            assert ctx.mode_invite.actif, "une phrase venue du téléphone, jamais vérifiée, ne sort pas du mode"
        assert ctx.memory.suspendue == "invite"
        assert any(e["event_type"] == "mode_invite_sortie_vocale_refusee" for e in ctx.consent.events(limit=10))
    finally:
        ctx.voice.verificateur_locuteur = None
        ctx.mode_invite.desactiver()


def test_interception_lit_lorigine_de_la_commande(client, app, monkeypatch):
    """Sans passer par le filet de la route : l'interception elle-même refuse une origine « voix_telephone »,
    et accepte le micro de l'ordinateur quand le verrou vocal y est installé."""
    from iris.voice.listener import ORIGINE_COMMANDE, ORIGINE_MICRO_PC, ORIGINE_VOIX_TELEPHONE

    ctx = app.state.ctx
    monkeypatch.setattr(ctx.voice, "verificateur_locuteur", lambda pcm: (True, ""), raising=False)
    ctx.mode_invite.activer(origine="ecran")
    try:
        refus = ctx.voice._intercepter("fin du mode invité", ORIGINE_VOIX_TELEPHONE)
        assert refus.startswith("Je ne peux pas savoir qui me parle") and ctx.mode_invite.actif
        assert ORIGINE_COMMANDE.get() == ORIGINE_MICRO_PC, "l'origine est rétablie après l'interception"
        # L'activation par le téléphone reste possible, mais elle ne promet pas une sortie à la voix.
        ctx.mode_invite.desactiver()
        activation = ctx.voice._intercepter("mode invité", ORIGINE_VOIX_TELEPHONE)
        assert "utilisez l'application" in activation and ctx.mode_invite.actif
        # Micro de l'ordinateur, audio admis par le verrou vocal : la sortie vocale est acceptée.
        assert ctx.voice._intercepter("fin du mode invité", ORIGINE_MICRO_PC).startswith("Mode invité terminé")
        assert not ctx.mode_invite.actif
    finally:
        if ctx.mode_invite.actif:
            ctx.mode_invite.desactiver()


def test_origine_transmise_aux_interceptions_asynchrones(app):
    """Les interceptions async tournent sur la boucle du service (autre fil, autre contexte) : l'origine doit les
    suivre, sinon elles croiraient à tort la phrase venue du micro de l'ordinateur."""
    import threading

    from iris.voice.listener import ORIGINE_COMMANDE, ORIGINE_VOIX_TELEPHONE

    voice = app.state.ctx.voice
    vues: list[str] = []

    async def espionne(texte: str):
        vues.append(ORIGINE_COMMANDE.get())
        return None

    boucle = asyncio.new_event_loop()
    fil = threading.Thread(target=boucle.run_forever, daemon=True)
    fil.start()
    ancienne = voice.loop
    voice.loop = boucle
    voice.ajouter_interception("test-origine", espionne, priorite=1)
    try:
        voice._intercepter("bonjour", ORIGINE_VOIX_TELEPHONE)
        voice._intercepter("bonjour")
    finally:
        voice.retirer_interception("test-origine")
        voice.loop = ancienne
        boucle.call_soon_threadsafe(boucle.stop)
        fil.join(timeout=2)
        boucle.close()
    assert vues == ["voix_telephone", "micro_pc"]
