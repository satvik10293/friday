"""
core/perception/store.py — FRIDAY 4.0 (M6)
PerceptionStore: SQLite persistence for observations, their change history, and
sensor health/metrics. Same store discipline as M2/M4/M5 — per-thread connections,
WAL, migration-gated schema — so perception survives restart.

Tables: observations, observation_history, sensor_health, sensor_metrics,
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

from .models import Observation, ObservationType

log = logging.getLogger("friday.perception.store")

_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_PATH = _ROOT / "data" / "perception.db"
_SCHEMA_VERSION = 1


class PerceptionStore:
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
            CREATE TABLE IF NOT EXISTS observations (
                id          TEXT PRIMARY KEY,
                ts          REAL NOT NULL,
                subject     TEXT NOT NULL,
                source      TEXT NOT NULL,
                type        TEXT NOT NULL,
                confidence  REAL NOT NULL DEFAULT 0.5,
                significance REAL NOT NULL DEFAULT 0.0,
                status      TEXT NOT NULL DEFAULT 'received',
                count       INTEGER NOT NULL DEFAULT 1,
                last_seen   REAL NOT NULL,
                payload     TEXT NOT NULL DEFAULT '{}',
                metadata    TEXT NOT NULL DEFAULT '{}'
            );
            CREATE TABLE IF NOT EXISTS observation_history (
                id      INTEGER PRIMARY KEY AUTOINCREMENT,
                subject TEXT NOT NULL,
                ts      REAL NOT NULL,
                kind    TEXT NOT NULL,
                data    TEXT NOT NULL DEFAULT '{}'
            );
            CREATE TABLE IF NOT EXISTS sensor_health (
                id      INTEGER PRIMARY KEY AUTOINCREMENT,
                sensor  TEXT NOT NULL,
                ts      REAL NOT NULL,
                healthy INTEGER NOT NULL DEFAULT 1,
                detail  TEXT
            );
            CREATE TABLE IF NOT EXISTS sensor_metrics (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                sensor      TEXT NOT NULL,
                ts          REAL NOT NULL,
                polls       INTEGER NOT NULL DEFAULT 0,
                observations INTEGER NOT NULL DEFAULT 0,
                errors      INTEGER NOT NULL DEFAULT 0
            );
            CREATE INDEX IF NOT EXISTS idx_obs_subject ON observations(subject);
            CREATE INDEX IF NOT EXISTS idx_obs_type ON observations(type);
            CREATE INDEX IF NOT EXISTS idx_hist_subject ON observation_history(subject);
            """
        )
        if c.execute("SELECT MAX(version) FROM schema_version").fetchone()[0] is None:
            c.execute("INSERT INTO schema_version (version, applied_at) VALUES (?, ?)",
                      (_SCHEMA_VERSION, time.time()))
        c.commit()

    # ── observations ───────────────────────────────────────────────────────────
    def upsert_observation(self, obs: Observation, *, significance: float,
                           status: str, count: int, last_seen: float) -> None:
        c = self._conn()
        c.execute(
            """INSERT INTO observations
               (id, ts, subject, source, type, confidence, significance, status, count,
                last_seen, payload, metadata)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(id) DO UPDATE SET
                 ts=excluded.ts, confidence=excluded.confidence,
                 significance=excluded.significance, status=excluded.status,
                 count=excluded.count, last_seen=excluded.last_seen,
                 payload=excluded.payload, metadata=excluded.metadata""",
            (obs.id, obs.timestamp, obs.subject(), obs.source.name, obs.type.value,
             obs.confidence, significance, status, count, last_seen,
             json.dumps(obs.payload), json.dumps(obs.metadata)),
        )
        c.commit()

    def set_status(self, obs_id: str, status: str) -> None:
        c = self._conn()
        c.execute("UPDATE observations SET status=? WHERE id=?", (status, obs_id))
        c.commit()

    def get_observation(self, obs_id: str) -> Optional[dict]:
        r = self._conn().execute("SELECT * FROM observations WHERE id=?", (obs_id,)).fetchone()
        return self._decode(r) if r else None

    def recent(self, limit: int = 50, status: Optional[str] = None) -> list[dict]:
        if status:
            rows = self._conn().execute(
                "SELECT * FROM observations WHERE status=? ORDER BY ts DESC LIMIT ?",
                (status, limit)).fetchall()
        else:
            rows = self._conn().execute(
                "SELECT * FROM observations ORDER BY ts DESC LIMIT ?", (limit,)).fetchall()
        return [self._decode(r) for r in rows]

    def by_type(self, t: ObservationType, limit: int = 50) -> list[dict]:
        rows = self._conn().execute(
            "SELECT * FROM observations WHERE type=? ORDER BY ts DESC LIMIT ?",
            (t.value, limit)).fetchall()
        return [self._decode(r) for r in rows]

    def latest_for_subject(self, subject: str) -> Optional[dict]:
        r = self._conn().execute(
            "SELECT * FROM observations WHERE subject=? ORDER BY ts DESC LIMIT 1",
            (subject,)).fetchone()
        return self._decode(r) if r else None

    def counts(self) -> dict:
        c = self._conn()
        total = c.execute("SELECT COUNT(*) FROM observations").fetchone()[0]
        by_status = {k: n for k, n in c.execute(
            "SELECT status, COUNT(*) FROM observations GROUP BY status")}
        by_type = {k: n for k, n in c.execute(
            "SELECT type, COUNT(*) FROM observations GROUP BY type")}
        return {"total": total, "by_status": by_status, "by_type": by_type}

    # ── history ────────────────────────────────────────────────────────────────
    def add_history(self, subject: str, kind: str, data: Optional[dict] = None) -> None:
        c = self._conn()
        c.execute(
            "INSERT INTO observation_history (subject, ts, kind, data) VALUES (?, ?, ?, ?)",
            (subject, time.time(), kind, json.dumps(data or {})))
        c.commit()

    def history(self, subject: str, limit: int = 50) -> list[dict]:
        rows = self._conn().execute(
            "SELECT * FROM observation_history WHERE subject=? ORDER BY ts DESC LIMIT ?",
            (subject, limit)).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            try:
                d["data"] = json.loads(d["data"])
            except (TypeError, ValueError):
                d["data"] = {}
            out.append(d)
        return out

    # ── sensor health / metrics ────────────────────────────────────────────────
    def record_sensor_health(self, sensor: str, healthy: bool, detail: str = "") -> None:
        c = self._conn()
        c.execute("INSERT INTO sensor_health (sensor, ts, healthy, detail) VALUES (?, ?, ?, ?)",
                  (sensor, time.time(), 1 if healthy else 0, detail))
        c.commit()

    def record_sensor_metrics(self, sensor: str, polls: int, observations: int,
                              errors: int) -> None:
        c = self._conn()
        c.execute(
            "INSERT INTO sensor_metrics (sensor, ts, polls, observations, errors) "
            "VALUES (?, ?, ?, ?, ?)", (sensor, time.time(), polls, observations, errors))
        c.commit()

    def sensor_health_log(self, sensor: str, limit: int = 10) -> list[dict]:
        rows = self._conn().execute(
            "SELECT * FROM sensor_health WHERE sensor=? ORDER BY ts DESC LIMIT ?",
            (sensor, limit)).fetchall()
        return [dict(r) for r in rows]

    def close(self) -> None:
        conn = getattr(self._local, "conn", None)
        if conn is not None:
            conn.close()
            self._local.conn = None

    # ── helpers ────────────────────────────────────────────────────────────────
    @staticmethod
    def _decode(r: sqlite3.Row) -> dict:
        d = dict(r)
        for f in ("payload", "metadata"):
            try:
                d[f] = json.loads(d[f])
            except (TypeError, ValueError):
                d[f] = {}
        return d
