"""Bus d'événements vers les clients WebSocket (renderer Electron, process principal)."""
from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any

log = logging.getLogger("iris.events")


class EventHub:
    def __init__(self):
        self._queues: set[asyncio.Queue] = set()
        self._loop: asyncio.AbstractEventLoop | None = None

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=2000)
        self._queues.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        self._queues.discard(q)

    @property
    def client_count(self) -> int:
        return len(self._queues)

    def _dispatch(self, event: dict) -> None:
        for q in list(self._queues):
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                log.warning("file d'événements pleine, client lent ignoré")

    def publish(self, type_: str, **data: Any) -> dict:
        """Utilisable depuis n'importe quel thread."""
        event = {"type": type_, "ts": time.time(), **data}
        loop = self._loop
        if loop is None or loop.is_closed():
            return event
        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            running = None
        if running is loop:
            self._dispatch(event)
        else:
            loop.call_soon_threadsafe(self._dispatch, event)
        return event

    @staticmethod
    def encode(event: dict) -> str:
        return json.dumps(event, ensure_ascii=False, default=str)
