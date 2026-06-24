"""
core/skills/audit.py — FRIDAY 4.0
The Audit Log. Every skill execution generates one durable record (data/audit.db).
Migration-gated, thread-safe, survives restart. This is the legal record of
"what FRIDAY did", complementing the Decision Log's "why".
"""

from __future__ import annotations

import logging
import sqlite3
import threading
import time
from pathlib import Path
from typing import Optional

log = logging.getLogger("friday.skills.audit")

_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_PATH = _ROOT / "data" / "audit.db"
_SCHEMA_VERSION = 1


class AuditLog:
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
                CREATE TABLE IF NOT EXISTS audit (
                    id             INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts             REAL    NOT NULL,
                    trace_id       TEXT,
                    skill_name     TEXT    NOT NULL,
                    caller         TEXT,
                    role           TEXT,
                    permission     TEXT,
                    approved       INTEGER NOT NULL DEFAULT 0,
                    duration_ms    REAL,
                    success        INTEGER NOT NULL DEFAULT 0,
                    error          TEXT,
                    result_summary TEXT,
                    source         TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_audit_trace ON audit(trace_id);
                CREATE INDEX IF NOT EXISTS idx_audit_skill ON audit(skill_name);
                CREATE INDEX IF NOT EXISTS idx_audit_ts    ON audit(ts);
                """
            )
            if self._conn.execute("SELECT MAX(version) FROM schema_version").fetchone()[0] is None:
                self._conn.execute(
                    "INSERT INTO schema_version (version, applied_at) VALUES (?, ?)",
                    (_SCHEMA_VERSION, time.time()),
                )
            self._conn.commit()

    def record(self, *, trace_id: Optional[str], skill_name: str, caller: Optional[str] = None,
               role: Optional[str] = None, permission: Optional[str] = None,
               approved: bool = False, duration_ms: float = 0.0, success: bool = False,
               error: Optional[str] = None, result_summary: Optional[str] = None,
               source: str = "skills.executor") -> int:
        with self._lock:
            cur = self._conn.execute(
                """INSERT INTO audit
                   (ts, trace_id, skill_name, caller, role, permission, approved,
                    duration_ms, success, error, result_summary, source)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (time.time(), trace_id, skill_name, caller, role, permission,
                 1 if approved else 0, duration_ms, 1 if success else 0,
                 error, result_summary, source),
            )
            self._conn.commit()
            return int(cur.lastrowid)

    @staticmethod
    def _decode(r: sqlite3.Row) -> dict:
        d = dict(r)
        d["approved"] = bool(d.get("approved"))
        d["success"] = bool(d.get("success"))
        return d

    def by_trace(self, trace_id: str) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM audit WHERE trace_id=? ORDER BY ts", (trace_id,)
            ).fetchall()
        return [self._decode(r) for r in rows]

    def recent(self, limit: int = 50) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM audit ORDER BY ts DESC LIMIT ?", (limit,)
            ).fetchall()
        return [self._decode(r) for r in rows]

    def stats(self) -> dict:
        with self._lock:
            total = self._conn.execute("SELECT COUNT(*) FROM audit").fetchone()[0]
            ok = self._conn.execute("SELECT COUNT(*) FROM audit WHERE success=1").fetchone()[0]
        return {"total": total, "success": ok, "failure": total - ok}

    def close(self) -> None:
        with self._lock:
            self._conn.close()
