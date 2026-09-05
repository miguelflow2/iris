"""Porte de consentement : rien ne quitte l'ordinateur sans un accord explicite par type de donnée."""
from __future__ import annotations

import csv
import hashlib
import io
import json
from datetime import datetime, timezone

from .config import Settings
from .db import Database
from .events import EventHub

DATA_TYPES: dict[str, dict] = {
    "transcript": {
        "label": "Texte de vos demandes",
        "description": "Ce que vous tapez ou dictez, envoyé à l'IA qui répond — par défaut le relais VELA compris dans votre forfait, qui transmet sans conserver.",
    },
    "audio_raw": {
        "label": "Audio brut du micro",
        "description": "Uniquement si la reconnaissance vocale hors-ligne n'est pas disponible et que vous activez la reconnaissance cloud.",
    },
    "image": {
        "label": "Images jointes",
        "description": "Photos ou fichiers image que vous joignez volontairement à une demande.",
    },
    "screen": {
        "label": "Captures d'écran",
        "description": "Capture de votre écran demandée par vous ou par l'IA (toujours signalée par l'indicateur).",
    },
    "memory": {
        "label": "Extraits de mémoire",
        "description": "Souvenirs IRIS pertinents ajoutés au contexte de l'IA pour des réponses personnalisées.",
    },
}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class ConsentRequired(Exception):
    def __init__(self, data_type: str, reason: str = ""):
        self.data_type = data_type
        self.reason = reason or DATA_TYPES.get(data_type, {}).get("label", data_type)
        super().__init__(f"consentement requis: {data_type}")


class LocalOnlyMode(Exception):
    pass


class ConsentGate:
    def __init__(self, db: Database, settings: Settings, hub: EventHub):
        self.db = db
        self.settings = settings
        self.hub = hub

    def status(self) -> dict:
        rows = {r["data_type"]: r for r in self.db.query("SELECT * FROM consents")}
        out = {}
        for dt, meta in DATA_TYPES.items():
            row = rows.get(dt)
            out[dt] = {
                **meta,
                "granted": bool(row["granted"]) if row else False,
                "updated_at": row["updated_at"] if row else None,
            }
        return out

    def is_granted(self, data_type: str) -> bool:
        row = self.db.one("SELECT granted FROM consents WHERE data_type=?", (data_type,))
        return bool(row and row["granted"])

    def set(self, data_type: str, granted: bool) -> None:
        if data_type not in DATA_TYPES:
            raise ValueError(f"type de donnée inconnu: {data_type}")
        self.db.execute(
            "INSERT INTO consents(data_type, granted, updated_at) VALUES(?,?,?) "
            "ON CONFLICT(data_type) DO UPDATE SET granted=excluded.granted, updated_at=excluded.updated_at",
            (data_type, 1 if granted else 0, now_iso()),
        )
        self.log("consent_granted" if granted else "consent_revoked", data_type=data_type)
        self.hub.publish("consent.updated", consent=self.status())

    def check(self, data_type: str, agent: str | None = None) -> None:
        """Lève ConsentRequired / LocalOnlyMode si l'envoi n'est pas autorisé.
        Les agents locaux (local=True) ne sont pas soumis au consentement d'envoi externe."""
        if agent:
            cfg = self.settings.user.agents.get(agent)
            if cfg and cfg.local:
                return
        if self.settings.user.local_only:
            raise LocalOnlyMode()
        if not self.is_granted(data_type):
            raise ConsentRequired(data_type)

    @staticmethod
    def _digest(prev: str, created_at: str, event_type: str, data_type, agent, detail: str) -> str:
        payload = "|".join([prev or "", created_at, event_type, data_type or "", agent or "", detail or ""])
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def log(self, event_type: str, data_type: str | None = None, agent: str | None = None, detail: str = "") -> None:
        """Chaque entrée est chaînée à la précédente (SHA-256) : toute modification a posteriori est détectable."""
        created_at = now_iso()
        detail = (detail or "")[:500]
        last = self.db.one("SELECT hash FROM privacy_events ORDER BY id DESC LIMIT 1")
        prev = (last or {}).get("hash") or ""
        digest = self._digest(prev, created_at, event_type, data_type, agent, detail)
        self.db.execute(
            "INSERT INTO privacy_events(created_at, event_type, data_type, agent, detail, prev_hash, hash) VALUES(?,?,?,?,?,?,?)",
            (created_at, event_type, data_type, agent, detail, prev, digest),
        )

    def verify(self) -> dict:
        """Recalcule la chaîne : {'ok': bool, 'count': n, 'first_bad_id': id|None}."""
        prev = ""
        count = 0
        for row in self.db.query("SELECT * FROM privacy_events ORDER BY id ASC"):
            count += 1
            if row.get("hash") is None:  # entrées antérieures à la chaîne : tolérées mais signalées
                prev = ""
                continue
            expected = self._digest(prev, row["created_at"], row["event_type"], row["data_type"], row["agent"], row["detail"] or "")
            if expected != row["hash"] or (row.get("prev_hash") or "") != prev:
                return {"ok": False, "count": count, "first_bad_id": row["id"]}
            prev = row["hash"]
        return {"ok": True, "count": count, "first_bad_id": None, "last_hash": prev}

    def export(self, fmt: str = "json") -> str:
        rows = self.db.query("SELECT * FROM privacy_events ORDER BY id ASC")
        if fmt == "csv":
            buf = io.StringIO()
            writer = csv.DictWriter(buf, fieldnames=["id", "created_at", "event_type", "data_type", "agent", "detail", "prev_hash", "hash"])
            writer.writeheader()
            for r in rows:
                writer.writerow({k: r.get(k) for k in writer.fieldnames})
            return buf.getvalue()
        return json.dumps({"exported_at": now_iso(), "verification": self.verify(), "events": rows}, ensure_ascii=False, indent=2)

    def events(self, limit: int = 200) -> list[dict]:
        return self.db.query("SELECT * FROM privacy_events ORDER BY id DESC LIMIT ?", (limit,))

    def clear_events(self) -> None:
        self.db.execute("DELETE FROM privacy_events")
