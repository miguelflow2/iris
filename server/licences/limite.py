"""Limitation de débit par adresse IP (fenêtre glissante, en mémoire).

Objectif principal : empêcher l'énumération de /api/licence. Sans limite, quelqu'un pourrait
essayer des millions d'adresses courriel pour savoir lesquelles ont un abonnement — et lesquelles
existent tout court. La limite est volontairement simple : pas de dépendance, pas de Redis.

Conséquence à connaître : le compteur vit dans le processus. Avec plusieurs instances (ou après
un redémarrage), chaque processus a le sien. C'est suffisant pour l'échelle visée ; au-delà, il
faudra un magasin partagé.
"""
from __future__ import annotations

import threading
import time
from collections import defaultdict, deque


class Limiteur:
    def __init__(self, requetes: int, fenetre: int):
        self.requetes = max(1, int(requetes))
        self.fenetre = max(1, int(fenetre))
        self._historique: dict[str, deque[float]] = defaultdict(deque)
        self._verrou = threading.Lock()

    def autoriser(self, cle: str) -> bool:
        """Consomme un jeton pour `cle` (typiquement une adresse IP). False si la limite est atteinte."""
        maintenant = time.monotonic()
        limite_basse = maintenant - self.fenetre
        with self._verrou:
            file = self._historique[cle]
            while file and file[0] < limite_basse:
                file.popleft()
            if len(file) >= self.requetes:
                return False
            file.append(maintenant)
            # Ménage : on évite que le dictionnaire grossisse indéfiniment.
            if len(self._historique) > 10000:
                self._nettoyer(limite_basse)
            return True

    def reste(self, cle: str) -> int:
        with self._verrou:
            return max(0, self.requetes - len(self._historique.get(cle, ())))

    def reinitialiser(self) -> None:
        with self._verrou:
            self._historique.clear()

    def _nettoyer(self, limite_basse: float) -> None:
        vides = [c for c, f in self._historique.items() if not f or f[-1] < limite_basse]
        for c in vides:
            del self._historique[c]


def adresse_client(requete) -> str:
    """IP de l'appelant, en tenant compte du reverse proxy de l'hébergeur (Render, Fly, Railway).

    On ne fait confiance à X-Forwarded-For que pour la limitation de débit ; elle n'autorise rien.
    """
    entete = requete.headers.get("x-forwarded-for") or ""
    if entete:
        return entete.split(",")[0].strip()
    client = getattr(requete, "client", None)
    return getattr(client, "host", "") or "inconnu"
