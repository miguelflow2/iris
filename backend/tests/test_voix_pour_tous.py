"""La voix ElevenLabs appartient à tous les forfaits — et ne doit jamais coûter plus que prévu.

Deux promesses tiennent ensemble dans ces tests, et l'une sans l'autre serait une faute :

1. « Tous les forfaits doivent avoir accès à ElevenLabs. Le forfait gratuit doit avoir accès à
   ElevenLabs. » (Miguel, 5 septembre 2026.) La voix cesse d'être un argument de vente entre
   paliers. Le code le disait déjà à moitié : une clé personnelle dans backend/.env
   court-circuitait le palier depuis le début, si bien qu'IRIS parlait en ElevenLabs en plan
   Gratuit pendant que l'application affichait « voix Windows ». Ce n'était pas une fonction
   manquante, c'était un mensonge.

2. Chaque caractère prononcé est facturé à une carte bancaire réelle. Ouvrir la porte sans poser
   le frein, ce serait signer un chèque dont le montant est décidé par les utilisateurs.

Et une troisième, qui prime sur les deux : quoi qu'il arrive — clé absente, quota épuisé, réseau
coupé — IRIS parle avec la voix de Windows. Une assistante qui se tait a l'air cassée ; une
assistante qui change de voix a seulement l'air moins jolie.

Aucun test ici n'ouvre le micro, ne joue de son ni ne touche au réseau.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from iris.config import Settings
from iris.db import Database
from iris.events import EventHub
from iris.plans import PLAN_ORDER, PLANS, PlanService


@pytest.fixture()
def service(monkeypatch, data_dir: Path):
    """Un PlanService en plan Gratuit, sans clé personnelle : ce sont les paliers qui décident."""
    s = Settings(data_dir)
    # Après Settings, jamais avant : sa construction recharge backend/.env, qui contient la clé
    # personnelle de Miguel. Sans cet ordre, ces tests mesureraient le comportement BYOK.
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
    db = Database(data_dir / "plans.db")
    hub = EventHub()
    evenements: list = []
    hub.publish = lambda type_, **data: evenements.append((type_, data))  # type: ignore[method-assign]
    svc = PlanService(db, s, hub)
    svc.evenements = evenements  # type: ignore[attr-defined]  (commodité de test)
    yield svc
    db.close()


# --------------------------------------------------------------------------- la porte est ouverte
def test_le_forfait_gratuit_a_droit_a_elevenlabs(service):
    """Si cette assertion tombe, le plan Gratuit retombe sur la voix Windows « Zira », anglaise,
    qui lit du français avec un accent — exactement ce que Miguel a demandé de supprimer."""
    assert service.plan == "gratuit"
    assert service.feature_allowed("elevenlabs"), "la voix n'est plus réservée aux forfaits payants"


def test_aucun_forfait_ne_reste_a_la_voix_de_windows(service):
    """Un seul palier oublié, et le site promet une voix que l'application refuse de donner."""
    for nom in PLAN_ORDER:
        assert "elevenlabs" in PLANS[nom]["features"], nom
        assert PLANS[nom]["tts"] == "elevenlabs", nom


def test_les_contenus_de_forfait_ne_vendent_plus_la_voix(service):
    """Le client lit ces lignes dans l'écran « Abonnement ». Laisser « voix Windows » au Gratuit ou
    « voix ElevenLabs » comme nouveauté du Pro, ce serait lui faire payer ce qu'il a déjà."""
    gratuit = " ".join(PLANS["gratuit"]["contents"]).lower()
    assert "elevenlabs" in gratuit, "le forfait gratuit doit annoncer la voix qu'il reçoit vraiment"
    assert "voix windows" not in gratuit
    for nom in ("pro", "premium", "entreprise"):
        for ligne in PLANS[nom]["contents"]:
            bas = ligne.lower()
            if "elevenlabs" in bas:
                assert "caractères" in bas, f"{nom} : la voix ne se vend plus, seule sa quantité change ({ligne!r})"


# --------------------------------------------------------------------------- le frein est posé
def test_chaque_forfait_a_un_plafond_de_caracteres_reel(service):
    """Un plafond à zéro n'est pas une simplification, c'est l'absence de frein. Le compteur
    existait déjà (count_tts) ; c'est de ne rien lui opposer qui laissait le robinet ouvert."""
    for nom in PLAN_ORDER:
        assert PLANS[nom]["quota_tts_chars"] > 0, nom


def test_au_dela_du_plafond_iris_repasse_a_la_voix_de_windows(service):
    """Le plafond doit être OPPOSABLE, pas décoratif : au-dessus, feature_allowed devient faux et
    voice/tts.py reprend le chemin de repli qui existe déjà. Sans cela, « ElevenLabs pour tous »
    est un robinet ouvert sur la carte de VELA."""
    plafond = PLANS["gratuit"]["quota_tts_chars"]
    service.count_tts(plafond - 1)
    assert service.feature_allowed("elevenlabs"), "sous le plafond, rien ne change"
    service.count_tts(1)
    assert not service.feature_allowed("elevenlabs"), "au plafond, la voix payante s'arrête"
    assert service.usage()["tts_chars_left"] == 0


def test_le_plafond_atteint_est_annonce_une_seule_fois(service):
    """Ce test est interrogé avant CHAQUE phrase : prévenir à chaque fois noierait l'utilisateur
    sous les avertissements, et ne rien dire lui ferait croire à une panne de la voix."""
    service.count_tts(PLANS["gratuit"]["quota_tts_chars"])
    for _ in range(5):
        service.feature_allowed("elevenlabs")
    alertes = [d for t, d in service.evenements if t == "plan.tts_quota"]
    assert len(alertes) == 1
    assert "Windows" in alertes[0]["message"], "dire ce qui reste, pas seulement ce qui s'arrête"


def test_le_plafond_sapplique_meme_a_une_cle_personnelle(monkeypatch, data_dir: Path):
    """Arbitrage du 5 septembre 2026, contre la version précédente de ce test.

    L'intention d'origine se défendait : ce que la clé de quelqu'un paie ne regarde pas son
    forfait. Sauf qu'une relecture adverse a montré l'effet réel — la clé personnelle, ici, c'est
    CELLE DE MIGUEL, posée dans son .env. Le raccourci répondait donc oui avant même que le
    plafond soit consulté, et le seul frein posé sur sa carte était inatteignable par construction.

    On tranche pour la prudence. Le pire que produise ce choix, c'est une phrase dite par la voix
    de Windows au lieu d'ElevenLabs — le repli est éprouvé, IRIS ne se tait pas. Le pire que
    produisait l'autre, c'est une carte vidée pendant la nuit."""
    monkeypatch.setenv("ELEVENLABS_API_KEY", "sk_personnelle_factice")
    s = Settings(data_dir)
    db = Database(data_dir / "byok.db")
    svc = PlanService(db, s, EventHub())
    assert svc.feature_allowed("elevenlabs"), "sous le plafond, la clé donne bien accès"
    svc.count_tts(PLANS["gratuit"]["quota_tts_chars"] * 10)
    assert not svc.feature_allowed("elevenlabs"), "au-delà, le plafond prime sur la clé"
    db.close()


# --------------------------------------------------------------------------- IRIS ne se tait jamais
# Trois pannes, un seul comportement attendu : la voix de Windows prend le relais et la phrase est
# prononcée quand même. C'est la partie la plus importante de tout le dossier — une assistante
# muette passe pour cassée, et sur scène personne ne saura que c'est ElevenLabs qui a lâché.
class _Journal:
    """Remplace la voix de Windows : on note la phrase au lieu de la faire sortir du haut-parleur."""

    def __init__(self):
        self.phrases: list[str] = []

    def __call__(self, texte: str) -> bool:
        self.phrases.append(texte)
        return True


@pytest.fixture()
def voix(monkeypatch, data_dir: Path):
    """TextToSpeech sans moteur : enabled=False n'ouvre ni SAPI ni périphérique audio."""
    from iris.voice.tts import TextToSpeech

    reglages = Settings(data_dir)
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)  # après Settings, qui recharge .env
    tts = TextToSpeech(reglages, EventHub(), enabled=False)
    journal = _Journal()
    # On ne remplace QUE la voix de Windows : le câblage entre les deux moteurs
    # (tts.py, `self.eleven.fallback_speak = ...`) reste celui qui tourne en vrai.
    tts._speak_windows = journal  # type: ignore[method-assign]
    return tts, journal


def test_sans_cle_iris_parle_avec_la_voix_de_windows(voix):
    tts, journal = voix
    assert tts.engine == "windows"
    assert tts.speak("Bonjour Miguel.", force=True) is True
    assert journal.phrases == ["Bonjour Miguel."], "la phrase doit sortir malgré tout"


def test_quota_elevenlabs_epuise_la_phrase_nest_pas_perdue(voix):
    """Le cas qui arrivera vraiment : le quota du compte ElevenLabs se tarit en pleine
    démonstration. La phrase en cours doit être rejouée par Windows, pas jetée."""
    tts, journal = voix
    erreur = RuntimeError("HTTP 429 quota_exceeded")
    erreur.response = type("R", (), {"status_code": 429, "text": "quota_exceeded"})()  # type: ignore[attr-defined]
    tts.eleven._handle_failure(erreur, "Il reste deux minutes.")
    assert journal.phrases == ["Il reste deux minutes."]
    assert not tts.eleven.available, "ElevenLabs est mis de côté : la phrase suivante n'attend pas un aller-retour perdu"
    assert tts.engine == "windows"


def test_reseau_coupe_iris_parle_quand_meme(voix):
    """Une coupure réseau n'est ni un 401 ni un 429 : ce chemin-là aussi doit rendre la parole."""
    tts, journal = voix
    tts.eleven._handle_failure(OSError("réseau coupé"), "Je continue.")
    assert journal.phrases == ["Je continue."]


def test_une_cle_invalide_ne_rend_pas_iris_muette(voix):
    tts, journal = voix
    erreur = RuntimeError("HTTP 401")
    erreur.response = type("R", (), {"status_code": 401, "text": "invalid_api_key"})()  # type: ignore[attr-defined]
    tts.eleven._handle_failure(erreur, "Bonjour.")
    assert journal.phrases == ["Bonjour."]


def test_le_repli_dit_a_lutilisateur_ce_qui_se_passe(voix):
    """Un repli silencieux se confond avec une panne : l'utilisateur entend une autre voix et croit
    qu'IRIS a changé toute seule. Le motif doit remonter à l'interface (événement tts.fallback)."""
    recu: list = []
    tts, _ = voix
    tts.eleven.hub.publish = lambda type_, **data: recu.append((type_, data))  # type: ignore[method-assign]
    erreur = RuntimeError("HTTP 402")
    erreur.response = type("R", (), {"status_code": 402, "text": "quota"})()  # type: ignore[attr-defined]
    tts.eleven._handle_failure(erreur, "Bonjour.")
    motifs = [d.get("reason", "") for t, d in recu if t == "tts.fallback"]
    assert motifs and "Windows" in motifs[0], "le message doit nommer la voix qui prend le relais"


# --------------------------------------------------------------------------- le plafond doit mordre
# Defaut trouve par une relecture adverse le 5 septembre 2026. Le plafond de caracteres etait place
# APRES le raccourci « cle personnelle » — or ce raccourci repond oui des qu'une cle ElevenLabs
# existe, ce qui est toujours le cas chez Miguel. Le seul frein pose sur sa carte etait donc
# inatteignable par construction : pas contournable par ruse, inerte.
def test_le_plafond_coupe_meme_avec_une_cle_personnelle(app, monkeypatch):
    plans = app.state.ctx.plans
    monkeypatch.setattr(plans, "byok_tts", lambda: True)
    monkeypatch.setattr(plans, "tts_quota_exceeded", lambda: True)
    assert plans.feature_allowed("elevenlabs") is False, "le plafond doit primer sur la cle personnelle"


def test_sous_le_plafond_la_cle_personnelle_donne_bien_acces(app, monkeypatch):
    plans = app.state.ctx.plans
    monkeypatch.setattr(plans, "byok_tts", lambda: True)
    monkeypatch.setattr(plans, "tts_quota_exceeded", lambda: False)
    assert plans.feature_allowed("elevenlabs") is True


def test_le_forfait_gratuit_a_droit_a_la_voix(app, monkeypatch):
    """Decision de Miguel : « tous les forfaits doivent avoir acces a ElevenLabs »."""
    plans = app.state.ctx.plans
    monkeypatch.setattr(plans, "byok_tts", lambda: False)
    monkeypatch.setattr(plans, "tts_quota_exceeded", lambda: False)
    assert plans.plan == "gratuit"
    assert plans.feature_allowed("elevenlabs") is True
