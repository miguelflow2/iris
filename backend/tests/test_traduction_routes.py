"""Le mode traduction piloté depuis l'interface : /api/traduction/etat, /demarrer, /arreter.

Ce que ces tests protègent : l'écran reçoit un état complet (langues proposées, empêchement),
« Démarrer » ouvre le mode ET met l'écoute en route pour qu'IRIS entende vraiment l'interlocuteur,
« Arrêter » referme, et aucun des verrous existants n'est contourné — mode local, consentement
« audio brut », écoute verrouillée (lunettes) : dans chacun de ces cas IRIS dit pourquoi au lieu
de faire semblant.

Aucun test n'ouvre de micro ni ne touche au réseau : `start()` est remplacé par une doublure qui
note l'appel, et le modèle est une fonction factice.
"""
from __future__ import annotations

import pytest

from iris.traduction import NOMS_LANGUES
from iris.voice import listener as ecoute


@pytest.fixture()
def voix(app, monkeypatch):
    """L'écoute réelle, dont le démarrage est simulé : `demarrages` note les appels, `ecoute_active`
    tient lieu de fil audio (le vrai `running` teste un thread vivant)."""
    ctx = app.state.ctx
    ctx.settings.update({"demo_sans_lunettes": True})
    ctx.consent.set("audio_raw", True)

    async def modele_factice(systeme: str, message: str) -> str:
        return '{"traduction": "Bonjour, comment ça va ?", "a_dire": "Bonjour, comment ça va ?"}'

    ctx.traduction._interroger = modele_factice
    v = ctx.voice
    v.error = None
    v.demarrages: list[bool] = []
    v.ecoute_active = False

    def faux_start(one_shot: bool = False) -> dict:
        v.demarrages.append(one_shot)
        v.ecoute_active = True
        return {"running": True}

    monkeypatch.setattr(ecoute.VoiceListener, "running", property(lambda self: bool(getattr(self, "ecoute_active", False))))
    v.start = faux_start
    return v


# --------------------------------------------------------------------------- l'état
def test_letat_contient_les_langues_et_lempechement(client, voix):
    corps = client.get("/api/traduction/etat").json()
    assert corps["actif"] is False
    assert corps["empechement"] == ""
    assert corps["ecoute"] is False
    assert corps["langues"] == [{"code": c, "nom": n} for c, n in NOMS_LANGUES.items()]
    assert {"code": "en", "nom": "anglais"} in corps["langues"]
    assert corps["langue_moi"] == "fr"


def test_les_routes_exigent_le_jeton(client_sans_jeton):
    assert client_sans_jeton.get("/api/traduction/etat").status_code == 401
    assert client_sans_jeton.post("/api/traduction/demarrer", json={"langue": "en"}).status_code == 401
    assert client_sans_jeton.post("/api/traduction/arreter").status_code == 401


# --------------------------------------------------------------------------- démarrer / arrêter
def test_demarrer_ouvre_le_mode_et_lance_lecoute(client, voix):
    corps = client.post("/api/traduction/demarrer", json={"langue": "es"}).json()
    assert corps["actif"] is True
    assert corps["langue_entendue"] == "es"
    assert corps["langue_entendue_nom"] == "espagnol"
    assert "traduction" in corps["phrase"].lower() and "espagnol" in corps["phrase"]
    assert "écoute vocale est arrêtée" not in corps["phrase"]
    assert corps["ecoute"] is True
    assert voix.demarrages == [False], "l'écoute a été démarrée (pas en mode « une commande »)"
    # Le fil audio verra le mode armé au bloc suivant : c'est ce que l'écoute regarde.
    assert voix._traduction_en_attente() is True
    assert client.get("/api/traduction/etat").json()["actif"] is True


def test_sans_langue_cest_langlais(client, voix):
    corps = client.post("/api/traduction/demarrer", json={}).json()
    assert corps["actif"] is True and corps["langue_entendue"] == "en"


def test_une_langue_dite_en_toutes_lettres_est_comprise(client, voix):
    corps = client.post("/api/traduction/demarrer", json={"langue": "italien"}).json()
    assert corps["actif"] is True and corps["langue_entendue"] == "it"


def test_lecoute_deja_en_route_nest_pas_redemarree(client, voix):
    voix.ecoute_active = True
    corps = client.post("/api/traduction/demarrer", json={"langue": "en"}).json()
    assert corps["actif"] is True
    assert voix.demarrages == []


def test_arreter_referme_le_mode_et_le_dit(client, voix):
    client.post("/api/traduction/demarrer", json={"langue": "en"})
    corps = client.post("/api/traduction/arreter").json()
    assert corps["actif"] is False
    assert corps["phrase"].endswith("Je ne traduis plus.")
    assert corps["tours_en_memoire"] == 0
    assert client.get("/api/traduction/etat").json()["actif"] is False
    # Sûre à appeler deux fois : l'interface peut cliquer sans regarder l'état.
    assert client.post("/api/traduction/arreter").json()["actif"] is False


# --------------------------------------------------------------------------- les verrous tiennent
def test_le_mode_local_refuse_et_ne_touche_pas_au_micro(client, voix):
    client.patch("/api/settings", json={"local_only": True})
    etat = client.get("/api/traduction/etat").json()
    assert "mode local" in etat["empechement"].lower()
    corps = client.post("/api/traduction/demarrer", json={"langue": "en"}).json()
    assert corps["actif"] is False
    assert corps["phrase"] == etat["empechement"]
    assert voix.demarrages == [], "rien ne démarre l'écoute quand la traduction est impossible"


def test_sans_consentement_audio_brut_iris_dit_pourquoi(client, voix):
    voix.consent.set("audio_raw", False)
    corps = client.post("/api/traduction/demarrer", json={"langue": "en"}).json()
    assert corps["actif"] is False
    assert "Audio brut du micro" in corps["phrase"]
    assert voix.demarrages == []


def test_lecoute_verrouillee_est_dite_au_lieu_detre_promise(client, voix):
    """`start()` refuse (lunettes exigées, micro coupé, mode confidentiel) : le mode est armé comme
    par l'outil, mais la phrase dit que personne n'écoute, et pourquoi."""

    def start_refuse(one_shot: bool = False) -> dict:
        voix.demarrages.append(one_shot)
        voix.error = "Connecte tes lunettes VELA pour utiliser IRIS."
        return {"running": False, "error": voix.error}

    voix.start = start_refuse
    corps = client.post("/api/traduction/demarrer", json={"langue": "en"}).json()
    assert corps["ecoute"] is False
    assert "écoute vocale est arrêtée" in corps["phrase"]
    assert "Connecte tes lunettes VELA" in corps["phrase"]


# --------------------------------------------------------------------------- le fil audio suit
class _FauxVosk:
    """Le moteur hors ligne, réduit à ce que `_wake_cycle` lui demande avant de lire un bloc."""

    def recognizer(self, phrases=None, words=False):
        return object()


def test_le_fil_audio_entre_dans_la_traduction_sans_mot_dactivation(voix):
    """Mode armé de l'extérieur : `_wake_cycle` y entre au bloc suivant, sans lire le micro.
    Avant, la traduction demandée à l'écran ne commençait qu'après la commande vocale suivante."""
    entrees: list[str] = []
    lectures: list[float] = []
    voix.traduction.demarrer("en")
    voix._boucle_traduction = lambda: entrees.append("traduction")
    voix._read = lambda timeout=0.3: lectures.append(timeout)
    voix._vosk = _FauxVosk()
    voix.calibrating = 0
    voix.engine = "vosk"
    voix._wake_cycle()
    assert entrees == ["traduction"]
    assert lectures == [], "aucun bloc lu : on n'attend pas le mot d'activation"

    voix.engine = "google"
    voix._capture_segment = lambda **kw: pytest.fail("le nuage n'a pas à capturer six secondes ici")
    voix._wake_cycle()
    assert entrees == ["traduction", "traduction"]


def test_sans_mode_arme_le_cycle_dactivation_ne_change_pas(voix):
    """Rien de demandé : la vérification coûte un booléen et le cycle lit le micro comme avant."""
    entrees: list[str] = []
    voix._boucle_traduction = lambda: entrees.append("traduction")
    voix._read = lambda timeout=0.3: voix._stop.set()  # premier bloc : on arrête, le cycle rend la main
    voix._vosk = _FauxVosk()
    voix.calibrating = 0
    voix.engine = "vosk"
    voix._stop.clear()
    voix._wake_cycle()
    assert entrees == []
    voix._stop.clear()
