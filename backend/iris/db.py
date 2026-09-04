"""Base SQLite locale. Les contenus sensibles sont chiffrés (voir security.crypto) avant insertion."""
from __future__ import annotations

import sqlite3
import threading
from pathlib import Path
from typing import Any, Iterable

SCHEMA = """
CREATE TABLE IF NOT EXISTS conversations (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    agent TEXT NOT NULL DEFAULT 'auto',
    kind TEXT NOT NULL DEFAULT 'chat',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    archived INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS messages (
    id TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    role TEXT NOT NULL,
    content_enc BLOB NOT NULL,
    agent TEXT,
    model TEXT,
    meta TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_messages_conv ON messages(conversation_id, created_at);
CREATE TABLE IF NOT EXISTS memories (
    id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    content_enc BLOB NOT NULL,
    source TEXT NOT NULL DEFAULT 'user',
    kind TEXT NOT NULL DEFAULT 'note',
    retained_until TEXT
);
CREATE TABLE IF NOT EXISTS consents (
    data_type TEXT PRIMARY KEY,
    granted INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS privacy_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    event_type TEXT NOT NULL,
    data_type TEXT,
    agent TEXT,
    detail TEXT
);
CREATE TABLE IF NOT EXISTS routines (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    trigger_phrase TEXT NOT NULL,
    steps TEXT NOT NULL,
    created_at TEXT NOT NULL,
    runs INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS reminders (
    id TEXT PRIMARY KEY,
    text TEXT NOT NULL,
    due_at TEXT NOT NULL,
    created_at TEXT NOT NULL,
    done INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS plan_usage (
    month TEXT PRIMARY KEY,
    requests INTEGER NOT NULL DEFAULT 0,
    tts_chars INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS tasks (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    instructions_enc BLOB NOT NULL,
    agent TEXT NOT NULL,
    status TEXT NOT NULL,
    conversation_id TEXT,
    created_at TEXT NOT NULL,
    started_at TEXT,
    completed_at TEXT,
    result_enc BLOB,
    error TEXT
);
"""


class Database:
    def __init__(self, path: Path | str):
        self.path = str(path)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.executescript(SCHEMA)
        self._migrate()

    def _migrate(self) -> None:
        cols = {r["name"] for r in self._conn.execute("PRAGMA table_info(privacy_events)").fetchall()}
        for col in ("prev_hash", "hash"):
            if col not in cols:
                self._conn.execute(f"ALTER TABLE privacy_events ADD COLUMN {col} TEXT")
        # Provenance des souvenirs : la phrase exacte dont ils viennent, et leur usage réel.
        # Sans cela, impossible de prouver qu'un souvenir n'a pas été inventé.
        mem = {r["name"] for r in self._conn.execute("PRAGMA table_info(memories)").fetchall()}
        for col, decl in (
            ("source_text_enc", "BLOB"),
            ("conversation_id", "TEXT"),
            ("pinned", "INTEGER NOT NULL DEFAULT 0"),
            ("uses", "INTEGER NOT NULL DEFAULT 0"),
            ("last_used_at", "TEXT"),
        ):
            if col not in mem:
                self._conn.execute(f"ALTER TABLE memories ADD COLUMN {col} {decl}")

    def execute(self, sql: str, params: Iterable[Any] = ()) -> sqlite3.Cursor:
        with self._lock:
            return self._conn.execute(sql, tuple(params))

    def query(self, sql: str, params: Iterable[Any] = ()) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(sql, tuple(params)).fetchall()
        return [dict(r) for r in rows]

    def one(self, sql: str, params: Iterable[Any] = ()) -> dict | None:
        rows = self.query(sql, params)
        return rows[0] if rows else None

    def close(self) -> None:
        with self._lock:
            self._conn.close()
