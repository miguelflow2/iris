"""Rotation des clés ElevenLabs : étaler la parole sur plusieurs comptes, basculer quand l'un refuse.

Ce que ces tests protègent. Un compte gratuit ElevenLabs plafonne à 10 000 caractères par mois.
Avec deux clés, IRIS doit alterner et, dès qu'une clé répond « quota atteint » (401/402/429),
basculer sur l'autre sans se taire. À une seule clé, rien ne doit changer par rapport à avant.

Aucun test ne touche le réseau : le client HTTP de Scribe est injecté. Les clés sont inventées et
posées dans l'environnement du test — jamais les vraies clés de Miguel."""
from __future__ import annotations

import pytest

import iris.voice.rotation_cles as rc
from iris.voice import stt
from iris.voice.rotation_cles import RotationCles, etiquette, parser_cles, pool_elevenlabs

PAROLE = b"\x11\x11" * 1600  # PCM 16 bits mono non vide, assez pour un WAV valide


def _reset_pool():
    rc._singleton = None
    rc._source = None


@pytest.fixture(autouse=True)
def pool_propre():
    _reset_pool()
    yield
    _reset_pool()


# --------------------------------------------------------------------------- doublures
class FausseReponse:
    def __init__(self, status_code=200, corps=None, text=""):
        self.status_code = status_code
        self._corps = corps
        self.text = text

    def json(self):
        if self._corps is None:
            raise ValueError("pas de JSON")
        return self._corps


class ClientParCle:
    """Client HTTP de Scribe qui répond selon la clé vue dans l'en-tête, et note l'ordre des clés."""

    def __init__(self, reponses: dict[str, FausseReponse]):
        self.reponses = reponses
        self.cles_vues: list[str] = []

    def post(self, url, **kw):
        cle = kw["headers"]["xi-api-key"]
        self.cles_vues.append(cle)
        return self.reponses[cle]


# --------------------------------------------------------------------------- le pool, seul
def test_parser_dedoublonne_et_garde_ordre():
    assert parser_cles("a, b ; a\nc") == ["a", "b", "c"]
    assert parser_cles("") == []
    assert parser_cles("   seule   ") == ["seule"]


def test_pool_vide_est_faux():
    p = RotationCles([])
    assert not p
    assert len(p) == 0
    assert p.courante() == ""


def test_alternance_apres_chaque_usage():
    p = RotationCles(["a", "b"])
    assert p.courante(0) == "a"
    p.apres_usage()
    assert p.courante(0) == "b"
    p.apres_usage()
    assert p.courante(0) == "a"


def test_cle_penalisee_est_evitee():
    p = RotationCles(["a", "b"], cooldown_s=100)
    p.marquer_epuisee("a", maintenant=0)
    assert p.courante(50) == "b"  # a est en pénalité, on prend b


def test_derniere_cle_saine_reprise_apres_expiration():
    p = RotationCles(["seule"], cooldown_s=100)
    p.marquer_epuisee("seule", maintenant=0)
    assert p.courante(50) == "seule"   # une seule clé : dernier recours même sous pénalité
    assert p.courante(200) == "seule"  # pénalité expirée : reprise normale


def test_toutes_penalisees_rend_la_moins_fraichement_penalisee():
    p = RotationCles(["a", "b"], cooldown_s=1000)
    p.marquer_epuisee("a", maintenant=0)    # a écartée jusqu'à 1000
    p.marquer_epuisee("b", maintenant=100)  # b écartée jusqu'à 1100
    assert p.courante(50) == "a"            # a redevient éligible en premier


def test_etiquette_ne_montre_que_la_fin():
    assert etiquette("sk_123456789abcd") == "…abcd"
    assert etiquette("") == "?"


def test_singleton_se_reconstruit_si_lenv_change(monkeypatch):
    monkeypatch.setenv("ELEVENLABS_API_KEY", "x")
    assert pool_elevenlabs().toutes() == ["x"]
    monkeypatch.setenv("ELEVENLABS_API_KEY", "x,y")
    assert pool_elevenlabs().toutes() == ["x", "y"]


# --------------------------------------------------------------------------- Scribe, de bout en bout
def test_scribe_bascule_quand_une_cle_est_epuisee(monkeypatch):
    monkeypatch.setenv("ELEVENLABS_API_KEY", "cleA,cleB")
    client = ClientParCle({
        "cleA": FausseReponse(429, text="quota"),
        "cleB": FausseReponse(200, {"text": "bonjour", "language_code": "fr"}),
    })
    texte = stt.scribe_recognize(PAROLE, 16000, "fr", client=client)
    assert texte == "bonjour"
    assert client.cles_vues == ["cleA", "cleB"]  # a bien basculé de A vers B


def test_scribe_toutes_cles_epuisees_leve_sans_boucler(monkeypatch):
    monkeypatch.setenv("ELEVENLABS_API_KEY", "cleA,cleB")
    client = ClientParCle({
        "cleA": FausseReponse(429, text="quota"),
        "cleB": FausseReponse(429, text="quota"),
    })
    with pytest.raises(stt.ReconnaissanceImpossible):
        stt.scribe_recognize(PAROLE, 16000, "fr", client=client)
    assert client.cles_vues == ["cleA", "cleB"]  # chaque clé essayée une fois, pas de boucle infinie


def test_scribe_une_seule_cle_ne_tourne_pas(monkeypatch):
    monkeypatch.setenv("ELEVENLABS_API_KEY", "cleA")
    client = ClientParCle({"cleA": FausseReponse(200, {"text": "salut"})})
    assert stt.scribe_recognize(PAROLE, 16000, "fr", client=client) == "salut"
    assert client.cles_vues == ["cleA"]


def test_scribe_cle_imposee_ignore_le_pool(monkeypatch):
    monkeypatch.setenv("ELEVENLABS_API_KEY", "cleA,cleB")
    client = ClientParCle({"imposee": FausseReponse(200, {"text": "ok"})})
    assert stt.scribe_recognize(PAROLE, 16000, "fr", client=client, cle="imposee") == "ok"
    assert client.cles_vues == ["imposee"]  # la clé passée en argument prime, aucune rotation


def test_scribe_alterne_dun_appel_a_lautre(monkeypatch):
    monkeypatch.setenv("ELEVENLABS_API_KEY", "cleA,cleB")
    client = ClientParCle({
        "cleA": FausseReponse(200, {"text": "un"}),
        "cleB": FausseReponse(200, {"text": "deux"}),
    })
    stt.scribe_recognize(PAROLE, 16000, "fr", client=client)
    stt.scribe_recognize(PAROLE, 16000, "fr", client=client)
    assert client.cles_vues == ["cleA", "cleB"]  # deux énoncés réussis -> deux comptes différents
