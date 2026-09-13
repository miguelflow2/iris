"""Rotation de clés ElevenLabs : étaler la parole sur plusieurs comptes, basculer quand l'un refuse.

Pourquoi. Un compte gratuit ElevenLabs plafonne à 10 000 caractères par mois. Avec deux clés (deux
comptes), IRIS dispose de deux fois plus de voix avant de retomber sur Windows — à condition
d'alterner d'un énoncé à l'autre, et de savoir contourner la clé qui vient de dire non (quota
atteint : 401, 402 ou 429). Ce module ne fait que ça : donner la clé du moment, retenir laquelle
refuse et pour combien de temps, et passer à la suivante.

Une seule clé (le cas normal) : le pool se comporte exactement comme avant, sans rotation ni
pénalité observable.

La clé n'est jamais journalisée en clair : seuls ses quatre derniers caractères servent d'étiquette
(voir `etiquette`). Le pool est partagé par la voix (`voice/elevenlabs.py`) et le STT Scribe
(`voice/stt.py`) : les deux tirent du même stock et partagent les pénalités.
"""
from __future__ import annotations

import os
import re
import threading
import time

# Une clé qui a refusé (quota/auth) est écartée ce nombre de secondes, puis réessayée : un quota
# mensuel ne rouvrira pas dans l'heure, mais un 429 passager, oui — et réessayer une clé morte ne
# coûte qu'un aller-retour, jamais un silence (l'appelant a d'autres clés d'ici là).
COOLDOWN_S = 3600.0

# Codes amont qui signifient « cette clé ne peut pas servir maintenant » : quota épuisé ou refusée.
CODES_BASCULE = (401, 402, 429)


def parser_cles(brut: str) -> list[str]:
    """Découpe une liste de clés (virgule, point-virgule ou espaces) en gardant l'ordre, sans doublon."""
    vues: set[str] = set()
    cles: list[str] = []
    for morceau in re.split(r"[,;\s]+", brut or ""):
        c = morceau.strip()
        if c and c not in vues:
            vues.add(c)
            cles.append(c)
    return cles


def etiquette(cle: str) -> str:
    """Étiquette non secrète d'une clé pour les journaux : les 4 derniers caractères."""
    return ("…" + cle[-4:]) if cle else "?"


class RotationCles:
    """Un pool de clés interchangeables. Pas d'état global : instanciable et testable seul."""

    def __init__(self, cles: list[str], cooldown_s: float = COOLDOWN_S):
        self._cles = list(cles)
        self._i = 0
        self._cooldown: dict[str, float] = {}
        self._cooldown_s = cooldown_s
        self._verrou = threading.RLock()

    def __bool__(self) -> bool:
        return bool(self._cles)

    def __len__(self) -> int:
        return len(self._cles)

    def toutes(self) -> list[str]:
        return list(self._cles)

    def courante(self, maintenant: float | None = None) -> str:
        """La clé à utiliser tout de suite : à partir de l'index courant, la première hors pénalité.

        Si toutes sont en pénalité, renvoie quand même la moins fraîchement pénalisée : mieux vaut
        un dernier essai (peut-être un 429 déjà passé) qu'un silence garanti."""
        maintenant = time.time() if maintenant is None else maintenant
        with self._verrou:
            n = len(self._cles)
            if n == 0:
                return ""
            for pas in range(n):
                c = self._cles[(self._i + pas) % n]
                if self._cooldown.get(c, 0.0) <= maintenant:
                    return c
            return min(self._cles, key=lambda c: self._cooldown.get(c, 0.0))

    def apres_usage(self) -> None:
        """Après un énoncé réussi : avancer d'un cran pour que le prochain change de clé (alternance)."""
        with self._verrou:
            if self._cles:
                self._i = (self._i + 1) % len(self._cles)

    def marquer_epuisee(self, cle: str, maintenant: float | None = None) -> None:
        """Cette clé a refusé : la mettre en pénalité et pointer l'index sur la suivante (bascule)."""
        maintenant = time.time() if maintenant is None else maintenant
        with self._verrou:
            if cle in self._cles:
                self._cooldown[cle] = maintenant + self._cooldown_s
                self._i = (self._cles.index(cle) + 1) % len(self._cles)


# --------------------------------------------------------------------------- singleton partagé
_singleton: RotationCles | None = None
_source: str | None = None
_verrou_singleton = threading.Lock()


def pool_elevenlabs() -> RotationCles:
    """Le pool partagé, construit depuis ELEVENLABS_API_KEY (une ou plusieurs clés).

    Reconstruit seulement si la variable d'environnement change (utile aux tests) ; sinon il garde
    ses pénalités d'une requête à l'autre."""
    global _singleton, _source
    brut = (os.environ.get("ELEVENLABS_API_KEY") or "").strip()
    with _verrou_singleton:
        if _singleton is None or _source != brut:
            _singleton = RotationCles(parser_cles(brut))
            _source = brut
        return _singleton
