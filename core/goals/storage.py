"""
core/goals/storage.py — FRIDAY 4.0
GoalStore: SQLite persistence for goals + their event history. Mirrors the M2
store discipline — per-thread connections, WAL, migration-gated schema — so goals
survive restart and concurrent access safely.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
import time
from pathlib import Path
from typing import Optional

from .models import Goal, GoalStatus

log = logging.getLogger("friday.goals.storage")

_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_PATH = _ROOT / "data" / "goals.db"
_SCHEMA_VERSION = 1


class GoalStore:
    def __init__(self, path: Optional[str | Path] = None) -> None:
        self._path = str(Path(path) if path else _DEFAULT_PATH)
        Path(self._path).parent.mkdir(parents=True, exist_ok=True)
        self._local = threading.local()
        self._init_schema()

    # ── connection (one per thread) ───────────────────────────────────────────
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
            CREATE TABLE IF NOT EXISTS goals (
                goal_id            TEXT PRIMARY KEY,
                title              TEXT NOT NULL,
                description        TEXT NOT NULL DEFAULT '',
                status             TEXT NOT NULL DEFAULT 'pending',
                priority           INTEGER NOT NULL DEFAULT 3,
                created_at         REAL NOT NULL,
                updated_at         REAL NOT NULL,
                parent_goal        TEXT,
                dependencies       TEXT NOT NULL DEFAULT '[]',
                owner              TEXT NOT NULL DEFAULT 'satvik',
                confidence         REAL NOT NULL DEFAULT 0.5,
                completion_percent REAL NOT NULL DEFAULT 0.0,
                metadata           TEXT NOT NULL DEFAULT '{}'
            );
            CREATE TABLE IF NOT EXISTS goal_events (
                id      INTEGER PRIMARY KEY AUTOINCREMENT,
                goal_id TEXT NOT NULL,
                ts      REAL NOT NULL,
                kind    TEXT NOT NULL,
                detail  TEXT,
                data    TEXT NOT NULL DEFAULT '{}'
            );
            CREATE INDEX IF NOT EXISTS idx_goals_status ON goals(status);
            CREATE INDEX IF NOT EXISTS idx_goals_parent ON goals(parent_goal);
            CREATE INDEX IF NOT EXISTS idx_goals_owner  ON goals(owner);
            CREATE INDEX IF NOT EXISTS idx_gevents_goal ON goal_events(goal_id);
            """
        )
        if c.execute("SELECT MAX(version) FROM schema_version").fetchone()[0] is None:
            c.execute("INSERT INTO schema_version (version, applied_at) VALUES (?, ?)",
                      (_SCHEMA_VERSION, time.time()))
        c.commit()
        log.debug("goal store ready at %s", self._path)

    # ── CRUD ───────────────────────────────────────────────────────────────────
    def create_goal(self, goal: Goal) -> str:
        c = self._conn()
        c.execute(
            """INSERT INTO goals
               (goal_id, title, description, status, priority, created_at, updated_at,
                parent_goal, dependencies, owner, confidence, completion_percent, metadata)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            goal.to_row(),
        )
        c.commit()
        return goal.goal_id

    def update_goal(self, goal: Goal) -> None:
        goal.updated_at = time.time()
        c = self._conn()
        c.execute(
            """UPDATE goals SET title=?, description=?, status=?, priority=?, updated_at=?,
               parent_goal=?, dependencies=?, owner=?, confidence=?, completion_percent=?,
               metadata=? WHERE goal_id=?""",
            (goal.title, goal.description, goal.status.value, goal.priority, goal.updated_at,
             goal.parent_goal, json.dumps(goal.dependencies), goal.owner, goal.confidence,
             goal.completion_percent, json.dumps(goal.metadata), goal.goal_id),
        )
        c.commit()

    def delete_goal(self, goal_id: str) -> None:
        c = self._conn()
        c.execute("DELETE FROM goals WHERE goal_id=?", (goal_id,))
        c.execute("DELETE FROM goal_events WHERE goal_id=?", (goal_id,))
        c.commit()

    def archive_goal(self, goal_id: str) -> None:
        c = self._conn()
        c.execute("UPDATE goals SET status=?, updated_at=? WHERE goal_id=?",
                  (GoalStatus.ARCHIVED.value, time.time(), goal_id))
        c.commit()

    def get_goal(self, goal_id: str) -> Optional[Goal]:
        r = self._conn().execute("SELECT * FROM goals WHERE goal_id=?", (goal_id,)).fetchone()
        return Goal.from_row(r) if r else None

    def list_goals(self, status: Optional[GoalStatus] = None, owner: Optional[str] = None,
                   parent: Optional[str] = None) -> list[Goal]:
        clauses, params = [], []
        if status is not None:
            clauses.append("status=?")
            params.append(status.value if isinstance(status, GoalStatus) else status)
        if owner is not None:
            clauses.append("owner=?")
            params.append(owner)
        if parent is not None:
            clauses.append("parent_goal=?")
            params.append(parent)
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        rows = self._conn().execute(
            f"SELECT * FROM goals{where} ORDER BY priority ASC, created_at ASC", params
        ).fetchall()
        return [Goal.from_row(r) for r in rows]

    def search_goals(self, query: str, limit: int = 20) -> list[Goal]:
        like = f"%{(query or '').lower()}%"
        rows = self._conn().execute(
            """SELECT * FROM goals
               WHERE LOWER(title) LIKE ? OR LOWER(description) LIKE ?
               ORDER BY priority ASC, created_at ASC LIMIT ?""",
            (like, like, limit),
        ).fetchall()
        return [Goal.from_row(r) for r in rows]

    def counts_by_status(self) -> dict:
        d = {s.value: 0 for s in GoalStatus}
        for status, n in self._conn().execute(
            "SELECT status, COUNT(*) FROM goals GROUP BY status"
        ):
            d[status] = n
        d["total"] = sum(v for k, v in d.items() if k != "total")
        return d

    # ── event history ──────────────────────────────────────────────────────────
    def add_event(self, goal_id: str, kind: str, detail: str = "",
                  data: Optional[dict] = None) -> None:
        c = self._conn()
        c.execute(
            "INSERT INTO goal_events (goal_id, ts, kind, detail, data) VALUES (?, ?, ?, ?, ?)",
            (goal_id, time.time(), kind, detail, json.dumps(data or {})),
        )
        c.commit()

    def get_events(self, goal_id: str) -> list[dict]:
        rows = self._conn().execute(
            "SELECT * FROM goal_events WHERE goal_id=? ORDER BY ts", (goal_id,)
        ).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            try:
                d["data"] = json.loads(d["data"])
            except (TypeError, ValueError):
                d["data"] = {}
            out.append(d)
        return out

    # ── import / export ────────────────────────────────────────────────────────
    def export_all(self) -> list[dict]:
        return [g.to_dict() for g in self.list_goals()]

    def import_all(self, goals: list[Goal]) -> int:
        n = 0
        for g in goals:
            if self.get_goal(g.goal_id) is None:
                self.create_goal(g)
                n += 1
        return n

    def close(self) -> None:
        c = getattr(self._local, "conn", None)
        if c is not None:
            c.close()
            self._local.conn = None
