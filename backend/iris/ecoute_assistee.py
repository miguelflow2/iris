"""Écoute assistée (EXPÉRIMENTALE) : le son du micro, débruité et amplifié, rejoué dans les lunettes.

Pour une personne malentendante qui veut entendre un peu plus fort la personne en face d'elle. La
chaîne est entièrement locale : robinet audio (copie des blocs micro) -> réduction de bruit spectrale
-> gain -> limiteur -> plafond -> sortie audio des lunettes. Rien n'est enregistré.

Ce que ce n'est PAS, et qu'il faut dire : une aide auditive. Aucun réglage par fréquence selon un
audiogramme, aucune homologation, et un retard audible :
- le micro livre le son par blocs de 0,25 s (voir voice/robinet.py) : le début de chaque bloc a
  déjà un quart de seconde quand IRIS le reçoit ;
- le Bluetooth mains libres ajoute son propre retard, dans les deux sens, qu'IRIS ne peut pas mesurer.
La latence affichée est MESURÉE (arrivée du bloc -> écriture dans la sortie, plus la latence annoncée
par le périphérique) ; elle ne compte ni ces délais Bluetooth ni la durée du bloc. Elle ne se
garantit pas : elle se lit.

Pourquoi une soustraction spectrale et pas un débruiteur appris : aucun modèle à télécharger, et un
comportement prévisible. Le profil de bruit est appris pendant les 1,5 premières secondes (la sortie
reste muette pendant ce temps, pour ne pas jouer le bruit qu'on apprend), puis suit lentement les
moments calmes.

Garde-fous : la sortie ne se fait JAMAIS vers les haut-parleurs par défaut (un micro amplifié vers un
haut-parleur voisin, c'est l'effet Larsen) ; elle se tait pendant qu'IRIS parle ; elle rend PortAudio
dès que le micro se tait ; le mode confidentiel l'arrête.

Service exposé sous ctx.ecoute_assistee (voir routes_alertes.py).
"""
from __future__ import annotations

import logging
import queue
import statistics
import threading
import time
from collections import deque
from typing import Any

import numpy as np

from .alertes_sonores import CONFIDENTIEL, EcouteRefusee, assurer_ecoute, publier_etat_ecoute

log = logging.getLogger("iris.ecoute_assistee")

TAUX = 16000
TRAME = 512
PAS = 256
DUREE_BLOC = 0.25
APPRENTISSAGE_S = 1.5
LIMITEUR_DB = -6.0  # crête visée par le limiteur (pleine échelle = 0 dB)
PLAFOND_DB = -3.0  # crête absolue : aucun échantillon ne dépasse, quel que soit le gain
ATTENUATION_MAX_DB = 20.0  # réduction de bruit maximale (réglage à 100)
EPS = 1e-12

AVERTISSEMENT = (
    "Écoute assistée expérimentale : elle ne remplace pas une aide auditive et n'est pas un appareil médical."
)

LIMITES = [
    "Le son arrive avec un retard d'au moins un quart de seconde, plus le délai du Bluetooth : utile pour "
    "entendre plus fort, pas pour suivre le mouvement des lèvres.",
    "La réduction de bruit apprend le bruit ambiant pendant les 1,5 premières secondes : restez dans le "
    "bruit habituel au démarrage. Un bruit qui change beaucoup est moins bien réduit.",
    "Le son joue seulement dans la sortie audio choisie (lunettes ou casque), jamais dans les haut-parleurs "
    "du PC, pour éviter l'effet Larsen. Avec un gain élevé, un sifflement reste possible.",
    "Le son se coupe pendant qu'IRIS parle.",
    "Le niveau est plafonné dans IRIS, mais le volume réel dépend aussi du volume des lunettes : "
    "commencez bas.",
]


class SortieIndisponible(Exception):
    """Aucune sortie audio acceptable pour l'écoute assistée ; le message est la raison exacte."""


# --------------------------------------------------------------------------- traitement du signal
class TraitementEcoute:
    """Réduction de bruit spectrale + gain + limiteur + plafond, en flux continu (PCM int16 16 kHz).

    Transformée de Fourier à court terme avec fenêtres racine de Hann recouvrantes à 50 % : sans
    traitement, la reconstruction est exacte (au décalage de TRAME - PAS échantillons près)."""

    def __init__(self, gain_db: float = 6.0, reduction: float = 60.0, apprentissage_s: float = APPRENTISSAGE_S):
        self.gain_db = float(gain_db)
        self.reduction = float(reduction)
        self.apprentissage_s = float(apprentissage_s)
        self._fenetre = np.sqrt(np.hanning(TRAME + 1)[:-1])
        self._entree = np.zeros(TRAME - PAS)
        self._accumulateur = np.zeros(TRAME)
        self._bruit: np.ndarray | None = None
        self._bruit_somme = np.zeros(TRAME // 2 + 1)
        self._trames_apprises = 0
        self._gain_precedent = np.ones(TRAME // 2 + 1)
        self._puissance_lissee: np.ndarray | None = None
        self._gain_limiteur = 1.0
        self.echantillons = 0

    def regler(self, gain_db: float, reduction: float) -> None:
        self.gain_db = float(min(18.0, max(0.0, gain_db)))
        self.reduction = float(min(100.0, max(0.0, reduction)))

    @property
    def apprentissage(self) -> bool:
        """Vrai tant que le profil de bruit n'est pas appris : la sortie est muette."""
        return self._trames_apprises * PAS < self.apprentissage_s * TAUX

    def traiter(self, pcm: bytes) -> bytes:
        brut = bytes(pcm)
        x = np.frombuffer(brut[: len(brut) - len(brut) % 2], dtype=np.int16).astype(np.float64) / 32768.0
        self.echantillons += len(x)
        tampon = np.concatenate([self._entree, x])
        n = (len(tampon) - TRAME) // PAS + 1 if len(tampon) >= TRAME else 0
        if n <= 0:
            self._entree = tampon
            return b""
        index = np.arange(TRAME)[None, :] + PAS * np.arange(n)[:, None]
        spectres = np.fft.rfft(tampon[index] * self._fenetre, axis=1)
        self._entree = tampon[n * PAS:]
        puissance = np.abs(spectres) ** 2
        gains = np.empty_like(puissance)
        for j in range(n):
            gains[j] = self._gain_trame(puissance[j])
        trames = np.fft.irfft(spectres * gains, TRAME, axis=1) * self._fenetre
        sortie = np.empty(n * PAS)
        for j in range(n):
            self._accumulateur += trames[j]
            sortie[j * PAS:(j + 1) * PAS] = self._accumulateur[:PAS]
            self._accumulateur = np.concatenate([self._accumulateur[PAS:], np.zeros(PAS)])
        sortie = self._amplifier(sortie)
        return np.round(sortie * 32767.0).astype(np.int16).tobytes()

    def _gain_trame(self, p: np.ndarray) -> np.ndarray:
        if self.apprentissage:
            self._bruit_somme += p
            self._trames_apprises += 1
            if not self.apprentissage:
                self._bruit = self._bruit_somme / max(1, self._trames_apprises)
            return np.zeros_like(p)
        bruit = self._bruit if self._bruit is not None else p
        # Le profil suit lentement les moments calmes (trame proche du bruit appris), jamais la parole.
        if p.sum() <= 2.0 * bruit.sum():
            self._bruit = 0.98 * bruit + 0.02 * p
        # Puissance lissée sur 3 cases et sur deux trames avant de décider du gain. Case par case, le
        # bruit fluctue tellement qu'une case sur sept dépasse deux fois sa moyenne et laisse passer
        # un « gazouillis » : mesuré sur bruit blanc, 8,8 dB de réduction seulement au réglage 100,
        # contre 17,4 dB avec ce lissage (et un meilleur rapport voix/bruit en sortie).
        lissee = np.convolve(p, np.ones(3) / 3.0, mode="same")
        self._puissance_lissee = lissee if self._puissance_lissee is None else 0.5 * self._puissance_lissee + 0.5 * lissee
        r = self.reduction / 100.0
        if r <= 0:
            return np.ones_like(p)
        plancher = 10 ** (-(ATTENUATION_MAX_DB * r) / 20)
        gain = np.sqrt(np.maximum(0.0, 1.0 - (1.0 + r) * self._bruit / (self._puissance_lissee + EPS)))
        gain = np.maximum(gain, plancher)
        # Ouverture immédiate (la parole n'est pas coupée), fermeture lissée (moins de « bruit musical »).
        gain = np.where(gain >= self._gain_precedent, gain, 0.6 * self._gain_precedent + 0.4 * gain)
        self._gain_precedent = gain
        return gain

    def _amplifier(self, y: np.ndarray) -> np.ndarray:
        y = y * 10 ** (self.gain_db / 20)
        seuil = 10 ** (LIMITEUR_DB / 20)
        plafond = 10 ** (PLAFOND_DB / 20)
        for debut in range(0, len(y), PAS):
            morceau = y[debut:debut + PAS]
            crete = float(np.max(np.abs(morceau))) if len(morceau) else 0.0
            cible = min(1.0, seuil / crete) if crete > 0 else 1.0
            precedent = self._gain_limiteur
            # Attaque immédiate, relâchement sur une dizaine de morceaux (≈ 160 ms) : pas de pompage audible.
            actuel = cible if cible < precedent else min(cible, precedent + 0.1 * (1.0 - precedent))
            y[debut:debut + len(morceau)] = morceau * np.linspace(precedent, actuel, len(morceau), endpoint=False)
            self._gain_limiteur = actuel
        return np.clip(y, -plafond, plafond)


# --------------------------------------------------------------------------- sortie audio réelle
def _score_hote(nom_hote: str) -> int:
    from .voice.elevenlabs import _score_hote as score

    return score(nom_hote)


class FluxSounddevice:
    """Flux de sortie PortAudio ouvert sous VERROU_PORTAUDIO, rendu à la fermeture."""

    def __init__(self, sd: Any, device: int, taux: int, verrou: threading.Lock):
        from .voice.elevenlabs import Reechantillonneur

        self._verrou = verrou
        self._ferme = False
        flux = None
        try:
            flux = sd.RawOutputStream(samplerate=taux, channels=1, dtype="int16",
                                      blocksize=max(1, taux // 20), device=device, latency="low")
            flux.start()
        except Exception:
            if flux is not None:
                try:
                    flux.close()
                except Exception:
                    pass
            verrou.release()
            raise
        self._flux = flux
        self._convertisseur = None if taux == TAUX else Reechantillonneur(TAUX, taux)
        try:
            self.latence_s = float(self._flux.latency)
        except Exception:
            self.latence_s = 0.0

    def ecrire(self, pcm: bytes) -> None:
        if self._ferme or not pcm:
            return
        donnees = self._convertisseur.convertir(pcm) if self._convertisseur is not None else pcm
        self._flux.write(donnees)

    def fermer(self) -> None:
        if self._ferme:
            return
        self._ferme = True
        try:
            self._flux.stop()
            self._flux.close()
        except Exception as exc:
            log.debug("fermeture du flux d'écoute assistée : %s", exc)
        finally:
            self._verrou.release()


class SortieLunettes:
    """Choisit la sortie des lunettes avec la même règle que les voix (classer_sorties) et l'ouvre."""

    def __init__(self, settings: Any):
        self.settings = settings

    def _sounddevice(self) -> Any:
        import sounddevice as sd

        return sd

    def _voulu(self) -> str:
        voulu = (self.settings.user.audio_output_device or "").strip()
        if not voulu:
            raise SortieIndisponible(
                "Aucune sortie audio choisie : l'écoute assistée joue le son dans les lunettes ou un casque choisi "
                "dans Paramètres › Voix, jamais dans les haut-parleurs du PC (effet Larsen).")
        return voulu

    def choisir(self) -> tuple[int, int, str]:
        """(index, fréquence, nom) de la sortie. À appeler SOUS VERROU_PORTAUDIO : le fil du micro peut
        fermer et rouvrir PortAudio pour ré-énumérer, et lister les sorties pendant ce temps plante."""
        voulu = self._voulu()
        from .voice.elevenlabs import classer_sorties, micro_mains_libres

        sd = self._sounddevice()
        try:
            apis = sd.query_hostapis()
            peripheriques = list(sd.query_devices())
        except Exception as exc:
            raise SortieIndisponible(f"Les sorties audio ne peuvent pas être listées : {exc}") from exc
        noms: list[str] = []
        scores: list[int] = []
        index: list[int] = []
        for idx, dev in enumerate(peripheriques):
            try:
                if int(dev.get("max_output_channels", 0) or 0) <= 0:
                    continue
                hote = apis[int(dev.get("hostapi", -1))].get("name") or ""
            except Exception:
                hote = ""
            noms.append(dev.get("name") or "")
            scores.append(_score_hote(hote))
            index.append(idx)
        ordre = classer_sorties(noms, voulu.lower(), micro_mains_libres(self.settings), scores)
        if not ordre:
            raise SortieIndisponible(f"Sortie audio « {voulu} » introuvable : lunettes éteintes ou hors de portée.")
        for position in ordre:
            idx = index[position]
            try:
                natif = int(float(peripheriques[idx].get("default_samplerate") or 0))
            except (TypeError, ValueError):
                natif = 0
            for taux in dict.fromkeys((TAUX, natif)):
                if taux <= 0:
                    continue
                try:
                    sd.check_output_settings(device=idx, samplerate=taux, channels=1, dtype="int16")
                except Exception:
                    continue
                return idx, taux, noms[position]
        raise SortieIndisponible(f"La sortie audio « {voulu} » refuse les fréquences essayées.")

    def verifier(self) -> str:
        """Nom de la sortie qui sera utilisée ; lève SortieIndisponible si aucune ne convient."""
        from .voice.elevenlabs import VERROU_PORTAUDIO

        voulu = self._voulu()
        if not VERROU_PORTAUDIO.acquire(timeout=2.0):
            return voulu  # une voix parle en ce moment : la sortie sera vérifiée à l'ouverture
        try:
            return self.choisir()[2]
        finally:
            VERROU_PORTAUDIO.release()

    def ouvrir(self) -> FluxSounddevice | None:
        """Ouvre le flux, ou None si PortAudio est occupé (une voix d'IRIS a un flux ouvert) : on réessaie."""
        from .voice.elevenlabs import VERROU_PORTAUDIO

        if not VERROU_PORTAUDIO.acquire(blocking=False):
            return None
        try:
            idx, taux, _nom = self.choisir()
        except BaseException:
            VERROU_PORTAUDIO.release()
            raise
        return FluxSounddevice(self._sounddevice(), idx, taux, VERROU_PORTAUDIO)


# --------------------------------------------------------------------------- service
class ServiceEcouteAssistee:
    NOM_ROBINET = "ecoute_assistee"

    def __init__(self, ctx: Any, sortie: Any = None):
        self.ctx = ctx
        self.sortie = sortie if sortie is not None else SortieLunettes(ctx.settings)
        self._verrou = threading.RLock()
        self._fil: threading.Thread | None = None
        self._arret: threading.Event | None = None
        self._traitement: TraitementEcoute | None = None
        self.raison: str | None = None
        self.en_attente_micro = False
        self.pause_voix = False
        self.nom_sortie: str | None = None
        self.latence_ms: int | None = None
        self.mesure_latence = "aucune"
        self.blocs_joues = 0
        self.blocs_sautes = 0
        self._latences: deque[float] = deque(maxlen=20)
        self._tts_fini = 0.0
        self._derniere_publication = 0.0

    @property
    def actif(self) -> bool:
        fil = self._fil
        return fil is not None and fil.is_alive()

    def etat(self) -> dict:
        u = self.ctx.settings.user
        traitement = self._traitement
        return {
            "actif": self.actif,
            "latence_ms": self.latence_ms,
            "mesure_latence": self.mesure_latence,
            "gain_db": u.ecoute_assistee_gain_db,
            "reduction": u.ecoute_assistee_reduction,
            "sortie": self.nom_sortie,
            "apprentissage": bool(self.actif and traitement is not None and traitement.apprentissage),
            "en_attente_micro": self.en_attente_micro,
            "pause_voix": self.pause_voix,
            "blocs_joues": self.blocs_joues,
            "blocs_sautes": self.blocs_sautes,
            "raison": self.raison,
            "experimental": True,
            "local": True,
            "avertissement": AVERTISSEMENT,
            "limites": LIMITES,
        }

    def _publier_etat(self) -> None:
        self._derniere_publication = time.monotonic()
        try:
            self.ctx.hub.publish("ecoute_assistee.etat", **{k: v for k, v in self.etat().items() if k != "limites"})
        except Exception:
            pass
        publier_etat_ecoute(self.ctx)

    # ------------------------------------------------------------------ marche / arrêt
    def demarrer(self, gain_db: int | None = None, reduction: int | None = None) -> dict:
        """Lève EcouteRefusee (mode confidentiel, aucune sortie acceptable)."""
        if self.ctx.settings.user.privacy_mode:
            raise EcouteRefusee(CONFIDENTIEL)
        patch = {}
        if gain_db is not None:
            patch["ecoute_assistee_gain_db"] = gain_db
        if reduction is not None:
            patch["ecoute_assistee_reduction"] = reduction
        if patch:
            user = self.ctx.settings.update(patch)
            self.ctx.hub.publish("settings.updated", settings=user.model_dump())
        try:
            nom = self.sortie.verifier()
        except SortieIndisponible as exc:
            raise EcouteRefusee(str(exc)) from exc
        raison = assurer_ecoute(self.ctx)
        u = self.ctx.settings.user
        with self._verrou:
            self.nom_sortie = nom
            self.raison = raison
            if self.actif:
                if self._traitement is not None:
                    self._traitement.regler(u.ecoute_assistee_gain_db, u.ecoute_assistee_reduction)
                return self.etat()
            file = self.ctx.voice.robinet.abonner(self.NOM_ROBINET, max_blocs=8)  # 2 s au plus : du direct
            arret = threading.Event()
            self._arret = arret
            self._traitement = TraitementEcoute(u.ecoute_assistee_gain_db, u.ecoute_assistee_reduction)
            self._latences.clear()
            self.latence_ms = None
            self.mesure_latence = "aucune"
            self.blocs_joues = self.blocs_sautes = 0
            self.en_attente_micro = self.pause_voix = False
            self._fil = threading.Thread(target=self._boucle, args=(file, arret, self._traitement),
                                         name="iris-ecoute-assistee", daemon=True)
            self._fil.start()
        log.info("écoute assistée démarrée vers « %s »", nom)
        self._publier_etat()
        return self.etat()

    def _arreter_depuis_le_fil(self, arret: threading.Event, raison: str) -> None:
        """Arrêt demandé par le fil lui-même : sans effet si une nouvelle séance a déjà remplacé la sienne."""
        with self._verrou:
            if self._arret is not arret:
                return
        self.arreter(raison)

    def arreter(self, raison: str | None = None) -> dict:
        with self._verrou:
            fil = self._fil
            if self._arret is not None:
                self._arret.set()
            try:
                self.ctx.voice.robinet.desabonner(self.NOM_ROBINET)
            except Exception:
                pass
            self._fil = None
            self._arret = None
            self.raison = raison
            self.en_attente_micro = self.pause_voix = False
        if fil is not None and fil is not threading.current_thread():
            fil.join(timeout=3)
        if fil is not None:
            log.info("écoute assistée arrêtée%s", f" : {raison}" if raison else "")
        self._publier_etat()
        return self.etat()

    # ------------------------------------------------------------------ boucle
    def _tts_parle(self) -> bool:
        tts = getattr(self.ctx, "tts", None)
        try:
            parle = bool(tts is not None and tts.is_speaking)
        except Exception:
            parle = False
        if parle:
            self._tts_fini = time.monotonic()
        return parle or time.monotonic() - self._tts_fini < 0.3

    def _horodatage_bloc(self, plus_recents: int) -> float:
        """Instant d'arrivée du bloc lu, en temps réel.

        Le micro horodate son dernier bloc (VoiceListener._last_block) et en livre un tous les 0,25 s :
        le bloc lu, suivi de `plus_recents` blocs encore en file, est arrivé environ
        plus_recents × 0,25 s avant ce dernier. Sans cet horodatage, on ne mesure que notre propre
        traitement, et l'état le dit (mesure_latence = « partielle »)."""
        maintenant = time.time()
        dernier = getattr(getattr(self.ctx, "voice", None), "_last_block", 0.0)
        if isinstance(dernier, (int, float)) and 0 < maintenant - float(dernier) < 2.0:
            self.mesure_latence = "micro"
            return float(dernier) - plus_recents * DUREE_BLOC
        self.mesure_latence = "partielle"
        return maintenant

    def _boucle(self, file: "queue.Queue[bytes]", arret: threading.Event, traitement: TraitementEcoute) -> None:
        flux = None
        dernier_bloc = time.monotonic()
        try:
            while not arret.is_set():
                if self.ctx.settings.user.privacy_mode:
                    threading.Thread(target=self._arreter_depuis_le_fil, args=(arret, CONFIDENTIEL), daemon=True).start()
                    return
                try:
                    bloc = file.get(timeout=0.3)
                except queue.Empty:
                    if time.monotonic() - dernier_bloc > 1.5:
                        if flux is not None:
                            flux.fermer()  # rend PortAudio : le micro a peut-être disparu et doit être rouvert
                            flux = None
                        if not self.en_attente_micro:
                            self.en_attente_micro = True
                            self._publier_etat()
                    continue
                dernier_bloc = time.monotonic()
                if self.en_attente_micro:
                    self.en_attente_micro = False
                    self._publier_etat()
                # Rattraper le retard : en écoute directe, un son vieux d'une seconde ne sert plus à rien.
                while file.qsize() > 1:
                    try:
                        bloc = file.get_nowait()
                        self.blocs_sautes += 1
                    except queue.Empty:
                        break
                instant = self._horodatage_bloc(file.qsize())
                u = self.ctx.settings.user
                traitement.regler(u.ecoute_assistee_gain_db, u.ecoute_assistee_reduction)
                son = traitement.traiter(bloc)  # toujours traité : le profil de bruit et le recouvrement restent continus
                if self._tts_parle():
                    if flux is not None:
                        flux.fermer()  # la voix d'IRIS a besoin de PortAudio, et on ne joue pas par-dessus
                        flux = None
                    if not self.pause_voix:
                        self.pause_voix = True
                        self._publier_etat()
                    continue
                if self.pause_voix:
                    self.pause_voix = False
                    self._publier_etat()
                if traitement.apprentissage or not son:
                    continue
                if flux is None:
                    try:
                        flux = self.sortie.ouvrir()
                    except SortieIndisponible as exc:
                        threading.Thread(target=self._arreter_depuis_le_fil, args=(arret, str(exc)), daemon=True).start()
                        return
                    except Exception as exc:
                        threading.Thread(target=self._arreter_depuis_le_fil,
                                         args=(arret, f"Sortie audio impossible à ouvrir : {exc}"), daemon=True).start()
                        return
                    if flux is None:
                        continue  # PortAudio occupé par une voix : bloc suivant
                flux.ecrire(son)
                self.blocs_joues += 1
                self._latences.append((time.time() - instant) * 1000.0 + float(getattr(flux, "latence_s", 0.0)) * 1000.0)
                self.latence_ms = int(round(statistics.median(self._latences)))
                if time.monotonic() - self._derniere_publication > 2.0:
                    self._publier_etat()
        except Exception as exc:
            log.warning("écoute assistée interrompue : %s", exc)
            threading.Thread(target=self._arreter_depuis_le_fil, args=(arret, f"Écoute assistée interrompue : {exc}"),
                             daemon=True).start()
        finally:
            if flux is not None:
                try:
                    flux.fermer()
                except Exception:
                    pass
