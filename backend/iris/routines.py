"""Routines vocales : « quand je dis "mode travail", ouvre VS Code, Spotify et mon dossier projet ».
Enregistrement des actions exécutées, puis rejeu direct (sans passer par le modèle)."""
from __future__ import annotations

import difflib
import json
import logging
import re
import unicodedata
import uuid
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable

from .db import Database
from .events import EventHub

log = logging.getLogger("iris.routines")

RECORDABLE = {
    "open_application", "open_url", "play_youtube", "open_path", "run_command", "type_text", "press_keys",
    "mouse_click", "mouse_move", "mouse_drag", "scroll", "click_text", "lock_computer", "set_reminder", "write_file",
}


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9 ]+", " ", text.lower()).strip()


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class RoutineService:
    def __init__(self, db: Database, hub: EventHub):
        self.db = db
        self.hub = hub
        self.recording: dict | None = None  # {"name", "trigger", "steps": []}

    # ------------------------------------------------------------------ CRUD
    def _public(self, row: dict) -> dict:
        return {
            "id": row["id"],
            "name": row["name"],
            "trigger": row["trigger_phrase"],
            "steps": json.loads(row["steps"] or "[]"),
            "created_at": row["created_at"],
            "runs": row["runs"],
        }

    def list(self) -> list[dict]:
        return [self._public(r) for r in self.db.query("SELECT * FROM routines ORDER BY name")]

    def get(self, routine_id: str) -> dict | None:
        row = self.db.one("SELECT * FROM routines WHERE id=?", (routine_id,))
        return self._public(row) if row else None

    def create(self, name: str, trigger: str, steps: list[dict]) -> dict:
        name = (name or "").strip()[:80]
        trigger = (trigger or name).strip()[:120]
        clean_steps = [
            {"tool": s.get("tool"), "args": s.get("args") or {}}
            for s in steps
            if isinstance(s, dict) and s.get("tool") in RECORDABLE
        ]
        if not name or not clean_steps:
            raise ValueError("routine sans nom ou sans étape exécutable")
        existing = self.db.one("SELECT id FROM routines WHERE lower(name)=lower(?)", (name,))
        rid = existing["id"] if existing else uuid.uuid4().hex
        if existing:
            self.db.execute(
                "UPDATE routines SET trigger_phrase=?, steps=? WHERE id=?", (trigger, json.dumps(clean_steps, ensure_ascii=False), rid)
            )
        else:
            self.db.execute(
                "INSERT INTO routines(id, name, trigger_phrase, steps, created_at, runs) VALUES(?,?,?,?,?,0)",
                (rid, name, trigger, json.dumps(clean_steps, ensure_ascii=False), now_iso()),
            )
        routine = self.get(rid)
        self.hub.publish("routine.updated", routine=routine)
        return routine  # type: ignore[return-value]

    def delete(self, routine_id: str) -> bool:
        cur = self.db.execute("DELETE FROM routines WHERE id=?", (routine_id,))
        if cur.rowcount:
            self.hub.publish("routine.deleted", routine_id=routine_id)
        return cur.rowcount > 0

    # ------------------------------------------------------------------ correspondance
    def match(self, text: str) -> dict | None:
        """La phrase contient-elle (ou ressemble-t-elle à) le déclencheur d'une routine ?"""
        t = normalize(text)
        if not t:
            return None
        best: tuple[float, dict] | None = None
        for routine in self.list():
            trig = normalize(routine["trigger"]) or normalize(routine["name"])
            if not trig:
                continue
            if trig in t:
                score = 1.0
            else:
                score = difflib.SequenceMatcher(None, t, trig).ratio()
            if score >= 0.82 and (best is None or score > best[0]):
                best = (score, routine)
        return best[1] if best else None

    def find_by_name(self, name: str) -> dict | None:
        n = normalize(name)
        for routine in self.list():
            if normalize(routine["name"]) == n or normalize(routine["trigger"]) == n:
                return routine
        candidates = {normalize(r["name"]): r for r in self.list()}
        close = difflib.get_close_matches(n, list(candidates), n=1, cutoff=0.7)
        return candidates[close[0]] if close else None

    # ------------------------------------------------------------------ exécution
    async def run(self, routine: dict, run_tool: Callable[[str, dict], Awaitable[Any]]) -> list[dict]:
        results: list[dict] = []
        for step in routine["steps"]:
            try:
                raw = await run_tool(step["tool"], step.get("args") or {})
                ok = not (isinstance(raw, dict) and raw.get("is_error"))
                text = raw["content"] if isinstance(raw, dict) else str(raw)
            except Exception as exc:
                ok, text = False, str(exc)
            results.append({"tool": step["tool"], "args": step.get("args") or {}, "ok": ok, "result": str(text)[:200]})
            self.hub.publish("routine.step", routine_id=routine["id"], step=results[-1])
        self.db.execute("UPDATE routines SET runs = runs + 1 WHERE id=?", (routine["id"],))
        self.hub.publish("routine.ran", routine_id=routine["id"], name=routine["name"], results=results)
        return results

    # ------------------------------------------------------------------ enregistrement
    def start_recording(self, name: str, trigger: str | None = None) -> dict:
        self.recording = {"name": name.strip()[:80], "trigger": (trigger or name).strip()[:120], "steps": []}
        self.hub.publish("routine.recording", active=True, name=self.recording["name"])
        return self.recording

    def record(self, tool: str, args: dict) -> None:
        if self.recording is not None and tool in RECORDABLE:
            self.recording["steps"].append({"tool": tool, "args": args})
            self.hub.publish("routine.recording", active=True, name=self.recording["name"], steps=len(self.recording["steps"]))

    def stop_recording(self) -> dict | None:
        rec, self.recording = self.recording, None
        self.hub.publish("routine.recording", active=False)
        if not rec or not rec["steps"]:
            return None
        return self.create(rec["name"], rec["trigger"], rec["steps"])
