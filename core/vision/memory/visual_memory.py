"""
core/vision/memory/visual_memory.py — FRIDAY 6.1 (M14)
Visual Memory: durable storage of what FRIDAY has *seen*. It records significant
observations, discrete visual events (object appeared/disappeared, motion started,
scene changed), per-object sighting histories, and scene changes — with retrieval
metadata for later recall. SQLite-backed (per-thread connections + WAL, the same
discipline as the World Model / Memory Service); in-memory when no path is given.

Visual Memory stores evidence; it does not reason. It is written by the Cognitive
Bridge and read by Mission Control / future retrieval. Side-effect-free to import.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
import time
from pathlib import Path
from typing import Optional

log = logging.getLogger("friday.vision.memory")

_SCHEMA_VERSION = 1


class VisualMemory:
    def __init__(self, path: Optional[str] = None, *, persistent: bool = True,
                 significance_threshold: float = 0.55, max_object_history: int = 200) -> None:
        self._threshold = significance_threshold
        self._max_history = max_object_history
        self._local = threading.local()
        self._writes = 0
        if persistent and path:
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            self._path = str(path)
        else:
            # a private in-memory database, shared across this object's connections
            self._path = "file:vismem_%d?mode=memory&cache=shared" % id(self)
            self._uri = True
            self._keepalive = sqlite3.connect(self._path, uri=True, check_same_thread=False)
        self._uri = getattr(self, "_uri", False)
        self._init_schema()

    # ── connection (one per thread) ──────────────────────────────────────────────
    def _conn(self) -> sqlite3.Connection:
        c = getattr(self._local, "conn", None)
        if c is None:
            c = sqlite3.connect(self._path, uri=self._uri, check_same_thread=False)
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
            CREATE TABLE IF NOT EXISTS observations (
                obs_id      TEXT PRIMARY KEY,
                camera_id   TEXT,
                subject     TEXT,
                ts          REAL NOT NULL,
                significance REAL NOT NULL DEFAULT 0,
                confidence  REAL NOT NULL DEFAULT 0,
                summary     TEXT,
                payload     TEXT NOT NULL DEFAULT '{}'
            );
            CREATE TABLE IF NOT EXISTS events (
                event_id    INTEGER PRIMARY KEY AUTOINCREMENT,
                camera_id   TEXT,
                kind        TEXT NOT NULL,
                ts          REAL NOT NULL,
                subject     TEXT,
                data        TEXT NOT NULL DEFAULT '{}'
            );
            CREATE TABLE IF NOT EXISTS object_history (
                hist_id     INTEGER PRIMARY KEY AUTOINCREMENT,
                stable_id   TEXT,
                track_id    TEXT,
                camera_id   TEXT,
                label       TEXT,
                ts          REAL NOT NULL,
                center_x    REAL, center_y REAL,
                data        TEXT NOT NULL DEFAULT '{}'
            );
            CREATE TABLE IF NOT EXISTS scene_changes (
                change_id   INTEGER PRIMARY KEY AUTOINCREMENT,
                camera_id   TEXT,
                ts          REAL NOT NULL,
                magnitude   REAL,
                data        TEXT NOT NULL DEFAULT '{}'
            );
            CREATE INDEX IF NOT EXISTS idx_obs_cam ON observations(camera_id, ts);
            CREATE INDEX IF NOT EXISTS idx_events_cam ON events(camera_id, ts);
            CREATE INDEX IF NOT EXISTS idx_hist_obj ON object_history(stable_id, ts);
            """
        )
        c.commit()

    # ── writes ───────────────────────────────────────────────────────────────────
    def remember_observation(self, observation, significance: float) -> bool:
        """Store an observation iff it clears the significance threshold. Returns True
        if stored. Accepts a core.perception Observation."""
        if significance < self._threshold:
            return False
        payload = observation.to_dict()
        summary = payload.get("payload", {}).get("name") or observation.subject()
        c = self._conn()
        c.execute(
            "INSERT OR REPLACE INTO observations "
            "(obs_id, camera_id, subject, ts, significance, confidence, summary, payload) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (observation.id, observation.metadata.get("camera_id", ""),
             observation.subject(), observation.timestamp, float(significance),
             float(observation.confidence), str(summary), json.dumps(payload)))
        c.commit()
        self._writes += 1
        return True

    def record_event(self, camera_id: str, kind: str, *, subject: str = "",
                     data: Optional[dict] = None, ts: Optional[float] = None) -> None:
        c = self._conn()
        c.execute("INSERT INTO events (camera_id, kind, ts, subject, data) VALUES (?, ?, ?, ?, ?)",
                  (camera_id, kind, ts if ts is not None else time.time(), subject,
                   json.dumps(data or {})))
        c.commit()
        self._writes += 1

    def record_sighting(self, *, stable_id: Optional[str], track_id: Optional[str],
                        camera_id: str, label: str, center: tuple,
                        ts: Optional[float] = None, data: Optional[dict] = None) -> None:
        c = self._conn()
        c.execute(
            "INSERT INTO object_history (stable_id, track_id, camera_id, label, ts, "
            "center_x, center_y, data) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (stable_id, track_id, camera_id, label, ts if ts is not None else time.time(),
             float(center[0]), float(center[1]), json.dumps(data or {})))
        # trim history per object
        if stable_id:
            c.execute(
                "DELETE FROM object_history WHERE stable_id=? AND hist_id NOT IN "
                "(SELECT hist_id FROM object_history WHERE stable_id=? ORDER BY ts DESC LIMIT ?)",
                (stable_id, stable_id, self._max_history))
        c.commit()
        self._writes += 1

    def record_scene_change(self, camera_id: str, magnitude: float,
                            data: Optional[dict] = None, ts: Optional[float] = None) -> None:
        c = self._conn()
        c.execute("INSERT INTO scene_changes (camera_id, ts, magnitude, data) VALUES (?, ?, ?, ?)",
                  (camera_id, ts if ts is not None else time.time(), float(magnitude),
                   json.dumps(data or {})))
        c.commit()
        self._writes += 1

    # ── reads / retrieval ────────────────────────────────────────────────────────
    def recent_observations(self, limit: int = 50, camera_id: Optional[str] = None) -> list:
        q = "SELECT * FROM observations"
        args: list = []
        if camera_id:
            q += " WHERE camera_id=?"
            args.append(camera_id)
        q += " ORDER BY ts DESC LIMIT ?"
        args.append(limit)
        return [self._obs_row(r) for r in self._conn().execute(q, args).fetchall()]

    def recent_events(self, limit: int = 50, camera_id: Optional[str] = None) -> list:
        q = "SELECT * FROM events"
        args: list = []
        if camera_id:
            q += " WHERE camera_id=?"
            args.append(camera_id)
        q += " ORDER BY ts DESC LIMIT ?"
        args.append(limit)
        return [dict(r) for r in self._conn().execute(q, args).fetchall()]

    def object_history(self, stable_id: str, limit: int = 100) -> list:
        rows = self._conn().execute(
            "SELECT * FROM object_history WHERE stable_id=? ORDER BY ts DESC LIMIT ?",
            (stable_id, limit)).fetchall()
        return [dict(r) for r in rows]

    def scene_changes(self, camera_id: Optional[str] = None, limit: int = 50) -> list:
        q = "SELECT * FROM scene_changes"
        args: list = []
        if camera_id:
            q += " WHERE camera_id=?"
            args.append(camera_id)
        q += " ORDER BY ts DESC LIMIT ?"
        args.append(limit)
        return [dict(r) for r in self._conn().execute(q, args).fetchall()]

    # ── diagnostics ──────────────────────────────────────────────────────────────
    def counts(self) -> dict:
        c = self._conn()
        return {t: c.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                for t in ("observations", "events", "object_history", "scene_changes")}

    def metrics(self) -> dict:
        return {"writes": self._writes, **self.counts()}

    def health(self) -> dict:
        return {"status": "ok", **self.counts()}

    def close(self) -> None:
        conn = getattr(self._local, "conn", None)
        if conn is not None:
            conn.close()
            self._local.conn = None
        ka = getattr(self, "_keepalive", None)
        if ka is not None:
            ka.close()

    # ── helpers ──────────────────────────────────────────────────────────────────
    @staticmethod
    def _obs_row(r: sqlite3.Row) -> dict:
        d = dict(r)
        try:
            d["payload"] = json.loads(d.get("payload") or "{}")
        except (TypeError, ValueError):
            d["payload"] = {}
        return d
