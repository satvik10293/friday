"""
core/security/auth/store.py — FRIDAY 4.0 (M10)
Local SQLite persistence for the auth layer (tokens, sessions, audit). Same store
discipline as the rest of FRIDAY (per-thread conns, WAL, schema_version). Secrets
are stored **hashed** (sha256), never in plaintext. Local-only.
"""

from __future__ import annotations

import sqlite3
import threading
import time
from pathlib import Path
from typing import Optional

_ROOT = Path(__file__).resolve().parents[3]
_DEFAULT_PATH = _ROOT / "data" / "auth.db"
_SCHEMA_VERSION = 1


class AuthStore:
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
            CREATE TABLE IF NOT EXISTS api_tokens (
                id TEXT PRIMARY KEY, name TEXT NOT NULL, token_hash TEXT NOT NULL,
                scopes TEXT NOT NULL DEFAULT '', created_at REAL NOT NULL,
                revoked INTEGER NOT NULL DEFAULT 0);
            CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY, actor TEXT NOT NULL, token_hash TEXT NOT NULL,
                created_at REAL NOT NULL, expires_at REAL NOT NULL,
                revoked INTEGER NOT NULL DEFAULT 0);
            CREATE TABLE IF NOT EXISTS auth_audit (
                id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL,
                actor TEXT NOT NULL, action TEXT NOT NULL, result TEXT NOT NULL,
                trace_id TEXT NOT NULL DEFAULT '', detail TEXT NOT NULL DEFAULT '');
            CREATE INDEX IF NOT EXISTS idx_audit_ts ON auth_audit(ts);
            """
        )
        if c.execute("SELECT MAX(version) FROM schema_version").fetchone()[0] is None:
            c.execute("INSERT INTO schema_version (version, applied_at) VALUES (?, ?)",
                      (_SCHEMA_VERSION, time.time()))
        c.commit()

    def close(self) -> None:
        c = getattr(self._local, "c", None)
        if c is not None:
            c.close()
            self._local.c = None
