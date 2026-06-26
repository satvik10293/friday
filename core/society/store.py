"""
core/society/store.py — FRIDAY 4.0 (M11)
SQLite persistence for the agent society: the agent roster, lifecycle events, task
history, and worker reputation. Same store discipline as the rest of FRIDAY
(per-thread conns, WAL, schema_version). Local-only.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Optional

_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_PATH = _ROOT / "data" / "society.db"
_SCHEMA_VERSION = 1


class SocietyStore:
    def __init__(self, path: Optional[str | Path] = None) -> None:
        self._path = str(Path(path) if path else _DEFAULT_PATH)
        Path(self._path).parent.mkdir(parents=True, exist_ok=True)
        self._local = threading.local()
        self._init_schema()

    def conn(self) -> sqlite3.Connection:
        c = getattr(self._local, "c", None)
        if c is None:
            c = sqlite3.connect(self._path, check_same_thread=False)
            c.row_factory = sqlite3.Row
            c.execute("PRAGMA journal_mode=WAL")
            c.execute("PRAGMA busy_timeout=5000")
            self._local.c = c
        return c

    def _init_schema(self) -> None:
        c = self.conn()
        c.executescript(
            """
            CREATE TABLE IF NOT EXISTS schema_version (
                version INTEGER PRIMARY KEY, applied_at REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS agents (
                id TEXT PRIMARY KEY, kind TEXT NOT NULL, role TEXT NOT NULL,
                name TEXT NOT NULL, status TEXT NOT NULL, created_at REAL NOT NULL,
                destroyed_at REAL);
            CREATE TABLE IF NOT EXISTS lifecycle (
                id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL,
                agent_id TEXT NOT NULL, event TEXT NOT NULL, data TEXT NOT NULL DEFAULT '{}');
            CREATE TABLE IF NOT EXISTS tasks (
                id TEXT PRIMARY KEY, description TEXT, domain TEXT, leader TEXT,
                ok INTEGER, workers INTEGER, duration_ms REAL, ts REAL NOT NULL,
                result TEXT NOT NULL DEFAULT '{}');
            CREATE TABLE IF NOT EXISTS reputation (
                template TEXT PRIMARY KEY, samples INTEGER NOT NULL DEFAULT 0,
                accuracy REAL NOT NULL DEFAULT 0, reliability REAL NOT NULL DEFAULT 0,
                speed REAL NOT NULL DEFAULT 0, efficiency REAL NOT NULL DEFAULT 0,
                success_rate REAL NOT NULL DEFAULT 0, score REAL NOT NULL DEFAULT 0,
                updated_at REAL NOT NULL DEFAULT 0);
            CREATE INDEX IF NOT EXISTS idx_life_agent ON lifecycle(agent_id);
            """
        )
        if c.execute("SELECT MAX(version) FROM schema_version").fetchone()[0] is None:
            c.execute("INSERT INTO schema_version (version, applied_at) VALUES (?, ?)",
                      (_SCHEMA_VERSION, time.time()))
        c.commit()

    # ── agents / lifecycle ──────────────────────────────────────────────────────
    def save_agent(self, rec) -> None:
        c = self.conn()
        c.execute("""INSERT INTO agents (id, kind, role, name, status, created_at, destroyed_at)
                     VALUES (?, ?, ?, ?, ?, ?, ?)
                     ON CONFLICT(id) DO UPDATE SET status=excluded.status,
                       destroyed_at=excluded.destroyed_at""",
                  (rec.id, rec.kind, rec.role, rec.name, rec.status, rec.created_at,
                   rec.destroyed_at))
        c.commit()

    def add_lifecycle(self, agent_id: str, event: str, data: Optional[dict] = None) -> None:
        c = self.conn()
        c.execute("INSERT INTO lifecycle (ts, agent_id, event, data) VALUES (?, ?, ?, ?)",
                  (time.time(), agent_id, event, json.dumps(data or {})))
        c.commit()

    def lifecycle(self, limit: int = 200) -> list[dict]:
        rows = self.conn().execute(
            "SELECT * FROM lifecycle ORDER BY ts DESC LIMIT ?", (limit,)).fetchall()
        return [dict(r) for r in rows]

    def active_agents(self) -> list[dict]:
        rows = self.conn().execute(
            "SELECT * FROM agents WHERE status != 'destroyed' ORDER BY created_at").fetchall()
        return [dict(r) for r in rows]

    # ── tasks ───────────────────────────────────────────────────────────────────
    def save_task(self, result) -> None:
        c = self.conn()
        c.execute("""INSERT OR REPLACE INTO tasks
                     (id, description, domain, leader, ok, workers, duration_ms, ts, result)
                     VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                  (result.task_id, "", "", result.leader, int(result.ok),
                   result.workers_spawned, result.duration_ms, time.time(),
                   json.dumps(result.to_dict())))
        c.commit()

    # ── reputation ──────────────────────────────────────────────────────────────
    def get_reputation(self, template: str) -> Optional[dict]:
        r = self.conn().execute("SELECT * FROM reputation WHERE template=?", (template,)).fetchone()
        return dict(r) if r else None

    def save_reputation(self, rep: dict) -> None:
        c = self.conn()
        c.execute("""INSERT INTO reputation
                     (template, samples, accuracy, reliability, speed, efficiency,
                      success_rate, score, updated_at)
                     VALUES (:template, :samples, :accuracy, :reliability, :speed,
                             :efficiency, :success_rate, :score, :updated_at)
                     ON CONFLICT(template) DO UPDATE SET samples=:samples,
                       accuracy=:accuracy, reliability=:reliability, speed=:speed,
                       efficiency=:efficiency, success_rate=:success_rate,
                       score=:score, updated_at=:updated_at""", rep)
        c.commit()

    def all_reputation(self) -> list[dict]:
        rows = self.conn().execute(
            "SELECT * FROM reputation ORDER BY score DESC").fetchall()
        return [dict(r) for r in rows]

    def counts(self) -> dict:
        c = self.conn()
        return {
            "agents_ever": c.execute("SELECT COUNT(*) FROM agents").fetchone()[0],
            "active": c.execute("SELECT COUNT(*) FROM agents WHERE status!='destroyed'").fetchone()[0],
            "tasks": c.execute("SELECT COUNT(*) FROM tasks").fetchone()[0],
            "templates_rated": c.execute("SELECT COUNT(*) FROM reputation").fetchone()[0],
        }

    def close(self) -> None:
        c = getattr(self._local, "c", None)
        if c is not None:
            c.close()
            self._local.c = None
