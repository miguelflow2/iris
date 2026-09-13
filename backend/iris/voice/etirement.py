"""Débit de la voix : accélérer ou ralentir un PCM sans changer la hauteur (WSOLA, numpy seul).

Pourquoi : les utilisateurs non voyants aguerris écoutent leur lecteur d'écran à 2 ou 3 fois la
vitesse normale. Deux des trois voix d'IRIS savent le faire elles-mêmes (Windows par son Rate,
la voix locale par la durée de ses phonèmes) ; la voix premium, elle, n'accepte qu'une plage
étroite (0,7 à 1,2). Le reste du facteur est donc appliqué ici, localement, sur le PCM reçu.

Pourquoi WSOLA et pas un simple rééchantillonnage : lire un son plus vite en sautant des
échantillons monte la voix d'autant (effet « dessin animé »). WSOLA découpe le signal en fenêtres
de ~25 ms, les recopie à un pas différent de celui où on les a lues, et choisit chaque fenêtre à
quelques millisecondes près pour qu'elle prolonge la précédente en phase (recherche du meilleur
recouvrement). Les fenêtres sont des Hann à 50 % de recouvrement : leur somme vaut exactement 1,
donc aucune jonction ne fait de clic et l'amplitude reste celle d'origine.

`Etireur` travaille en flux (morceaux de taille quelconque, comme la socket HTTPS les rend) et
produit exactement les mêmes échantillons que `etirer_pcm` sur le tampon complet : une trame n'est
calculée que lorsque tout l'audio dont elle dépend est arrivé.

Limites réelles : les tests le mesurent sur des signaux synthétiques (durée de sortie = durée/taux,
hauteur conservée, pas de saut). Sur la parole, au-delà de 2× on entend un léger « grain », propre à
toute compression temporelle : la voix reste intelligible, elle n'est pas identique à un débit natif."""
from __future__ import annotations

import math

try:  # import protégé : tts.py importe ce module au démarrage, un numpy absent ne doit pas empêcher IRIS de parler
    import numpy as np
except Exception:  # pragma: no cover - numpy fait partie des dépendances livrées
    np = None  # type: ignore[assignment]

# tts_rate qui vaut « vitesse normale » pour les trois moteurs (185 = 1×, 370 = 2×, 555 = 3×).
DEBIT_NORMAL = 185

_FENETRE_S = 0.025  # longueur d'une fenêtre : assez longue pour contenir une période de voix grave
_TOLERANCE_S = 0.010  # ± recherche du recouvrement : couvre une période fondamentale jusqu'à 50 Hz
_FONDU_FINAL_S = 0.004  # fondu de la toute fin, au cas où la coupe tombe au milieu d'un son


def facteur_debit(tts_rate: object) -> float:
    """Multiplicateur de vitesse demandé par le réglage tts_rate (185 → 1,0 ; 555 → 3,0).

    Une valeur illisible vaut la vitesse normale : un réglage corrompu ne doit jamais rendre IRIS
    inaudible (trop lente ou trop rapide)."""
    try:
        valeur = float(tts_rate)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 1.0
    if not math.isfinite(valeur) or valeur <= 0:
        return 1.0
    return valeur / DEBIT_NORMAL


def est_identite(taux: float) -> bool:
    """Un taux assez proche de 1 pour ne rien toucher (ni calcul, ni latence ajoutée)."""
    return abs(float(taux) - 1.0) < 1e-3


class Etireur:
    """Étirement temporel WSOLA en flux : PCM int16 mono entrant → PCM int16 mono sortant.

    `taux` > 1 accélère (sortie plus courte), < 1 ralentit. `pousser` rend ce qui ne changera plus ;
    `vider` termine le flux et rend le reste. Au total, la sortie compte round(entrée / taux)
    échantillons."""

    def __init__(self, taux: float, rate: int):
        if np is None:
            # Levée avant toute lecture : la voix appelante bascule alors sur la voix Windows, qui
            # applique le débit elle-même. Jamais muette.
            raise RuntimeError("numpy indisponible : étirement du débit impossible")
        taux = float(taux)
        if not math.isfinite(taux) or taux <= 0:
            raise ValueError(f"taux d'étirement invalide : {taux}")
        self.taux = taux
        self.rate = int(rate)
        self.identite = est_identite(taux)
        self.n = max(16, 2 * int(round(_FENETRE_S * self.rate / 2)))  # longueur de fenêtre, paire
        self.hs = self.n // 2  # pas de synthèse : 50 % de recouvrement
        self.ha = self.hs * taux  # pas d'analyse (réel : la position nominale k × ha ne dérive pas)
        self.tolerance = max(1, int(round(_TOLERANCE_S * self.rate)))
        # Hann périodique : w[i] + w[i + n/2] = 1 exactement, d'où une somme plate au recouvrement.
        self._fenetre = 0.5 - 0.5 * np.cos(2.0 * np.pi * np.arange(self.n) / self.n)
        self._entree = np.zeros(0, dtype=np.float64)  # audio reçu, à partir de l'indice absolu _base
        self._base = 0
        self.recus = 0  # échantillons reçus au total
        self.emis = 0  # échantillons rendus au total
        self._k = 0  # prochaine trame à calculer
        self._prec: int | None = None  # position (absolue, dans l'entrée) de la trame précédente
        self._recouvrement = np.zeros(self.n, dtype=np.float64)  # somme en cours des fenêtres
        # Sortie calculée mais pas encore rendue, en morceaux : concaténer à chaque trame coûterait un
        # temps quadratique sur un long tampon.
        self._pret: list[np.ndarray] = []
        self._pret_longueur = 0
        # Les derniers échantillons attendent `vider`, qui y pose le fondu final.
        self._reserve = max(1, int(round(_FONDU_FINAL_S * self.rate)))
        self._termine = False

    # ------------------------------------------------------------------ flux
    def pousser(self, pcm: np.ndarray) -> np.ndarray:
        """Ajoute des échantillons int16 ; rend ceux de la sortie qui ne changeront plus."""
        if self._termine:
            raise RuntimeError("flux d'étirement déjà terminé")
        pcm = np.asarray(pcm).reshape(-1)
        if self.identite:
            self.recus += len(pcm)
            self.emis += len(pcm)
            return pcm.astype(np.int16, copy=True)
        if len(pcm):
            self._entree = np.concatenate((self._entree, pcm.astype(np.float64)))
            self.recus += len(pcm)
        while self._besoin(self._k) <= self.recus:
            self._calculer_trame()
        # Jamais au-delà de recus/taux : le total final vaut round(total/taux), qui est au moins ce
        # plafond — rien de ce qui est rendu ici n'aura donc à être « repris » à la fin du flux.
        plafond = int(math.floor(self.recus / self.taux)) - self._reserve
        return self._en_int16(self._rendre(plafond - self.emis))

    def vider(self) -> np.ndarray:
        """Termine le flux : calcule les dernières trames (complétées de silence) et rend la fin."""
        if self._termine:
            return np.zeros(0, dtype=np.int16)
        self._termine = True
        if self.identite:
            return np.zeros(0, dtype=np.int16)
        # Les dernières trames sont complétées de silence. Si l'entrée s'arrête au milieu d'une onde,
        # ce silence tombe DANS la sortie quand on ralentit : la voix chuterait d'un coup à zéro (clic).
        # On adoucit donc les 4 dernières ms de l'entrée avant de calculer ces trames-là.
        restant = self.recus - self._base
        if restant > 0:
            longueur = min(restant, self._reserve)
            self._entree = self._entree.copy()
            self._entree[-longueur:] *= np.linspace(1.0, 0.0, longueur)
        while self._k * self.ha < self.recus:
            self._calculer_trame()
        if self._k > 0:  # la moitié descendante de la dernière fenêtre
            self._ajouter(self._recouvrement[: self.hs].copy())
            self._recouvrement = np.zeros(self.n, dtype=np.float64)
        cible = int(round(self.recus / self.taux))
        manque = cible - self.emis - self._pret_longueur
        if manque > 0:
            self._ajouter(np.zeros(manque, dtype=np.float64))
        fin = self._rendre(cible - self.emis)
        self._pret, self._pret_longueur = [], 0
        if len(fin):
            longueur = min(len(fin), self._reserve)
            fin[-longueur:] *= np.linspace(1.0, 0.0, longueur)
        return self._en_int16(fin)

    def pousser_octets(self, data: bytes) -> bytes:
        """`pousser` pour un flux d'octets int16 petit-boutiste (nombre pair d'octets)."""
        return self.pousser(np.frombuffer(data, dtype="<i2")).astype("<i2").tobytes()

    def vider_octets(self) -> bytes:
        return self.vider().astype("<i2").tobytes()

    # ------------------------------------------------------------------ interne
    def _besoin(self, k: int) -> int:
        """Indice absolu (exclu) jusqu'où l'entrée doit être arrivée pour calculer la trame k."""
        if k == 0 or self._prec is None:
            return self.n
        fin = int(round(k * self.ha)) + self.tolerance + self.n
        return max(fin, self._prec + self.hs + self.n)

    def _segment(self, debut: int, longueur: int) -> np.ndarray:
        """Entrée [debut, debut + longueur), complétée de silence au-delà de ce qui est reçu."""
        i = debut - self._base
        morceau = self._entree[max(0, i) : max(0, i + longueur)]
        if len(morceau) < longueur:
            morceau = np.concatenate((morceau, np.zeros(longueur - len(morceau), dtype=np.float64)))
        return morceau

    def _calculer_trame(self) -> None:
        k = self._k
        nominal = int(round(k * self.ha))
        if k == 0 or self._prec is None:
            position = 0
        else:
            # Le prolongement naturel de la trame précédente : ce qui la suivait dans l'original.
            naturel = self._segment(self._prec + self.hs, self.n)
            bas = max(0, nominal - self.tolerance)
            haut = nominal + self.tolerance
            region = self._segment(bas, haut - bas + self.n)
            correlation = np.correlate(region, naturel, mode="valid")
            cumul = np.concatenate(([0.0], np.cumsum(region * region)))
            energie = np.maximum(cumul[self.n :] - cumul[: -self.n], 0.0)
            # Normalisée par l'énergie du candidat : sinon la recherche préfère le passage le plus
            # fort au lieu de celui qui est en phase.
            score = correlation / np.sqrt(energie + 1e-9)
            meilleur = int(np.argmax(score))
            position = bas + meilleur if score[meilleur] > 1e-6 else nominal
        trame = self._segment(position, self.n)
        if k == 0:
            # La première moitié n'a pas de voisine avec qui se recouvrir : on la garde entière,
            # sinon le son commencerait en fondu et la première syllabe serait mangée.
            self._recouvrement[: self.hs] += trame[: self.hs]
            self._recouvrement[self.hs :] += self._fenetre[self.hs :] * trame[self.hs :]
        else:
            self._recouvrement += self._fenetre * trame
        self._ajouter(self._recouvrement[: self.hs].copy())
        self._recouvrement = np.concatenate((self._recouvrement[self.hs :], np.zeros(self.hs, dtype=np.float64)))
        self._prec = position
        self._k = k + 1
        # On oublie l'entrée dont aucune trame future n'aura besoin (recherche ou prolongement).
        garder = min(int(round(self._k * self.ha)) - self.tolerance, position + self.hs)
        coupe = garder - self._base
        if coupe > 0:
            self._entree = self._entree[coupe:]
            self._base += coupe

    def _ajouter(self, valeurs: np.ndarray) -> None:
        self._pret.append(valeurs)
        self._pret_longueur += len(valeurs)

    def _rendre(self, nombre: int) -> np.ndarray:
        """Retire et rend (en flottants) les `nombre` premiers échantillons calculés."""
        nombre = max(0, min(int(nombre), self._pret_longueur))
        if nombre == 0:
            return np.zeros(0, dtype=np.float64)
        tout = np.concatenate(self._pret) if len(self._pret) > 1 else self._pret[0]
        sortie = tout[:nombre].copy()
        reste = tout[nombre:]
        self._pret = [reste] if len(reste) else []
        self._pret_longueur = len(reste)
        self.emis += nombre
        return sortie

    @staticmethod
    def _en_int16(valeurs: np.ndarray) -> np.ndarray:
        return np.clip(np.rint(valeurs), -32768, 32767).astype(np.int16)


def etirer_pcm(pcm: np.ndarray, taux: float, rate: int) -> np.ndarray:
    """PCM int16 mono complet → PCM int16 mono de round(len / taux) échantillons, hauteur conservée.

    taux = 1 rend une copie identique ; une entrée vide rend un tableau vide."""
    pcm = np.asarray(pcm).reshape(-1)
    if len(pcm) == 0:
        return np.zeros(0, dtype=np.int16)
    etireur = Etireur(taux, rate)
    debut = etireur.pousser(pcm)
    fin = etireur.vider()
    return np.concatenate((debut, fin)).astype(np.int16)
