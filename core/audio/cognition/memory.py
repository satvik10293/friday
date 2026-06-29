"""
core/audio/cognition/memory.py — FRIDAY V3 (M15)
Auditory Memory. Durable record of *meaningful* audio events — each with a timestamp,
event type, confidence, optional source, and session id. Only events at/above a
significance threshold are persisted, so routine background sound never floods memory.

SQLite-backed (per-thread WAL connections, the World-Model/Visual-Memory discipline),
in-memory when no path is given. It can also forward significant events to FRIDAY's
long-term memory/Chronicle via an injected, duck-typed sink (best-effort, guarded).
Stores evidence; performs no reasoning. Side-effect-free to import.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
from pathlib import Path
from typing import Optional

from .events import AuditoryEvent

log = logging.getLogger("friday.audio.memory")


class AuditoryMemory:
    def __init__(self, path: Optional[str] = None, *, persistent: bool = True,
                 significance_threshold: float = 0.6, chronicle=None) -> None:
        self._threshold = significance_threshold
        self._chronicle = chronicle          # optional long-term memory sink (duck-typed)
        self._local = threading.local()
        self._writes = 0
        if persistent and path:
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            self._path = str(path)
            self._uri = False
        else:
            self._path = "file:audmem_%d?mode=memory&cache=shared" % id(self)
            self._uri = True
            self._keepalive = sqlite3.connect(self._path, uri=True, check_same_thread=False)
        self._init_schema()

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
        self._conn().executescript(
            """
            CREATE TABLE IF NOT EXISTS audio_events (
                event_id    TEXT PRIMARY KEY,
                sound       TEXT NOT NULL,
                category    TEXT,
                confidence  REAL NOT NULL,
                ts          REAL NOT NULL,
                source      TEXT,
                session_id  TEXT,
                features    TEXT NOT NULL DEFAULT '{}'
            );
            CREATE INDEX IF NOT EXISTS idx_audio_ts ON audio_events(ts);
            CREATE INDEX IF NOT EXISTS idx_audio_sound ON audio_events(sound, ts);
            CREATE INDEX IF NOT EXISTS idx_audio_session ON audio_events(session_id, ts);
            """)
        self._conn().commit()

    # ── write (meaningful only) ──────────────────────────────────────────────────
    def remember(self, event: AuditoryEvent, *, significance: Optional[float] = None) -> bool:
        """Persist an event iff it clears the significance threshold. Returns True if
        stored. `significance` defaults to the event confidence."""
        score = event.confidence if significance is None else significance
        if score < self._threshold:
            return False
        c = self._conn()
        c.execute(
            "INSERT OR REPLACE INTO audio_events "
            "(event_id, sound, category, confidence, ts, source, session_id, features) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (event.event_id, event.sound, event.category, float(event.confidence),
             event.timestamp, event.source, event.session_id, json.dumps(event.features)))
        c.commit()
        self._writes += 1
        self._forward_to_chronicle(event)
        return True

    def _forward_to_chronicle(self, event: AuditoryEvent) -> None:
        if self._chronicle is None:
            return
        text = f"Heard {event.sound.replace('_', ' ')} ({round(event.confidence * 100)}%)."
        for method in ("remember", "record", "add", "log_event"):
            fn = getattr(self._chronicle, method, None)
            if callable(fn):
                try:
                    fn(text)                 # best-effort; chronicle APIs vary
                    return
                except Exception:  # noqa: BLE001
                    log.debug("chronicle forward via %s failed", method, exc_info=True)
                    return

    # ── read / retrieval ─────────────────────────────────────────────────────────
    def recent(self, limit: int = 50, *, sound: Optional[str] = None,
               session_id: Optional[str] = None) -> list:
        q = "SELECT * FROM audio_events"
        clauses, args = [], []
        if sound:
            clauses.append("sound=?"); args.append(sound)
        if session_id:
            clauses.append("session_id=?"); args.append(session_id)
        if clauses:
            q += " WHERE " + " AND ".join(clauses)
        q += " ORDER BY ts DESC LIMIT ?"
        args.append(limit)
        return [self._row(r) for r in self._conn().execute(q, args).fetchall()]

    def history(self, sound: str, limit: int = 100) -> list:
        return self.recent(limit, sound=sound)

    def counts(self) -> dict:
        c = self._conn()
        total = c.execute("SELECT COUNT(*) FROM audio_events").fetchone()[0]
        by_sound = {s: n for s, n in c.execute(
            "SELECT sound, COUNT(*) FROM audio_events GROUP BY sound")}
        return {"events": total, "by_sound": by_sound}

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
            d["features"] = json.loads(d.get("features") or "{}")
        except (TypeError, ValueError):
            d["features"] = {}
        return d
