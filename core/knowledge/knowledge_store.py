"""
core/knowledge/knowledge_store.py — FRIDAY 4.0 (M7)
KnowledgeStore: SQLite persistence + index for distilled knowledge. Same store
discipline as M2/M4/M5/M6 (per-thread connections, WAL, migration gate).

Storage hierarchy (M7): the Obsidian vault (Markdown) is the human-readable source
of truth; this DB is the rebuildable structured index + metadata; the vector index
is the rebuildable retrieval cache. Either derived layer can be reconstructed from
the vault.

Tables: knowledge, knowledge_links, knowledge_history, knowledge_metrics,
schema_version.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
import time
from pathlib import Path
from typing import Optional

from .knowledge_models import KnowledgeEntry, KnowledgeLink

log = logging.getLogger("friday.knowledge.store")

_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_PATH = _ROOT / "data" / "knowledge.db"
_SCHEMA_VERSION = 1


class KnowledgeStore:
    def __init__(self, path: Optional[str | Path] = None) -> None:
        self._path = str(Path(path) if path else _DEFAULT_PATH)
        Path(self._path).parent.mkdir(parents=True, exist_ok=True)
        self._local = threading.local()
        self._init_schema()

    def _conn(self) -> sqlite3.Connection:
        c = getattr(self._local, "conn", None)
        if c is None:
            c = sqlite3.connect(self._path, check_same_thread=False)
            c.row_factory = sqlite3.Row
            c.execute("PRAGMA journal_mode=WAL")
            c.execute("PRAGMA synchronous=NORMAL")
            c.execute("PRAGMA busy_timeout=5000")
            self._local.conn = c
        return c

    def _init_schema(self) -> None:
        c = self._conn()
        c.executescript(
            """
            CREATE TABLE IF NOT EXISTS schema_version (
                version INTEGER PRIMARY KEY, applied_at REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS knowledge (
                id          TEXT PRIMARY KEY,
                title       TEXT NOT NULL,
                category    TEXT NOT NULL DEFAULT 'General',
                content     TEXT NOT NULL DEFAULT '',
                confidence  REAL NOT NULL DEFAULT 0.5,
                source      TEXT NOT NULL DEFAULT 'system',
                created_at  REAL NOT NULL,
                updated_at  REAL NOT NULL,
                usage_count INTEGER NOT NULL DEFAULT 0,
                status      TEXT NOT NULL DEFAULT 'active',
                embed_id    INTEGER,
                vault_path  TEXT,
                metadata    TEXT NOT NULL DEFAULT '{}'
            );
            CREATE TABLE IF NOT EXISTS knowledge_links (
                source_id TEXT NOT NULL,
                target_id TEXT NOT NULL,
                relation  TEXT NOT NULL DEFAULT 'related',
                metadata  TEXT NOT NULL DEFAULT '{}',
                PRIMARY KEY (source_id, target_id, relation)
            );
            CREATE TABLE IF NOT EXISTS knowledge_history (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                knowledge_id TEXT NOT NULL,
                ts           REAL NOT NULL,
                kind         TEXT NOT NULL,
                data         TEXT NOT NULL DEFAULT '{}'
            );
            CREATE TABLE IF NOT EXISTS knowledge_metrics (
                id     INTEGER PRIMARY KEY AUTOINCREMENT,
                ts     REAL NOT NULL,
                metric TEXT NOT NULL,
                value  REAL NOT NULL DEFAULT 0
            );
            CREATE INDEX IF NOT EXISTS idx_know_category ON knowledge(category);
            CREATE INDEX IF NOT EXISTS idx_know_status ON knowledge(status);
            CREATE INDEX IF NOT EXISTS idx_klinks_src ON knowledge_links(source_id);
            CREATE INDEX IF NOT EXISTS idx_khist_kid ON knowledge_history(knowledge_id);
            """
        )
        if c.execute("SELECT MAX(version) FROM schema_version").fetchone()[0] is None:
            c.execute("INSERT INTO schema_version (version, applied_at) VALUES (?, ?)",
                      (_SCHEMA_VERSION, time.time()))
        c.commit()

    # ── CRUD ───────────────────────────────────────────────────────────────────
    def create(self, entry: KnowledgeEntry) -> str:
        c = self._conn()
        c.execute(
            """INSERT INTO knowledge
               (id, title, category, content, confidence, source, created_at, updated_at,
                usage_count, status, embed_id, vault_path, metadata)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            entry.to_row(),
        )
        c.commit()
        return entry.id

    def update(self, entry: KnowledgeEntry) -> None:
        entry.updated_at = time.time()
        c = self._conn()
        c.execute(
            """UPDATE knowledge SET title=?, category=?, content=?, confidence=?, source=?,
               updated_at=?, usage_count=?, status=?, embed_id=?, vault_path=?, metadata=?
               WHERE id=?""",
            (entry.title, entry.category, entry.content, entry.confidence, entry.source,
             entry.updated_at, entry.usage_count, entry.status, entry.embed_id,
             entry.vault_path, json.dumps(entry.metadata), entry.id),
        )
        c.commit()

    def delete(self, knowledge_id: str) -> None:
        c = self._conn()
        c.execute("DELETE FROM knowledge WHERE id=?", (knowledge_id,))
        c.execute("DELETE FROM knowledge_links WHERE source_id=? OR target_id=?",
                  (knowledge_id, knowledge_id))
        c.commit()

    def get(self, knowledge_id: str) -> Optional[KnowledgeEntry]:
        r = self._conn().execute("SELECT * FROM knowledge WHERE id=?", (knowledge_id,)).fetchone()
        return KnowledgeEntry.from_row(r) if r else None

    def touch_usage(self, knowledge_id: str) -> None:
        c = self._conn()
        c.execute("UPDATE knowledge SET usage_count = usage_count + 1 WHERE id=?",
                  (knowledge_id,))
        c.commit()

    def set_status(self, knowledge_id: str, status: str) -> None:
        c = self._conn()
        c.execute("UPDATE knowledge SET status=?, updated_at=? WHERE id=?",
                  (status, time.time(), knowledge_id))
        c.commit()

    def list(self, category: Optional[str] = None, status: Optional[str] = None,
             limit: int = 1000) -> list[KnowledgeEntry]:
        clauses, params = [], []
        if category is not None:
            clauses.append("category=?"); params.append(category)
        if status is not None:
            clauses.append("status=?"); params.append(status)
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        rows = self._conn().execute(
            f"SELECT * FROM knowledge{where} ORDER BY updated_at DESC LIMIT ?",
            params + [limit]).fetchall()
        return [KnowledgeEntry.from_row(r) for r in rows]

    def search_text(self, query: str, limit: int = 20) -> list[KnowledgeEntry]:
        like = f"%{(query or '').lower()}%"
        rows = self._conn().execute(
            """SELECT * FROM knowledge
               WHERE status='active' AND (LOWER(title) LIKE ? OR LOWER(content) LIKE ?)
               ORDER BY confidence DESC, usage_count DESC LIMIT ?""",
            (like, like, limit)).fetchall()
        return [KnowledgeEntry.from_row(r) for r in rows]

    def find_by_title(self, title: str, category: Optional[str] = None) -> Optional[KnowledgeEntry]:
        if category is not None:
            r = self._conn().execute(
                "SELECT * FROM knowledge WHERE LOWER(title)=? AND category=? LIMIT 1",
                (title.strip().lower(), category)).fetchone()
        else:
            r = self._conn().execute(
                "SELECT * FROM knowledge WHERE LOWER(title)=? LIMIT 1",
                (title.strip().lower(),)).fetchone()
        return KnowledgeEntry.from_row(r) if r else None

    def by_ids(self, ids: list[str]) -> list[KnowledgeEntry]:
        if not ids:
            return []
        marks = ",".join("?" * len(ids))
        rows = self._conn().execute(
            f"SELECT * FROM knowledge WHERE id IN ({marks})", ids).fetchall()
        return [KnowledgeEntry.from_row(r) for r in rows]

    def all_entries(self, status: Optional[str] = None) -> list[KnowledgeEntry]:
        return self.list(status=status, limit=1_000_000)

    # ── links ──────────────────────────────────────────────────────────────────
    def add_link(self, link: KnowledgeLink) -> None:
        c = self._conn()
        c.execute(
            """INSERT INTO knowledge_links (source_id, target_id, relation, metadata)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(source_id, target_id, relation) DO UPDATE SET
                 metadata=excluded.metadata""",
            (link.source_id, link.target_id, link.relation, json.dumps(link.metadata)))
        c.commit()

    def remove_link(self, source_id: str, target_id: str, relation: str) -> None:
        c = self._conn()
        c.execute("DELETE FROM knowledge_links WHERE source_id=? AND target_id=? AND relation=?",
                  (source_id, target_id, relation))
        c.commit()

    def links_for(self, knowledge_id: str) -> list[KnowledgeLink]:
        rows = self._conn().execute(
            "SELECT * FROM knowledge_links WHERE source_id=? OR target_id=?",
            (knowledge_id, knowledge_id)).fetchall()
        return [KnowledgeLink(r["source_id"], r["target_id"], r["relation"],
                              _loads(r["metadata"], {})) for r in rows]

    def all_links(self) -> list[KnowledgeLink]:
        rows = self._conn().execute("SELECT * FROM knowledge_links").fetchall()
        return [KnowledgeLink(r["source_id"], r["target_id"], r["relation"],
                              _loads(r["metadata"], {})) for r in rows]

    # ── history / metrics ──────────────────────────────────────────────────────
    def add_history(self, knowledge_id: str, kind: str, data: Optional[dict] = None) -> None:
        c = self._conn()
        c.execute("INSERT INTO knowledge_history (knowledge_id, ts, kind, data) VALUES (?, ?, ?, ?)",
                  (knowledge_id, time.time(), kind, json.dumps(data or {})))
        c.commit()

    def history(self, knowledge_id: str, limit: int = 50) -> list[dict]:
        rows = self._conn().execute(
            "SELECT * FROM knowledge_history WHERE knowledge_id=? ORDER BY ts DESC LIMIT ?",
            (knowledge_id, limit)).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["data"] = _loads(d["data"], {})
            out.append(d)
        return out

    def record_metric(self, metric: str, value: float = 1.0) -> None:
        c = self._conn()
        c.execute("INSERT INTO knowledge_metrics (ts, metric, value) VALUES (?, ?, ?)",
                  (time.time(), metric, value))
        c.commit()

    # ── diagnostics ────────────────────────────────────────────────────────────
    def counts(self) -> dict:
        c = self._conn()
        total = c.execute("SELECT COUNT(*) FROM knowledge").fetchone()[0]
        active = c.execute("SELECT COUNT(*) FROM knowledge WHERE status='active'").fetchone()[0]
        archived = c.execute("SELECT COUNT(*) FROM knowledge WHERE status='archived'").fetchone()[0]
        by_cat = {k: n for k, n in c.execute(
            "SELECT category, COUNT(*) FROM knowledge GROUP BY category")}
        links = c.execute("SELECT COUNT(*) FROM knowledge_links").fetchone()[0]
        return {"total": total, "active": active, "archived": archived,
                "by_category": by_cat, "links": links}

    def health(self) -> dict:
        c = self.counts()
        return {"status": "ok", "entries": c["total"], "active": c["active"],
                "archived": c["archived"], "links": c["links"]}

    # ── export / import ────────────────────────────────────────────────────────
    def export(self) -> dict:
        return {
            "entries": [e.to_dict() for e in self.all_entries()],
            "links": [l.to_dict() for l in self.all_links()],
        }

    def import_(self, data: dict) -> int:
        n = 0
        for d in data.get("entries", []):
            if self.get(d["id"]) is None:
                self.create(KnowledgeEntry.from_dict(d))
                n += 1
        for l in data.get("links", []):
            self.add_link(KnowledgeLink(l["source_id"], l["target_id"],
                                        l.get("relation", "related"), l.get("metadata", {})))
        return n

    def close(self) -> None:
        conn = getattr(self._local, "conn", None)
        if conn is not None:
            conn.close()
            self._local.conn = None


def _loads(text, default):
    try:
        return json.loads(text)
    except (TypeError, ValueError):
        return default
