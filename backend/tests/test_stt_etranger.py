"""Entendre une langue étrangère par un service officiel, et ne jamais rester muette.

Ce que ces tests protègent. La parole d'un interlocuteur part D'ABORD chez ElevenLabs Scribe (sous
contrat, avec la clé déjà utilisée pour la voix), et seulement en repli vers l'endpoint gratuit et
non officiel de Google. Quand aucune voie ne rend de texte, une exception typée le dit en français
— elle n'est jamais avalée, c'est ce qui permet à l'écoute de dire « je n'ai pas pu entendre » au
lieu de se taire, comme elle l'a fait le 5 septembre 2026. Et pas un octet ne part sans le
consentement audio_raw.

Aucun test ne touche le réseau : le client HTTP de Scribe est injecté, la voie Google est remplacée
par une doublure, et un client qui explose si on l'appelle sert de détecteur d'envoi. La clé
ElevenLabs des tests est une chaîne inventée posée dans l'environnement du test — la vraie clé de
Miguel n'est jamais lue ni exposée."""
from __future__ import annotations

import io
import wave

import pytest

from iris.voice import stt
from iris.voice.stt import (
    AGENT_GOOGLE,
    AGENT_SCRIBE,
    CONSENTEMENT,
    INCOMPRIS,
    NON_CONFIGURE,
    PANNE,
    REFUS,
    RESEAU,
    SCRIBE_MODEL,
    SCRIBE_URL,
    ReconnaissanceImpossible,
    reconnaitre_etranger,
    wav_en_memoire,
)

# Deux secondes de « parole » : de l'int16 mono à 16 kHz, comme ce que le micro rend au listener.
PAROLE = bytes(range(256)) * 250
CLE_DE_TEST = "cle-elevenlabs-inventee-pour-les-tests"


# --------------------------------------------------------------------------- doublures
class FausseReponse:
    def __init__(self, status_code: int = 200, corps: dict | None = None, text: str = ""):
        self.status_code = status_code
        self._corps = corps
        self.text = text

    def json(self):
        if self._corps is None:
            raise ValueError("pas de JSON")
        return self._corps


class FauxClient:
    """Client HTTP de Scribe : enregistre l'appel, rend ce qu'on lui a dit de rendre."""

    def __init__(self, reponse: FausseReponse | None = None, erreur: Exception | None = None):
        self.reponse = reponse or FausseReponse(200, {"text": "hello there", "language_code": "en"})
        self.erreur = erreur
        self.appels: list[tuple[str, dict]] = []

    def post(self, url, **kw):
        self.appels.append((url, kw))
        if self.erreur:
            raise self.erreur
        return self.reponse


class ClientInterdit:
    """Détecteur d'envoi : le moindre appel fait échouer le test."""

    def post(self, *a, **kw):
        raise AssertionError("aucun octet ne devait partir vers Scribe")


class FauxGoogle:
    """Doublure de `stt.google_recognize` : enregistre les appels, rend un texte ou lève."""

    def __init__(self, texte: str = "", erreur: Exception | None = None):
        self.texte = texte
        self.erreur = erreur
        self.appels: list[tuple[bytes, int, str]] = []

    def __call__(self, pcm, rate, langue):
        self.appels.append((pcm, rate, langue))
        if self.erreur:
            raise self.erreur
        return self.texte


class GoogleInterdit:
    def __call__(self, *a, **kw):
        raise AssertionError("aucun octet ne devait partir vers Google")


@pytest.fixture()
def avec_cle(monkeypatch):
    monkeypatch.setenv("ELEVENLABS_API_KEY", CLE_DE_TEST)


@pytest.fixture()
def sans_cle(monkeypatch):
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)


@pytest.fixture()
def google(monkeypatch):
    """Par défaut, la voie Google est un détecteur : un test qui veut Google le dit explicitement."""
    doublure = GoogleInterdit()
    monkeypatch.setattr(stt, "google_recognize", doublure)
    return doublure


def _brancher_google(monkeypatch, doublure: FauxGoogle) -> FauxGoogle:
    monkeypatch.setattr(stt, "google_recognize", doublure)
    return doublure


# --------------------------------------------------------------------------- 1. le WAV en mémoire
def test_le_wav_construit_en_memoire_est_bien_forme():
    """Scribe reçoit un fichier WAV : 16 kHz, mono, 16 bits, et exactement les échantillons du micro."""
    wav = wav_en_memoire(PAROLE, 16000)
    assert wav[:4] == b"RIFF" and wav[8:12] == b"WAVE"
    with wave.open(io.BytesIO(wav), "rb") as lu:
        assert lu.getnchannels() == 1
        assert lu.getsampwidth() == 2
        assert lu.getframerate() == 16000
        assert lu.getnframes() == len(PAROLE) // 2
        assert lu.readframes(lu.getnframes()) == PAROLE


def test_un_octet_orphelin_ne_casse_pas_le_wav():
    """Un tampon coupé au milieu d'un échantillon (nombre impair d'octets) est tronqué, pas refusé."""
    wav = wav_en_memoire(PAROLE + b"\x01", 16000)
    with wave.open(io.BytesIO(wav), "rb") as lu:
        assert lu.getnframes() == len(PAROLE) // 2


# --------------------------------------------------------------------------- 2. Scribe d'abord
def test_scribe_est_essaye_en_premier_et_son_texte_est_rendu(avec_cle, google):
    """Avec une clé ElevenLabs, la parole part chez Scribe et Google n'est jamais appelé."""
    client = FauxClient()
    assert reconnaitre_etranger(PAROLE, 16000, "en", consentement=True, client=client) == "hello there"
    assert len(client.appels) == 1


def test_la_requete_scribe_porte_la_cle_le_modele_et_un_wav(avec_cle, google):
    """Ce que Scribe reçoit : la clé dans `xi-api-key`, `scribe_v2`, la langue en indice court, un WAV."""
    client = FauxClient()
    reconnaitre_etranger(PAROLE, 16000, "en-US", consentement=True, client=client)
    url, kw = client.appels[0]
    assert url == SCRIBE_URL
    assert kw["headers"]["xi-api-key"] == CLE_DE_TEST
    assert kw["data"]["model_id"] == SCRIBE_MODEL
    assert kw["data"]["language_code"] == "en", "Scribe veut un code ISO court, pas une locale"
    nom, contenu, mime = kw["files"]["file"]
    assert nom.endswith(".wav") and mime == "audio/wav"
    assert contenu[:4] == b"RIFF"
    with wave.open(io.BytesIO(contenu), "rb") as lu:
        assert (lu.getframerate(), lu.getnchannels(), lu.getsampwidth()) == (16000, 1, 2)
    assert kw["timeout"] == stt.SCRIBE_TIMEOUT, "sans délai, un service qui pend rend IRIS muette"


def test_sans_langue_scribe_detecte_lui_meme(avec_cle, google):
    """Multilingue : sans indice, on ne force aucun code — Scribe reconnaît la langue."""
    client = FauxClient()
    reconnaitre_etranger(PAROLE, 16000, "", consentement=True, client=client)
    assert "language_code" not in client.appels[0][1]["data"]


# --------------------------------------------------------------------------- 3. le repli Google
def test_sans_cle_elevenlabs_google_prend_le_relais_sans_toucher_scribe(sans_cle, monkeypatch):
    """Sur une machine neuve sans clé ElevenLabs, IRIS entend quand même — par Google, avec la locale complète."""
    doublure = _brancher_google(monkeypatch, FauxGoogle("good morning"))
    assert reconnaitre_etranger(PAROLE, 16000, "en", consentement=True, client=ClientInterdit()) == "good morning"
    assert doublure.appels == [(PAROLE, 16000, "en-US")]


def test_si_scribe_est_injoignable_google_prend_le_relais(avec_cle, monkeypatch):
    client = FauxClient(erreur=ConnectionError("Name or service not known"))
    doublure = _brancher_google(monkeypatch, FauxGoogle("see you soon"))
    assert reconnaitre_etranger(PAROLE, 16000, "en", consentement=True, client=client) == "see you soon"
    assert len(client.appels) == 1 and len(doublure.appels) == 1


def test_si_scribe_refuse_la_cle_google_prend_le_relais(avec_cle, monkeypatch):
    """Un 401 (clé révoquée, quota) n'est pas la fin : la conversation continue par Google."""
    client = FauxClient(FausseReponse(401, text='{"detail":"invalid api key"}'))
    _brancher_google(monkeypatch, FauxGoogle("thank you"))
    assert reconnaitre_etranger(PAROLE, 16000, "en", consentement=True, client=client) == "thank you"


def test_si_scribe_ne_trouve_aucun_mot_google_a_sa_chance(avec_cle, monkeypatch):
    client = FauxClient(FausseReponse(200, {"text": "", "language_code": "en"}))
    _brancher_google(monkeypatch, FauxGoogle("yes"))
    assert reconnaitre_etranger(PAROLE, 16000, "en", consentement=True, client=client) == "yes"


# --------------------------------------------------------------------------- 4. jamais muette
def test_quand_tout_echoue_lexception_dit_en_francais_ce_qui_a_manque(avec_cle, monkeypatch):
    """Scribe refuse, Google n'a pas de réseau : l'exception nomme les deux, en français, et n'est pas avalée."""
    client = FauxClient(FausseReponse(401, text="invalid api key"))
    _brancher_google(monkeypatch, FauxGoogle(erreur=ReconnaissanceImpossible(RESEAU, "Google : recognition connection failed")))
    with pytest.raises(ReconnaissanceImpossible) as info:
        reconnaitre_etranger(PAROLE, 16000, "en", consentement=True, client=client)
    exc = info.value
    assert exc.raison == REFUS, "un refus se corrige (clé, quota) : c'est lui qu'on dit d'abord"
    message = str(exc)
    assert "service refusé" in message and "pas de réseau" in message
    assert "Scribe" in message and "Google" in message
    assert exc.a_dire == "Je n'ai pas pu entendre : service refusé."


def test_rien_compris_partout_se_dit_rien_compris(avec_cle, monkeypatch):
    """Deux services ont reçu la parole et n'y ont rien trouvé : c'est l'audio qui est vide, pas le réseau."""
    client = FauxClient(FausseReponse(200, {"text": ""}))
    _brancher_google(monkeypatch, FauxGoogle(""))
    with pytest.raises(ReconnaissanceImpossible) as info:
        reconnaitre_etranger(PAROLE, 16000, "en", consentement=True, client=client)
    assert info.value.raison == INCOMPRIS
    assert str(info.value).startswith("rien compris")
    assert "Je n'ai pas pu entendre : rien compris." == info.value.a_dire


def test_rien_compris_lemporte_sur_une_panne(avec_cle, monkeypatch):
    """Scribe en panne (503), Google n'a rien compris : le service qui a écouté l'audio a le dernier mot."""
    client = FauxClient(FausseReponse(503, text="Service Unavailable"))
    _brancher_google(monkeypatch, FauxGoogle(""))
    with pytest.raises(ReconnaissanceImpossible) as info:
        reconnaitre_etranger(PAROLE, 16000, "en", consentement=True, client=client)
    assert info.value.raison == INCOMPRIS
    assert "service en panne" in str(info.value) and "503" in str(info.value)


def test_sans_cle_et_sans_reseau_lexception_le_dit(sans_cle, monkeypatch):
    _brancher_google(monkeypatch, FauxGoogle(erreur=ReconnaissanceImpossible(RESEAU, "Google : recognition connection failed")))
    with pytest.raises(ReconnaissanceImpossible) as info:
        reconnaitre_etranger(PAROLE, 16000, "en", consentement=True, client=ClientInterdit())
    assert info.value.raison == RESEAU
    assert "ELEVENLABS_API_KEY" in str(info.value), "le journal doit dire pourquoi Scribe n'a même pas été essayé"


def test_un_defaut_imprevu_dune_voie_ne_fait_pas_taire_iris(avec_cle, monkeypatch):
    """Un bogue dans une voie (ici Google lève n'importe quoi) devient une cause nommée, pas un silence."""
    client = FauxClient(FausseReponse(200, {"text": ""}))
    _brancher_google(monkeypatch, FauxGoogle(erreur=TypeError("argument inattendu")))
    with pytest.raises(ReconnaissanceImpossible) as info:
        reconnaitre_etranger(PAROLE, 16000, "en", consentement=True, client=client)
    assert "TypeError" in str(info.value)
    assert info.value.a_dire.startswith("Je n'ai pas pu entendre")


def test_une_reponse_scribe_illisible_est_une_panne(avec_cle, monkeypatch):
    client = FauxClient(FausseReponse(200, None, text="<html>maintenance</html>"))
    _brancher_google(monkeypatch, FauxGoogle(erreur=ReconnaissanceImpossible(RESEAU)))
    with pytest.raises(ReconnaissanceImpossible) as info:
        reconnaitre_etranger(PAROLE, 16000, "en", consentement=True, client=client)
    assert info.value.raison == PANNE


def test_un_audio_vide_ne_part_nulle_part(avec_cle, google):
    with pytest.raises(ReconnaissanceImpossible) as info:
        reconnaitre_etranger(b"", 16000, "en", consentement=True, client=ClientInterdit())
    assert info.value.raison == INCOMPRIS


# --------------------------------------------------------------------------- 5. pas un octet sans consentement
@pytest.mark.parametrize("consentement", [False, None, lambda: False], ids=["faux", "absent", "fonction_fausse"])
def test_aucun_octet_ne_part_sans_consentement(avec_cle, google, consentement):
    """Ni Scribe ni Google : l'exception le dit, et son message parle de consentement."""
    with pytest.raises(ReconnaissanceImpossible) as info:
        reconnaitre_etranger(PAROLE, 16000, "en", consentement=consentement, client=ClientInterdit())
    assert info.value.raison == CONSENTEMENT
    assert "consentement" in str(info.value)


def test_appeler_sans_dire_le_consentement_est_un_refus(avec_cle, google):
    """La valeur par défaut est le refus : oublier l'argument ne peut pas faire partir la voix d'un tiers."""
    with pytest.raises(ReconnaissanceImpossible) as info:
        reconnaitre_etranger(PAROLE, 16000, "en", client=ClientInterdit())
    assert info.value.raison == CONSENTEMENT


def test_un_consentement_qui_explose_vaut_un_refus(avec_cle, google):
    """Base de consentement inaccessible : dans le doute, rien ne part."""

    def casse():
        raise RuntimeError("base verrouillée")

    with pytest.raises(ReconnaissanceImpossible) as info:
        reconnaitre_etranger(PAROLE, 16000, "en", consentement=casse, client=ClientInterdit())
    assert info.value.raison == CONSENTEMENT


def test_un_consentement_par_fonction_laisse_partir(avec_cle, google):
    assert reconnaitre_etranger(PAROLE, 16000, "en", consentement=lambda: True, client=FauxClient()) == "hello there"


# --------------------------------------------------------------------------- 6. le registre des sorties
def test_le_registre_dit_quel_service_a_recu_laudio(avec_cle, monkeypatch):
    """Le registre chaîné répond à « vers qui est-ce sorti ? » : Scribe, puis Google au repli, avant chaque envoi."""
    client = FauxClient(FausseReponse(401, text="invalid api key"))
    _brancher_google(monkeypatch, FauxGoogle("hello"))
    traces: list[tuple[str, str]] = []
    reconnaitre_etranger(PAROLE, 16000, "en", consentement=True, client=client, journal=lambda agent, detail: traces.append((agent, detail)))
    assert [agent for agent, _ in traces] == [AGENT_SCRIBE, AGENT_GOOGLE]
    assert all("2000 ms" in detail and "en" in detail for _, detail in traces)


def test_le_registre_ne_ment_pas_quand_scribe_nest_pas_configure(sans_cle, monkeypatch):
    """Sans clé, rien ne part chez ElevenLabs : le registre ne doit pas prétendre le contraire."""
    _brancher_google(monkeypatch, FauxGoogle("hello"))
    traces: list[str] = []
    reconnaitre_etranger(PAROLE, 16000, "en", consentement=True, client=ClientInterdit(), journal=lambda agent, detail: traces.append(agent))
    assert traces == [AGENT_GOOGLE]


def test_rien_au_registre_quand_rien_ne_part(avec_cle, google):
    traces: list[str] = []
    with pytest.raises(ReconnaissanceImpossible):
        reconnaitre_etranger(PAROLE, 16000, "en", consentement=False, client=ClientInterdit(), journal=lambda a, d: traces.append(a))
    assert traces == []


# --------------------------------------------------------------------------- 7. google_recognize lui-même
def _doublure_google(monkeypatch, effet):
    """Remplace la méthode de SpeechRecognition : aucune socket ne s'ouvre pendant ces tests."""
    import speech_recognition as sr

    vus: list[dict] = []

    def faux(self, audio, **kw):
        vus.append({"timeout": self.operation_timeout, "language": kw.get("language")})
        if isinstance(effet, Exception):
            raise effet
        return effet

    monkeypatch.setattr(sr.Recognizer, "recognize_google", faux)
    return vus


def test_google_recognize_convertit_lerreur_reseau_en_exception_typee(monkeypatch):
    """Avant, la RequestError remontait telle quelle et finissait avalée : IRIS restait muette."""
    import speech_recognition as sr

    _doublure_google(monkeypatch, sr.RequestError("recognition connection failed: [Errno 11001] getaddrinfo failed"))
    with pytest.raises(ReconnaissanceImpossible) as info:
        stt.google_recognize(PAROLE, 16000, "en-US")
    assert info.value.raison == RESEAU
    assert str(info.value).startswith("pas de réseau")


def test_google_recognize_distingue_le_refus_de_la_panne(monkeypatch):
    import speech_recognition as sr

    _doublure_google(monkeypatch, sr.RequestError("recognition request failed: Forbidden"))
    with pytest.raises(ReconnaissanceImpossible) as refus:
        stt.google_recognize(PAROLE, 16000, "en-US")
    assert refus.value.raison == REFUS

    _doublure_google(monkeypatch, sr.RequestError("recognition request failed: Service Unavailable"))
    with pytest.raises(ReconnaissanceImpossible) as panne:
        stt.google_recognize(PAROLE, 16000, "en-US")
    assert panne.value.raison == PANNE


def test_google_recognize_rend_vide_quand_il_ne_comprend_pas(monkeypatch):
    """Sur le chemin du mot d'activation, « rien compris » est un silence normal, pas une erreur."""
    import speech_recognition as sr

    _doublure_google(monkeypatch, sr.UnknownValueError())
    assert stt.google_recognize(PAROLE, 16000, "fr-CA") == ""


def test_google_recognize_impose_un_delai(monkeypatch):
    """Sans délai, `urlopen` attend pour toujours — et le fil de traduction avec lui."""
    vus = _doublure_google(monkeypatch, "bonjour")
    assert stt.google_recognize(PAROLE, 16000, "fr-CA") == "bonjour"
    assert vus[0]["timeout"] == stt.GOOGLE_TIMEOUT
    assert vus[0]["language"] == "fr-CA"


# --------------------------------------------------------------------------- 8. l'exception elle-même
def test_lexception_parle_francais_meme_avec_une_raison_inconnue():
    exc = ReconnaissanceImpossible("quelque chose d'imprévu")
    assert exc.raison == stt.INCONNU
    assert "raison inconnue" in str(exc) and "quelque chose d'imprévu" in str(exc)
    assert exc.a_dire == "Je n'ai pas pu entendre : raison inconnue."


def test_scribe_non_configure_est_une_cause_nommee(sans_cle):
    with pytest.raises(ReconnaissanceImpossible) as info:
        stt.scribe_recognize(PAROLE, 16000, "en", client=ClientInterdit())
    assert info.value.raison == NON_CONFIGURE
