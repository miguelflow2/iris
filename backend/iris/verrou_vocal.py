"""Verrou vocal : seule la voix enregistrée du propriétaire déclenche IRIS (interface I, 2026-09-13).

Ce que c'est, sans enjolivure : une vérification DE BASE du locuteur, calculée sur cet ordinateur. Une
voix proche, ou un enregistrement de la voix du propriétaire, peut la tromper ; le mot de passe reste
la vraie protection. On l'écrit là où l'utilisateur la voit (`LIMITE`), pas seulement ici.

Donnée biométrique. Une empreinte vocale sert à reconnaître une personne : c'est une caractéristique
biométrique au sens de la Loi concernant le cadre juridique des technologies de l'information (Québec).
D'où trois règles :
- rien n'est enregistré sans un consentement EXPRÈS (`definir_consentement(True)`), daté et journalisé ;
- l'empreinte est chiffrée (ctx.crypto) et reste sur cet ordinateur ; retirer le consentement l'efface ;
- AUCUN son n'est conservé : chaque échantillon est réduit sur-le-champ à des statistiques (nombre de
  trames, moyenne et moyenne des carrés de 12 coefficients), puis l'audio est jeté.
La fonction est livrée désactivée (réglage `verrou_vocal_actif`) : la création d'une banque de
caractéristiques biométriques doit être déclarée à la Commission d'accès à l'information avant la mise
en marché.

Caractéristiques (numpy seul) : pré-accentuation 0,97 ; fenêtres de Hamming de 25 ms au pas de 10 ms ;
spectre de puissance (512 points) ; banc de 26 filtres mel ; logarithme ; DCT-II orthonormée,
coefficients 1 à 12 (le coefficient 0 suit le volume, pas la voix) ; deltas (régression sur ±2 trames) ;
normalisation cepstrale par soustraction de la moyenne (CMN).

Pourquoi le score porte sur la moyenne cepstrale, et pas sur les trames normalisées. Mesuré sur voix
synthétiques avant d'écrire ce module : après CMN, un modèle à UNE gaussienne diagonale ne sépare plus
deux timbres (distance moyenne des trames ≈ 1,0 pour la même voix comme pour une autre). La CMN retire
justement ce qui distingue le plus un conduit vocal d'un autre : l'enveloppe spectrale moyenne. On garde
donc les deux moitiés que la CMN sépare : la moyenne retirée (timbre + micro) et la covariance des
trames normalisées (variation naturelle de la voix). Le modèle du locuteur est une moyenne et une
covariance diagonale ; le score mesure l'écart entre la moyenne cepstrale de la commande et celle du
modèle, en unités de ce que la variation naturelle permet pour une phrase de cette durée. Les deltas
servent à rejeter ce qui n'est pas de la parole (un ronronnement stable passe le seuil d'énergie, mais
ne module pas).

Conséquence honnête : la moyenne cepstrale dépend aussi du micro. Enregistrer l'empreinte avec le micro
des lunettes puis parler dans celui du portable fait baisser le score : il faut l'enregistrer avec le
micro qu'on utilise.

Calibrage : avec au moins trois échantillons, chacun est comparé au modèle construit avec les autres
(validation croisée). L'écart typique ainsi mesuré fixe l'échelle du score 0-100 pour CETTE voix.
"""
from __future__ import annotations

import json
import logging
import queue
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

log = logging.getLogger("iris.verrou_vocal")

TAUX = 16000
FENETRE = 400  # 25 ms
PAS = 160  # 10 ms
NFFT = 512
NB_FILTRES = 26
NB_COEFS = 12
PREACCENTUATION = 0.97
PLAGE_PAROLE_DB = 30.0  # une trame à plus de 30 dB sous les plus fortes est du silence
PLANCHER_DB = -55.0  # sous ce niveau absolu, rien n'est de la parole exploitable
TRAMES_CORRELEES = 15  # ~150 ms, une syllabe : des trames voisines ne sont pas des observations indépendantes
TRAMES_MIN_ECHANTILLON = 150  # 1,5 s de parole pour un échantillon d'enregistrement
TRAMES_MIN_COMMANDE = 50  # 0,5 s de parole pour juger une commande
MODULATION_MIN = 0.06  # variance moyenne des deltas sous laquelle le son ne module pas (mesuré : bruit blanc
# 0,04, sinusoïde 0,05 ou moins ; voix synthétiques des tests 0,08 à 0,25). Filtre de bon sens, pas une sécurité.
PLANCHER_VARIANCE = 0.05
ECHANTILLONS_REQUIS = 3
ECHANTILLONS_MAX = 8
ECHELLE_SCORE = 5.0  # écart (en unités calibrées) auquel le score vaut 50
ATTENTE_MICRO_S = 3.0
NOM_ROBINET = "verrou-vocal"
VERSION_CONSENTEMENT = "2026-09-13"

LIMITE = (
    "Vérification de base : une voix proche ou un enregistrement peuvent la tromper ; "
    "le mot de passe reste la vraie protection."
)
TEXTE_CONSENTEMENT = (
    "Votre empreinte vocale est une donnée biométrique : elle sert à reconnaître votre voix. "
    "IRIS la calcule et la stocke chiffrée sur cet ordinateur seulement ; elle n'est jamais envoyée. "
    "Aucun enregistrement de votre voix n'est gardé, seulement des mesures. "
    "Vous pouvez l'effacer à tout moment, et retirer votre consentement l'efface."
)
NOTE_LEGALE = (
    "Au Québec, une banque de caractéristiques biométriques doit être déclarée à la Commission d'accès "
    "à l'information avant sa mise en service : cette fonction est livrée désactivée."
)
PHRASE_SUGGEREE = (
    "Le vieux chat gris saute sur la table pendant que je prépare un café bien chaud pour mes amis."
)
CONFIDENTIEL = "Mode confidentiel actif : le micro est coupé, aucun échantillon ne peut être enregistré."
MICRO_MUET = "Micro coupé (muet) : réactivez le micro pour enregistrer votre voix."
ATTENTE_MICRO = "En attente du micro : aucun son reçu depuis quelques secondes."


class RefusVerrouVocal(Exception):
    """Refus explicable ; les routes le rendent avec son code HTTP (403, 409 ou 422)."""

    def __init__(self, message: str, code: int = 409):
        super().__init__(message)
        self.message = message
        self.code = code


def maintenant_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ---------------------------------------------------------------------------- caractéristiques
def _mel(frequence: np.ndarray | float) -> np.ndarray | float:
    return 2595.0 * np.log10(1.0 + np.asarray(frequence) / 700.0)


def _inverse_mel(mel: np.ndarray) -> np.ndarray:
    return 700.0 * (10.0 ** (mel / 2595.0) - 1.0)


def _banc_mel() -> np.ndarray:
    """26 filtres triangulaires de 20 Hz à 8 kHz (la moitié du taux : tout le spectre disponible)."""
    points = _inverse_mel(np.linspace(_mel(20.0), _mel(TAUX / 2), NB_FILTRES + 2))
    cases = np.floor((NFFT + 1) * points / TAUX).astype(int)
    banc = np.zeros((NB_FILTRES, NFFT // 2 + 1))
    for m in range(1, NB_FILTRES + 1):
        gauche, centre, droite = cases[m - 1], cases[m], cases[m + 1]
        for k in range(gauche, centre):
            banc[m - 1, k] = (k - gauche) / max(1, centre - gauche)
        for k in range(centre, droite):
            banc[m - 1, k] = (droite - k) / max(1, droite - centre)
    return banc


def _dct_orthonormee() -> np.ndarray:
    n = NB_FILTRES
    matrice = np.sqrt(2.0 / n) * np.cos(np.pi / n * (np.arange(n)[None, :] + 0.5) * np.arange(n)[:, None])
    matrice[0] /= np.sqrt(2.0)
    return matrice


BANC_MEL = _banc_mel()
DCT = _dct_orthonormee()
HAMMING = np.hamming(FENETRE)


def caracteristiques(pcm: bytes) -> dict[str, Any]:
    """MFCC d'un segment PCM int16 mono 16 kHz, restreints aux trames de parole.

    Renvoie {"n": trames de parole, "moyenne": moyenne cepstrale (12), "carres": moyenne des carrés
    (12), "trames": trames normalisées CMN + deltas (n × 24), "modulation": variance moyenne des deltas}."""
    vide = {"n": 0, "moyenne": np.zeros(NB_COEFS), "carres": np.zeros(NB_COEFS),
            "trames": np.zeros((0, 2 * NB_COEFS)), "modulation": 0.0}
    donnees = bytes(pcm or b"")
    if len(donnees) % 2:
        donnees = donnees[:-1]
    x = np.frombuffer(donnees, dtype=np.int16).astype(np.float64) / 32768.0
    if len(x) < FENETRE + 4 * PAS:
        return vide
    x = np.append(x[0], x[1:] - PREACCENTUATION * x[:-1])
    trames = np.lib.stride_tricks.sliding_window_view(x, FENETRE)[::PAS] * HAMMING
    puissance = np.abs(np.fft.rfft(trames, NFFT)) ** 2 / NFFT
    log_mel = np.log(puissance @ BANC_MEL.T + 1e-10)
    statiques = (log_mel @ DCT.T)[:, 1:NB_COEFS + 1]
    # Deltas sur la suite complète (avant de retirer les silences) : la dérivée garde sa continuité.
    bord = np.pad(statiques, ((2, 2), (0, 0)), mode="edge")
    deltas = (bord[3:-1] - bord[1:-3] + 2.0 * (bord[4:] - bord[:-4])) / 10.0
    energie = 10.0 * np.log10(np.mean(trames ** 2, axis=1) + 1e-12)
    seuil = max(float(np.percentile(energie, 95)) - PLAGE_PAROLE_DB, PLANCHER_DB)
    parole = energie > seuil
    n = int(parole.sum())
    if n < 2:
        return vide
    statiques, deltas = statiques[parole], deltas[parole]
    moyenne = statiques.mean(axis=0)
    return {
        "n": n,
        "moyenne": moyenne,
        "carres": (statiques ** 2).mean(axis=0),
        "trames": np.hstack([statiques - moyenne, deltas]),  # normalisation cepstrale (CMN)
        "modulation": float(deltas.var(axis=0).mean()),
    }


# ---------------------------------------------------------------------------- modèle et score
def construire_modele(echantillons: list[dict]) -> dict[str, np.ndarray] | None:
    """Moyenne cepstrale (pondérée par la durée) et covariance diagonale intra-phrase (trames CMN)."""
    utiles = [e for e in echantillons if int(e.get("n") or 0) > 0]
    if not utiles:
        return None
    poids = np.array([float(e["n"]) for e in utiles])
    moyennes = np.array([np.asarray(e["moyenne"], dtype=np.float64) for e in utiles])
    carres = np.array([np.asarray(e["carres"], dtype=np.float64) for e in utiles])
    total = poids.sum()
    moyenne = (poids[:, None] * moyennes).sum(axis=0) / total
    intra = (poids[:, None] * (carres - moyennes ** 2)).sum(axis=0) / total
    return {"moyenne": moyenne, "variance": np.maximum(intra, PLANCHER_VARIANCE)}


def ecart(moyenne: np.ndarray, n: int, modele: dict[str, np.ndarray]) -> float:
    """Écart quadratique moyen de la moyenne cepstrale, en unités de sa variation attendue.

    Pour une phrase de n trames de la même voix, la moyenne varie d'environ variance / n_eff, où
    n_eff = n / 15 (des trames d'une même syllabe ne sont pas indépendantes) : l'écart vaut alors ≈ 1."""
    n_eff = max(1.0, n / TRAMES_CORRELEES)
    return float(np.mean((np.asarray(moyenne) - modele["moyenne"]) ** 2 / (modele["variance"] / n_eff)))


def calibrer(echantillons: list[dict]) -> float:
    """Écart typique de CETTE voix : chaque échantillon contre le modèle des autres (médiane, au moins 1)."""
    if len(echantillons) < 2:
        return 1.0
    ecarts = []
    for i, echantillon in enumerate(echantillons):
        modele = construire_modele([e for j, e in enumerate(echantillons) if j != i])
        if modele is not None:
            ecarts.append(ecart(echantillon["moyenne"], int(echantillon["n"]), modele))
    return max(1.0, float(np.median(ecarts))) if ecarts else 1.0


def score_depuis_ecart(valeur: float, echelle: float) -> int:
    """0-100 : 100 = identique ; 50 quand l'écart atteint 5 fois l'écart typique de la voix enregistrée."""
    rapport = max(0.0, valeur) / (ECHELLE_SCORE * max(1.0, echelle))
    return int(round(100.0 / (1.0 + rapport ** 2)))


# ---------------------------------------------------------------------------- service
class VerrouVocal:
    """Empreinte vocale du propriétaire, consentement, enregistrement et vérification des commandes."""

    def __init__(self, ctx: Any):
        self.ctx = ctx
        dossier = Path(ctx.settings.data_dir)
        self.fichier = dossier / "empreinte-vocale.bin"
        self.fichier_consentement = dossier / "empreinte-vocale-consentement.json"
        self._verrou = threading.Lock()
        self._occupe = threading.Lock()  # un seul enregistrement à la fois (un seul micro)
        self._echantillons: list[dict] = self._charger()
        self._cache: tuple[dict, float] | None = None  # (modèle, échelle), recalculé à chaque changement

    # ------------------------------------------------------------------ stockage chiffré
    def _charger(self) -> list[dict]:
        try:
            if not self.fichier.is_file():
                return []
            brut = json.loads(self.ctx.crypto.decrypt(self.fichier.read_bytes()))
            echantillons = []
            for e in brut.get("echantillons", []):
                if len(e.get("moyenne", [])) == NB_COEFS and len(e.get("carres", [])) == NB_COEFS:
                    echantillons.append({"n": int(e["n"]), "moyenne": np.array(e["moyenne"], dtype=np.float64),
                                         "carres": np.array(e["carres"], dtype=np.float64),
                                         "cree_le": str(e.get("cree_le") or "")})
            return echantillons[-ECHANTILLONS_MAX:]
        except Exception as exc:
            # Illisible (clé changée, fichier abîmé) : on ne devine rien, l'empreinte est à refaire.
            log.warning("empreinte vocale illisible, à enregistrer de nouveau : %s", exc)
            return []

    def _ecrire(self) -> None:
        contenu = {
            "version": 1,
            "echantillons": [
                {"n": e["n"], "moyenne": [float(v) for v in e["moyenne"]],
                 "carres": [float(v) for v in e["carres"]], "cree_le": e.get("cree_le", "")}
                for e in self._echantillons
            ],
        }
        self.fichier.parent.mkdir(parents=True, exist_ok=True)
        temporaire = self.fichier.with_suffix(".tmp")
        temporaire.write_bytes(self.ctx.crypto.encrypt(json.dumps(contenu)))
        temporaire.replace(self.fichier)

    # ------------------------------------------------------------------ consentement
    def consentement(self) -> dict | None:
        try:
            donnees = json.loads(self.fichier_consentement.read_text(encoding="utf-8"))
            return donnees if donnees.get("accepte") is True else None
        except Exception:
            return None

    def definir_consentement(self, accepte: bool) -> dict:
        if accepte:
            self.fichier_consentement.parent.mkdir(parents=True, exist_ok=True)
            self.fichier_consentement.write_text(json.dumps({
                "accepte": True, "date": maintenant_iso(), "version": VERSION_CONSENTEMENT,
                "texte": TEXTE_CONSENTEMENT,
            }, ensure_ascii=False, indent=2), encoding="utf-8")
            self._journaliser("consentement_biometrique_accorde")
        else:
            # Retirer son consentement, c'est effacer : garder l'empreinte « au cas où » serait la trahir.
            try:
                self.fichier_consentement.unlink(missing_ok=True)
            except OSError as exc:
                log.warning("consentement biométrique : fichier non retiré (%s)", exc)
            self.effacer(journaliser=False)
            self._journaliser("consentement_biometrique_retire")
        self.appliquer()
        return self.etat()

    def _journaliser(self, evenement: str, detail: str = "") -> None:
        try:
            self.ctx.consent.log(evenement, detail=detail)
        except Exception as exc:  # pragma: no cover - le registre ne doit pas faire échouer l'action
            log.debug("registre de confidentialité : %s", exc)

    # ------------------------------------------------------------------ état
    @property
    def pret(self) -> bool:
        return len(self._echantillons) >= ECHANTILLONS_REQUIS

    @property
    def actif(self) -> bool:
        """Le verrou protège-t-il RÉELLEMENT les commandes en ce moment ?"""
        voice = getattr(self.ctx, "voice", None)
        return voice is not None and getattr(voice, "verificateur_locuteur", None) == self.verifier

    def etat(self) -> dict:
        user = self.ctx.settings.user
        return {
            "enregistree": self.pret,
            "echantillons": len(self._echantillons),
            "echantillons_requis": ECHANTILLONS_REQUIS,
            "actif": self.actif,
            "reglage_actif": bool(getattr(user, "verrou_vocal_actif", False)),
            "seuil": int(getattr(user, "verrou_vocal_seuil", 70)),
            "consentement_biometrique": self.consentement() is not None,
            "limite": LIMITE,
            "texte_consentement": TEXTE_CONSENTEMENT,
            "note_legale": NOTE_LEGALE,
            "phrase_suggeree": PHRASE_SUGGEREE,
        }

    def appliquer(self) -> None:
        """Installe le vérificateur quand le réglage est actif ET l'empreinte prête ET consentie ; le retire sinon."""
        voice = getattr(self.ctx, "voice", None)
        if voice is None:
            return
        voulu = (bool(getattr(self.ctx.settings.user, "verrou_vocal_actif", False))
                 and self.pret and self.consentement() is not None)
        installe = getattr(voice, "verificateur_locuteur", None) == self.verifier
        if voulu and not installe:
            voice.verificateur_locuteur = self.verifier
            log.info("verrou vocal installé")
        elif not voulu and installe:
            voice.verificateur_locuteur = None
            log.info("verrou vocal retiré")

    # ------------------------------------------------------------------ échantillons
    def ajouter_echantillon_pcm(self, pcm: bytes) -> dict:
        if self.consentement() is None:
            raise RefusVerrouVocal(
                "Consentement biométrique requis avant d'enregistrer votre voix.", 403)
        mesures = caracteristiques(pcm)
        if mesures["n"] < TRAMES_MIN_ECHANTILLON or mesures["modulation"] < MODULATION_MIN:
            raise RefusVerrouVocal(
                "Trop peu de parole dans cet échantillon : lisez la phrase proposée d'une voix normale, "
                "près du micro, puis réessayez.", 422)
        with self._verrou:
            self._echantillons.append({"n": mesures["n"], "moyenne": mesures["moyenne"],
                                       "carres": mesures["carres"], "cree_le": maintenant_iso()})
            self._echantillons = self._echantillons[-ECHANTILLONS_MAX:]
            self._cache = None
            self._ecrire()
        self.appliquer()
        return {"echantillons": len(self._echantillons), "pret": self.pret}

    def _modele(self) -> tuple[dict, float] | None:
        with self._verrou:
            if self._cache is None and self.pret:
                modele = construire_modele(self._echantillons)
                if modele is not None:
                    self._cache = (modele, calibrer(self._echantillons))
            return self._cache

    def score_pcm(self, pcm: bytes) -> tuple[int | None, str]:
        """(score 0-100, raison) ; score None quand la commande ne peut pas être jugée."""
        calcule = self._modele()
        if calcule is None:
            return None, "empreinte vocale incomplète"
        mesures = caracteristiques(pcm)
        if mesures["n"] < TRAMES_MIN_COMMANDE or mesures["modulation"] < MODULATION_MIN:
            return None, "commande trop courte pour reconnaître la voix : répétez un peu plus longuement"
        modele, echelle = calcule
        return score_depuis_ecart(ecart(mesures["moyenne"], mesures["n"], modele), echelle), ""

    def verifier(self, pcm: bytes) -> tuple[bool, str]:
        """Le vérificateur installé dans l'écoute : (admis, raison). Tout reste sur cet ordinateur."""
        score, raison = self.score_pcm(pcm)
        if score is None:
            return False, raison
        seuil = int(getattr(self.ctx.settings.user, "verrou_vocal_seuil", 70))
        if score >= seuil:
            return True, ""
        return False, f"voix non reconnue (score {score} sur 100, seuil {seuil})"

    def tester_pcm(self, pcm: bytes) -> dict:
        if not self.pret:
            raise RefusVerrouVocal(
                f"Empreinte incomplète : enregistrez au moins {ECHANTILLONS_REQUIS} échantillons.", 409)
        score, raison = self.score_pcm(pcm)
        if score is None:
            raise RefusVerrouVocal(raison[:1].upper() + raison[1:] + ".", 422)
        seuil = int(getattr(self.ctx.settings.user, "verrou_vocal_seuil", 70))
        return {"score": score, "admis": score >= seuil, "seuil": seuil}

    def effacer(self, journaliser: bool = True) -> None:
        with self._verrou:
            self._echantillons = []
            self._cache = None
            try:
                self.fichier.unlink(missing_ok=True)
            except OSError as exc:
                log.warning("empreinte vocale : fichier non supprimé (%s)", exc)
        voice = getattr(self.ctx, "voice", None)
        if voice is not None and getattr(voice, "verificateur_locuteur", None) == self.verifier:
            voice.verificateur_locuteur = None
        if getattr(self.ctx.settings.user, "verrou_vocal_actif", False):
            # Sans empreinte, le réglage « actif » mentirait : il retombe, et l'interface le voit.
            try:
                user = self.ctx.settings.update({"verrou_vocal_actif": False})
                self.ctx.hub.publish("settings.updated", settings=user.model_dump())
            except Exception as exc:  # pragma: no cover
                log.warning("verrou vocal : réglage non remis à faux (%s)", exc)
        if journaliser:
            self._journaliser("empreinte_vocale_effacee")

    # ------------------------------------------------------------------ micro
    def _empechement(self) -> str | None:
        if self.ctx.settings.user.privacy_mode:
            return CONFIDENTIEL
        voice = getattr(self.ctx, "voice", None)
        if voice is None:
            return "L'écoute n'est pas disponible sur cet appareil."
        if getattr(voice, "muted", False):
            return MICRO_MUET
        if not voice.running:
            try:
                voice.start()
            except Exception as exc:
                log.warning("verrou vocal : démarrage de l'écoute impossible (%s)", exc)
                return "L'écoute n'a pas pu démarrer. Vérifiez le micro dans Paramètres › Voix, puis réessayez."
            if not voice.running:
                return (getattr(voice, "error", None) or "L'écoute n'a pas pu démarrer.").strip()
        return None

    def enregistrer(self, secondes: float) -> bytes:
        """Copie `secondes` de son depuis le robinet de l'écoute (bloquant : à appeler dans un fil)."""
        secondes = min(10.0, max(2.0, float(secondes or 4)))
        raison = self._empechement()
        if raison:
            raise RefusVerrouVocal(raison, 409)
        if not self._occupe.acquire(blocking=False):
            raise RefusVerrouVocal("Un enregistrement de voix est déjà en cours.", 409)
        robinet = self.ctx.voice.robinet
        file = robinet.abonner(NOM_ROBINET, max_blocs=int(secondes * 4) + 8)
        try:
            voulu = int(secondes * TAUX) * 2
            blocs: list[bytes] = []
            recu = 0
            dernier = time.monotonic()
            limite = dernier + secondes + 2 * ATTENTE_MICRO_S
            while recu < voulu and time.monotonic() < limite:
                try:
                    bloc = file.get(timeout=0.25)
                except queue.Empty:
                    if time.monotonic() - dernier > ATTENTE_MICRO_S:
                        raise RefusVerrouVocal(ATTENTE_MICRO, 409)
                    continue
                dernier = time.monotonic()
                blocs.append(bloc)
                recu += len(bloc)
            if recu < voulu // 2:
                raise RefusVerrouVocal(ATTENTE_MICRO, 409)
            return b"".join(blocs)[:voulu]
        finally:
            robinet.desabonner(NOM_ROBINET)
            self._occupe.release()
