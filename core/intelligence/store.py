"""
core/intelligence/store.py — FRIDAY 4.0 (M12)
SQLite persistence for the Intelligence OS: reasoning traces (searchable),
registered-model snapshots, and benchmark history. Per-thread connections + WAL +
schema_version, like every other FRIDAY store. Local-only.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Optional

_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_PATH = _ROOT / "data" / "intelligence.db"
_SCHEMA_VERSION = 1


class IntelligenceStore:
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
            CREATE TABLE IF NOT EXISTS traces (
                id TEXT PRIMARY KEY, ts REAL NOT NULL, goal TEXT, task TEXT,
                models TEXT, agents TEXT, confidence REAL, outcome TEXT,
                execution_ms REAL, data TEXT NOT NULL DEFAULT '{}');
            CREATE TABLE IF NOT EXISTS model_snapshots (
                name TEXT PRIMARY KEY, info TEXT NOT NULL, updated_at REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS benchmarks (
                id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL,
                model TEXT NOT NULL, suite TEXT NOT NULL, score REAL NOT NULL,
                detail TEXT NOT NULL DEFAULT '{}');
            CREATE INDEX IF NOT EXISTS idx_traces_ts ON traces(ts);
            CREATE INDEX IF NOT EXISTS idx_traces_task ON traces(task);
            CREATE INDEX IF NOT EXISTS idx_bench_model ON benchmarks(model);
            """
        )
        if c.execute("SELECT MAX(version) FROM schema_version").fetchone()[0] is None:
            c.execute("INSERT INTO schema_version (version, applied_at) VALUES (?, ?)",
                      (_SCHEMA_VERSION, time.time()))
        c.commit()

    # ── traces ──────────────────────────────────────────────────────────────────
    def save_trace(self, trace: dict) -> None:
        c = self.conn()
        c.execute("""INSERT OR REPLACE INTO traces
                     (id, ts, goal, task, models, agents, confidence, outcome, execution_ms, data)
                     VALUES (?,?,?,?,?,?,?,?,?,?)""",
                  (trace["id"], trace.get("ts", time.time()), trace.get("goal", ""),
                   trace.get("task", ""), json.dumps(trace.get("models", [])),
                   json.dumps(trace.get("agents", [])), trace.get("confidence", 0.0),
                   trace.get("outcome", ""), trace.get("execution_ms", 0.0),
                   json.dumps(trace.get("data", {}))))
        c.commit()

    def get_trace(self, trace_id: str) -> Optional[dict]:
        r = self.conn().execute("SELECT * FROM traces WHERE id=?", (trace_id,)).fetchone()
        return self._trace_row(r) if r else None

    def search_traces(self, query: str = "", *, task: Optional[str] = None,
                      limit: int = 50) -> list[dict]:
        sql, params = "SELECT * FROM traces", []
        clauses = []
        if query:
            clauses.append("(goal LIKE ? OR outcome LIKE ?)")
            params += [f"%{query}%", f"%{query}%"]
        if task:
            clauses.append("task = ?")
            params.append(task)
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY ts DESC LIMIT ?"
        params.append(limit)
        return [self._trace_row(r) for r in self.conn().execute(sql, params).fetchall()]

    @staticmethod
    def _trace_row(r) -> dict:
        d = dict(r)
        for k in ("models", "agents", "data"):
            try:
                d[k] = json.loads(d[k])
            except (TypeError, ValueError):
                d[k] = [] if k != "data" else {}
        return d

    # ── model snapshots ─────────────────────────────────────────────────────────
    def save_model(self, name: str, info: dict) -> None:
        c = self.conn()
        c.execute("""INSERT OR REPLACE INTO model_snapshots (name, info, updated_at)
                     VALUES (?, ?, ?)""", (name, json.dumps(info), time.time()))
        c.commit()

    def all_models(self) -> list[dict]:
        rows = self.conn().execute("SELECT info FROM model_snapshots").fetchall()
        out = []
        for r in rows:
            try:
                out.append(json.loads(r["info"]))
            except (TypeError, ValueError):
                pass
        return out

    # ── benchmarks ──────────────────────────────────────────────────────────────
    def save_benchmark(self, model: str, suite: str, score: float, detail: dict) -> None:
        c = self.conn()
        c.execute("INSERT INTO benchmarks (ts, model, suite, score, detail) VALUES (?,?,?,?,?)",
                  (time.time(), model, suite, score, json.dumps(detail)))
        c.commit()

    def benchmarks(self, model: Optional[str] = None) -> list[dict]:
        if model:
            rows = self.conn().execute(
                "SELECT * FROM benchmarks WHERE model=? ORDER BY ts DESC", (model,)).fetchall()
        else:
            rows = self.conn().execute("SELECT * FROM benchmarks ORDER BY ts DESC").fetchall()
        return [dict(r) for r in rows]

    def counts(self) -> dict:
        c = self.conn()
        return {"traces": c.execute("SELECT COUNT(*) FROM traces").fetchone()[0],
                "models": c.execute("SELECT COUNT(*) FROM model_snapshots").fetchone()[0],
                "benchmarks": c.execute("SELECT COUNT(*) FROM benchmarks").fetchone()[0]}

    def close(self) -> None:
        c = getattr(self._local, "c", None)
        if c is not None:
            c.close()
            self._local.c = None
