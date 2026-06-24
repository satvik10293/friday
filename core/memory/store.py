"""
core/memory/store.py — FRIDAY 4.0
The MemoryStore: SQLite source of truth for episodic/semantic/archival memory.

Fixes the verified 3.0 chronicle defects:
  • Per-thread connections (threading.local) + WAL + busy_timeout — replaces the
    single shared connection whose `_conn_lock` was declared but never used.
  • `embed_id` is actually written (the in-row link the 3.0 schema had but ignored),
    so the vector index is always rebuildable from the store.
  • Migration-gated schema (`schema_version`) from day one.
  • Soft-delete (`forget`) + supersede lineage (`amend`) for auditability — and the
    deletion path 3.0 never had.
  • FTS5 keyword search when available, LIKE fallback otherwise.

One table, one id space: summaries are just memory rows with kind='summary',
tier='semantic'. No second table to keep in sync.
"""

from __future__ import annotations

import json
import logging
import re
import sqlite3
import threading
import time
from pathlib import Path
from typing import Iterator, Optional

log = logging.getLogger("friday.memory.store")

_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_PATH = _ROOT / "data" / "memory.db"
_SCHEMA_VERSION = 1
_TOKEN = re.compile(r"[a-z0-9]+")

TIERS = ("working", "episodic", "semantic", "archival")


class MemoryStore:
    def __init__(self, path: Optional[str | Path] = None) -> None:
        self._path = str(Path(path) if path else _DEFAULT_PATH)
        Path(self._path).parent.mkdir(parents=True, exist_ok=True)
        self._local = threading.local()
        self._fts = False
        self._init_schema()

    # ── connection (one per thread) ───────────────────────────────────────────
    def _conn(self) -> sqlite3.Connection:
        c = getattr(self._local, "conn", None)
        if c is None:
            c = sqlite3.connect(self._path, check_same_thread=False)
            c.row_factory = sqlite3.Row
            c.execute("PRAGMA journal_mode=WAL")
            c.execute("PRAGMA synchronous=NORMAL")
            c.execute("PRAGMA foreign_keys=ON")
            c.execute("PRAGMA busy_timeout=5000")
            self._local.conn = c
        return c

    # ── schema ─────────────────────────────────────────────────────────────────
    def _detect_fts(self, c: sqlite3.Connection) -> bool:
        try:
            c.execute("CREATE VIRTUAL TABLE IF NOT EXISTS _fts_probe USING fts5(x)")
            c.execute("DROP TABLE IF EXISTS _fts_probe")
            return True
        except sqlite3.OperationalError:
            return False

    def _init_schema(self) -> None:
        c = self._conn()
        self._fts = self._detect_fts(c)
        c.executescript(
            """
            CREATE TABLE IF NOT EXISTS schema_version (
                version INTEGER PRIMARY KEY, applied_at REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS imports (
                name TEXT PRIMARY KEY, applied_at REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS memories (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                ts            REAL    NOT NULL,
                session_id    TEXT    NOT NULL DEFAULT '',
                role          TEXT    NOT NULL,
                kind          TEXT    NOT NULL DEFAULT 'conversation',
                content       TEXT    NOT NULL,
                topic         TEXT    NOT NULL DEFAULT '',
                importance    REAL    NOT NULL DEFAULT 0.5,
                tier          TEXT    NOT NULL DEFAULT 'episodic',
                embed_id      INTEGER,
                access_count  INTEGER NOT NULL DEFAULT 0,
                last_access   REAL,
                deleted       INTEGER NOT NULL DEFAULT 0,
                superseded_by INTEGER,
                metadata      TEXT    NOT NULL DEFAULT '{}'
            );
            CREATE INDEX IF NOT EXISTS idx_mem_tier    ON memories(tier);
            CREATE INDEX IF NOT EXISTS idx_mem_topic   ON memories(topic);
            CREATE INDEX IF NOT EXISTS idx_mem_ts      ON memories(ts);
            CREATE INDEX IF NOT EXISTS idx_mem_deleted ON memories(deleted);
            """
        )
        if self._fts:
            c.executescript(
                """
                CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts
                    USING fts5(content, topic, content='memories', content_rowid='id');
                CREATE TRIGGER IF NOT EXISTS memories_ai AFTER INSERT ON memories BEGIN
                    INSERT INTO memories_fts(rowid, content, topic)
                    VALUES (new.id, new.content, new.topic);
                END;
                CREATE TRIGGER IF NOT EXISTS memories_ad AFTER DELETE ON memories BEGIN
                    INSERT INTO memories_fts(memories_fts, rowid, content, topic)
                    VALUES ('delete', old.id, old.content, old.topic);
                END;
                CREATE TRIGGER IF NOT EXISTS memories_au AFTER UPDATE ON memories BEGIN
                    INSERT INTO memories_fts(memories_fts, rowid, content, topic)
                    VALUES ('delete', old.id, old.content, old.topic);
                    INSERT INTO memories_fts(rowid, content, topic)
                    VALUES (new.id, new.content, new.topic);
                END;
                """
            )
        if c.execute("SELECT MAX(version) FROM schema_version").fetchone()[0] is None:
            c.execute("INSERT INTO schema_version (version, applied_at) VALUES (?, ?)",
                      (_SCHEMA_VERSION, time.time()))
        c.commit()
        log.debug("memory store ready at %s (fts=%s)", self._path, self._fts)

    # ── writes ─────────────────────────────────────────────────────────────────
    def insert(self, role: str, content: str, *, topic: str = "", kind: str = "conversation",
               importance: float = 0.5, tier: str = "episodic", session_id: str = "",
               metadata: Optional[dict] = None) -> int:
        c = self._conn()
        cur = c.execute(
            """INSERT INTO memories (ts, session_id, role, kind, content, topic, importance, tier, metadata)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (time.time(), session_id, role, kind, content, topic, importance, tier,
             json.dumps(metadata or {})),
        )
        c.commit()
        return int(cur.lastrowid)

    def mark_embedded(self, mem_id: int, embed_id: int) -> None:
        c = self._conn()
        c.execute("UPDATE memories SET embed_id=? WHERE id=?", (embed_id, mem_id))
        c.commit()

    def touch(self, mem_id: int) -> None:
        c = self._conn()
        c.execute("UPDATE memories SET access_count=access_count+1, last_access=? WHERE id=?",
                  (time.time(), mem_id))
        c.commit()

    def update_tier(self, mem_id: int, tier: str) -> None:
        if tier not in TIERS:
            raise ValueError(f"unknown tier {tier!r}")
        c = self._conn()
        c.execute("UPDATE memories SET tier=? WHERE id=?", (tier, mem_id))
        c.commit()

    def soft_delete(self, mem_id: int) -> None:
        c = self._conn()
        c.execute("UPDATE memories SET deleted=1 WHERE id=?", (mem_id,))
        c.commit()

    def hard_delete(self, mem_id: int) -> None:
        c = self._conn()
        c.execute("DELETE FROM memories WHERE id=?", (mem_id,))
        c.commit()

    def set_superseded(self, old_id: int, new_id: int) -> None:
        c = self._conn()
        c.execute("UPDATE memories SET superseded_by=?, deleted=1 WHERE id=?", (new_id, old_id))
        c.commit()

    # ── reads ──────────────────────────────────────────────────────────────────
    def get(self, mem_id: int) -> Optional[dict]:
        r = self._conn().execute("SELECT * FROM memories WHERE id=?", (mem_id,)).fetchone()
        return self._decode(r) if r else None

    def by_ids(self, ids: list[int], include_deleted: bool = False) -> list[dict]:
        if not ids:
            return []
        ph = ",".join("?" * len(ids))
        sql = f"SELECT * FROM memories WHERE id IN ({ph})"
        if not include_deleted:
            sql += " AND deleted=0"
        rows = self._conn().execute(sql, ids).fetchall()
        return [self._decode(r) for r in rows]

    def keyword_search(self, query: str, limit: int = 8, include_deleted: bool = False) -> list[dict]:
        c = self._conn()
        del_clause = "" if include_deleted else " AND m.deleted=0"
        if self._fts:
            tokens = _TOKEN.findall((query or "").lower())
            if not tokens:
                return []
            match = " OR ".join(f'"{t}"' for t in tokens)
            rows = c.execute(
                f"""SELECT m.* FROM memories m
                    WHERE m.id IN (SELECT rowid FROM memories_fts WHERE memories_fts MATCH ?)
                    {del_clause}
                    ORDER BY m.importance DESC, m.ts DESC LIMIT ?""",
                (match, limit),
            ).fetchall()
            return [self._decode(r) for r in rows]
        like = f"%{(query or '').lower()}%"
        rows = c.execute(
            f"""SELECT m.* FROM memories m
                WHERE (LOWER(m.content) LIKE ? OR LOWER(m.topic) LIKE ?){del_clause}
                ORDER BY m.importance DESC, m.ts DESC LIMIT ?""",
            (like, like, limit),
        ).fetchall()
        return [self._decode(r) for r in rows]

    def episodic_older_than(self, ts: float) -> list[dict]:
        # `<=` (inclusive): "at least this old". Avoids a coarse-clock boundary
        # miss on platforms (Windows) where time.time() granularity is ~15ms.
        rows = self._conn().execute(
            "SELECT * FROM memories WHERE tier='episodic' AND deleted=0 AND ts <= ? ORDER BY ts",
            (ts,),
        ).fetchall()
        return [self._decode(r) for r in rows]

    def iter_live(self) -> Iterator[tuple[int, str]]:
        for r in self._conn().execute("SELECT id, content FROM memories WHERE deleted=0"):
            yield int(r["id"]), r["content"]

    def counts(self) -> dict:
        c = self._conn()
        d = {t: 0 for t in TIERS}
        for tier, n in c.execute("SELECT tier, COUNT(*) FROM memories WHERE deleted=0 GROUP BY tier"):
            d[tier] = n
        d["deleted"] = c.execute("SELECT COUNT(*) FROM memories WHERE deleted=1").fetchone()[0]
        d["total"] = c.execute("SELECT COUNT(*) FROM memories").fetchone()[0]
        return d

    # ── import bookkeeping (migrations from legacy stores) ─────────────────────
    def import_done(self, name: str) -> bool:
        return self._conn().execute(
            "SELECT 1 FROM imports WHERE name=?", (name,)
        ).fetchone() is not None

    def mark_import(self, name: str) -> None:
        c = self._conn()
        c.execute("INSERT OR REPLACE INTO imports (name, applied_at) VALUES (?, ?)",
                  (name, time.time()))
        c.commit()

    # ── helpers ────────────────────────────────────────────────────────────────
    @staticmethod
    def _decode(r: sqlite3.Row) -> dict:
        d = dict(r)
        try:
            d["metadata"] = json.loads(d["metadata"])
        except (TypeError, ValueError):
            d["metadata"] = {}
        d["deleted"] = bool(d.get("deleted"))
        return d

    def close(self) -> None:
        c = getattr(self._local, "conn", None)
        if c is not None:
            c.close()
            self._local.conn = None
