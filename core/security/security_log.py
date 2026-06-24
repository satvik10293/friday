"""
core/security/security_log.py — FRIDAY 4.0
Dedicated security event log (data/security.db). Records failed approvals,
permission violations, policy violations, and suspicious activity — separate from
the audit trail so security review has a focused, durable stream.
"""

from __future__ import annotations

import logging
import sqlite3
import threading
import time
from pathlib import Path
from typing import Optional

log = logging.getLogger("friday.security.log")

_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_PATH = _ROOT / "data" / "security.db"
_SCHEMA_VERSION = 1

EVENT_TYPES = ("failed_approval", "permission_violation", "policy_violation", "suspicious")
SEVERITIES = ("low", "medium", "high", "critical")


class SecurityLog:
    def __init__(self, path: Optional[str | Path] = None) -> None:
        self._path = Path(path) if path else _DEFAULT_PATH
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(self._path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._init()

    def _init(self) -> None:
        with self._lock:
            self._conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS schema_version (
                    version INTEGER PRIMARY KEY, applied_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS security_events (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts         REAL NOT NULL,
                    event_type TEXT NOT NULL,
                    severity   TEXT NOT NULL DEFAULT 'medium',
                    trace_id   TEXT,
                    skill_name TEXT,
                    caller     TEXT,
                    role       TEXT,
                    detail     TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_sec_type ON security_events(event_type);
                CREATE INDEX IF NOT EXISTS idx_sec_ts   ON security_events(ts);
                """
            )
            if self._conn.execute("SELECT MAX(version) FROM schema_version").fetchone()[0] is None:
                self._conn.execute(
                    "INSERT INTO schema_version (version, applied_at) VALUES (?, ?)",
                    (_SCHEMA_VERSION, time.time()),
                )
            self._conn.commit()

    def record(self, *, event_type: str, severity: str = "medium",
               trace_id: Optional[str] = None, skill_name: Optional[str] = None,
               caller: Optional[str] = None, role: Optional[str] = None,
               detail: Optional[str] = None) -> int:
        with self._lock:
            cur = self._conn.execute(
                """INSERT INTO security_events
                   (ts, event_type, severity, trace_id, skill_name, caller, role, detail)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (time.time(), event_type, severity, trace_id, skill_name, caller, role, detail),
            )
            self._conn.commit()
        log.warning("security[%s/%s] skill=%s caller=%s: %s",
                    event_type, severity, skill_name, caller, detail)
        return int(cur.lastrowid)

    def by_type(self, event_type: str, limit: int = 100) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM security_events WHERE event_type=? ORDER BY ts DESC LIMIT ?",
                (event_type, limit),
            ).fetchall()
        return [dict(r) for r in rows]

    def recent(self, limit: int = 50) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM security_events ORDER BY ts DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(r) for r in rows]

    def stats(self) -> dict:
        with self._lock:
            total = self._conn.execute("SELECT COUNT(*) FROM security_events").fetchone()[0]
            by_type = {
                t: self._conn.execute(
                    "SELECT COUNT(*) FROM security_events WHERE event_type=?", (t,)
                ).fetchone()[0]
                for t in EVENT_TYPES
            }
        return {"total": total, "by_type": by_type}

    def close(self) -> None:
        with self._lock:
            self._conn.close()
