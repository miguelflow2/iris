"""Mémoire IRIS : souvenirs chiffrés sur l'appareil, ancrés dans ce qui a été réellement dit.

Cette mémoire n'est pas générative : aucun modèle n'invente ni ne reformule un souvenir. Chaque ligne
conserve la phrase d'origine (`source_text`), sa date et la conversation d'où elle vient, si bien qu'IRIS
peut toujours dire d'où elle tient une information, et que l'utilisateur peut la relire et la corriger.
"""
from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timedelta, timezone

from .config import Settings
from .db import Database
from .security.crypto import Crypto

_WORD = re.compile(r"[\wàâäéèêëïîôöùûüÿç'-]{2,}", re.IGNORECASE)
_STOP = {
    "le", "la", "les", "un", "une", "des", "de", "du", "et", "ou", "en", "au", "aux", "ce", "ca", "ça",
    "je", "tu", "il", "elle", "on", "nous", "vous", "ils", "est", "sont", "pour", "dans", "sur", "que",
    "qui", "pas", "ne", "the", "a", "an", "of", "to", "in", "is", "it", "and", "or", "my", "me", "mon", "ma",
}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def tokenize(text: str) -> set[str]:
    return {w.lower() for w in _WORD.findall(text or "") if w.lower() not in _STOP}


class MemoryService:
    def __init__(self, db: Database, crypto: Crypto, settings: Settings):
        self.db = db
        self.crypto = crypto
        self.settings = settings

    def _retained_until(self) -> str | None:
        days = self.settings.user.retention_days
        if not days or days <= 0:
            return None
        return (datetime.now(timezone.utc) + timedelta(days=days)).isoformat(timespec="seconds")

    def add(
        self,
        text: str,
        source: str = "user",
        kind: str = "note",
        source_text: str | None = None,
        conversation_id: str | None = None,
        pinned: bool = False,
    ) -> dict:
        text = (text or "").strip()
        if not text:
            raise ValueError("mémoire vide")
        item = {
            "id": uuid.uuid4().hex,
            "created_at": now_iso(),
            "source": source,
            "kind": kind,
            "retained_until": self._retained_until(),
        }
        self.db.execute(
            "INSERT INTO memories(id, created_at, content_enc, source, kind, retained_until, "
            "source_text_enc, conversation_id, pinned) VALUES(?,?,?,?,?,?,?,?,?)",
            (
                item["id"], item["created_at"], self.crypto.encrypt(text), source, kind, item["retained_until"],
                self.crypto.encrypt(source_text) if source_text else None, conversation_id, 1 if pinned else 0,
            ),
        )
        return {**item, "text": text, "source_text": source_text, "pinned": pinned}

    def capture(self, text: str, conversation_id: str | None = None, source: str = "conversation") -> list[dict]:
        """Retient les faits durables énoncés par l'utilisateur, mot pour mot, sans passer par un modèle.
        Renvoie les souvenirs réellement ajoutés (les doublons sont ignorés)."""
        from .recall import doublon, extraire

        trouves = extraire(text)
        if not trouves:
            return []
        existants = [m["text"] for m in self.list(limit=400)]
        ajoutes: list[dict] = []
        for t in trouves:
            if doublon(t["fait"], existants):
                continue
            item = self.add(t["fait"], source=source, kind=t["kind"], source_text=t["phrase"], conversation_id=conversation_id)
            existants.append(t["fait"])
            ajoutes.append(item)
        return ajoutes

    def touch(self, ids: list[str]) -> None:
        """Un souvenir réellement utilisé compte davantage la prochaine fois : la mémoire vit à l'usage."""
        for mid in ids:
            self.db.execute("UPDATE memories SET uses = uses + 1, last_used_at = ? WHERE id = ?", (now_iso(), mid))

    def pin(self, memory_id: str, pinned: bool = True) -> bool:
        cur = self.db.execute("UPDATE memories SET pinned = ? WHERE id = ?", (1 if pinned else 0, memory_id))
        return cur.rowcount > 0

    def _decode(self, row: dict) -> dict:
        brut = row.get("source_text_enc")
        return {
            "id": row["id"],
            "created_at": row["created_at"],
            "source": row["source"],
            "kind": row["kind"],
            "retained_until": row["retained_until"],
            "text": self.crypto.decrypt(row["content_enc"]),
            # provenance : la phrase exacte d'où vient ce souvenir (preuve qu'il n'a pas été inventé)
            "source_text": self.crypto.decrypt(brut) if brut else None,
            "conversation_id": row.get("conversation_id"),
            "pinned": bool(row.get("pinned")),
            "uses": int(row.get("uses") or 0),
            "last_used_at": row.get("last_used_at"),
        }

    def list(self, limit: int = 200) -> list[dict]:
        rows = self.db.query("SELECT * FROM memories ORDER BY created_at DESC LIMIT ?", (limit,))
        return [self._decode(r) for r in rows]

    def count(self) -> int:
        row = self.db.one("SELECT COUNT(*) AS n FROM memories")
        return int(row["n"]) if row else 0

    def search(self, query: str, limit: int = 8) -> list[dict]:
        q_tokens = tokenize(query)
        if not q_tokens:
            return []
        scored = []
        for item in self.list(limit=2000):
            tokens = tokenize(item["text"])
            if not tokens:
                continue
            overlap = q_tokens & tokens
            if not overlap:
                overlap = {
                    q for q in q_tokens if len(q) >= 5 and any(t.startswith(q[:5]) for t in tokens)
                }
            if overlap:
                score = len(overlap) / len(q_tokens) + 0.1 * len(overlap) / len(tokens)
                # un souvenir épinglé ou déjà utile remonte : la mémoire se renforce à l'usage
                if item.get("pinned"):
                    score += 0.5
                score += min(0.3, 0.05 * int(item.get("uses") or 0))
                scored.append((score, item))
        scored.sort(key=lambda s: (-s[0], s[1]["created_at"]))
        return [{**item, "score": round(score, 3)} for score, item in scored[:limit]]

    def context(self, query: str, limit: int = 5, baseline: int = 4) -> list[dict]:
        """Souvenirs à donner à l'agent pour cette demande.

        La recherche par mots-clés ne suffit pas : « dis-moi tout ce que tu sais à mon sujet »
        ne partage aucun mot avec « Couleur préférée : violet », et IRIS répondait alors
        qu'elle ne savait rien alors qu'elle savait. On ajoute donc toujours les souvenirs
        épinglés et les plus récents, que la question les mentionne ou non."""
        retenus: dict[str, dict] = {}
        recents = self.list(limit=200)
        for item in recents:  # épinglés : toujours présents
            if item.get("pinned"):
                retenus[item["id"]] = item
        for item in self.search(query, limit=limit):  # pertinents pour la demande
            retenus.setdefault(item["id"], item)
        for item in recents:  # socle général, pour qu'IRIS sache toujours ce qu'elle sait
            if len(retenus) >= limit + baseline:
                break
            retenus.setdefault(item["id"], item)
        return list(retenus.values())

    def delete(self, memory_id: str) -> bool:
        cur = self.db.execute("DELETE FROM memories WHERE id=?", (memory_id,))
        return cur.rowcount > 0

    def clear(self) -> int:
        cur = self.db.execute("DELETE FROM memories")
        return cur.rowcount

    def export(self) -> str:
        return json.dumps(self.list(limit=100000), ensure_ascii=False, indent=2)

    def purge_expired(self) -> dict:
        """Purge vérifiable : suppression physique + VACUUM pour ne pas laisser de résidus."""
        now = now_iso()
        purged = {"memories": 0, "messages": 0, "events": 0}
        cur = self.db.execute(
            "DELETE FROM memories WHERE retained_until IS NOT NULL AND retained_until < ?", (now,)
        )
        purged["memories"] = cur.rowcount
        days = self.settings.user.retention_days
        if days and days > 0:
            cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat(timespec="seconds")
            cur = self.db.execute("DELETE FROM messages WHERE created_at < ?", (cutoff,))
            purged["messages"] = cur.rowcount
            self.db.execute(
                "DELETE FROM conversations WHERE kind='chat' AND updated_at < ? "
                "AND id NOT IN (SELECT DISTINCT conversation_id FROM messages)",
                (cutoff,),
            )
            cur = self.db.execute("DELETE FROM privacy_events WHERE created_at < ?", (cutoff,))
            purged["events"] = cur.rowcount
        if any(purged.values()):
            try:
                self.db.execute("VACUUM")
            except Exception:
                pass
        return purged
