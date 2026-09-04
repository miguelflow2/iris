"""Rappels contextuels : « rappelle-moi d'appeler Paul dans 20 minutes » → annonce vocale + notification à l'heure dite."""
from __future__ import annotations

import asyncio
import logging
import re
import uuid
from datetime import datetime, timedelta
from typing import Callable

from .db import Database
from .events import EventHub

log = logging.getLogger("iris.reminders")


def parse_due(minutes: float | None = None, at: str | None = None, now: datetime | None = None) -> datetime:
    """`minutes` (délai) ou `at` ('HH:MM', 'demain 09:00', 'YYYY-MM-DD HH:MM')."""
    now = now or datetime.now()
    if minutes is not None and minutes > 0:
        return now + timedelta(minutes=float(minutes))
    if at:
        text = at.strip().lower()
        tomorrow = "demain" in text
        m = re.search(r"(\d{4}-\d{2}-\d{2})\s+(\d{1,2})[:h](\d{2})?", text)
        if m:
            date = datetime.strptime(m.group(1), "%Y-%m-%d")
            return date.replace(hour=int(m.group(2)), minute=int(m.group(3) or 0))
        m = re.search(r"(\d{1,2})\s*[:h]\s*(\d{2})?", text)
        if m:
            due = now.replace(hour=int(m.group(1)), minute=int(m.group(2) or 0), second=0, microsecond=0)
            if tomorrow or due <= now:
                due += timedelta(days=1)
            return due
    raise ValueError("précise un délai (minutes) ou une heure (ex. 15:30)")


class ReminderService:
    def __init__(self, db: Database, hub: EventHub, announce: Callable[[str], None] | None = None):
        self.db = db
        self.hub = hub
        self.announce = announce
        self._task: asyncio.Task | None = None

    def _public(self, row: dict) -> dict:
        return {"id": row["id"], "text": row["text"], "due_at": row["due_at"], "created_at": row["created_at"], "done": bool(row["done"])}

    def list(self, include_done: bool = False) -> list[dict]:
        sql = "SELECT * FROM reminders" + ("" if include_done else " WHERE done=0") + " ORDER BY due_at"
        return [self._public(r) for r in self.db.query(sql)]

    def create(self, text: str, minutes: float | None = None, at: str | None = None) -> dict:
        text = (text or "").strip()
        if not text:
            raise ValueError("rappel vide")
        due = parse_due(minutes, at)
        rid = uuid.uuid4().hex
        self.db.execute(
            "INSERT INTO reminders(id, text, due_at, created_at, done) VALUES(?,?,?,?,0)",
            (rid, text, due.isoformat(timespec="seconds"), datetime.now().isoformat(timespec="seconds")),
        )
        item = self._public(self.db.one("SELECT * FROM reminders WHERE id=?", (rid,)))  # type: ignore[arg-type]
        self.hub.publish("reminder.updated", reminder=item)
        return item

    def delete(self, reminder_id: str) -> bool:
        cur = self.db.execute("DELETE FROM reminders WHERE id=?", (reminder_id,))
        if cur.rowcount:
            self.hub.publish("reminder.deleted", reminder_id=reminder_id)
        return cur.rowcount > 0

    def due_now(self, now: datetime | None = None) -> list[dict]:
        now = (now or datetime.now()).isoformat(timespec="seconds")
        rows = self.db.query("SELECT * FROM reminders WHERE done=0 AND due_at <= ? ORDER BY due_at", (now,))
        return [self._public(r) for r in rows]

    def fire(self, reminder: dict) -> None:
        self.db.execute("UPDATE reminders SET done=1 WHERE id=?", (reminder["id"],))
        self.hub.publish("reminder.due", reminder=reminder)
        if self.announce:
            self.announce(f"Rappel : {reminder['text']}")

    async def loop(self, interval: float = 15.0) -> None:
        while True:
            try:
                for reminder in self.due_now():
                    self.fire(reminder)
            except Exception as exc:  # pragma: no cover
                log.warning("rappels: %s", exc)
            await asyncio.sleep(interval)
