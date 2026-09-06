"""Le mode traduction : ce qu'il apporte, et surtout ce qu'il ne casse pas.

Trois promesses sont protégées ici, dans cet ordre d'importance.

1. LE CYCLE VOCAL NORMAL NE BOUGE PAS quand la traduction est éteinte. L'écoute a été totalement
   hors service le matin du 5 septembre 2026 — moteur figé sur le nuage, file audio en retard de
   83 secondes, pas un seul mot d'activation entendu de la matinée. Rien de ce qui a été ajouté
   après n'a le droit de la reprendre en otage.
2. LA SORTIE EST INFAILLIBLE. Un mot (« Iris, arrête »), un bouton, l'arrêt de l'écoute, la
   disparition des lunettes, ou l'expiration — et sur chacun de ces chemins IRIS le DIT. Croire
   qu'elle traduit encore alors qu'elle est revenue à l'écoute normale, c'est parler dans le vide
   devant quelqu'un : c'est le pire raté possible de cette fonction, pire qu'une mauvaise traduction,
   parce que celle-là au moins s'entend.
3. L'OUTIL EST BRANCHÉ. Déclaré, offert au modèle, et son handler répond. Constat du 5 septembre
   2026 : deux modules entiers, 81 Ko et 97 tests verts, sont restés inutilisables une journée
   entière parce que personne ne les avait branchés dans tools.py.

Aucun test n'ouvre de micro, ne joue de son, ne charge de modèle ni ne touche au réseau : les blocs
audio sont fabriqués, le guetteur de sortie et le service de traduction sont des doublures.
"""
from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field

import pytest

from iris.voice import listener as ecoute
from iris.voice import stt
from iris.voice.listener import TRAD_PAROLE_MIN, TRAD_SEGMENT_MAX, TRAD_SILENCE_FIN

# Un bloc de micro vaut 0,25 s à 16 kHz. Le silence porte un pic de 0, la parole un pic de 6000 —
# au-dessus de SPEECH_PEAK (700) et sous la saturation.
SILENCE = b"\x00\x00" * ecoute.BLOCK
PAROLE = (6000).to_bytes(2, "little", signed=True) * ecoute.BLOCK
BLOC = ecoute.BLOCK / stt.SAMPLE_RATE
# Les quatre premiers blocs mesurent le bruit ambiant (seuil adaptatif, comme `_listen_command`) :
# toute suite de blocs commence donc par du silence, sans quoi le seuil se calerait sur la parole.
CALIBRATION = [SILENCE] * 4


# --------------------------------------------------------------------------- doublures
@dataclass
class FauxTTS:
    """La voix d'IRIS, sans un son. `dites` garde ce qui aurait été prononcé."""

    available: bool = True
    is_speaking: bool = False
    dites: list[str] = field(default_factory=list)

    def speak(self, texte: str, force: bool = False) -> bool:
        self.dites.append(texte)
        return True

    def wait_idle(self, timeout: float = 30.0) -> bool:
        return True

    def stop(self) -> None:
        pass


@dataclass
class FauxService:
    """Le ServiceTraduction, réduit à ce que l'écoute lui demande vraiment."""

    actif: bool = True
    langue_entendue: str = "en"
    fermeture: str = ""  # ce que `doit_fermer` renvoie
    empechement: str = ""
    silence: float = 0.0
    raisons: list[str] = field(default_factory=list)
    langues: list[str] = field(default_factory=list)

    def pourquoi_impossible(self) -> str:
        return self.empechement

    def silence_depuis(self) -> float:
        return self.silence

    def doit_fermer(self) -> str:
        return self.fermeture

    def demarrer(self, langue: str = "") -> str:
        self.langues.append(langue)
        self.actif = not self.empechement
        return self.empechement or "Mode traduction. J'écoute en anglais et je te traduis à mesure."

    def arreter(self, raison: str = "demande") -> str:
        self.actif = False
        self.raisons.append(raison)
        return f"Fin ({raison}). Je ne traduis plus."


class FauxGuetteur:
    """Le reconnaisseur à grammaire restreinte, sans Vosk : rend un texte au bloc demandé."""

    def __init__(self, textes: dict[int, str]):
        self.textes = dict(textes)
        self.blocs = 0
        self._dernier = ""

    def AcceptWaveform(self, data: bytes) -> bool:  # noqa: N802 - signature imposée par Vosk
        self.blocs += 1
        self._dernier = self.textes.get(self.blocs, "")
        return bool(self._dernier)

    def Result(self) -> str:  # noqa: N802 - signature imposée par Vosk
        return json.dumps({"text": self._dernier})


@pytest.fixture()
def voice(app):
    """L'écoute réelle de l'application, avec une voix muette et sans verrou de lunettes."""
    app.state.ctx.settings.update({"demo_sans_lunettes": True})
    # Le consentement « audio brut » est la configuration réelle de la machine de Miguel, et sans lui
    # la traduction refuse de démarrer (la reconnaissance hors ligne ne connaît que le français).
    # Les tests qui vérifient ce refus le retirent eux-mêmes.
    app.state.ctx.consent.set("audio_raw", True)
    v = app.state.ctx.voice
    v.tts = FauxTTS()
    v._stop.clear()
    v._ptt.clear()
    v._one_shot = False
    return v


def _preparer(voice, blocs, guetteur=None):
    """Remplace le micro par une suite de blocs, et le fil de travail par un carnet.

    Quand les blocs sont épuisés, l'écoute s'arrête : une boucle qui tournerait à vide dans un test
    ne se distinguerait pas d'une boucle qui refuse de rendre la main."""
    restants = list(blocs)
    segments: list[bytes] = []

    def lire(timeout: float = 0.3):
        if restants:
            return restants.pop(0)
        voice._stop.set()
        return None

    voice._read = lire
    voice._drain = lambda: None
    voice._guetteur_de_sortie = lambda mots: guetteur
    voice._traduire_segment = segments.append
    return segments


def _attendre(segments: list[bytes], combien: int, delai: float = 3.0) -> list[bytes]:
    """Attend que le fil de travail ait reçu ses segments (il tourne à côté du fil audio)."""
    fin = time.time() + delai
    while time.time() < fin and len(segments) < combien:
        time.sleep(0.02)
    return segments


def _secondes(pcm: bytes) -> float:
    return len(pcm) / 2 / stt.SAMPLE_RATE


# --------------------------------------------------------------------------- 1. ne rien casser
def test_le_cycle_vocal_normal_ne_connait_pas_la_traduction(voice, monkeypatch):
    """Sans service de traduction, une commande se termine par la fenêtre de dialogue, comme avant.

    Si cette assertion tombait, le branchement de la traduction aurait détourné le chemin par lequel
    passe TOUTE commande vocale — celui qui a coûté la matinée du 5 septembre 2026."""
    suivi: list[str] = []
    voice.traduction = None
    monkeypatch.setattr(voice, "_set_state", lambda *a, **k: None)
    monkeypatch.setattr(voice, "_listen_command", lambda **k: "ouvre spotify")
    monkeypatch.setattr(voice, "_process", lambda texte, **k: suivi.append(f"traite:{texte}"))
    monkeypatch.setattr(voice, "_fenetre_dialogue", lambda: suivi.append("fenetre"))
    monkeypatch.setattr(voice, "_boucle_traduction", lambda: suivi.append("traduction"))
    voice._command_cycle()
    assert suivi == ["traite:ouvre spotify", "fenetre"]


def test_sans_service_aucune_traduction_ne_peut_etre_en_attente(voice):
    """`traduction` non branché : le test coûte un booléen et répond toujours non."""
    voice.traduction = None
    assert voice._traduction_en_attente() is False
    assert voice._traduire_si_demande() is False


def test_le_mode_demande_remplace_la_fenetre_de_dialogue(voice, monkeypatch):
    """Quand la traduction est demandée, on n'ouvre pas la fenêtre de dialogue.

    Les deux écoutent la même file : guetter en même temps une commande française et la parole d'un
    anglophone reviendrait à se partager les blocs au hasard."""
    suivi: list[str] = []
    voice.traduction = FauxService(actif=True)
    monkeypatch.setattr(voice, "_set_state", lambda *a, **k: None)
    monkeypatch.setattr(voice, "_listen_command", lambda **k: "traduis ce qu'il dit")
    monkeypatch.setattr(voice, "_process", lambda texte, **k: suivi.append("traite"))
    monkeypatch.setattr(voice, "_fenetre_dialogue", lambda: suivi.append("fenetre"))
    monkeypatch.setattr(voice, "_boucle_traduction", lambda: suivi.append("traduction"))
    voice._command_cycle()
    assert suivi == ["traite", "traduction"]


def test_une_demande_oubliee_ne_sinvite_pas_dans_la_conversation_suivante(voice):
    """Mode armé depuis le chat écrit, micro fermé, puis plus rien pendant deux minutes : on referme.

    Sans cette péremption, la commande vocale suivante — une heure plus tard — basculerait en
    traduction sans que personne ne l'ait demandé."""
    service = FauxService(actif=True, silence=ecoute.TRAD_OUVERTURE_PERIMEE + 1)
    voice.traduction = service
    assert voice._traduction_en_attente() is False
    assert service.raisons == ["silence"]


# --------------------------------------------------------------------------- 2. l'entrée
@pytest.mark.parametrize(
    "phrase, attendu",
    [
        ("traduis ce qu'il dit", True),
        ("est-ce que tu peux me traduire ce que cette personne dit", True),
        ("mets-toi en mode traduction", True),
        ("traduis-moi l'espagnol", True),
        ("arrête la traduction", False),  # la phrase qui ferme le mode ne doit pas le rouvrir
        ("annule la traduction", False),
        ("ouvre mon navigateur", False),
        ("mets de la musique", False),
    ],
)
def test_les_phrases_qui_ouvrent_le_mode_et_celles_qui_ne_louvrent_pas(voice, phrase, attendu):
    """Le test se fait AVANT le modèle : sur scène, une fonction qui dépend d'un aller-retour réseau
    est une fonction qui peut manquer."""
    assert voice._est_demande_traduction(phrase) is attendu


def test_ouvrir_le_mode_ne_passe_pas_par_le_modele(voice, monkeypatch):
    """« Iris, traduis ce qu'il dit » ouvre le mode sans un seul appel au modèle.

    Si l'état « processing » apparaissait, la demande serait partie chez l'agent : elle coûterait
    trois secondes et dépendrait du réseau au pire moment."""
    etats: list[str] = []
    service = FauxService(actif=False)
    voice.traduction = service
    app_consent = voice.consent
    app_consent.set("audio_raw", True)
    monkeypatch.setattr(voice, "_set_state", lambda etat, **k: etats.append(etat))
    voice._process("traduis-moi ce qu'il dit")
    assert "processing" not in etats
    assert service.actif is True
    assert any("traduction" in d.lower() for d in voice.tts.dites)


def test_la_langue_nommee_est_celle_qui_est_ouverte(voice):
    """« traduis-moi l'espagnol » ouvre le mode en espagnol, pas en anglais."""
    service = FauxService(actif=False)
    voice.traduction = service
    voice.consent.set("audio_raw", True)
    voice._demarrer_traduction("traduis-moi l'espagnol")
    assert service.langues == ["es"]


def test_sans_consentement_audio_iris_dit_pourquoi_elle_ne_traduira_pas(voice):
    """La reconnaissance hors ligne installée ici ne connaît que le français : sans l'envoi audio,
    IRIS n'entend rien d'étranger. Elle doit le dire, pas ouvrir un mode qui ne traduira jamais."""
    voice.traduction = FauxService(actif=False)
    voice.consent.set("audio_raw", False)
    assert voice._demarrer_traduction("traduis ce qu'il dit") is False
    assert voice.tts.dites and "Confidentialité" in voice.tts.dites[0]


def test_le_mode_local_refuse_la_traduction_et_lexplique(voice):
    """Le refus vient du service (c'est lui qui connaît le mode local) et il est dit tel quel."""
    voice.traduction = FauxService(actif=False, empechement="Le mode local est actif.")
    voice.consent.set("audio_raw", True)
    assert voice._demarrer_traduction("traduis ce qu'il dit") is False
    assert voice.tts.dites == ["Le mode local est actif."]


# --------------------------------------------------------------------------- 3. le découpage
def test_une_phrase_se_ferme_sur_le_silence_et_part_au_fil_de_travail(voice):
    """Une seconde de parole puis 0,75 s de silence : un segment, et un seul.

    Si le segment ne se fermait pas, IRIS attendrait la fin de la conversation pour traduire la
    première phrase."""
    voice.traduction = FauxService()
    segments = _preparer(voice, CALIBRATION + [PAROLE] * 4 + [SILENCE] * 3)
    voice._boucle_traduction()
    _attendre(segments, 1)
    assert len(segments) == 1
    assert _secondes(segments[0]) == pytest.approx(1.75, abs=0.01)  # 1 s de parole + 0,75 s de silence


def test_un_raclement_de_gorge_ne_coute_pas_un_aller_retour(voice):
    """Une demi-seconde de bruit sous TRAD_PAROLE_MIN n'est pas une phrase.

    La traduire coûterait un aller-retour réseau et, surtout, deux secondes pendant lesquelles IRIS
    parlerait par-dessus l'interlocuteur pour dire « yeah »."""
    assert 2 * BLOC < TRAD_PAROLE_MIN
    voice.traduction = FauxService()
    segments = _preparer(voice, CALIBRATION + [PAROLE] * 2 + [SILENCE] * 4)
    voice._boucle_traduction()
    time.sleep(0.1)
    assert segments == []


def test_un_long_parleur_est_traduit_en_morceaux(voice):
    """Douze secondes sans respirer : le plafond coupe, sinon la traduction arriverait après la réponse."""
    voice.traduction = FauxService()
    segments = _preparer(voice, CALIBRATION + [PAROLE] * 48)
    voice._boucle_traduction()
    _attendre(segments, 1)
    assert segments, "le plafond de durée n'a pas coupé"
    assert _secondes(segments[0]) == pytest.approx(TRAD_SEGMENT_MAX, abs=BLOC)


def test_pendant_quiris_parle_rien_nest_accumule(voice):
    """L'alternat, assumé : ce qui entre pendant qu'IRIS lit une traduction, c'est SA voix.

    L'accumuler la ferait se traduire elle-même — et le micro des lunettes, en mains libres, la
    reprend en plein."""
    voice.traduction = FauxService()
    voice.tts.is_speaking = True
    segments = _preparer(voice, CALIBRATION + [PAROLE] * 8 + [SILENCE] * 4)
    voice._boucle_traduction()
    time.sleep(0.1)
    assert segments == []


# --------------------------------------------------------------------------- 4. la sortie
def test_iris_arrete_referme_le_mode_et_le_dit(voice):
    """« Iris, arrête » sort du mode, et IRIS l'annonce.

    Le mot d'activation est exigé : au milieu d'un flot d'anglais, une grammaire de six mots français
    plaque volontiers un son étranger sur son voisin le plus proche."""
    service = FauxService()
    voice.traduction = service
    guetteur = FauxGuetteur({3: "dis moi iris arrete"})
    _preparer(voice, CALIBRATION + [PAROLE] * 8, guetteur=guetteur)
    voice._boucle_traduction()
    assert service.raisons == ["demande"]
    assert service.actif is False
    assert voice.tts.dites and "ne traduis plus" in voice.tts.dites[-1]
    assert not voice._stop.is_set(), "la sortie du mode ne doit pas arrêter l'écoute"


@pytest.mark.parametrize("entendu", ["arrete", "stop", "iris", "", "the store is right there"])
def test_ce_qui_ne_referme_pas_le_mode(voice, entendu):
    """Un mot d'arrêt sans le nom ne ferme rien : sinon un mot anglais mal décodé couperait la
    traduction en pleine conversation, et il faudrait la rouvrir devant l'interlocuteur."""
    assert voice._sortie_traduction(entendu, []) == ""


def test_le_nom_seul_ne_referme_pas_le_mode_mais_le_nom_plus_larret_oui(voice):
    """`_est_arret("iris arrête")` est FAUX : il compare l'énoncé entier à un mot d'arrêt.
    C'est le dépouillage du nom AVANT le test qui sauve la phrase — dans cet ordre, jamais l'inverse."""
    assert voice._est_arret("iris arrete") is False
    assert voice._sortie_traduction("dis moi iris", []) == ""
    assert voice._sortie_traduction("iris arrete", []) == "demande"


def test_le_bouton_parler_maintenant_sort_du_mode(voice):
    """La sortie de secours qui ne dépend d'aucun décodage : sur scène, un bouton ne se trompe jamais."""
    service = FauxService()
    voice.traduction = service
    _preparer(voice, [SILENCE] * 20)
    voice._ptt.set()
    voice._boucle_traduction()
    assert service.actif is False
    assert voice._ptt.is_set() is False  # le bouton est consommé, pas laissé armé


def test_larret_de_lecoute_referme_le_mode(voice):
    """Bouton « Arrêter l'écoute », muet, chien de garde, micro disparu : tous posent `_stop`.

    La raison dite n'est pas « demande » : l'écoute s'est arrêtée sous nos pieds, et ça ne se dit pas
    comme une sortie qu'on a demandée."""
    service = FauxService()
    voice.traduction = service
    _preparer(voice, [SILENCE] * 20)
    voice._stop.set()
    voice._boucle_traduction()
    assert service.raisons == ["arret"]
    assert service.actif is False


def test_les_lunettes_debranchees_referment_le_mode(voice):
    """La voix est verrouillée par les lunettes : le mode traduction ne peut pas y échapper."""
    service = FauxService()
    voice.traduction = service
    voice.settings.update({"demo_sans_lunettes": False, "require_glasses": True})
    voice.glasses_connected = lambda: False
    _preparer(voice, [SILENCE] * 20)
    voice._boucle_traduction()
    assert service.raisons == ["lunettes"]


def test_le_mode_expire_et_le_dit(voice):
    """Personne ne parle : le service demande la fermeture, et IRIS ne laisse pas le micro ouvert.

    Un micro ouvert que personne ne surveille est précisément ce que ce produit promet de ne pas
    faire — et le dire à voix haute est la seule façon de le savoir sans regarder l'écran."""
    service = FauxService(fermeture="silence")
    voice.traduction = service
    _preparer(voice, [SILENCE] * 20)
    voice._boucle_traduction()
    assert service.raisons == ["silence"]
    assert voice.tts.dites and "ne traduis plus" in voice.tts.dites[-1]


def test_le_mode_se_referme_quand_on_le_ferme_de_lexterieur(voice):
    """`arreter_traduction()` (outil, bouton, API) est vu par la boucle au bloc suivant, soit 0,25 s."""
    service = FauxService()
    voice.traduction = service
    lus: list[int] = []

    def lire(timeout: float = 0.3):
        lus.append(1)
        if len(lus) > 8:
            voice._stop.set()  # garde-fou du test : une boucle qui ne sort pas ne doit pas figer la suite
        return SILENCE

    voice._read = lire
    voice._drain = lambda: None
    voice._guetteur_de_sortie = lambda mots: None
    voice.arreter_traduction("demande")
    voice._boucle_traduction()
    assert service.actif is False
    assert lus == [], "la boucle doit sortir avant même de lire un bloc de plus"


def test_une_traduction_qui_arrive_apres_la_fermeture_nest_pas_lue(voice):
    """IRIS ne parle pas dans le dos de son propriétaire.

    Un segment encore en vol quand le mode se referme serait lu APRÈS « Je ne traduis plus » : le
    propriétaire, revenu à une conversation normale, entendrait IRIS traduire toute seule."""
    service = FauxService(actif=False)  # déjà refermé pendant l'aller-retour
    voice.traduction = service
    voice._reconnaitre_etranger = lambda pcm, langue: "hello there"
    voice._executer = lambda coro, timeout=20.0: type("R", (), {"a_dire": "Bonjour", "en_dict": lambda s: {}})()
    voice._traduire_segment(PAROLE)
    assert voice.tts.dites == []


def test_le_reseau_qui_tombe_ne_fait_pas_exploser_le_fil_de_travail(voice):
    """Une exception ici serait avalée par l'exécuteur et IRIS resterait muette sans que rien ne
    l'explique. Le mode, lui, doit continuer : le réseau revient souvent tout seul."""
    def echoue(pcm, langue):
        raise RuntimeError("réseau coupé")

    voice.traduction = FauxService()
    voice._reconnaitre_etranger = echoue
    voice._traduire_segment(PAROLE)  # ne doit rien lever
    assert voice.tts.dites == []


def test_trois_echecs_de_suite_referment_le_mode(voice):
    """C'est le service qui compte les échecs ; l'écoute lui obéit et le dit.

    Continuer laisserait le micro ouvert sur une conversation privée pour rien."""
    service = FauxService(fermeture="erreur")
    voice.traduction = service
    _preparer(voice, [SILENCE] * 10)
    voice._boucle_traduction()
    assert service.raisons == ["erreur"]
    assert voice.tts.dites and "ne traduis plus" in voice.tts.dites[-1]


# --------------------------------------------------------------------------- 5. l'outil est branché
def _contexte(app, **extra):
    from iris.tools import ToolContext

    c = app.state.ctx

    async def refuser(titre: str, detail: str) -> bool:
        return False

    return ToolContext(settings=c.settings, consent=c.consent, capture=c.capture, memory=c.memory,
                       agent="test", confirm=refuser, **extra)


def test_les_outils_de_traduction_sont_offerts_au_modele(app):
    """Déclarés ET dans la liste réellement envoyée au modèle.

    Le 5 septembre 2026, deux modules entiers sont restés inutilisables toute une journée parce que
    personne n'avait vérifié cette ligne-là."""
    from iris.tools import tool_specs

    noms = [s.name for s in tool_specs(_contexte(app))]
    for outil in ("traduire_conversation", "arreter_traduction", "traduire_ma_reponse"):
        assert outil in noms


def test_loutil_ouvre_le_mode_et_rend_la_phrase_a_dire(app, voice):
    """Le second chemin d'entrée : le modèle appelle l'outil, et le fil audio prend le relais."""
    from iris.tools import make_tool_runner

    service = FauxService(actif=False)
    voice.traduction = service
    voice.consent.set("audio_raw", True)
    ctx = _contexte(app, voice=voice)
    reponse = asyncio.run(make_tool_runner(ctx)("traduire_conversation", {"langue": "anglais"}))
    assert service.actif is True
    assert service.langues == ["anglais"]
    assert "traduction" in str(reponse).lower()
    assert voice._traduction_en_attente() is True


def test_loutil_dit_que_lecoute_est_arretee_au_lieu_de_promettre(app, voice):
    """Mode armé mais micro fermé : le dire. Promettre une traduction à quelqu'un qui parle dans le
    vide est le raté le plus coûteux de cette fonction."""
    from iris.tools import make_tool_runner

    voice.traduction = FauxService(actif=False)
    voice.consent.set("audio_raw", True)
    reponse = asyncio.run(make_tool_runner(_contexte(app, voice=voice))("traduire_conversation", {}))
    assert "écoute vocale est arrêtée" in str(reponse)


def test_loutil_referme_le_mode(app, voice):
    from iris.tools import make_tool_runner

    service = FauxService(actif=True)
    voice.traduction = service
    reponse = asyncio.run(make_tool_runner(_contexte(app, voice=voice))("arreter_traduction", {}))
    assert service.actif is False
    assert "ne traduis plus" in str(reponse)


def test_loutil_traduit_ce_que_lutilisateur_veut_dire(app):
    """« Comment je lui dis que… » : l'autre sens, celui qui répond à « ensuite me dit ce que je dois dire »."""
    from iris.tools import make_tool_runner

    class ServiceAvecReponse(FauxService):
        async def traduire_ma_reponse(self, texte: str):
            return type("T", (), {"ok": True, "traduction": "See you tomorrow.", "raison": ""})()

    ctx = _contexte(app, traduction=ServiceAvecReponse())
    reponse = asyncio.run(make_tool_runner(ctx)("traduire_ma_reponse", {"texte": "on se voit demain"}))
    assert "See you tomorrow." in str(reponse)


def test_sans_service_branche_loutil_le_dit_au_lieu_de_faire_semblant(app):
    """Le pire résultat serait un outil qui répond « c'est fait » sans que rien n'écoute."""
    from iris.tools import make_tool_runner

    reponse = asyncio.run(make_tool_runner(_contexte(app))("traduire_conversation", {}))
    assert isinstance(reponse, dict) and reponse.get("is_error")


# --------------------------------------------------------------------------- ne pas ouvrir en silence
def test_une_commande_locale_dit_ce_que_loutil_repond(app):
    """Le 5 septembre 2026, IRIS a ouvert le mode traduction EN SILENCE. La commande etait bien
    reconnue localement, l'outil bien execute — et le message rendu etait vide. Entrer dans un mode
    sans le dire est le pire des rates : on ignore qu'il est actif, et donc quand en sortir."""
    import asyncio
    from types import SimpleNamespace

    chat = app.state.ctx.chat
    quick = SimpleNamespace(tool="traduire_conversation", args={}, reply="", kind="traduction")
    conv = chat.create_conversation()
    cid = conv["id"] if isinstance(conv, dict) else conv

    rendu = asyncio.run(chat._run_quick(cid, quick, "test"))
    texte = (rendu["message"].get("text") or "").strip()
    assert texte, "IRIS doit dire quelque chose : ouvrir un mode en silence est le defaut corrige ici"
    # Deux issues legitimes selon l'etat de la machine, et les deux sont des phrases francaises :
    # le mode s'ouvre, ou IRIS explique ce qui l'en empeche. Ce qui n'est pas acceptable, c'est le
    # silence — ou un morceau de JSON lu a voix haute.
    assert len(texte.split()) >= 3, texte
    assert not texte.startswith("{") and not texte.startswith("["), "jamais de JSON dit a voix haute"


def test_une_commande_locale_sans_phrase_reste_muette_si_loutil_nen_rend_pas(app):
    """L'inverse doit rester vrai : un outil qui ne rend pas de phrase ne doit pas faire dire a
    IRIS un morceau de JSON ou un identifiant technique."""
    import asyncio
    from types import SimpleNamespace

    chat = app.state.ctx.chat
    conv = chat.create_conversation()
    cid = conv["id"] if isinstance(conv, dict) else conv
    quick = SimpleNamespace(tool="", args={}, reply="Il est midi.", kind="heure")

    rendu = asyncio.run(chat._run_quick(cid, quick, "test"))
    assert (rendu["message"].get("text") or "").strip() == "Il est midi."
