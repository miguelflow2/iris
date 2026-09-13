"""Robinet audio : une COPIE de chaque bloc micro pour les services qui écoutent en parallèle.

Sous-titres, alertes sonores, enregistrement, écoute assistée, verrou vocal : tous ont besoin du son
du micro pendant que l'écoute du mot d'activation continue. Deux choses sont interdites (voir
listener.py) : un second lecteur de la file de l'écoute (les blocs seraient partagés au hasard) et
un second flux d'entrée (le Bluetooth mains libres n'a qu'une entrée). Le robinet est la troisième
voie : le callback du micro publie chaque bloc ici, et chaque abonné reçoit sa propre copie dans sa
propre file bornée.

Règles : `publier` ne bloque JAMAIS (il tourne dans le callback audio) ; une file pleine perd son
plus VIEUX bloc (pour une alerte, le son de maintenant compte plus que celui d'il y a une minute) ;
les blocs sont du PCM int16 mono 16 kHz, 0,25 s chacun (8000 octets).
"""
from __future__ import annotations

import queue
import threading

TAUX = 16000  # Hz
OCTETS_PAR_BLOC = 8000  # 0,25 s en int16 mono


class RobinetAudio:
    def __init__(self) -> None:
        self._abonnes: dict[str, queue.Queue[bytes]] = {}
        self._verrou = threading.Lock()
        self.perdus: dict[str, int] = {}

    def abonner(self, nom: str, max_blocs: int = 240) -> "queue.Queue[bytes]":
        """Nouvelle file pour `nom` (remplace une éventuelle file précédente du même nom)."""
        file: queue.Queue[bytes] = queue.Queue(maxsize=max(1, int(max_blocs)))
        with self._verrou:
            self._abonnes[nom] = file
            self.perdus[nom] = 0
        return file

    def desabonner(self, nom: str) -> None:
        with self._verrou:
            self._abonnes.pop(nom, None)

    def abonnes(self) -> list[str]:
        with self._verrou:
            return list(self._abonnes)

    @property
    def actif(self) -> bool:
        return bool(self._abonnes)

    def publier(self, bloc: bytes) -> None:
        if not self._abonnes or not bloc:
            return
        with self._verrou:
            cibles = list(self._abonnes.items())
        for nom, file in cibles:
            try:
                file.put_nowait(bloc)
            except queue.Full:
                try:
                    file.get_nowait()
                except queue.Empty:
                    pass
                try:
                    file.put_nowait(bloc)
                except queue.Full:
                    pass
                self.perdus[nom] = self.perdus.get(nom, 0) + 1
