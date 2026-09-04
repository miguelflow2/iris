"""Présence : IRIS vit sur cet appareil, elle sait depuis quand, et ce qui s'est passé entre deux fois.

Sans cela, IRIS redémarre amnésique à chaque lancement : elle ne sait ni depuis combien de temps elle est
installée, ni quand elle a parlé à l'utilisateur pour la dernière fois. Tout est écrit sur le disque local,
rien n'est reconstitué par un modèle.
"""
from __future__ import annotations

import logging
import platform
import socket
from datetime import datetime, timezone

from .db import Database

log = logging.getLogger("iris.presence")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _parse(value: str | None) -> datetime | None:
    try:
        return datetime.fromisoformat(value) if value else None
    except ValueError:
        return None


def humanize_gap(seconds: float) -> str:
    """Écart en français parlé : ce qu'IRIS peut dire à voix haute sans lire un nombre brut."""
    if seconds < 90:
        return "à l'instant"
    minutes = seconds / 60
    if minutes < 60:
        n = int(round(minutes))
        return f"il y a {n} minute{'s' if n > 1 else ''}"
    heures = minutes / 60
    if heures < 24:
        n = int(round(heures))
        return f"il y a {n} heure{'s' if n > 1 else ''}"
    jours = heures / 24
    if jours < 30:
        n = int(round(jours))
        return "hier" if n == 1 else f"il y a {n} jours"
    mois = jours / 30.4
    n = int(round(mois))
    return f"il y a {n} mois" if n > 1 else "il y a un mois"


class Presence:
    """Journal de vie d'IRIS sur cet appareil : première installation, sessions, dernière parole."""

    def __init__(self, db: Database):
        self.db = db
        self.session_started = now_iso()
        self._ensure()

    # ------------------------------------------------------------------ stockage
    def _ensure(self) -> None:
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS presence (key TEXT PRIMARY KEY, value TEXT NOT NULL, updated_at TEXT NOT NULL)"
        )

    def get(self, key: str, default: str = "") -> str:
        row = self.db.one("SELECT value FROM presence WHERE key=?", (key,))
        return row["value"] if row else default

    def set(self, key: str, value: str) -> None:
        self.db.execute(
            "INSERT INTO presence(key, value, updated_at) VALUES(?,?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
            (key, str(value), now_iso()),
        )

    def bump(self, key: str, step: int = 1) -> int:
        try:
            valeur = int(self.get(key, "0")) + step
        except ValueError:
            valeur = step
        self.set(key, str(valeur))
        return valeur

    # ------------------------------------------------------------------ cycle de vie
    def start_session(self) -> dict:
        """Appelé au démarrage du backend. Retient l'écart avec la session précédente."""
        premiere = self.get("first_seen")
        if not premiere:
            self.set("first_seen", self.session_started)
            self.set("device_name", socket.gethostname())
            self.set("device_os", f"{platform.system()} {platform.release()}")
            premiere = self.session_started
        self.set("previous_seen", self.get("last_seen"))
        self.set("last_seen", self.session_started)
        sessions = self.bump("sessions")
        log.info("présence : session %d sur cet appareil, installée depuis %s", sessions, premiere[:10])
        return self.info()

    def heartbeat(self) -> None:
        """Marque IRIS comme vivante ; permet de savoir, au prochain démarrage, quand elle s'est arrêtée."""
        self.set("last_seen", now_iso())

    def note_interaction(self, kind: str = "chat") -> None:
        self.set("last_interaction", now_iso())
        self.set("last_interaction_kind", kind)
        self.bump("interactions")

    # ------------------------------------------------------------------ lecture
    def info(self) -> dict:
        premiere = _parse(self.get("first_seen"))
        precedente = _parse(self.get("previous_seen"))
        derniere_parole = _parse(self.get("last_interaction"))
        maintenant = datetime.now(timezone.utc)
        return {
            "device_name": self.get("device_name") or socket.gethostname(),
            "device_os": self.get("device_os"),
            "first_seen": self.get("first_seen"),
            "installed_days": (maintenant - premiere).days if premiere else 0,
            "sessions": int(self.get("sessions", "0") or 0),
            "interactions": int(self.get("interactions", "0") or 0),
            "previous_seen": self.get("previous_seen"),
            "away_for": humanize_gap((maintenant - precedente).total_seconds()) if precedente else "",
            "last_interaction": self.get("last_interaction"),
            "last_interaction_ago": humanize_gap((maintenant - derniere_parole).total_seconds()) if derniere_parole else "",
            "session_started": self.session_started,
        }

    def context_line(self) -> str:
        """Une ligne factuelle pour le prompt : ce qu'IRIS sait vraiment de sa vie sur cet appareil.
        Uniquement des faits lus sur le disque, jamais une reconstitution."""
        i = self.info()
        bouts = [f"Tu es installée sur l'ordinateur « {i['device_name']} »"]
        if i["installed_days"] >= 1:
            bouts.append(f"depuis {i['installed_days']} jour{'s' if i['installed_days'] > 1 else ''}")
        if i["sessions"] > 1:
            bouts.append(f"c'est ton {i['sessions']}e démarrage")
        ligne = ", ".join(bouts) + "."
        if i["last_interaction_ago"]:
            ligne += f" Dernier échange avec l'utilisateur : {i['last_interaction_ago']}."
        return ligne
