"""Sous-titres en direct : ce qui se dit autour de l'utilisateur, affiché en texte, reconnu SUR l'appareil.

Pour une personne sourde ou malentendante, c'est la fonction qui rend une conversation lisible. Le
son vient du robinet audio (voice/robinet.py) : une copie de chaque bloc micro pendant que l'écoute
du mot d'activation continue. La reconnaissance est faite par le modèle hors ligne déjà utilisé par
l'écoute, en plein vocabulaire : AUCUN son ni texte ne quitte l'ordinateur.

Ce qu'il faut savoir, et que l'interface dit :
- le modèle hors ligne est petit : la transcription est approximative (noms propres, accents
  marqués, bruit, plusieurs personnes à la fois), sans ponctuation ni identification de qui parle ;
- le son n'existe que si l'écoute tourne. Si elle est arrêtée, on la démarre ; en mode confidentiel
  ou micro coupé, on refuse et on dit pourquoi ; si plus aucun bloc n'arrive, on affiche
  « en attente du micro » plutôt que de laisser croire que personne ne parle.

Un seul fil de reconnaissance sert tout le monde : l'écran de sous-titres, le journal continu et le
mode cours sont des « demandes » ; le fil tourne tant qu'il en reste une.
"""
from __future__ import annotations

import logging
import queue
import threading
import time
from collections import deque
from typing import Any, Callable

from .voice import stt
from .voice.robinet import TAUX

log = logging.getLogger("iris.sous_titres")

NOM_ROBINET = "sous-titres"
ATTENTE_MICRO_S = 3.0  # sans bloc depuis ce délai : « en attente du micro »
PARTIEL_INTERVALLE_S = 0.25  # au plus 4 partiels par seconde : au-delà, l'écran clignote et le bus sature
SEGMENT_MAX_S = 30.0  # parole continue sans pause : on coupe la ligne quand même, sinon elle n'apparaît jamais
PLAFOND_LIGNES = 5000  # session gardée en mémoire vive (~ une journée de conversation), jamais sur disque
MAX_BLOCS_EN_FILE = 240  # 60 s de retard toléré ; au-delà, le plus vieux son est jeté (voir robinet.py)

ATTENTE_MICRO = "En attente du micro : aucun son reçu depuis quelques secondes."
CONFIDENTIEL = "Mode confidentiel actif : le micro est coupé, aucune écoute ne peut démarrer."
MICRO_MUET = "Micro coupé (muet) : réactivez le micro pour utiliser l'écoute."
MODELE_ABSENT = (
    "La reconnaissance hors ligne n'est pas installée : téléchargez le modèle dans Paramètres › Voix. "
    "Les sous-titres ne passent jamais par Internet."
)

# Sorties typiques du petit modèle sur un bruit (porte, toux, souffle) : un mot isolé sans contenu.
# Les afficher ferait croire qu'on a parlé.
BRUITS = {"euh", "hum", "hein", "le", "la", "les", "de", "un", "une", "et", "ben", "bah", "oh", "ah"}


class EcouteImpossible(Exception):
    """Refus explicable (mode confidentiel, micro muet, modèle absent…). Les routes le rendent en 409."""

    def __init__(self, message: str, code: int = 409):
        super().__init__(message)
        self.message = message
        self.code = code


# ---------------------------------------------------------------------------- micro partagé
def empechement_micro(ctx) -> str | None:
    """Pourquoi un service qui a besoin du son ne peut pas démarrer maintenant (None = rien ne l'empêche)."""
    if ctx.settings.user.privacy_mode:
        return CONFIDENTIEL
    voice = getattr(ctx, "voice", None)
    if voice is None:
        return "L'écoute n'est pas disponible sur cet appareil."
    if getattr(voice, "muted", False):
        return MICRO_MUET
    return None


def assurer_ecoute(ctx) -> str | None:
    """Démarre l'écoute si elle est arrêtée (c'est elle qui ouvre le micro et remplit le robinet).

    Renvoie None si l'écoute tourne, sinon la raison exacte du refus, telle que l'écoute la donne
    (lunettes absentes, micro introuvable…). On ne démarre JAMAIS en mode confidentiel : start()
    marquerait alors l'écoute comme arrêtée par l'utilisateur, ce qui empêcherait sa relance."""
    raison = empechement_micro(ctx)
    if raison:
        return raison
    voice = ctx.voice
    if voice.running:
        return None
    try:
        voice.start()
    except Exception as exc:  # une panne de démarrage se dit, elle ne remonte pas en 500
        log.warning("démarrage de l'écoute impossible : %s", exc)
        return "L'écoute n'a pas pu démarrer. Vérifiez le micro dans Paramètres › Voix, puis réessayez."
    if voice.running:
        return None
    return (voice.error or "L'écoute n'a pas pu démarrer.").strip()


def liberer_micro(ctx, nom: str) -> None:
    """Éteint le témoin micro SEULEMENT si personne d'autre ne s'en sert (écoute, autres abonnés du robinet)."""
    voice = getattr(ctx, "voice", None)
    try:
        if voice is not None and voice.running:
            return  # l'écoute garde le micro ouvert : le témoin doit rester allumé
        autres = [a for a in (voice.robinet.abonnes() if voice is not None else []) if a != nom]
        if not autres:
            ctx.capture.set(mic=False)
    except Exception as exc:  # pragma: no cover - le témoin ne doit jamais faire échouer un arrêt
        log.debug("témoin micro : %s", exc)


def texte_utile(texte: str) -> str:
    """Nettoie une phrase reconnue ; "" si ce n'est qu'un bruit."""
    texte = " ".join((texte or "").split())
    if not texte or texte.lower() in BRUITS:
        return ""
    return texte[0].upper() + texte[1:]


# ---------------------------------------------------------------------------- fichier entier
def transcrire_pcm(
    reconnaisseur: Any,
    pcm: bytes,
    taux: int = TAUX,
    arret: threading.Event | None = None,
    progression: Callable[[float], None] | None = None,
) -> list[dict]:
    """Transcrit un PCM int16 mono en lignes [{ts (secondes depuis le début), texte}].

    Sert à l'import d'un enregistrement de cours. Même découpage que le direct : une ligne par
    phrase reconnue (fin détectée par le modèle), coupée d'office après SEGMENT_MAX_S de parole
    continue. L'horodatage est le début approximatif de la phrase (à une demi-seconde près)."""
    pas = max(2, (taux // 4) * 2)  # 0,25 s, nombre pair d'octets
    total = len(pcm)
    lignes: list[dict] = []
    debut_phrase: float | None = None
    fin_precedente = 0.0
    dernier_signal = -1.0

    def garder(texte_json: str, position: float) -> None:
        nonlocal debut_phrase, fin_precedente
        texte = texte_utile(stt.VoskEngine.text_of(texte_json))
        if texte:
            ts = debut_phrase if debut_phrase is not None else fin_precedente
            lignes.append({"ts": round(max(0.0, ts), 2), "texte": texte})
        debut_phrase = None
        fin_precedente = position

    for i in range(0, total, pas):
        if arret is not None and arret.is_set():
            break
        position = i / 2 / taux
        if reconnaisseur.AcceptWaveform(pcm[i:i + pas]):
            garder(reconnaisseur.Result(), position + pas / 2 / taux)
        else:
            if debut_phrase is None and stt.VoskEngine.text_of(reconnaisseur.PartialResult(), "partial"):
                # le partiel arrive avec un léger retard sur la voix : on recule d'une demi-seconde
                debut_phrase = max(fin_precedente, position - 0.5)
            if debut_phrase is not None and position - debut_phrase >= SEGMENT_MAX_S:
                garder(reconnaisseur.FinalResult(), position)
        if progression is not None and total:
            fraction = i / total
            if fraction - dernier_signal >= 0.01:
                dernier_signal = fraction
                try:
                    progression(fraction)
                except Exception:  # pragma: no cover
                    pass
    if arret is None or not arret.is_set():
        garder(reconnaisseur.FinalResult(), total / 2 / taux)
    return lignes


# ---------------------------------------------------------------------------- direct
class SousTitres:
    def __init__(self, ctx):
        self.ctx = ctx
        self._verrou = threading.RLock()
        self._demandes: set[str] = set()
        self._fil: threading.Thread | None = None
        self._arret = threading.Event()
        self._lignes: deque[dict] = deque(maxlen=PLAFOND_LIGNES)
        self._abonnes_finals: dict[str, Callable[[float, str], Any]] = {}
        self.raison: str | None = None
        self.partiel = ""
        self._moteur = None
        self._moteur_chemin = None
        # Remplaçable (tests, autre moteur local) : renvoie un reconnaisseur au protocole Vosk
        # (AcceptWaveform, Result, PartialResult, FinalResult).
        self.fabrique_reconnaisseur: Callable[[], Any] = self._reconnaisseur_vosk
        # Appelé à chaque changement d'état (routes_ecoute y branche la publication de ecoute.etat).
        self.notifier: Callable[[], None] = lambda: None

    # ------------------------------------------------------------------ modèle
    def modele_pret(self) -> bool:
        try:
            return stt.model_dir(self.ctx.settings.models_dir, self.ctx.settings.user.language) is not None
        except Exception:
            return False

    def _reconnaisseur_vosk(self):
        """Plein vocabulaire, sur le modèle déjà chargé par l'écoute si c'est le même (41 Mo de moins)."""
        chemin = stt.model_dir(self.ctx.settings.models_dir, self.ctx.settings.user.language)
        if chemin is None:
            raise EcouteImpossible(MODELE_ABSENT)
        voice = getattr(self.ctx, "voice", None)
        moteur = getattr(voice, "_vosk", None)
        if moteur is None or getattr(voice, "_vosk_path", None) != chemin:
            with self._verrou:
                if self._moteur is None or self._moteur_chemin != chemin:
                    self._moteur = stt.VoskEngine(chemin)
                    self._moteur_chemin = chemin
                moteur = self._moteur
        return moteur.recognizer()

    # ------------------------------------------------------------------ état
    @property
    def actif(self) -> bool:
        return self._fil is not None and self._fil.is_alive()

    def demandes(self) -> list[str]:
        with self._verrou:
            return sorted(self._demandes)

    def lignes(self) -> list[dict]:
        with self._verrou:
            return list(self._lignes)

    def abonner_finals(self, nom: str, fonction: Callable[[float, str], Any]) -> None:
        """`fonction(moment_epoch, texte)` est appelée pour chaque phrase finale, depuis le fil de reconnaissance."""
        self._abonnes_finals[nom] = fonction

    def desabonner_finals(self, nom: str) -> None:
        self._abonnes_finals.pop(nom, None)

    def _changer_raison(self, raison: str | None) -> None:
        if raison != self.raison:
            self.raison = raison
            self._notifier()

    def _notifier(self) -> None:
        try:
            self.notifier()
        except Exception as exc:  # pragma: no cover
            log.debug("publication de l'état d'écoute : %s", exc)

    # ------------------------------------------------------------------ contrôle
    def demarrer(self, demande: str = "ecran") -> None:
        """Ajoute une demande et fait tourner la reconnaissance. Lève EcouteImpossible avec la raison."""
        raison = empechement_micro(self.ctx)
        if raison:
            raise EcouteImpossible(raison)
        with self._verrou:
            if self.actif and self._arret.is_set():
                raise EcouteImpossible("Les sous-titres sont en train de s'arrêter : réessayez dans un instant.")
            if demande in self._demandes and self.actif:
                return
        if not self.actif and self.fabrique_reconnaisseur == self._reconnaisseur_vosk and not self.modele_pret():
            raise EcouteImpossible(MODELE_ABSENT)
        raison = assurer_ecoute(self.ctx)
        if raison:
            raise EcouteImpossible(raison)
        with self._verrou:
            nouvelle_session = demande == "ecran" and "ecran" not in self._demandes
            if not self.actif:
                try:
                    reconnaisseur = self.fabrique_reconnaisseur()
                except EcouteImpossible:
                    raise
                except Exception as exc:
                    log.warning("reconnaisseur hors ligne indisponible : %s", exc)
                    # Le détail technique (bibliothèque, chemin du modèle) reste au journal.
                    raise EcouteImpossible("La reconnaissance hors ligne n'a pas pu démarrer. Réinstallez le modèle dans Paramètres › Voix.")
                if nouvelle_session:
                    self._lignes.clear()
                self._arret.clear()
                self.partiel = ""
                self.raison = None
                file = self.ctx.voice.robinet.abonner(NOM_ROBINET, max_blocs=MAX_BLOCS_EN_FILE)
                self._fil = threading.Thread(
                    target=self._boucle, args=(reconnaisseur, file), name="iris-sous-titres", daemon=True
                )
                self._demandes.add(demande)
                self._fil.start()
            else:
                if nouvelle_session:
                    self._lignes.clear()
                self._demandes.add(demande)
        try:
            self.ctx.capture.set(mic=True)
        except Exception:  # pragma: no cover
            pass
        self._notifier()

    def arreter(self, demande: str = "ecran") -> list[dict]:
        """Retire une demande ; la reconnaissance s'arrête quand il n'en reste plus. Renvoie la session."""
        with self._verrou:
            self._demandes.discard(demande)
            reste = bool(self._demandes)
        if not reste:
            self._stopper()
        self._notifier()
        return self.lignes()

    def arreter_tout(self) -> None:
        with self._verrou:
            self._demandes.clear()
        self._stopper()
        self._notifier()

    def _stopper(self) -> None:
        self._arret.set()
        fil = self._fil
        if fil is not None and fil.is_alive() and threading.current_thread() is not fil:
            fil.join(timeout=3)
        # Un fil encore vivant après 3 s (décodage d'un gros bloc) reste référencé : sinon un nouveau
        # démarrage s'abonnerait au robinet sous le même nom, et la fin de l'ancien fil le désabonnerait.
        if fil is not None and not fil.is_alive():
            self._fil = None

    # ------------------------------------------------------------------ fil de reconnaissance
    def _publier_final(self, texte: str, debut: float | None = None) -> None:
        """`debut` : heure (epoch) du premier partiel de la phrase. La ligne est datée du DÉBUT de la phrase,
        comme à l'import d'un fichier, pour qu'un cours en direct et un cours importé se lisent pareil."""
        texte = texte_utile(texte)
        if not texte:
            return
        moment = max(0.0, debut - 0.5) if debut is not None else time.time()
        with self._verrou:
            self._lignes.append({"ts": round(moment, 2), "texte": texte})
        self.partiel = ""
        self.ctx.hub.publish("ecoute.sous_titre", partiel=None, final=texte, ts=moment)
        for nom, fonction in list(self._abonnes_finals.items()):
            try:
                fonction(moment, texte)
            except Exception as exc:  # un abonné en panne (journal, cours) ne coupe pas les sous-titres
                log.warning("abonné %s des sous-titres en erreur : %s", nom, exc)

    def _boucle(self, reconnaisseur: Any, file: "queue.Queue[bytes]") -> None:
        dernier_bloc = time.monotonic()
        dernier_partiel_envoye = 0.0
        partiel_envoye = ""
        debut_phrase: float | None = None  # horloge monotone : durée de la phrase
        debut_epoch: float | None = None  # horloge murale : date de la phrase
        try:
            while not self._arret.is_set():
                try:
                    bloc = file.get(timeout=0.3)
                except queue.Empty:
                    if time.monotonic() - dernier_bloc >= ATTENTE_MICRO_S:
                        self._changer_raison(ATTENTE_MICRO)
                    continue
                dernier_bloc = time.monotonic()
                if self.raison == ATTENTE_MICRO:
                    self._changer_raison(None)
                if reconnaisseur.AcceptWaveform(bloc):
                    self._publier_final(stt.VoskEngine.text_of(reconnaisseur.Result()), debut_epoch)
                    debut_phrase, debut_epoch, partiel_envoye = None, None, ""
                    continue
                partiel = stt.VoskEngine.text_of(reconnaisseur.PartialResult(), "partial")
                if not partiel:
                    continue
                maintenant = time.monotonic()
                if debut_phrase is None:
                    debut_phrase, debut_epoch = maintenant, time.time()
                if maintenant - debut_phrase >= SEGMENT_MAX_S:
                    self._publier_final(stt.VoskEngine.text_of(reconnaisseur.FinalResult()), debut_epoch)
                    debut_phrase, debut_epoch, partiel_envoye = None, None, ""
                    continue
                if partiel != partiel_envoye and maintenant - dernier_partiel_envoye >= PARTIEL_INTERVALLE_S:
                    dernier_partiel_envoye, partiel_envoye = maintenant, partiel
                    self.partiel = partiel
                    self.ctx.hub.publish("ecoute.sous_titre", partiel=partiel, final=None, ts=time.time())
            try:  # la dernière phrase, coupée par l'arrêt, est gardée
                self._publier_final(stt.VoskEngine.text_of(reconnaisseur.FinalResult()), debut_epoch)
            except Exception:
                pass
        except Exception as exc:
            log.exception("sous-titres interrompus")
            with self._verrou:
                self._demandes.clear()
            self.raison = "Les sous-titres se sont arrêtés à cause d'une erreur de reconnaissance. Relancez-les."
        finally:
            try:
                self.ctx.voice.robinet.desabonner(NOM_ROBINET)
            except Exception:  # pragma: no cover
                pass
            liberer_micro(self.ctx, NOM_ROBINET)
            self.partiel = ""
            if self._fil is threading.current_thread():
                self._fil = None
            self._notifier()
