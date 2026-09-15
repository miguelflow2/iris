"""« Lunettes d'abord » (décisions de Miguel, 2026-09-13).

IRIS est vendue avec les lunettes VELA : toute fonction qui capte ou agit exige des lunettes
présentes (PC ou téléphone attesté) ; le chat écrit a droit à un aperçu limité ; le mode
démonstration est un accès propriétaire caché ; les réglages qui ouvriraient IRIS sans lunettes ne
se modifient pas depuis l'application.
"""
from __future__ import annotations

import pytest

from iris.lunettes_presence import APERCU_MESSAGES, DUREE_ATTESTATION_S, LunettesRequises, PresenceLunettes


class _Horloge:
    def __init__(self) -> None:
        self.t = 1_000_000.0

    def __call__(self) -> float:
        return self.t


def _sans_lunettes(app, monkeypatch, nom: str = "M01 Pro_F444"):
    ctx = app.state.ctx
    ctx.settings.update({"require_glasses": True, "demo_sans_lunettes": False,
                         "glasses": {"name": nom, "address": "65:A2:9F:5C:F4:44" if nom else "", "auto_connect": False}})
    monkeypatch.setattr(ctx.voice, "lunettes_presentes", lambda: False)
    return ctx


# --------------------------------------------------------------------------- présence
def test_sans_preuve_les_lunettes_sont_absentes_meme_sur_un_pc_neuf(app, monkeypatch):
    ctx = _sans_lunettes(app, monkeypatch, nom="")
    assert ctx.presence_lunettes.presentes() is False, "plus de passe-droit pour un appareil qui n'a jamais eu de lunettes"
    with pytest.raises(LunettesRequises) as refus:
        ctx.presence_lunettes.exiger("decrire")
    assert refus.value.status_code == 428
    assert refus.value.detail["code"] == "lunettes_requises" and refus.value.detail["fonction"] == "decrire"
    assert "velaglass.ca" in refus.value.detail["acheter_url"]


def test_les_trois_preuves(app, monkeypatch):
    ctx = _sans_lunettes(app, monkeypatch)
    presence = ctx.presence_lunettes
    monkeypatch.setattr(ctx.voice, "lunettes_presentes", lambda: True)
    assert presence.source() == "pc"
    monkeypatch.setattr(ctx.voice, "lunettes_presentes", lambda: False)
    presence.attester("M01 Pro_F444", "ABC-123", 80)
    assert presence.source() == "telephone"
    presence.retirer_attestation()
    assert presence.source() is None
    ctx.settings.update({"demo_sans_lunettes": True})
    assert presence.source() == "demo"
    ctx.settings.update({"demo_sans_lunettes": False, "require_glasses": False})
    assert presence.source() == "desactive"


def test_lattestation_du_telephone_expire_et_verifie_les_lunettes(app, monkeypatch):
    ctx = _sans_lunettes(app, monkeypatch)
    horloge = _Horloge()
    presence = PresenceLunettes(ctx.settings, ctx.settings.data_dir, voice=ctx.voice, horloge=horloge)
    presence.attester("M01 Pro_F444", "ABC")
    assert presence.presentes()
    horloge.t += DUREE_ATTESTATION_S + 1
    assert not presence.presentes(), "une attestation ancienne ne prouve plus rien"
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as autre:
        presence.attester("Écouteurs de quelqu'un d'autre", "XYZ")
    assert autre.value.status_code == 403


def test_routes_presence_et_attestation(client, app, monkeypatch):
    _sans_lunettes(app, monkeypatch)
    assert client.get("/api/lunettes/presence").json()["presentes"] is False
    r = client.post("/api/lunettes/attestation", json={"nom": "M01 Pro_F444", "identifiant": "ios-1", "batterie": 55})
    assert r.status_code == 200 and r.json()["presentes"] is True and r.json()["source"] == "telephone"
    assert client.delete("/api/lunettes/attestation").json()["presentes"] is False


# --------------------------------------------------------------------------- aperçu du chat écrit
def test_laperçu_du_chat_ecrit_est_limite_puis_invite_aux_lunettes(app, monkeypatch):
    ctx = _sans_lunettes(app, monkeypatch)
    chat = ctx.chat
    for _ in range(APERCU_MESSAGES):
        assert chat._verrou_lunettes_chat("text") is None
    refus = chat._verrou_lunettes_chat("text")
    assert refus and "lunettes" in refus.lower() and "démonstration" not in refus.lower()
    assert ctx.presence_lunettes.apercu_restant() == 0


def test_la_voix_et_le_telephone_distant_nont_pas_de_passe_droit(app, monkeypatch):
    ctx = _sans_lunettes(app, monkeypatch)
    assert ctx.chat._verrou_lunettes_chat("voice"), "la voix passe par les lunettes"
    assert "lunettes" in ctx.voice.lunettes_requises().lower()
    for fond in ("task", "daily_summary", "veille", "resume"):
        assert ctx.chat._verrou_lunettes_chat(fond) is None, fond
    ctx.presence_lunettes.attester("M01 Pro_F444", "iphone-1")
    assert ctx.chat._verrou_lunettes_chat("voice") is None, "la voix dite dans les lunettes, relayée par le téléphone"
    # Constat du 2026-09-14 : attestées par le téléphone, les lunettes sont dehors. Le micro de l'ordinateur
    # resté à la maison ne s'ouvre pas pour autant.
    refus_micro = ctx.voice.lunettes_requises()
    assert refus_micro and "téléphone" in refus_micro


# --------------------------------------------------------------------------- dehors : le PC n'écoute pas la maison
def test_attestation_du_telephone_et_micro_par_defaut_lecoute_du_pc_reste_off(app, monkeypatch):
    """Constat bloquant du 2026-09-14 : lunettes connectées au téléphone, PC à la maison. Ni le démarrage
    (chien de garde, autodémarrage) ni l'ouverture du flux ne doivent prendre le micro par défaut du PC."""
    from iris.lunettes_presence import LunettesAilleurs

    ctx = _sans_lunettes(app, monkeypatch)
    voice = ctx.voice
    ctx.presence_lunettes.attester("M01 Pro_F444", "iphone-1")
    assert ctx.presence_lunettes.presentes() is True
    assert ctx.presence_lunettes.presentes_pour_capture_pc() is False
    ouvertures: list = []
    monkeypatch.setattr(voice, "_choose_engine", lambda: ouvertures.append("moteur") or "vosk")
    voice.stopped_by_user = False
    etat = voice.start()
    assert etat["state"] == "off" and voice.running is False and ouvertures == []
    assert "téléphone" in (etat["error"] or "")

    class FauxSd:
        @staticmethod
        def query_devices(*args, **kwargs):
            return []

        @staticmethod
        def query_hostapis():
            return []

        @staticmethod
        def RawInputStream(**kwargs):  # noqa: N802 - nom imposé par sounddevice
            ouvertures.append("flux")
            raise AssertionError("le micro par défaut ne doit pas s'ouvrir")

    monkeypatch.setattr("iris.voice.listener.rafraichir_peripheriques", lambda sd: False)
    with pytest.raises(RuntimeError):
        voice._ouvrir_flux_verrouille(FauxSd, forcer_defaut=True)
    assert "flux" not in ouvertures
    with pytest.raises(LunettesAilleurs) as ailleurs:
        ctx.presence_lunettes.exiger_capture_pc("sous_titres")
    assert ailleurs.value.status_code == 409 and "téléphone" in ailleurs.value.detail


def test_routes_de_capture_pc_refusent_dehors_mais_pas_les_donnees_du_telephone(client, app, monkeypatch):
    _sans_lunettes(app, monkeypatch)
    r = client.post("/api/lunettes/attestation", json={"nom": "M01 Pro_F444", "identifiant": "android-1"})
    assert r.status_code == 200 and r.json()["source"] == "telephone"
    try:
        for chemin, corps in (("/api/ecoute/sous-titres/demarrer", None), ("/api/ecoute/enregistrement/demarrer", None),
                              ("/api/alertes/activer", None), ("/api/traduction/ecran", {"langue_cible": "fr"}),
                              ("/api/accessibilite/decrire", {"mode": "scene", "source": "ecran"}),
                              ("/api/glasses/photo", {"reconnaissance": False})):
            refus = client.post(chemin, json=corps) if corps is not None else client.post(chemin)
            assert refus.status_code == 409 and "téléphone" in str(refus.json()["detail"]), (chemin, refus.text)
        # Une photo fournie par le téléphone passe la garde (le service refuse ensuite pour sa propre raison).
        photo = client.post("/api/accessibilite/decrire", json={"mode": "inconnu", "source": "image"})
        assert photo.status_code == 422, photo.text
    finally:
        client.delete("/api/lunettes/attestation")


# --------------------------------------------------------------------------- attestation : association réelle
def test_attestation_sans_paire_connue_de_lordinateur_est_refusee(client, app, monkeypatch):
    """Constat du 2026-09-14 : sans paire mémorisée, n'importe quel nom était accepté — une boucle
    « curl » ouvrait toutes les fonctions à qui n'a pas de lunettes."""
    _sans_lunettes(app, monkeypatch, nom="")
    r = client.post("/api/lunettes/attestation", json={"nom": "x", "identifiant": "y"})
    assert r.status_code == 409 and "Associe d'abord" in r.json()["detail"]
    assert client.get("/api/lunettes/presence").json()["presentes"] is False


def test_attestation_exige_le_nom_exact_et_un_appareil_associe(client, app, monkeypatch):
    _sans_lunettes(app, monkeypatch)
    assert client.post("/api/lunettes/attestation", json={"nom": "M01 Pro_F444"}).status_code == 422, "identifiant exigé"
    # Le premier mot seul (« M01 ») ou un nom qui CONTIENT le nom connu ne suffisent plus.
    for nom in ("M01", "M01 Pro_F444 contrefaçon", "Autres lunettes"):
        assert client.post("/api/lunettes/attestation", json={"nom": nom, "identifiant": "a-1"}).status_code == 403, nom
    assert client.post("/api/lunettes/attestation", json={"nom": "m01  pro_f444", "identifiant": "a-1"}).status_code == 200
    # Un autre appareil n'est pas associé d'office…
    autre = client.post("/api/lunettes/attestation", json={"nom": "M01 Pro_F444", "identifiant": "a-2"})
    assert autre.status_code == 403 and autre.json()["detail"]["code"] == "appareil_non_associe"
    assert "mot de passe" in autre.json()["detail"]["message"]
    # … il s'associe avec le mot de passe du propriétaire.
    client.post("/api/compte", json={"nouveau": "motdepasse-2026", "nom": "Miguel"})
    assert client.post("/api/lunettes/association",
                       json={"nom": "M01 Pro_F444", "identifiant": "a-2", "mot_de_passe": "mauvais"}).status_code == 403
    ok = client.post("/api/lunettes/association",
                     json={"nom": "M01 Pro_F444", "identifiant": "a-2", "mot_de_passe": "motdepasse-2026"})
    assert ok.status_code == 200 and ok.json()["appareils"] == 2
    assert client.post("/api/lunettes/attestation", json={"nom": "M01 Pro_F444", "identifiant": "a-2"}).status_code == 200
    client.delete("/api/lunettes/attestation")


def test_le_retrait_dattestation_dun_autre_appareil_est_ignore(client, app, monkeypatch):
    """Demande de la revue mobile (2026-09-14) : DELETE ?identifiant= ne retire l'attestation que si c'est cet
    appareil qui l'a donnée ; sans paramètre, le comportement d'origine reste."""
    _sans_lunettes(app, monkeypatch)
    assert client.post("/api/lunettes/attestation", json={"nom": "M01 Pro_F444", "identifiant": "a-1"}).status_code == 200
    assert client.delete("/api/lunettes/attestation", params={"identifiant": "a-2"}).json()["presentes"] is True
    assert app.state.ctx.presence_lunettes.source() == "telephone"
    assert client.delete("/api/lunettes/attestation", params={"identifiant": "a-1"}).json()["presentes"] is False
    client.post("/api/lunettes/attestation", json={"nom": "M01 Pro_F444", "identifiant": "a-1"})
    assert client.delete("/api/lunettes/attestation").json()["presentes"] is False


def test_un_nom_de_lunettes_generique_ne_prouve_rien(app, monkeypatch):
    """Constat du 2026-09-14 : glasses.name = « Micro » faisait de tout « Microphone (Realtek) » une preuve."""
    from iris.voice.listener import nom_de_lunettes_distinctif

    voice = app.state.ctx.voice
    voice.glasses_connected = lambda: False
    monkeypatch.setattr(voice, "mic_devices", lambda: ["Microphone (Realtek(R) Audio)", "Casque (M01 Pro_F444 Hands-Free"])
    for nom in ("Micro", "Microphone", "Casque", "USB audio", "Hands-Free", "M01"):
        app.state.ctx.settings.update({"glasses": {"name": nom, "address": "", "auto_connect": False}})
        assert voice.lunettes_presentes() is False, nom
        assert not nom_de_lunettes_distinctif(nom), nom
    app.state.ctx.settings.update({"glasses": {"name": "M01 Pro_F444", "address": "", "auto_connect": False}})
    assert voice.lunettes_presentes() is True


def test_laperçu_survit_au_redemarrage(app, monkeypatch):
    ctx = _sans_lunettes(app, monkeypatch)
    ctx.presence_lunettes.consommer_apercu()
    ctx.presence_lunettes.consommer_apercu()
    neuve = PresenceLunettes(ctx.settings, ctx.settings.data_dir, voice=ctx.voice)
    assert neuve.apercu_restant() == APERCU_MESSAGES - 2


# --------------------------------------------------------------------------- réglages protégés et démo cachée
def test_les_reglages_qui_ouvriraient_iris_sans_lunettes_sont_proteges(client):
    # « glasses » (constat du 2026-09-14) : un nom posé à la main (« Micro ») faisait passer tout micro pour les lunettes.
    for cle, valeur in (("require_glasses", False), ("demo_sans_lunettes", True),
                        ("glasses", {"name": "Micro", "address": "", "auto_connect": False})):
        r = client.patch("/api/settings", json={cle: valeur})
        assert r.status_code == 403, cle
    corps = client.get("/api/settings").json()
    assert corps["require_glasses"] is True and corps["demo_sans_lunettes"] is False


def test_le_mode_demo_exige_le_mot_de_passe_du_proprietaire(client, app, monkeypatch):
    _sans_lunettes(app, monkeypatch)
    assert client.post("/api/demo/activer", json={"mot_de_passe": "x"}).status_code == 409, "pas de compte : pas de démo"
    client.post("/api/compte", json={"nouveau": "motdepasse-2026", "nom": "Miguel"})
    assert client.post("/api/demo/activer", json={"mot_de_passe": "mauvais"}).status_code == 403
    r = client.post("/api/demo/activer", json={"mot_de_passe": "motdepasse-2026"})
    assert r.status_code == 200 and r.json()["presentes"] is True
    assert client.post("/api/demo/desactiver").json()["presentes"] is False
    # Constat du 2026-09-14 : le registre de confidentialité est visible par quiconque ouvre l'écran et part
    # dans l'export. L'accès propriétaire caché ne s'y nomme jamais.
    evenements = client.get("/api/privacy/events").json()["events"]
    types = [e["event_type"] for e in evenements]
    assert "acces_proprietaire" in types and "acces_proprietaire_fin" in types
    visible = str(evenements).lower() + client.get("/api/privacy/export?format=csv").text.lower()
    assert "demo" not in visible and "démonstration" not in visible


# --------------------------------------------------------------------------- contre-vérification du 2026-09-14
def test_un_nom_generique_avec_ponctuation_ne_prouve_rien(app, monkeypatch):
    """« Realtek(R) Audio » passait le filtre : la parenthèse interne faisait de « realtek(r » un mot distinctif."""
    from iris.voice.listener import nom_de_lunettes_distinctif

    for nom in ("Realtek(R) Audio", "(Realtek) Audio", "Microphone Array", "Intel® Smart Sound"):
        assert not nom_de_lunettes_distinctif(nom), nom
    voice = app.state.ctx.voice
    voice.glasses_connected = lambda: False
    monkeypatch.setattr(voice, "mic_devices", lambda: ["Microphone (Realtek(R) Audio)"])
    app.state.ctx.settings.update({"glasses": {"name": "Realtek(R) Audio", "address": "", "auto_connect": False}})
    assert voice.lunettes_presentes() is False
    assert nom_de_lunettes_distinctif("M01 Pro_F444") and nom_de_lunettes_distinctif("VELA K900")


class _FauxClientBle:
    is_connected = True

    def __init__(self):
        self.deconnecte = False

    async def disconnect(self):
        self.deconnecte = True
        self.is_connected = False


def _brancher_faux_ble(glasses, monkeypatch, services, nom_gatt=None):
    client = _FauxClientBle()

    async def sur_ble(coro):
        return await coro

    async def connecter(BleakClient, cible):
        return client

    async def abonner(c):
        return services

    async def lire(c):
        if nom_gatt and glasses.device:
            glasses.device["name"] = nom_gatt

    monkeypatch.setattr(glasses, "_on_ble", sur_ble)
    monkeypatch.setattr(glasses, "_ble_connect", connecter)
    monkeypatch.setattr(glasses, "_ble_subscribe", abonner)
    monkeypatch.setattr(glasses, "_read_basics", lire)
    return client


def test_connecter_nimporte_quel_appareil_ble_ne_fait_pas_des_lunettes(client, app, monkeypatch):
    """/api/glasses/connect enregistrait le nom FOURNI par l'appelant, après connexion à n'importe quel appareil."""
    ctx = app.state.ctx
    faux = _brancher_faux_ble(ctx.glasses, monkeypatch, [{"uuid": "0000180f-0000-1000-8000-00805f9b34fb",
                                                          "characteristics": []}])
    r = client.post("/api/glasses/connect", json={"address": "AA:BB:CC:DD:EE:FF", "name": "M01 Pro_F444"})
    assert r.status_code == 400 and "aucun service des lunettes VELA" in r.json()["detail"]
    assert faux.deconnecte and ctx.glasses.connected is False
    assert ctx.settings.user.glasses.name == "" and ctx.settings.user.glasses.address == ""


def test_le_nom_retenu_est_celui_annonce_par_les_lunettes(client, app, monkeypatch):
    ctx = app.state.ctx
    services = [{"uuid": "0000ffe0-0000-1000-8000-00805f9b34fb",
                 "characteristics": [{"uuid": "de5bf72a-d711-4e47-af26-65e3012a5dc7", "properties": ["notify"]}]}]
    _brancher_faux_ble(ctx.glasses, monkeypatch, services, nom_gatt="M01 Pro_F444")
    r = client.post("/api/glasses/connect", json={"address": "65:A2:9F:5C:F4:44", "name": "Realtek(R) Audio"})
    assert r.status_code == 200, r.text
    assert ctx.settings.user.glasses.name == "M01 Pro_F444"
    # Nom GATT illisible : le nom de l'appelant n'est toujours pas retenu.
    ctx.settings.update({"glasses": {"name": "", "address": "", "auto_connect": False}})
    _brancher_faux_ble(ctx.glasses, monkeypatch, services, nom_gatt=None)
    assert client.post("/api/glasses/connect", json={"address": "65:A2:9F:5C:F4:45", "name": "Micro Realtek"}).status_code == 200
    assert ctx.settings.user.glasses.name == ""


def test_association_sans_mot_de_passe_proprietaire_refusee_et_premier_appareil_journalise(client, app, monkeypatch):
    """Contre-vérification du 2026-09-14 : sans compte, /api/lunettes/association posait valide=True, et n'importe
    quelle session associait un identifiant inventé puis attestait en boucle."""
    ctx = _sans_lunettes(app, monkeypatch)
    assert client.post("/api/lunettes/attestation", json={"nom": "M01 Pro_F444", "identifiant": "vrai-tel"}).status_code == 200
    client.delete("/api/lunettes/attestation")
    assoc = client.post("/api/lunettes/association", json={"nom": "M01 Pro_F444", "identifiant": "curl-bidon"})
    assert assoc.status_code == 409 and "mot de passe du propriétaire" in assoc.json()["detail"]
    refus = client.post("/api/lunettes/attestation", json={"nom": "M01 Pro_F444", "identifiant": "curl-bidon"})
    assert refus.status_code == 403
    assert ctx.presence_lunettes.source() is None
    # La confiance au premier usage n'est jamais silencieuse : le registre de confidentialité la montre.
    types = [e["event_type"] for e in ctx.consent.events(limit=50)]
    assert "appareil_lunettes_associe" in types


# --------------------------------------------------------------------------- finition B du 2026-09-14
NOMS_MICROS_WINDOWS_FRANCAIS = (
    "Réseau de microphones (Technologie Intel® Smart Sound pour microphones numériques)",
    "Réseau de microphones",
    "Microphones (Realtek(R) Audio)",
    "Microphone (Realtek(R) Audio)",
    "Groupe de microphones",
    "Microphones (2- High Definition Audio Device)",
    "Micro (Realtek(R) Audio)",
    "Technologie Intel® Smart Sound pour microphones numériques",
)


def test_les_noms_francais_par_defaut_des_micros_windows_ne_prouvent_rien(app, monkeypatch):
    """Le filtre jugeait « distinctifs » les noms français par défaut de Windows (pluriel « microphones », « réseau »,
    « groupe », « numériques »). Posé comme nom de lunettes, l'un d'eux rendait les lunettes présentes par le micro
    intégré du PC, même déconnectées."""
    from iris.voice.listener import nom_de_lunettes_distinctif

    for nom in NOMS_MICROS_WINDOWS_FRANCAIS:
        assert not nom_de_lunettes_distinctif(nom), nom
    voice = app.state.ctx.voice
    voice.glasses_connected = lambda: False
    monkeypatch.setattr(voice, "mic_devices", lambda: list(NOMS_MICROS_WINDOWS_FRANCAIS))
    for nom in NOMS_MICROS_WINDOWS_FRANCAIS:
        app.state.ctx.settings.update({"glasses": {"name": nom, "address": "AA:BB:CC:DD:EE:FF", "auto_connect": False}})
        assert voice.lunettes_presentes() is False, nom
    # Les vrais noms restent des preuves.
    assert nom_de_lunettes_distinctif("M01 Pro_F444") and nom_de_lunettes_distinctif("VELA K900")
    monkeypatch.setattr(voice, "mic_devices", lambda: ["Casque (M01 Pro_F444 Hands-Free AG Audio)"])
    app.state.ctx.settings.update({"glasses": {"name": "M01 Pro_F444", "address": "", "auto_connect": False}})
    assert voice.lunettes_presentes() is True


def test_le_service_generique_ae00_seul_n_est_pas_une_signature(client, app, monkeypatch):
    """0000ae00 est l'UUID du profil générique de la puce, présent sur beaucoup d'appareils Bluetooth bon marché."""
    from iris.glasses import signature_vela

    ae = "0000ae0{}-0000-1000-8000-00805f9b34fb"
    assert not signature_vela([{"uuid": ae.format(0), "characteristics": []}])
    assert not signature_vela([{"uuid": ae.format(0), "characteristics": [{"uuid": ae.format(1)}]}])
    assert not signature_vela([{"uuid": ae.format(0), "characteristics": [{"uuid": ae.format(3)}]}])
    assert not signature_vela([{"uuid": ae.format(0), "characteristics": [{"uuid": ae.format(1)}]},
                               {"uuid": "0000ffe0-0000-1000-8000-00805f9b34fb", "characteristics": [{"uuid": ae.format(2)}]}])
    assert signature_vela([{"uuid": ae.format(0), "characteristics": [{"uuid": ae.format(1)}, {"uuid": ae.format(2)}]}])
    assert signature_vela([{"uuid": "0000ffe0-0000-1000-8000-00805f9b34fb",
                            "characteristics": [{"uuid": "de5bf72a-d711-4e47-af26-65e3012a5dc7"}]}])
    ctx = app.state.ctx
    faux = _brancher_faux_ble(ctx.glasses, monkeypatch, [{"uuid": ae.format(0), "characteristics": []}],
                              nom_gatt="Microphones (Realtek(R) Audio)")
    r = client.post("/api/glasses/connect", json={"address": "AA:BB:CC:DD:EE:01"})
    assert r.status_code == 400 and faux.deconnecte
    assert ctx.settings.user.glasses.name == ""


def test_la_presence_dit_que_l_attestation_du_telephone_est_declarative(client):
    """Tant que le défi signé par l'app native n'existe pas, la limite est affichée avec la présence."""
    limite = client.get("/api/lunettes/presence").json()["limite"]
    assert "Verrou logiciel" in limite
    assert "pas de preuve cryptographique" in limite and "associé d'office" in limite
