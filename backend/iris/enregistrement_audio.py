"""Enregistrement audio : un fichier WAV sur l'ordinateur, sur demande explicite, jamais en douce.

Le son vient du robinet audio (voice/robinet.py), donc du même micro que l'écoute : PCM int16 mono
16 kHz, écrit tel quel dans data_dir/captures/audio. Rien ne part sur le réseau.

Garde-fous, tous dits à l'utilisateur :
- un signal vocal court (« Enregistrement. ») si settings.user.annonce_capture — les personnes
  enregistrées ont le droit de le savoir, et le témoin micro s'allume ;
- 4 heures au plus par fichier (≈ 460 Mo) ; au-delà, l'enregistrement s'arrête et le fichier est gardé ;
- l'espace disque est vérifié au départ et pendant l'enregistrement : on s'arrête avant de remplir
  le disque, parce qu'un disque plein fait tomber tout IRIS, pas seulement l'enregistrement ;
- mémoire suspendue (mode invité, zone sans mémoire) ou mode confidentiel : refus, avec la raison.

Le module `wave` réécrit l'en-tête à chaque écriture : si IRIS s'arrête brutalement, le fichier
reste lisible jusqu'au dernier bloc écrit.
"""
from __future__ import annotations

import logging
import queue
import shutil
import threading
import time
import wave
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable

from .sous_titres import ATTENTE_MICRO, ATTENTE_MICRO_S, EcouteImpossible, assurer_ecoute, empechement_micro, liberer_micro
from .voice.robinet import TAUX

log = logging.getLogger("iris.enregistrement")

NOM_ROBINET = "enregistrement"
DUREE_MAX_S = 4 * 3600
OCTETS_PAR_SECONDE = TAUX * 2
ESPACE_MIN_DEMARRAGE = 200 * 1024 * 1024  # en dessous, on ne commence pas
ESPACE_MIN_EN_COURS = 100 * 1024 * 1024  # en dessous, on s'arrête en gardant ce qui est écrit
VERIFICATION_ESPACE_S = 30.0
PREFIXES_GERES = ("enregistrement-", "cours-")  # fichiers dont ce module applique la rétention

DUREE_ATTEINTE = "Enregistrement arrêté : durée maximale de 4 heures atteinte. Le fichier est gardé."
DISQUE_PLEIN = "Enregistrement arrêté : l'espace disque devient insuffisant. Le fichier est gardé."


def dossier_audio(ctx) -> Path:
    dossier = Path(ctx.settings.data_dir) / "captures" / "audio"
    dossier.mkdir(parents=True, exist_ok=True)
    return dossier


def nom_libre(dossier: Path, prefixe: str) -> str:
    base = f"{prefixe}-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    nom, n = f"{base}.wav", 2
    while (dossier / nom).exists():
        nom, n = f"{base}-{n}.wav", n + 1
    return nom


def espace_libre(dossier: Path) -> int:
    try:
        return int(shutil.disk_usage(dossier).free)
    except OSError:  # lecteur réseau, chemin exotique : on ne bloque pas sur une mesure impossible
        return ESPACE_MIN_DEMARRAGE * 10


def memoire_suspendue(ctx) -> str | None:
    memoire = getattr(ctx, "memory", None)
    return getattr(memoire, "suspendue", None) if memoire is not None else None


def annoncer(ctx, texte: str) -> None:
    """Signal vocal court, sans bloquer l'appelant (la voix peut mettre une seconde à partir)."""
    if not getattr(ctx.settings.user, "annonce_capture", True):
        return
    tts = getattr(ctx, "tts", None)
    if tts is None:
        return

    def _dire() -> None:
        try:
            tts.speak(texte, True)
        except Exception as exc:  # pragma: no cover
            log.debug("annonce vocale impossible : %s", exc)

    threading.Thread(target=_dire, name="iris-annonce-capture", daemon=True).start()


def purger_fichiers(dossier: Path, jours: int, prefixes: tuple[str, ...] = PREFIXES_GERES, epargnes: set[str] | None = None) -> list[str]:
    """Rétention : supprime les enregistrements plus vieux que `jours` (0 = illimité). Renvoie les noms supprimés."""
    if not jours or jours <= 0 or not dossier.exists():
        return []
    limite = time.time() - timedelta(days=jours).total_seconds()
    supprimes: list[str] = []
    for chemin in dossier.glob("*.wav"):
        if not chemin.name.startswith(prefixes) or chemin.name in (epargnes or set()):
            continue
        try:
            if chemin.stat().st_mtime < limite:
                chemin.unlink()
                supprimes.append(chemin.name)
        except OSError as exc:
            log.warning("rétention : %s non supprimé (%s)", chemin.name, exc)
    return supprimes


class SessionEnregistrement:
    """Un fichier WAV alimenté par le robinet, dans son propre fil (le callback du micro n'attend jamais le disque)."""

    def __init__(self, ctx, chemin: Path, nom_robinet: str, fin: Callable[[dict], None] | None = None,
                 duree_max_s: float = DUREE_MAX_S):
        self.ctx = ctx
        self.chemin = chemin
        self.nom_robinet = nom_robinet
        self.duree_max_s = duree_max_s
        self._fin = fin
        self._arret = threading.Event()
        self._fil: threading.Thread | None = None
        self.octets_audio = 0
        self.raison: str | None = None  # attente du micro, ou raison de l'arrêt automatique
        self.resultat: dict | None = None
        self.debut = 0.0

    @property
    def nom(self) -> str:
        return self.chemin.name

    @property
    def actif(self) -> bool:
        return self._fil is not None and self._fil.is_alive()

    @property
    def secondes(self) -> float:
        return round(self.octets_audio / OCTETS_PAR_SECONDE, 1)

    def demarrer(self) -> None:
        if espace_libre(self.chemin.parent) < ESPACE_MIN_DEMARRAGE:
            raise EcouteImpossible("Espace disque insuffisant pour enregistrer (moins de 200 Mo libres).")
        fichier = wave.open(str(self.chemin), "wb")
        fichier.setnchannels(1)
        fichier.setsampwidth(2)
        fichier.setframerate(TAUX)
        file = self.ctx.voice.robinet.abonner(self.nom_robinet, max_blocs=240)
        self.debut = time.time()
        self._fil = threading.Thread(target=self._boucle, args=(fichier, file), name=f"iris-{self.nom_robinet}", daemon=True)
        self._fil.start()
        try:
            self.ctx.capture.set(mic=True)
        except Exception:  # pragma: no cover
            pass

    def arreter(self, timeout: float = 5.0) -> dict:
        self._arret.set()
        fil = self._fil
        if fil is not None and fil.is_alive() and threading.current_thread() is not fil:
            fil.join(timeout=timeout)
        return self.resultat or {"nom": self.nom, "secondes": self.secondes, "octets": self._taille()}

    def _taille(self) -> int:
        try:
            return self.chemin.stat().st_size
        except OSError:
            return 0

    def _boucle(self, fichier, file: "queue.Queue[bytes]") -> None:
        dernier_bloc = time.monotonic()
        derniere_verification = time.monotonic()
        raison_fin: str | None = None
        try:
            while not self._arret.is_set():
                try:
                    bloc = file.get(timeout=0.3)
                except queue.Empty:
                    if time.monotonic() - dernier_bloc >= ATTENTE_MICRO_S and self.raison != ATTENTE_MICRO:
                        self.raison = ATTENTE_MICRO
                        self._signaler()
                    continue
                dernier_bloc = time.monotonic()
                if self.raison == ATTENTE_MICRO:
                    self.raison = None
                    self._signaler()
                reste = int(self.duree_max_s * OCTETS_PAR_SECONDE) - self.octets_audio
                if reste <= 0:
                    raison_fin = DUREE_ATTEINTE
                    break
                bloc = bloc[: reste - (reste % 2)]
                fichier.writeframes(bloc)
                self.octets_audio += len(bloc)
                if time.monotonic() - derniere_verification >= VERIFICATION_ESPACE_S:
                    derniere_verification = time.monotonic()
                    if espace_libre(self.chemin.parent) < ESPACE_MIN_EN_COURS:
                        raison_fin = DISQUE_PLEIN
                        break
        except Exception as exc:
            log.exception("enregistrement interrompu")
            raison_fin = "Enregistrement interrompu par une erreur d'écriture. Le fichier est gardé jusqu'au dernier bloc écrit."
        finally:
            try:
                fichier.close()
            except Exception as exc:  # pragma: no cover
                log.warning("fermeture du WAV : %s", exc)
            try:
                self.ctx.voice.robinet.desabonner(self.nom_robinet)
            except Exception:  # pragma: no cover
                pass
            liberer_micro(self.ctx, self.nom_robinet)
            self.raison = raison_fin
            self.resultat = {"nom": self.nom, "secondes": self.secondes, "octets": self._taille()}
            if self._fin is not None:
                try:
                    self._fin({**self.resultat, "raison": raison_fin, "automatique": raison_fin is not None})
                except Exception as exc:  # pragma: no cover
                    log.warning("fin d'enregistrement : %s", exc)

    def _signaler(self) -> None:
        notifier = getattr(self.ctx, "publier_ecoute_etat", None)
        if callable(notifier):
            try:
                notifier()
            except Exception:  # pragma: no cover
                pass


class EnregistreurAudio:
    """L'enregistrement demandé par l'utilisateur (un seul à la fois). Le mode cours a le sien."""

    def __init__(self, ctx):
        self.ctx = ctx
        self._verrou = threading.Lock()
        self.session: SessionEnregistrement | None = None
        self.derniere_raison: str | None = None
        self.notifier: Callable[[], None] = lambda: None

    @property
    def actif(self) -> bool:
        return self.session is not None and self.session.actif

    @property
    def raison(self) -> str | None:
        if self.actif and self.session is not None:
            return self.session.raison
        return self.derniere_raison

    def etat(self) -> dict:
        session = self.session if self.actif else None
        return {
            "actif": session is not None,
            "nom": session.nom if session else None,
            "secondes": session.secondes if session else 0,
        }

    def fichiers_en_cours(self) -> set[str]:
        return {self.session.nom} if self.actif and self.session is not None else set()

    def demarrer(self, annonce: str = "Enregistrement.") -> dict:
        """Lève EcouteImpossible (409) avec la raison exacte si l'enregistrement ne peut pas commencer."""
        with self._verrou:
            if self.actif and self.session is not None:
                raise EcouteImpossible(f"Un enregistrement est déjà en cours ({self.session.nom}).")
            raison = empechement_micro(self.ctx)
            if raison:
                raise EcouteImpossible(raison)
            suspendue = memoire_suspendue(self.ctx)
            if suspendue:
                raise EcouteImpossible(
                    f"Mémorisation suspendue ({suspendue}) : aucun enregistrement n'est conservé tant que ce mode est actif."
                )
            raison = assurer_ecoute(self.ctx)
            if raison:
                raise EcouteImpossible(raison)
            dossier = dossier_audio(self.ctx)
            session = SessionEnregistrement(self.ctx, dossier / nom_libre(dossier, "enregistrement"), NOM_ROBINET, fin=self._fini)
            session.demarrer()
            self.session = session
            self.derniere_raison = None
        annoncer(self.ctx, annonce)
        self.ctx.consent.log("enregistrement_audio_debut", detail=session.nom)
        self._notifier()
        return {"actif": True, "nom": session.nom}

    def arreter(self) -> dict:
        with self._verrou:
            session = self.session
            if session is None or (not session.actif and session.resultat is None):
                raise EcouteImpossible("Aucun enregistrement en cours.")
            resultat = session.arreter()
            self.session = None
        self._notifier()
        return {"nom": resultat["nom"], "secondes": resultat["secondes"], "octets": resultat["octets"]}

    def _fini(self, resultat: dict) -> None:
        """Fin du fil (demandée ou automatique) : le fichier est complet, l'album peut le montrer."""
        self.ctx.hub.publish("album.nouveau", nom=resultat["nom"], genre="audio", octets=resultat["octets"])
        self.ctx.consent.log("enregistrement_audio_fin", detail=f"{resultat['nom']} ({resultat['secondes']} s)")
        if resultat.get("automatique"):
            self.derniere_raison = resultat.get("raison")
            if self.session is not None and self.session.nom == resultat["nom"]:
                self.session = None
            annoncer(self.ctx, "Enregistrement arrêté.")
            self._notifier()

    def _notifier(self) -> None:
        try:
            self.notifier()
        except Exception:  # pragma: no cover
            pass
