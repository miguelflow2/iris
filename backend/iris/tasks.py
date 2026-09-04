"""Tâches asynchrones : un agent travaille en arrière-plan, IRIS prévient (vocalement) à la fin."""
from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timezone
from typing import Callable

from .chat import ChatService
from .db import Database
from .events import EventHub
from .security.crypto import Crypto

log = logging.getLogger("iris.tasks")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class TaskService:
    def __init__(self, db: Database, crypto: Crypto, hub: EventHub, chat: ChatService, announce: Callable[[str], None] | None = None):
        self.db = db
        self.crypto = crypto
        self.hub = hub
        self.chat = chat
        self.announce = announce
        self._running: dict[str, asyncio.Task] = {}
        chat.create_task_fn = self.create

    def _public(self, row: dict, with_result: bool = False) -> dict:
        item = {
            "id": row["id"],
            "title": row["title"],
            "agent": row["agent"],
            "status": row["status"],
            "conversation_id": row["conversation_id"],
            "created_at": row["created_at"],
            "started_at": row["started_at"],
            "completed_at": row["completed_at"],
            "error": row["error"],
            "instructions": self.crypto.decrypt(row["instructions_enc"]),
        }
        if with_result:
            item["result"] = self.crypto.decrypt(row["result_enc"]) if row["result_enc"] else ""
        return item

    def list(self, limit: int = 100) -> list[dict]:
        rows = self.db.query("SELECT * FROM tasks ORDER BY created_at DESC LIMIT ?", (limit,))
        return [self._public(r) for r in rows]

    def get(self, task_id: str) -> dict | None:
        row = self.db.one("SELECT * FROM tasks WHERE id=?", (task_id,))
        return self._public(row, with_result=True) if row else None

    def _set(self, task_id: str, **fields) -> None:
        cols = ", ".join(f"{k}=?" for k in fields)
        self.db.execute(f"UPDATE tasks SET {cols} WHERE id=?", (*fields.values(), task_id))
        task = self.get(task_id)
        if task:
            self.hub.publish("task.updated", task=task)

    async def create(self, title: str, instructions: str, agent: str = "auto") -> dict:
        title = (title or "Tâche").strip()[:120]
        instructions = (instructions or "").strip()
        if not instructions:
            raise ValueError("instructions manquantes")
        conv = self.chat.create_conversation(title=f"Tâche : {title}", agent=agent or "auto", kind="task")
        task_id = uuid.uuid4().hex
        self.db.execute(
            "INSERT INTO tasks(id, title, instructions_enc, agent, status, conversation_id, created_at) VALUES(?,?,?,?,?,?,?)",
            (task_id, title, self.crypto.encrypt(instructions), agent or "auto", "pending", conv["id"], now_iso()),
        )
        task = self.get(task_id)
        self.hub.publish("task.updated", task=task)
        runner = asyncio.get_running_loop().create_task(self._run(task_id, conv["id"], instructions, agent or "auto"))
        self._running[task_id] = runner
        runner.add_done_callback(lambda _t: self._running.pop(task_id, None))
        return task  # type: ignore[return-value]

    async def _run(self, task_id: str, conv_id: str, instructions: str, agent: str) -> None:
        self._set(task_id, status="running", started_at=now_iso())
        title = (self.get(task_id) or {}).get("title", "")
        prompt = (
            "Tu travailles en arrière-plan sur une tâche longue, sans poser de question. Méthode : 1) écris un plan en 3 à 6 "
            "étapes ; 2) exécute chaque étape avec les outils (write_file pour créer les fichiers dans ~/Documents/IRIS/<projet>, "
            "run_command pour installer/lancer/tester, read_file ou take_screenshot pour vérifier) ; 3) vérifie que le résultat "
            "fonctionne réellement ; 4) termine par un rapport en 3 phrases : ce qui a été fait, où le trouver, ce qui reste. "
            "Tâche :\n\n" + instructions
        )
        try:
            result = await self.chat.run_and_wait(conv_id, prompt, agent=agent, source="task")
        except asyncio.CancelledError:
            self._set(task_id, status="cancelled", completed_at=now_iso())
            return
        except Exception as exc:  # pragma: no cover
            log.exception("tâche %s en échec", task_id)
            self._set(task_id, status="failed", completed_at=now_iso(), error=str(exc))
            return
        if result.get("cancelled"):
            self._set(task_id, status="cancelled", completed_at=now_iso())
            return
        if result.get("error") and not (result.get("message") or {}).get("text"):
            self._set(task_id, status="failed", completed_at=now_iso(), error=result["error"])
            if self.announce:
                self.announce(f"La tâche {title} a échoué.")
            return
        text = (result.get("message") or {}).get("text", "")
        self._set(task_id, status="done", completed_at=now_iso(), result_enc=self.crypto.encrypt(text))
        if self.announce:
            self.announce(f"Tâche terminée : {title}.")

    def cancel(self, task_id: str) -> bool:
        task = self.get(task_id)
        if not task:
            return False
        runner = self._running.get(task_id)
        if runner and not runner.done():
            if task.get("conversation_id"):
                self.chat.cancel(task["conversation_id"])
            runner.cancel()
            return True
        return False

    def delete(self, task_id: str) -> bool:
        self.cancel(task_id)
        task = self.get(task_id)
        if task and task.get("conversation_id"):
            self.chat.delete_conversation(task["conversation_id"])
        cur = self.db.execute("DELETE FROM tasks WHERE id=?", (task_id,))
        if cur.rowcount:
            self.hub.publish("task.deleted", task_id=task_id)
        return cur.rowcount > 0
