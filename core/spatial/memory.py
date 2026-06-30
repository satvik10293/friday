"""
core/spatial/memory.py — FRIDAY V3 (M16)
Spatial Memory — the durable record of *what was where, and what moved*. It stores
meaningful spatial events (object, room, relationships, timestamp, confidence, session)
and per-object movement history, and forwards salient events to long-term memory /
Chronicle (via the injected MemoryService — never importing memory internals).

Redundancy is suppressed: identical events for the same object+room within a short
window are dropped, so a stationary object doesn't flood memory. SQLite-backed
(per-thread WAL), in-memory when no path is given. Side-effect-free to import.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
import time
from pathlib import Path
from typing import Optional

log = logging.getLogger("friday.spatial.memory")


class SpatialMemory:
    def __init__(self, *, path: Optional[str] = None, persistent: bool = False,
                 memory_service=None, significance_threshold: float = 0.7,
                 dedup_window_s: float = 2.0, max_movement_history: int = 200,
                 session: str = "") -> None:
        self._memory_service = memory_service
        self._threshold = significance_threshold
        self._dedup_window = dedup_window_s
        self._max_movement = max_movement_history
        self._session = session
        self._local = threading.local()
        self._recent: dict[str, float] = {}            # dedup key -> last ts
        self._writes = 0
        self._lock = threading.Lock()
        if persistent and path:
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            self._path, self._uri = str(path), False
        else:
            self._path = "file:spatialmem_%d?mode=memory&cache=shared" % id(self)
            self._uri = True
            self._keepalive = sqlite3.connect(self._path, uri=True, check_same_thread=False)
        self._init_schema()

    def _conn(self) -> sqlite3.Connection:
        c = getattr(self._local, "conn", None)
        if c is None:
            c = sqlite3.connect(self._path, uri=self._uri, check_same_thread=False)
            c.row_factory = sqlite3.Row
            c.execute("PRAGMA journal_mode=WAL")
            c.execute("PRAGMA busy_timeout=5000")
            self._local.conn = c
        return c

    def _init_schema(self) -> None:
        self._conn().executescript(
            """
            CREATE TABLE IF NOT EXISTS spatial_events (
                event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                kind TEXT NOT NULL, persistent_id TEXT, label TEXT, object_class TEXT,
                room TEXT, confidence REAL, ts REAL NOT NULL, session TEXT,
                data TEXT NOT NULL DEFAULT '{}'
            );
            CREATE TABLE IF NOT EXISTS movement_history (
                hist_id INTEGER PRIMARY KEY AUTOINCREMENT,
                persistent_id TEXT, label TEXT, room TEXT, x REAL, y REAL, ts REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_sev_ts ON spatial_events(ts);
            CREATE INDEX IF NOT EXISTS idx_sev_obj ON spatial_events(persistent_id, ts);
            CREATE INDEX IF NOT EXISTS idx_mov_obj ON movement_history(persistent_id, ts);
            """)
        self._conn().commit()

    # ── write ────────────────────────────────────────────────────────────────────
    def record_event(self, *, kind: str, persistent_id: str = "", label: str = "",
                     object_class: str = "", room: str = "", confidence: float = 1.0,
                     ts: Optional[float] = None, data: Optional[dict] = None,
                     significant: Optional[bool] = None) -> bool:
        """Store a spatial event unless it is a redundant repeat. Significant events are
        forwarded to long-term memory. Returns True if stored."""
        ts = ts if ts is not None else time.time()
        key = f"{kind}:{persistent_id}:{room}"
        with self._lock:
            last = self._recent.get(key)                # None on first sight (never a dup)
            if last is not None and kind in ("detected", "tracked") \
                    and ts - last < self._dedup_window:
                return False                            # redundant stationary repeat
            self._recent[key] = ts
        c = self._conn()
        c.execute("INSERT INTO spatial_events "
                  "(kind, persistent_id, label, object_class, room, confidence, ts, session, data) "
                  "VALUES (?,?,?,?,?,?,?,?,?)",
                  (kind, persistent_id, label, object_class, room, float(confidence), ts,
                   self._session, json.dumps(data or {})))
        c.commit()
        self._writes += 1
        meaningful = significant if significant is not None else (
            confidence >= self._threshold and kind != "tracked")
        if meaningful:
            self._forward(kind, label, room, ts)
        return True

    def record_movement(self, *, persistent_id: str, label: str, room: str,
                        center: tuple, ts: Optional[float] = None) -> None:
        ts = ts if ts is not None else time.time()
        c = self._conn()
        c.execute("INSERT INTO movement_history (persistent_id, label, room, x, y, ts) "
                  "VALUES (?,?,?,?,?,?)",
                  (persistent_id, label, room, float(center[0]), float(center[1]), ts))
        c.execute("DELETE FROM movement_history WHERE persistent_id=? AND hist_id NOT IN "
                  "(SELECT hist_id FROM movement_history WHERE persistent_id=? "
                  "ORDER BY ts DESC LIMIT ?)", (persistent_id, persistent_id, self._max_movement))
        c.commit()
        self._writes += 1

    def _forward(self, kind: str, label: str, room: str, ts: float) -> None:
        if self._memory_service is None:
            return
        verb = {"moved": "moved to", "lost": "went missing in", "returned": "reappeared in",
                "removed": "was removed from", "detected": "was seen in"}.get(kind, "changed in")
        try:
            self._memory_service.remember(f"{label or 'an object'} {verb} the {room}.",
                                          kind="spatial", metadata={"event": kind, "ts": ts})
        except Exception:  # noqa: BLE001
            log.debug("chronicle forward failed", exc_info=True)

    # ── read / retrieval ─────────────────────────────────────────────────────────
    def last_location(self, *, persistent_id: str = "", label: str = "") -> Optional[dict]:
        c = self._conn()
        if persistent_id:
            row = c.execute("SELECT * FROM spatial_events WHERE persistent_id=? "
                            "ORDER BY ts DESC LIMIT 1", (persistent_id,)).fetchone()
        else:
            row = c.execute("SELECT * FROM spatial_events WHERE label LIKE ? "
                            "ORDER BY ts DESC LIMIT 1", (f"%{label}%",)).fetchone()
        return self._row(row) if row else None

    def events_since(self, ts: float, *, limit: int = 200) -> list:
        rows = self._conn().execute(
            "SELECT * FROM spatial_events WHERE ts >= ? ORDER BY ts DESC LIMIT ?",
            (ts, limit)).fetchall()
        return [self._row(r) for r in rows]

    def moved_since(self, ts: float, *, limit: int = 200) -> list:
        rows = self._conn().execute(
            "SELECT * FROM spatial_events WHERE ts >= ? AND kind IN "
            "('moved','lost','returned','removed') ORDER BY ts DESC LIMIT ?",
            (ts, limit)).fetchall()
        return [self._row(r) for r in rows]

    def movement_history(self, persistent_id: str, *, limit: int = 100) -> list:
        rows = self._conn().execute(
            "SELECT * FROM movement_history WHERE persistent_id=? ORDER BY ts DESC LIMIT ?",
            (persistent_id, limit)).fetchall()
        return [dict(r) for r in rows]

    def counts(self) -> dict:
        c = self._conn()
        return {"events": c.execute("SELECT COUNT(*) FROM spatial_events").fetchone()[0],
                "movements": c.execute("SELECT COUNT(*) FROM movement_history").fetchone()[0]}

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

    @staticmethod
    def _row(r: sqlite3.Row) -> dict:
        d = dict(r)
        try:
            d["data"] = json.loads(d.get("data") or "{}")
        except (TypeError, ValueError):
            d["data"] = {}
        return d
