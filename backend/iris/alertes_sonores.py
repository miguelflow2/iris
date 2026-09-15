"""Alertes sonores locales : alarme, sirène, klaxon, sonnette, coups frappés, prénom.

Pensé d'abord pour une personne sourde ou malentendante, qui n'entend pas l'avertisseur de fumée de
la pièce voisine ni la sonnette de la porte. IRIS écoute une COPIE du micro (le robinet audio, voir
voice/robinet.py) et y cherche quelques motifs sonores précis avec du traitement du signal simple :
transformée de Fourier par trames de 32 ms (numpy), niveau de bruit appris en continu, puis des
règles écrites à la main pour chaque son. Aucun modèle appris, aucun envoi : tout reste sur
l'ordinateur, et rien n'est enregistré (les trames sont oubliées après quelques secondes).

Ce que ce détecteur N'EST PAS, et qu'il faut dire partout où il est proposé : un avertisseur
homologué. Il rate des sons (micro trop loin, bruit ambiant fort, alarme au timbre inhabituel) et il
se trompe parfois (un instrument, une sonnerie de téléphone). Il ne remplace ni un avertisseur de
fumée ou de monoxyde de carbone, ni un avertisseur lumineux ou à vibration pour personnes sourdes.

Pourquoi des règles et pas un réseau de neurones : on ne télécharge aucun modèle (règle du chantier),
et chaque règle se lit, se teste sur un signal synthétique et s'explique à l'utilisateur. Les seuils
suivent le réglage alertes_sensibilite (0 = seulement les sons nets, 100 = aussi les sons faibles, au
prix de fausses alertes plus fréquentes).

Le prénom est à part : il passe par la reconnaissance vocale locale, restreinte à un seul mot (le
prénom tiré de settings.user_name), exactement comme le mot d'activation dans listener.py.

Service exposé sous ctx.alertes (voir routes_alertes.py).
"""
from __future__ import annotations

import json
import logging
import queue
import re
import threading
import time
import unicodedata
from collections import deque
from typing import Any, Callable

import numpy as np

from .config import TYPES_ALERTES

log = logging.getLogger("iris.alertes")

# --------------------------------------------------------------------------- découpage du signal
TAUX = 16000  # Hz, comme le robinet
TRAME = 512  # 32 ms : assez court pour séparer les bips d'une alarme T4 (0,1 s)
PAS = 256  # 16 ms entre deux trames
DT = PAS / TAUX
RES = TAUX / TRAME  # 31,25 Hz par case de fréquence
DUREE_BLOC = 0.25  # durée d'un bloc du robinet
HISTORIQUE_S = 8.0  # une sirène lente met plusieurs secondes à monter puis redescendre
FOND_S = 6.0  # fenêtre du niveau de bruit adaptatif
FOND_CENTILE = 15  # le bruit, c'est ce qu'on entend la plupart du temps quand rien ne se passe
ECHAUFFEMENT_S = 1.0  # avant, le niveau de bruit n'est pas encore appris : on ne signale rien
ANTI_REBOND_S = 8.0  # une même alarme qui continue ne répète pas son alerte toutes les secondes
NIV_MIN = -62.0  # dB (valeur efficace, pleine échelle = 0 dB) : en dessous, trop faible pour juger
PLANCHER_CASE = 1e-11  # puissance minimale par case : un silence numérique parfait ne divise pas par zéro
EPS = 1e-12

TYPES_ACOUSTIQUES = ("alarme", "sirene", "klaxon", "sonnette", "porte")

INFOS: dict[str, dict[str, str]] = {
    "alarme": {"libelle": "Alarme (fumée ou monoxyde de carbone)", "annonce": "Son d'alarme détecté."},
    "sirene": {"libelle": "Sirène de véhicule d'urgence", "annonce": "Sirène détectée."},
    "klaxon": {"libelle": "Klaxon", "annonce": "Klaxon détecté."},
    "sonnette": {"libelle": "Sonnette", "annonce": "Sonnette détectée."},
    "porte": {"libelle": "Coups frappés (porte)", "annonce": "Coups frappés détectés."},
    "prenom": {"libelle": "Votre prénom", "annonce": "Votre prénom a peut-être été prononcé."},
}

AVERTISSEMENT = (
    "Les alertes sonores d'IRIS ne remplacent pas un avertisseur homologué : gardez vos avertisseurs de "
    "fumée et de monoxyde de carbone, et un avertisseur lumineux ou à vibration si vous êtes sourd ou "
    "malentendant."
)

LIMITES = [
    "IRIS n'entend que ce que capte le micro choisi : lunettes éteintes, micro coupé ou mode confidentiel, "
    "et aucune alerte n'est possible.",
    "Détection par règles simples sur l'ordinateur : certains sons sont manqués (bruit ambiant fort, son "
    "lointain, timbre inhabituel) et d'autres sont pris à tort pour une alerte (instrument, sonnerie).",
    "Avec le micro mains libres des lunettes, le son est limité à la qualité téléphone : les alarmes très "
    "aiguës peuvent être atténuées.",
    "Une sonnette ou des coups frappés sont confirmés environ une seconde après le dernier son, et passent "
    "souvent inaperçus pendant une conversation ou devant la télévision.",
    "Un son d'orgue ou de cuivre tenu peut être pris pour un klaxon.",
    "Le prénom passe par la reconnaissance vocale locale : un prénom rare, absent de son vocabulaire, ou "
    "très court est mal reconnu.",
]

CONFIDENTIEL = "Mode confidentiel actif : aucune écoute ne démarre tant qu'il l'est."


class PrenomHorsVocabulaire(LookupError):
    """Le prénom n'existe pas dans le lexique du modèle local : la grammaire restreinte l'ignorerait."""


def mot_connu(modele: Any, mot: str) -> bool:
    """Le mot est-il dans le lexique du modèle de reconnaissance locale ? Vrai quand on ne peut pas le savoir
    (modèle sans cette fonction) : on ne déclare pas une panne qu'on n'a pas constatée."""
    for nom in ("vosk_model_find_word", "find_word"):
        chercher = getattr(modele, nom, None)
        if callable(chercher):
            try:
                return int(chercher(mot)) >= 0
            except Exception as exc:
                log.debug("lexique du modèle illisible : %s", exc)
                return True
    return True


class EcouteRefusee(Exception):
    """Le service ne peut pas écouter maintenant ; le message est la raison exacte (réponse 409)."""


# --------------------------------------------------------------------------- outils
def _case(hz: float) -> int:
    return int(round(hz / RES))


def _db(x: Any) -> Any:
    return 10.0 * np.log10(np.maximum(x, EPS))


def _segments(masque: np.ndarray, trou_max: int = 0) -> list[tuple[int, int]]:
    """Plages [début, fin] (incluses) où le masque est vrai, en soudant les trous de `trou_max` trames."""
    idx = np.flatnonzero(masque)
    if len(idx) == 0:
        return []
    plages: list[tuple[int, int]] = []
    debut = precedent = int(idx[0])
    for i in idx[1:]:
        i = int(i)
        if i - precedent - 1 > trou_max:
            plages.append((debut, precedent))
            debut = i
        precedent = i
    plages.append((debut, precedent))
    return plages


def _pente(t: np.ndarray, y: np.ndarray) -> float:
    """Pente (unités par seconde) de la droite des moindres carrés ; 0 s'il n'y a pas de quoi juger."""
    if len(t) < 3:
        return 0.0
    tc = t - t.mean()
    den = float(np.sum(tc * tc))
    return float(np.sum(tc * (y - y.mean())) / den) if den > 0 else 0.0


def _confiance(marge_db: float, bonus: float = 0.0) -> float:
    """Marge au-dessus du seuil (dB) -> confiance entre 0,5 et 0,99. Une indication, pas une probabilité."""
    valeur = 0.5 + 0.45 * (1.0 - float(np.exp(-max(0.0, marge_db) / 10.0))) + bonus
    return float(min(0.99, max(0.5, valeur)))


def _mediane_glissante(x: np.ndarray, largeur: int = 5) -> np.ndarray:
    if len(x) < largeur:
        return x.copy()
    demi = largeur // 2
    bord = np.concatenate([np.full(demi, x[0]), x, np.full(demi, x[-1])])
    fenetres = np.lib.stride_tricks.sliding_window_view(bord, largeur)
    return np.median(fenetres, axis=1)


def _inversions(f: np.ndarray, hysteresis: float) -> int:
    """Nombre de changements de sens d'une trajectoire de fréquence, en ignorant les petites oscillations."""
    if len(f) < 3:
        return 0
    sens = 0  # 1 = monte, -1 = descend, 0 = pas encore décidé
    extreme = float(f[0])
    inversions = 0
    for valeur in f[1:]:
        valeur = float(valeur)
        if sens == 0:
            if abs(valeur - extreme) > hysteresis:
                sens = 1 if valeur > extreme else -1
                extreme = valeur
        elif sens == 1:
            if valeur > extreme:
                extreme = valeur
            elif extreme - valeur > hysteresis:
                inversions += 1
                sens, extreme = -1, valeur
        else:
            if valeur < extreme:
                extreme = valeur
            elif valeur - extreme > hysteresis:
                inversions += 1
                sens, extreme = 1, valeur
    return inversions


class _Historique:
    """Caractéristiques par trame, en colonnes numpy alignées, bornées aux dernières secondes."""

    def __init__(self, max_trames: int):
        self.max = max_trames
        self.colonnes: dict[str, np.ndarray] = {}

    def ajouter(self, **colonnes: np.ndarray) -> None:
        for nom, valeurs in colonnes.items():
            valeurs = np.asarray(valeurs, dtype=np.float64)
            ancien = self.colonnes.get(nom)
            nouveau = valeurs if ancien is None else np.concatenate([ancien, valeurs])
            self.colonnes[nom] = nouveau[-self.max:]

    def __getitem__(self, nom: str) -> np.ndarray:
        return self.colonnes[nom]

    def __len__(self) -> int:
        t = self.colonnes.get("t")
        return 0 if t is None else len(t)


# --------------------------------------------------------------------------- détecteur acoustique
class DetecteurAcoustique:
    """Reçoit des blocs PCM int16 mono 16 kHz, rend les alertes reconnues.

    Tout est horodaté en temps AUDIO (secondes de son analysées depuis la création) : le même signal
    donne toujours le même résultat, en direct comme dans les tests. En direct, le robinet livre les
    blocs au rythme réel, donc temps audio et temps réel avancent ensemble.
    """

    def __init__(self, sensibilite: int = 50, anti_rebond_s: float = ANTI_REBOND_S):
        self.sensibilite = sensibilite
        self.anti_rebond_s = float(anti_rebond_s)
        self._fenetre = np.hanning(TRAME + 1)[:-1]
        # Normalisation : la somme des cases d'une bande donne la puissance moyenne du signal dans
        # cette bande (théorème de Parseval, fenêtre de Hann comprise).
        self._norme = 2.0 / (TRAME * float(np.sum(self._fenetre ** 2)))
        self._reste = np.zeros(0, dtype=np.float64)
        self._trames = 0
        self._echantillons = 0
        self._spectres = np.zeros((0, TRAME // 2 + 1))
        self._h = _Historique(int(HISTORIQUE_S / DT))
        self._derniere: dict[str, float] = {t: -1e9 for t in TYPES_ACOUSTIQUES}
        self._vu: dict[str, float] = {"sonnette": -1e9, "porte": -1e9}

    # ------------------------------------------------------------------ entrée
    @property
    def maintenant(self) -> float:
        return self._echantillons / TAUX

    @property
    def k(self) -> float:
        """Sensibilité ramenée à [-1, 1] : -1 = stricte, 0 = défaut, 1 = permissive."""
        try:
            s = float(self.sensibilite)
        except (TypeError, ValueError):
            s = 50.0
        return (min(100.0, max(0.0, s)) - 50.0) / 50.0

    def traiter(self, bloc: bytes | np.ndarray) -> list[dict]:
        """Analyse un bloc ; rend [{"type", "confiance", "t"}] pour chaque son reconnu à l'instant."""
        if isinstance(bloc, (bytes, bytearray, memoryview)):
            brut = bytes(bloc)
            x = np.frombuffer(brut[: len(brut) - len(brut) % 2], dtype=np.int16)
        else:
            x = np.asarray(bloc)
        if len(x) == 0:
            return []
        x = x.astype(np.float64) / 32768.0
        self._echantillons += len(x)
        tampon = np.concatenate([self._reste, x])
        n = (len(tampon) - TRAME) // PAS + 1 if len(tampon) >= TRAME else 0
        if n <= 0:
            self._reste = tampon
            return []
        index = np.arange(TRAME)[None, :] + PAS * np.arange(n)[:, None]
        trames = tampon[index] * self._fenetre
        self._reste = tampon[n * PAS:]
        spectre = (np.abs(np.fft.rfft(trames, axis=1)) ** 2) * self._norme + PLANCHER_CASE
        t = (self._trames + np.arange(n)) * DT + TRAME / 2 / TAUX
        self._trames += n
        self._spectres = np.concatenate([self._spectres, spectre])[-int(FOND_S / DT):]
        # Niveau de bruit adaptatif, case par case : le 15e centile des six dernières secondes. Un son
        # bref ou intermittent ne le déplace pas ; un bruit de fond qui change (ventilation, rue) oui.
        rang = int(FOND_CENTILE / 100 * (len(self._spectres) - 1))
        fond = np.partition(self._spectres, rang, axis=0)[rang] + PLANCHER_CASE
        self._h.ajouter(**self._caracteristiques(spectre, fond, t))
        if self.maintenant < ECHAUFFEMENT_S:
            return []
        return self._evaluer()

    # ------------------------------------------------------------------ caractéristiques par trame
    def _pic(self, P: np.ndarray, fond: np.ndarray, lo: float, hi: float) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
        """Pic dominant dans [lo, hi] Hz : (fréquence interpolée, puissance ±2 cases, bruit ±2 cases, case)."""
        a, b = _case(lo), _case(hi)
        k = np.argmax(P[:, a:b + 1], axis=1) + a
        lignes = np.arange(len(P))
        voisins = np.clip(k[:, None] + np.arange(-2, 3)[None, :], 0, P.shape[1] - 1)
        puissance = np.take_along_axis(P, voisins, axis=1).sum(axis=1)
        bruit = fond[voisins].sum(axis=1)
        g = np.log(P[lignes, np.clip(k - 1, 0, None)])
        c = np.log(P[lignes, k])
        d = np.log(P[lignes, np.clip(k + 1, None, P.shape[1] - 1)])
        den = g - 2 * c + d
        delta = np.where(np.abs(den) > 1e-9, 0.5 * (g - d) / np.where(np.abs(den) > 1e-9, den, 1.0), 0.0)
        frequence = (k + np.clip(delta, -0.5, 0.5)) * RES
        return frequence, puissance, bruit, k

    def _sauts_locaux(self, k: np.ndarray, n: int, demi_largeur: int = 2) -> np.ndarray:
        """Montée (dB) de la puissance autour de la case k par rapport aux trames d'il y a 50 à 100 ms."""
        S = self._spectres
        lignes = len(S) - n + np.arange(n)
        cases = np.clip(np.asarray(k)[:, None] + np.arange(-demi_largeur, demi_largeur + 1)[None, :], 0, S.shape[1] - 1)
        maintenant = S[lignes[:, None], cases].sum(axis=1)
        # Au tout début, faute de passé, la trame se compare à la plus ancienne disponible.
        avant = np.clip(lignes[:, None] - np.arange(3, 7)[None, :], 0, None)
        reference = S[avant[:, :, None], cases[:, None, :]].sum(axis=2).mean(axis=1)
        return _db(maintenant) - _db(reference)

    def _caracteristiques(self, P: np.ndarray, fond: np.ndarray, t: np.ndarray) -> dict[str, np.ndarray]:
        n = len(P)
        blanchi = P / fond
        a, b = _case(156), _case(7500)
        tot = P[:, a:b].sum(axis=1) + EPS
        niv = _db(tot)
        snr_tot = niv - _db(fond[a:b].sum())

        # Montée d'énergie large bande par rapport aux trames d'il y a 50 à 100 ms (attaque d'un son).
        puissance_passee = np.concatenate([self._h["niv"], niv]) if len(self._h) else niv
        puissance_passee = 10 ** (puissance_passee / 10)
        rangs = len(puissance_passee) - n + np.arange(n)
        avant = np.clip(rangs[:, None] - np.arange(3, 7)[None, :], 0, None)
        saut = niv - _db(puissance_passee[avant].mean(axis=1))

        # Pic dominant global (±2 cases) : sa part de l'énergie dit si le son est tonal ou large bande.
        cumul = np.concatenate([np.zeros((n, 1)), np.cumsum(P[:, a:b], axis=1)], axis=1)
        fenetres5 = cumul[:, 5:] - cumul[:, :-5]
        kg = np.argmax(fenetres5, axis=1) + a + 2
        part_g = fenetres5.max(axis=1) / tot
        saut_pic = self._sauts_locaux(kg, n)
        saut_g = np.maximum(saut, saut_pic)

        # Alarme : tonalité étroite 2,4-4,1 kHz, comparée à la bande 1,5-7,5 kHz (un grondement grave ne la masque pas).
        al_f, al_pk, al_bruit, al_k = self._pic(P, fond, 2400, 4100)
        al_ref = P[:, _case(1500):b].sum(axis=1) + EPS
        al_part = al_pk / al_ref
        al_snr = _db(al_pk) - _db(al_bruit)
        # Pureté : un bip d'avertisseur est une raie isolée ; une zone de formant de la voix aligne
        # plusieurs harmoniques voisines (une tous les 100 à 250 Hz) dans ±250 Hz.
        voisinage = np.clip(al_k[:, None] + np.arange(-8, 9)[None, :], 0, P.shape[1] - 1)
        al_pur = al_pk / (np.take_along_axis(P, voisinage, axis=1).sum(axis=1) + EPS)
        # Une harmonique de parole ou de musique a une fondamentale plus grave, plus forte qu'elle ;
        # un avertisseur piézoélectrique, non. On mesure le plus fort sous-multiple f/2, f/3, f/4.
        lignes = np.arange(n)[:, None]
        trois = np.arange(-1, 2)[None, :]
        derniere_case = P.shape[1] - 1
        al_pic_blanchi = blanchi[lignes, np.clip(al_k[:, None] + trois, 0, derniere_case)].max(axis=1)
        pire = np.zeros(n)
        for div in (2, 3, 4):
            c = np.rint(al_f / div / RES).astype(int)
            pire = np.maximum(pire, blanchi[lignes, np.clip(c[:, None] + trois, 0, derniere_case)].max(axis=1))
        al_sous = _db(pire) - _db(al_pic_blanchi)

        # Sirène : tonalité dominante 450-1900 Hz, sans énergie propre plus grave (la parole en a).
        si_f, si_pk, si_bruit, si_k = self._pic(P, fond, 450, 1900)
        si_ref = P[:, _case(250):_case(4000)].sum(axis=1) + EPS
        si_part = si_pk / si_ref
        si_snr = _db(si_pk) - _db(si_bruit)
        haut = np.rint(0.75 * si_f / RES).astype(int)
        cases = np.arange(P.shape[1])[None, :]
        dessous = (cases >= _case(250)) & (cases < haut[:, None])
        si_pic_blanchi = blanchi[lignes, np.clip(si_k[:, None] + trois, 0, derniere_case)].max(axis=1)
        si_bas = np.where(dessous.any(axis=1),
                          _db(np.where(dessous, blanchi, 0.0).max(axis=1)) - _db(si_pic_blanchi), -60.0)

        # Sonnette : attaque tonale 480-2600 Hz.
        so_f, so_pk, so_bruit, so_k = self._pic(P, fond, 480, 2600)
        so_ref = P[:, _case(250):_case(5000)].sum(axis=1) + EPS
        so_part = so_pk / so_ref
        so_snr = _db(so_pk) - _db(so_bruit)
        # ±1 case seulement : les notes d'un carillon sont parfois à un ton d'écart (60 Hz, deux cases),
        # et la note précédente, encore sonore, masquerait l'attaque de la suivante.
        so_saut = self._sauts_locaux(so_k, n, demi_largeur=1)

        # Klaxon : plusieurs raies fortes entre 250 et 3000 Hz, la plus grave entre 280 et 720 Hz.
        kl_f = np.zeros(n)
        kl_npics = np.zeros(n)
        kl_conc = np.zeros(n)
        c0, c1 = _case(250), _case(3000)
        for r in range(n):
            if snr_tot[r] < 8:
                continue
            seg = P[r, c0:c1 + 1]
            bruit = fond[c0:c1 + 1]
            locaux = np.flatnonzero((seg[1:-1] > seg[:-2]) & (seg[1:-1] >= seg[2:])) + 1
            if len(locaux) == 0:
                continue
            forts = locaux[(seg[locaux] >= bruit[locaux] * 10 ** 1.5) & (seg[locaux] >= seg.max() * 10 ** -2.5)]
            if len(forts) == 0:
                continue
            kl_npics[r] = len(forts)
            cumul_seg = np.concatenate([[0.0], np.cumsum(seg)])
            kl_conc[r] = float(np.sum(cumul_seg[np.minimum(forts + 2, len(seg))] - cumul_seg[np.maximum(forts - 1, 0)])) / tot[r]
            c = int(forts[0])
            if 0 < c < len(seg) - 1:
                g, m, d = np.log(seg[c - 1]), np.log(seg[c]), np.log(seg[c + 1])
                den = g - 2 * m + d
                delta = 0.5 * (g - d) / den if abs(den) > 1e-9 else 0.0
            else:
                delta = 0.0
            kl_f[r] = (c0 + c + float(np.clip(delta, -0.5, 0.5))) * RES

        # Coups frappés : impulsion large bande (plusieurs bandes au-dessus du bruit à la fois).
        n_large = np.zeros(n)
        for lo, hi in ((156, 700), (700, 2000), (2000, 5000)):
            ca, cb = _case(lo), _case(hi)
            n_large += (P[:, ca:cb].sum(axis=1) / fond[ca:cb].sum()) >= 10 ** 0.8

        return {
            "t": t, "niv": niv, "snr_tot": snr_tot, "saut_g": saut_g, "part_g": part_g,
            "al_f": al_f, "al_part": al_part, "al_snr": al_snr, "al_sous": al_sous, "al_pur": al_pur,
            "si_f": si_f, "si_part": si_part, "si_snr": si_snr, "si_bas": si_bas,
            "so_f": so_f, "so_part": so_part, "so_snr": so_snr, "so_saut": so_saut,
            "kl_f": kl_f, "kl_npics": kl_npics, "kl_conc": kl_conc, "n_large": n_large,
        }

    # ------------------------------------------------------------------ règles
    def _evaluer(self) -> list[dict]:
        h = self._h
        k = self.k
        maintenant = self.maintenant
        trouvees: list[dict] = []
        for type_, regle in (("alarme", self._regle_alarme), ("sirene", self._regle_sirene),
                             ("klaxon", self._regle_klaxon), ("sonnette", self._regle_sonnette),
                             ("porte", self._regle_porte)):
            if maintenant - self._derniere[type_] < self.anti_rebond_s:
                continue
            try:
                confiance = regle(h, k, maintenant)
            except Exception as exc:  # une règle en erreur ne doit pas faire taire les autres
                log.warning("règle d'alerte %s en erreur : %s", type_, exc)
                confiance = None
            if confiance is not None:
                self._derniere[type_] = maintenant
                trouvees.append({"type": type_, "confiance": round(confiance, 2), "t": round(maintenant, 3)})
        return trouvees

    def _depuis(self, h: _Historique, type_: str, fenetre_s: float, maintenant: float) -> np.ndarray:
        """Trames utilisables par une règle : récentes, et postérieures à la dernière alerte du même type."""
        return (h["t"] > maintenant - fenetre_s) & (h["t"] > self._derniere[type_])

    def _regle_alarme(self, h: _Historique, k: float, maintenant: float) -> float | None:
        """Au moins trois bips de même hauteur (2,4-4,1 kHz) qui s'allument et s'éteignent (motifs T3 et T4)."""
        seuil_snr = 15 - 6 * k
        allume = (self._depuis(h, "alarme", 6.0, maintenant) & (h["al_snr"] >= seuil_snr)
                  & (h["al_part"] >= 0.45 - 0.15 * k) & (h["al_pur"] >= 0.8) & (h["al_sous"] <= -8)
                  & (h["niv"] >= NIV_MIN))
        dernier = len(allume) - 1
        bips = []
        for i0, i1 in _segments(allume, trou_max=1):
            if i1 >= dernier - 1:
                continue  # bip en cours : on attend qu'il s'éteigne
            duree = (i1 - i0 + 1) * DT
            if not 0.07 <= duree <= 1.3:
                continue
            sel = np.arange(i0, i1 + 1)[allume[i0:i1 + 1]]
            hauteurs = h["al_f"][sel]
            mediane = float(np.median(hauteurs))
            # Un avertisseur tient sa note au Hz près pendant le bip ; une voix glisse (intonation).
            if float(np.percentile(hauteurs, 90) - np.percentile(hauteurs, 10)) > 0.02 * mediane:
                continue
            bips.append((i0, i1, mediane, float(np.median(h["al_snr"][sel]))))
        # Trois bips consécutifs de même hauteur, RÉGULIERS : mêmes durées et mêmes silences, comme
        # le motif normalisé T3 (0,5 s / 0,5 s) ou T4 (0,1 s / 0,1 s). Une voix peut aligner trois
        # harmoniques aiguës de même hauteur, pas à ce rythme de métronome.
        def regulier(a: float, b: float) -> bool:
            return max(a, b) <= 1.5 * min(a, b) or abs(a - b) <= 0.05

        meilleure = 0
        marges: list[float] = []
        for i in range(len(bips) - 2):
            trio = bips[i:i + 3]
            if any(abs(b[2] - trio[0][2]) > 0.06 * trio[0][2] for b in trio):
                continue
            durees = [(b[1] - b[0] + 1) * DT for b in trio]
            silences = [(trio[j + 1][0] - trio[j][1]) * DT for j in range(2)]
            if not all(0.05 <= x <= 2.0 for x in silences):
                continue
            if not (regulier(min(durees), max(durees)) and regulier(silences[0], silences[1])):
                continue
            meilleure += 1
            marges.extend(b[3] - seuil_snr for b in trio)
        if meilleure == 0:
            return None
        return _confiance(float(np.median(marges)), 0.02 * (meilleure - 1))

    def _regle_sirene(self, h: _Historique, k: float, maintenant: float) -> float | None:
        """Une tonalité dominante qui balaie 450-1900 Hz sans à-coups, en montant et descendant."""
        seuil_snr = 12 - 6 * k
        ton = (self._depuis(h, "sirene", HISTORIQUE_S, maintenant) & (h["si_snr"] >= seuil_snr)
               & (h["si_part"] >= 0.5 - 0.15 * k) & (h["si_bas"] <= -12) & (h["niv"] >= NIV_MIN))
        if not ton[-8:].any():
            return None  # la sirène doit être en cours
        plages = _segments(ton, trou_max=8)
        i0, i1 = plages[-1]
        duree = (i1 - i0 + 1) * DT
        if duree < 1.5:
            return None
        if ton[i0:i1 + 1].mean() < 0.7:
            return None
        idx = np.arange(i0, i1 + 1)[ton[i0:i1 + 1]]
        f = h["si_f"][idx]
        continu = np.abs(np.diff(f)) <= 200 * np.diff(idx)
        if len(continu) == 0 or continu.mean() < 0.9:
            return None
        lisse = _mediane_glissante(f, 5)
        # Une sirène glisse sans cesse ; une mélodie tient chaque note puis saute à la suivante.
        plat = np.abs(np.diff(lisse)) <= 3.0 * np.diff(idx)
        if plat.mean() > 0.45:
            return None
        etendue = float(np.percentile(lisse, 95) - np.percentile(lisse, 5))
        if etendue < 300:
            return None
        inversions = _inversions(lisse, 80.0)
        if inversions < 2 and not (inversions >= 1 and etendue >= 500 and duree >= 3.0):
            return None
        marge = float(np.median(h["si_snr"][idx])) - seuil_snr
        return _confiance(marge, 0.03 * min(3, inversions - 1))

    def _regle_klaxon(self, h: _Historique, k: float, maintenant: float) -> float | None:
        """Son fort, riche en raies (au moins cinq), la plus grave entre 280 et 720 Hz, tenu au moins 0,4 s sans décroître."""
        seuil_snr = 15 - 6 * k
        candidat = (self._depuis(h, "klaxon", 3.0, maintenant) & (h["snr_tot"] >= seuil_snr)
                    & (h["kl_conc"] >= 0.5 - 0.1 * k) & (h["kl_npics"] >= 5)
                    & (h["kl_f"] >= 280) & (h["kl_f"] <= 720) & (h["niv"] >= NIV_MIN + 5))
        plages = _segments(candidat, trou_max=2)
        if not plages:
            return None
        i0, i1 = plages[-1]
        if (len(candidat) - 1 - i1) * DT > 0.5:
            return None
        idx = np.arange(i0, i1 + 1)[candidat[i0:i1 + 1]]
        if (i1 - i0 + 1) * DT < 0.4 or len(idx) < 0.4 / DT * 0.85:
            return None
        f = h["kl_f"][idx]
        mediane = float(np.median(f))
        if np.mean(np.abs(f - mediane) <= 0.04 * mediane) < 0.9:
            return None
        niv = h["niv"][idx]
        if _pente(h["t"][idx], niv) < -8.0:
            return None  # note qui s'éteint (piano, cloche) : pas un klaxon
        if float(np.percentile(niv, 90) - np.percentile(niv, 10)) > 6.0:
            return None
        marge = float(np.median(h["snr_tot"][idx])) - seuil_snr
        return _confiance(marge)

    @staticmethod
    def _calme_avant(h: _Historique, instant: float, crete: float, ecart_db: float) -> bool:
        """Dans la seconde qui précède `instant`, le niveau restait-il `ecart_db` sous la crête ?

        Faux aussi quand l'historique ne couvre pas cette seconde : sans voir l'avant, on ne peut pas
        dire qu'un son était isolé (une mélodie commencée juste avant l'écoute ressemble à un carillon)."""
        t = h["t"]
        if len(t) == 0 or t[0] > instant - 1.0 + DT:
            return False
        masque = (t >= instant - 1.0) & (t <= instant - 0.05)
        return bool(masque.any()) and float(np.median(h["niv"][masque])) <= crete - ecart_db

    def _evenements(self, h: _Historique, depuis: float) -> np.ndarray:
        """Instants d'attaque de n'importe quel son (montée brusque), soudés à 80 ms près."""
        masque = (h["t"] > depuis) & (h["saut_g"] >= 10) & (h["snr_tot"] >= 10) & (h["niv"] >= NIV_MIN)
        return np.array([h["t"][i0] for i0, _i1 in _segments(masque, trou_max=4)])

    def _regle_sonnette(self, h: _Historique, k: float, maintenant: float) -> float | None:
        """Une à trois notes tonales à attaque nette qui décroissent, isolées : avant et après, le calme."""
        seuil_snr = 18 - 6 * k
        attaque = ((h["t"] > self._vu["sonnette"]) & (h["t"] > self._derniere["sonnette"])
                   & (h["so_saut"] >= 9 - 3 * k) & (h["so_part"] >= 0.5 - 0.15 * k)
                   & (h["so_snr"] >= seuil_snr) & (h["niv"] >= NIV_MIN))
        t = h["t"]
        notes = []  # (instant d'attaque, marge, valide, crête)
        for i0, _i1 in _segments(attaque, trou_max=4):
            fin_zone = min(len(t) - 1, i0 + 3)
            ip = i0 + int(np.argmax(h["niv"][i0:fin_zone + 1]))
            f0 = h["so_f"][ip]
            j = ip
            limite = min(len(t) - 1, ip + int(0.8 / DT))
            trous = 0
            while j + 1 <= limite:
                suivant = j + 1
                tenue = (abs(h["so_f"][suivant] - f0) <= 0.03 * f0 and h["so_part"][suivant] >= 0.3
                         and h["so_snr"][suivant] >= 6)
                if tenue:
                    trous = 0
                elif trous < 1:
                    trous += 1
                else:
                    break
                j = suivant
            tenue_s = (j - ip + 1) * DT
            fin_pente = min(j, ip + int(0.5 / DT))
            pente = _pente(t[ip:fin_pente + 1], h["niv"][ip:fin_pente + 1])
            valide = tenue_s >= 0.15 and pente <= -4.0
            notes.append((float(t[i0]), float(h["so_snr"][ip]) - seuil_snr, valide, float(h["niv"][ip])))
        valides = [n for n in notes if n[2]]
        if not valides:
            return None
        dernier = valides[-1][0]
        if maintenant - dernier < 1.0:
            return None  # on attend une seconde de calme pour être sûr que la mélodie est finie
        groupe = [valides[-1]]
        for note in reversed(valides[:-1]):
            if groupe[0][0] - note[0] <= 1.2:
                groupe.insert(0, note)
            else:
                break
        self._vu["sonnette"] = dernier + 0.3  # ce groupe (attaque comprise) est jugé une fois pour toutes
        if not 1 <= len(groupe) <= 3:
            return None
        instants = [n[0] for n in groupe]
        for evenement in self._evenements(h, groupe[0][0] - 1.5):
            if min(abs(evenement - x) for x in instants) > 0.1:
                return None  # un autre son autour : musique, parole, bruit — pas une sonnette isolée
        crete = max(n[3] for n in groupe)
        if any(not n[2] and groupe[0][0] - 1.5 <= n[0] <= dernier + 1.0 and n[3] >= crete - 20
               and min(abs(n[0] - x) for x in instants) > 0.15 for n in notes):
            return None  # une autre attaque tonale qui ne décroît pas, tout près : bip ou note tenue
        if not self._calme_avant(h, groupe[0][0], crete, 15 - 3 * k):
            return None
        apres = (h["t"] >= dernier + 0.5) & (h["t"] <= dernier + 1.0)
        if apres.any() and float(np.median(h["niv"][apres])) > groupe[-1][3] - 5:
            return None  # le son ne s'éteint pas : une musique continue, pas une sonnette
        return _confiance(float(np.median([n[1] for n in groupe])))

    def _regle_porte(self, h: _Historique, k: float, maintenant: float) -> float | None:
        """Deux à cinq impulsions brèves et large bande, rapprochées, entourées de calme."""
        seuil_snr = 15 - 6 * k
        t = h["t"]
        niv = h["niv"]
        impulsion = ((t > self._vu["porte"]) & (t > self._derniere["porte"]) & (h["saut_g"] >= 12 - 4 * k)
                     & (h["snr_tot"] >= seuil_snr) & (h["n_large"] >= 2) & (h["part_g"] <= 0.35)
                     & (niv >= NIV_MIN))
        coups = []  # (instant, marge, bref, crête)
        for i0, _i1 in _segments(impulsion, trou_max=3):
            fin = min(len(t) - 1, i0 + 12)
            if fin - i0 < 9:
                return None  # impulsion trop récente pour juger sa durée
            crete = float(niv[i0:min(len(t), i0 + 3)].max())
            au_dessus = int(np.sum(niv[i0:fin + 1] >= crete - 10))
            bref = au_dessus <= 5 and niv[min(fin, i0 + 9)] <= crete - 10
            coups.append((float(t[i0]), float(h["snr_tot"][i0]) - seuil_snr, bref, crete))
        if not coups:
            return None
        dernier = coups[-1][0]
        if maintenant - dernier < 0.9:
            return None
        groupe = [coups[-1]]
        for coup in reversed(coups[:-1]):
            if 0.08 <= groupe[0][0] - coup[0] <= 0.8:
                groupe.insert(0, coup)
            else:
                break
        self._vu["porte"] = dernier + 0.1
        if not 2 <= len(groupe) <= 5 or not all(c[2] for c in groupe):
            return None
        instants = [c[0] for c in groupe]
        for evenement in self._evenements(h, groupe[0][0] - 1.0):
            if min(abs(evenement - x) for x in instants) > 0.1:
                return None
        if not self._calme_avant(h, groupe[0][0], max(c[3] for c in groupe), 15 - 3 * k):
            return None
        return _confiance(float(np.median([c[1] for c in groupe])), 0.02 * (len(groupe) - 2))


# --------------------------------------------------------------------------- prénom
def normaliser(texte: str) -> str:
    """Minuscules sans accents ni ponctuation : « Hélène » et « helene » sont le même prénom."""
    texte = unicodedata.normalize("NFKD", texte or "").encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9 ]+", " ", texte.lower()).strip()


def prenom_depuis(user_name: str) -> str:
    """Le prénom tel que la reconnaissance vocale l'attend : premier mot, en minuscules, accents gardés
    (le vocabulaire français du modèle local est accentué)."""
    mots = re.findall(r"[^\W\d_]+(?:[-'][^\W\d_]+)*", (user_name or "").strip())
    return mots[0].lower() if mots else ""


class DetecteurPrenom:
    """Reconnaît le prénom de l'utilisateur dans le flux, par la reconnaissance vocale locale.

    `reconnaisseur` est un objet à la Vosk (AcceptWaveform, Result) créé avec la grammaire
    [prénom, "[unk]"] et les mots horodatés : tout ce qui n'est pas le prénom tombe dans « [unk] »,
    et la confiance du mot écarte les ressemblances trop lointaines."""

    def __init__(self, reconnaisseur: Any, prenom: str, anti_rebond_s: float = ANTI_REBOND_S):
        self.reconnaisseur = reconnaisseur
        self.prenom = prenom
        self._cible = normaliser(prenom)
        self.anti_rebond_s = float(anti_rebond_s)
        self._derniere = -1e9

    @staticmethod
    def seuil(sensibilite: int) -> float:
        return 0.95 - 0.4 * min(100, max(0, int(sensibilite))) / 100

    def traiter(self, bloc: bytes, sensibilite: int, maintenant: float, ignorer: bool = False) -> dict | None:
        """`ignorer` : l'audio est consommé (le décodage reste continu) mais aucun résultat n'est rendu —
        pendant qu'IRIS parle, c'est souvent elle qui prononce le prénom."""
        if not self._cible or not self.reconnaisseur.AcceptWaveform(bytes(bloc)):
            return None
        try:
            resultat = json.loads(self.reconnaisseur.Result() or "{}")
        except (TypeError, ValueError):
            return None
        if ignorer or maintenant - self._derniere < self.anti_rebond_s:
            return None
        seuil = self.seuil(sensibilite)
        for mot in resultat.get("result") or []:
            if normaliser(str(mot.get("word", ""))) == self._cible:
                try:
                    conf = float(mot.get("conf", 0.0))
                except (TypeError, ValueError):
                    conf = 0.0
                if conf >= seuil:
                    self._derniere = maintenant
                    return {"type": "prenom", "confiance": round(min(0.99, conf), 2), "t": round(maintenant, 3)}
        return None


# --------------------------------------------------------------------------- signaux synthétiques
def _bruit_rose(n: int, rng: np.random.Generator) -> np.ndarray:
    blanc = rng.standard_normal(n)
    spectre = np.fft.rfft(blanc)
    f = np.fft.rfftfreq(n, 1 / TAUX)
    f[0] = f[1]
    rose = np.fft.irfft(spectre / np.sqrt(f), n)
    return rose / (np.sqrt(np.mean(rose ** 2)) + EPS)


def _rampe(n: int, rampe: int) -> np.ndarray:
    env = np.ones(n)
    rampe = max(1, min(rampe, n // 2))
    env[:rampe] = np.linspace(0, 1, rampe)
    env[-rampe:] = np.linspace(1, 0, rampe)
    return env


def _composer(duree_s: float, sons: list[tuple[float, np.ndarray]], niveau_db: float, bruit_db: float,
              graine: int) -> np.ndarray:
    """Pose chaque son à son instant sur un bruit rose faible ; le son le plus fort est ramené à niveau_db."""
    rng = np.random.default_rng(graine)
    n = int(duree_s * TAUX)
    signal = np.zeros(n)
    for debut, son in sons:
        i = int(debut * TAUX)
        fin = min(n, i + len(son))
        signal[i:fin] += son[:fin - i]
    crete_efficace = max(float(np.sqrt(np.mean(son ** 2))) for _d, son in sons) if sons else 1.0
    signal *= 10 ** (niveau_db / 20) / (crete_efficace + EPS)
    signal += _bruit_rose(n, rng) * 10 ** (bruit_db / 20)
    return np.clip(np.round(signal * 32767), -32768, 32767).astype(np.int16)


def _ton(freq: float | np.ndarray, duree_s: float, harmoniques: tuple[float, ...] = (1.0,)) -> np.ndarray:
    n = int(duree_s * TAUX)
    if np.ndim(freq) == 0:
        phase = 2 * np.pi * float(freq) * np.arange(n) / TAUX
    else:
        phase = 2 * np.pi * np.cumsum(np.asarray(freq)[:n]) / TAUX
    return sum(a * np.sin((i + 1) * phase) for i, a in enumerate(harmoniques))


def signal_synthetique(type_: str, niveau_db: float = -20.0, bruit_db: float = -58.0, graine: int = 7) -> np.ndarray:
    """Signal de démonstration d'un type d'alerte (PCM int16 16 kHz), précédé de deux secondes de bruit.

    Sert au bouton « Tester » : le signal passe dans le VRAI détecteur, avec les réglages en vigueur.
    Ces signaux sont des imitations simples ; un vrai son peut être reconnu moins bien."""
    if type_ == "alarme":
        # Motif temporel T3 d'un avertisseur de fumée : trois bips de 0,5 s, puis une pause de 1,5 s.
        bip = _ton(3150.0, 0.5, (1.0, 0.0, 0.08)) * _rampe(int(0.5 * TAUX), 80)
        sons = [(2.0 + cycle * 3.0 + i * 1.0, bip) for cycle in range(2) for i in range(3)]
        return _composer(8.5, sons, niveau_db, bruit_db, graine)
    if type_ == "sirene":
        duree = 7.0
        t = np.arange(int(duree * TAUX)) / TAUX
        f = 1050.0 + 450.0 * np.sin(2 * np.pi * t / 2.5)  # « wail » : 600 à 1500 Hz, cycle de 2,5 s
        son = _ton(f, duree, (1.0, 0.0, 0.3)) * _rampe(len(t), 400)
        return _composer(9.5, [(2.0, son)], niveau_db, bruit_db, graine)
    if type_ == "klaxon":
        duree = 1.2
        n = int(duree * TAUX)
        son = _ton(415.0, duree, (1.0, 0.6, 0.4, 0.3, 0.2)) + _ton(520.0, duree, (0.9, 0.5, 0.35, 0.25))
        son = np.tanh(1.5 * son / np.max(np.abs(son))) * _rampe(n, 320)  # un klaxon sature un peu
        return _composer(4.5, [(2.0, son)], niveau_db, bruit_db, graine)
    if type_ == "sonnette":
        def note(freq: float) -> np.ndarray:
            n = int(1.8 * TAUX)
            t = np.arange(n) / TAUX
            env = np.exp(-t / 0.5) * np.minimum(1.0, t / 0.003)
            return (np.sin(2 * np.pi * freq * t) + 0.3 * np.sin(2 * np.pi * 2.76 * freq * t)) * env
        return _composer(6.0, [(2.0, note(659.0)), (2.6, note(523.0))], niveau_db + 3, bruit_db, graine)
    if type_ == "porte":
        rng = np.random.default_rng(graine + 1)

        def coup() -> np.ndarray:
            n = int(0.06 * TAUX)
            t = np.arange(n) / TAUX
            bruit = rng.standard_normal(n)
            filtre = np.zeros(n)
            for i in range(1, n):  # passe-bas doux : un coup sur du bois est plus sourd qu'un claquement
                filtre[i] = 0.6 * filtre[i - 1] + 0.4 * bruit[i]
            return filtre * np.exp(-t / 0.012)
        sons = [(2.0 + i * 0.22, coup()) for i in range(3)]
        return _composer(4.5, sons, niveau_db + 6, bruit_db, graine)
    raise KeyError(type_)


# --------------------------------------------------------------------------- service
_VERROU_ECOUTE = threading.Lock()
MICRO_NON_DEMARRE = "L'écoute du micro n'a pas pu démarrer. Vérifiez le micro dans Paramètres › Voix."


def assurer_ecoute(ctx: Any) -> str | None:
    """Démarre l'écoute du micro si elle est arrêtée : le robinet n'existe que si elle tourne.

    Lève EcouteRefusee en mode confidentiel. Rend la raison (texte) si le micro ne s'est pas ouvert —
    le service tourne quand même et dira « en attente du micro » : le chien de garde vocal peut
    relancer l'écoute plus tard (lunettes rallumées) sans qu'il faille réactiver les alertes."""
    if ctx.settings.user.privacy_mode:
        raise EcouteRefusee(CONFIDENTIEL)
    voix = getattr(ctx, "voice", None)
    if voix is None:
        return "Le service d'écoute du micro n'est pas disponible."
    # Un seul démarrage à la fois : deux services qui démarrent ensemble ouvriraient deux flux micro.
    with _VERROU_ECOUTE:
        if not getattr(voix, "running", False) and getattr(voix, "state", "off") == "off":
            try:
                voix.start()
            except Exception as exc:
                # Détail technique (souvent en anglais) au journal ; une phrase claire pour l'utilisateur.
                log.warning("écoute du micro non démarrée : %s", exc)
                return MICRO_NON_DEMARRE
    if not getattr(voix, "running", False) and getattr(voix, "state", "off") == "off":
        return getattr(voix, "error", None) or "L'écoute du micro est arrêtée."
    return None


def publier_etat_ecoute(ctx: Any) -> None:
    """L'état d'écoute (interface C) change quand les alertes ou l'écoute assistée changent : on le republie."""
    fonction = getattr(ctx, "ecoute_etat", None)
    if not callable(fonction):
        return
    try:
        ctx.hub.publish("ecoute.etat", **fonction())
    except Exception as exc:
        log.debug("état d'écoute non publié : %s", exc)


class ServiceAlertes:
    """Fil d'écoute des alertes : robinet -> détecteurs -> événement alerte.sonore (+ voix)."""

    NOM_ROBINET = "alertes"
    ATTENTE_MICRO_S = 2.0  # sans bloc depuis ce délai, on dit « en attente du micro »

    def __init__(self, ctx: Any, fabrique_reconnaisseur: Callable[[str], Any] | None = None):
        self.ctx = ctx
        self._fabrique_reconnaisseur = fabrique_reconnaisseur or self._reconnaisseur_vosk
        self._verrou = threading.RLock()
        self._fil: threading.Thread | None = None
        self._arret: threading.Event | None = None
        self._detecteur = DetecteurAcoustique()
        self._prenom: DetecteurPrenom | None = None
        self._prenom_a_recharger = True
        self.prenom_raison: str | None = None
        self.raison: str | None = None
        self.en_attente_micro = False
        self.dernieres: deque[dict] = deque(maxlen=30)
        self._tts_fini = 0.0
        self._erreurs = 0

    # ------------------------------------------------------------------ état
    @property
    def actif(self) -> bool:
        fil = self._fil
        return fil is not None and fil.is_alive()

    def etat(self) -> dict:
        u = self.ctx.settings.user
        return {
            "actives": bool(u.alertes_actives),
            "en_marche": self.actif,
            "types": [{"id": t, "libelle": INFOS[t]["libelle"], "actif": t in u.alertes_types} for t in TYPES_ALERTES],
            "sensibilite": u.alertes_sensibilite,
            "voix": bool(u.alertes_voix),
            "dernieres": list(self.dernieres)[:20],
            "raison": self.raison,
            "en_attente_micro": self.en_attente_micro,
            "prenom": {"prenom": prenom_depuis(u.user_name) or None, "disponible": self._prenom is not None,
                       "raison": self.prenom_raison},
            "local": True,
            "avertissement": AVERTISSEMENT,
            "limites": LIMITES,
        }

    def _publier_etat(self) -> None:
        try:
            self.ctx.hub.publish("alertes.etat", actives=bool(self.ctx.settings.user.alertes_actives),
                                 en_marche=self.actif, raison=self.raison, en_attente_micro=self.en_attente_micro)
        except Exception:
            pass
        publier_etat_ecoute(self.ctx)

    # ------------------------------------------------------------------ marche / arrêt
    def demarrer(self) -> dict:
        """Démarre le fil (idempotent). Lève EcouteRefusee en mode confidentiel."""
        raison = assurer_ecoute(self.ctx)
        with self._verrou:
            self.raison = raison
            if self.actif:
                return self.etat()
            robinet = self.ctx.voice.robinet
            file = robinet.abonner(self.NOM_ROBINET, max_blocs=40)  # 10 s : au-delà, le son est périmé
            arret = threading.Event()
            self._arret = arret
            self._detecteur = DetecteurAcoustique(self.ctx.settings.user.alertes_sensibilite)
            self._prenom_a_recharger = True
            self.en_attente_micro = False
            self._fil = threading.Thread(target=self._boucle, args=(file, arret), name="iris-alertes", daemon=True)
            self._fil.start()
        log.info("alertes sonores démarrées%s", f" ({raison})" if raison else "")
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
            self.en_attente_micro = False
        if fil is not None and fil is not threading.current_thread():
            fil.join(timeout=2)
        if fil is not None:
            log.info("alertes sonores arrêtées%s", f" : {raison}" if raison else "")
        self._publier_etat()
        return self.etat()

    def recharger_prenom(self) -> None:
        self._prenom_a_recharger = True

    # ------------------------------------------------------------------ boucle
    def _boucle(self, file: "queue.Queue[bytes]", arret: threading.Event) -> None:
        dernier_bloc = time.monotonic()
        while not arret.is_set():
            if self.ctx.settings.user.privacy_mode:
                # Le mode confidentiel ferme déjà le micro ; on s'arrête aussi, et on le dit.
                threading.Thread(target=self._arreter_depuis_le_fil, args=(arret, CONFIDENTIEL), daemon=True).start()
                return
            try:
                bloc = file.get(timeout=0.5)
            except queue.Empty:
                if not self.en_attente_micro and time.monotonic() - dernier_bloc > self.ATTENTE_MICRO_S:
                    self.en_attente_micro = True
                    self._publier_etat()
                continue
            dernier_bloc = time.monotonic()
            if self.en_attente_micro:
                self.en_attente_micro = False
                self._publier_etat()
            try:
                self.traiter_bloc(bloc)
                self._erreurs = 0
            except Exception as exc:
                self._erreurs += 1
                if self._erreurs in (1, 50) or self._erreurs % 1000 == 0:
                    log.warning("analyse d'alerte en erreur (%d) : %s", self._erreurs, exc)

    def _tts_parle(self) -> bool:
        tts = getattr(self.ctx, "tts", None)
        try:
            parle = bool(tts is not None and tts.is_speaking)
        except Exception:
            parle = False
        if parle:
            self._tts_fini = time.monotonic()
        return parle or time.monotonic() - self._tts_fini < 0.6

    def traiter_bloc(self, bloc: bytes) -> list[dict]:
        """Passe un bloc dans les détecteurs, signale et rend les alertes des types actifs."""
        u = self.ctx.settings.user
        types = set(u.alertes_types)
        self._detecteur.sensibilite = u.alertes_sensibilite
        trouvees = [d for d in self._detecteur.traiter(bloc) if d["type"] in types]
        if "prenom" in types:
            if self._prenom_a_recharger:
                self._charger_prenom()
            if self._prenom is not None:
                d = self._prenom.traiter(bloc, u.alertes_sensibilite, self._detecteur.maintenant,
                                         ignorer=self._tts_parle())
                if d:
                    trouvees.append(d)
        for d in trouvees:
            self._signaler(d["type"], d["confiance"], test=False)
        return trouvees

    def _charger_prenom(self) -> None:
        self._prenom_a_recharger = False
        self._prenom = None
        prenom = prenom_depuis(self.ctx.settings.user.user_name)
        if not prenom:
            self.prenom_raison = "Aucun prénom renseigné dans les réglages : l'alerte prénom ne peut pas fonctionner."
            return
        try:
            reconnaisseur = self._fabrique_reconnaisseur(prenom)
        except PrenomHorsVocabulaire:
            # Cas CERTAIN, pas une limite générale : avec une grammaire restreinte, un mot absent du lexique
            # est ignoré par la reconnaissance locale, et la détection ne se déclencherait jamais.
            self.prenom_raison = (f"Le prénom « {prenom} » est absent du vocabulaire de la reconnaissance locale : "
                                  "l'alerte prénom ne peut pas se déclencher.")
            return
        except Exception as exc:
            # Le détail technique va au journal ; l'utilisateur lit une phrase sans nom de composant.
            log.warning("reconnaissance du prénom indisponible : %s", exc)
            reconnaisseur = None
            self.prenom_raison = "La reconnaissance vocale locale n'a pas pu démarrer : l'alerte prénom ne fonctionne pas."
        if reconnaisseur is None:
            self.prenom_raison = self.prenom_raison or (
                "Le modèle de reconnaissance vocale locale n'est pas installé : l'alerte prénom ne peut pas fonctionner.")
            return
        self._prenom = DetecteurPrenom(reconnaisseur, prenom)
        self.prenom_raison = None

    def _reconnaisseur_vosk(self, prenom: str) -> Any:
        """Reconnaisseur restreint au prénom, sur le modèle local déjà chargé par l'écoute s'il existe."""
        from .voice import stt

        moteur = getattr(getattr(self.ctx, "voice", None), "_vosk", None)
        if moteur is None:
            chemin = stt.model_dir(self.ctx.settings.models_dir, self.ctx.settings.user.language)
            if chemin is None:
                return None
            moteur = stt.VoskEngine(chemin)
        if not mot_connu(getattr(moteur, "model", None), prenom):
            raise PrenomHorsVocabulaire(prenom)
        return moteur.recognizer([prenom], words=True)

    # ------------------------------------------------------------------ signalement
    def _signaler(self, type_: str, confiance: float, test: bool) -> dict:
        info = INFOS[type_]
        alerte = {"type": type_, "genre": type_, "libelle": info["libelle"], "confiance": round(float(confiance), 2),
                  "ts": time.time(), "test": bool(test)}
        self.dernieres.appendleft(alerte)
        # « genre » et non « type » : EventHub.publish place le type d'événement sous la clé « type »,
        # qu'un champ du même nom écraserait (l'événement ne s'appellerait plus alerte.sonore).
        self.ctx.hub.publish("alerte.sonore", genre=type_, libelle=info["libelle"], confiance=alerte["confiance"],
                             ts=alerte["ts"], test=bool(test))
        u = self.ctx.settings.user
        if u.alertes_voix and not u.privacy_mode:
            phrase = f"Essai réussi. {info['annonce']}" if test else info["annonce"]
            try:
                self.ctx.tts.speak(phrase, force=True)
            except Exception as exc:
                log.debug("annonce vocale de l'alerte impossible : %s", exc)
        return alerte

    def tester(self, type_: str) -> dict:
        """Passe le signal synthétique du type dans un détecteur neuf (le vrai code, les réglages en vigueur)."""
        type_ = (type_ or "").strip().lower()
        if type_ == "prenom":
            raise ValueError(
                "Le prénom ne se teste pas avec un son synthétique : IRIS ne fabrique pas de voix pour cela. "
                "Activez les alertes et faites dire votre prénom près du micro.")
        if type_ not in TYPES_ACOUSTIQUES:
            raise KeyError(type_)
        u = self.ctx.settings.user
        detecteur = DetecteurAcoustique(u.alertes_sensibilite)
        signal = signal_synthetique(type_)
        meilleure: float | None = None
        autres: set[str] = set()
        for i in range(0, len(signal), 4000):
            for d in detecteur.traiter(signal[i:i + 4000]):
                if d["type"] == type_:
                    meilleure = max(meilleure or 0.0, d["confiance"])
                else:
                    autres.add(d["type"])
        if meilleure is not None:
            self._signaler(type_, meilleure, test=True)
        return {"detecte": meilleure is not None, "confiance": round(meilleure or 0.0, 2), "type": type_,
                "sensibilite": u.alertes_sensibilite, "autres_types_detectes": sorted(autres),
                "note": "Signal d'essai synthétique passé dans le détecteur réel ; un vrai son peut être reconnu moins bien."}
