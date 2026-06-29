"""
core/vision/transport/registry.py — FRIDAY 6.1 (M14)
Permanent camera identity. Each camera is identified by a stable *key* (a client
token, USB index, or stream URL); the registry maps that key to a permanent opaque
id (CAMERA_0001) so the same physical camera keeps its id across reconnects, browser
refreshes, and server restarts. In-memory by default; SQLite when a path is given.
"""

from __future__ import annotations

import sqlite3
import threading
import time
from pathlib import Path
from typing import Optional

_ROOT = Path(__file__).resolve().parents[3]
_DEFAULT_PATH = _ROOT / "data" / "vision.db"


class CameraRegistry:
    def __init__(self, path: Optional[str | Path] = None, *, persistent: bool = False) -> None:
        self._lock = threading.Lock()
        self._by_key: dict[str, str] = {}
        self._seq = 0
        self._conn: Optional[sqlite3.Connection] = None
        if persistent:
            self._open(path or _DEFAULT_PATH)

    def _open(self, path) -> None:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute(
            """CREATE TABLE IF NOT EXISTS cameras (
                 camera_id TEXT PRIMARY KEY, key TEXT UNIQUE NOT NULL,
                 kind TEXT, label TEXT, registered_at REAL NOT NULL)""")
        self._conn.commit()
        rows = self._conn.execute("SELECT camera_id, key FROM cameras").fetchall()
        for cid, key in rows:
            self._by_key[key] = cid
            self._seq = max(self._seq, int(cid.split("_")[-1]))

    def allocate(self, key: str, *, kind: str = "", label: str = "") -> str:
        """Return the permanent id for `key`, creating it on first sight."""
        with self._lock:
            existing = self._by_key.get(key)
            if existing is not None:
                return existing
            self._seq += 1
            camera_id = f"CAMERA_{self._seq:04d}"
            self._by_key[key] = camera_id
            if self._conn is not None:
                self._conn.execute(
                    "INSERT OR IGNORE INTO cameras VALUES (?, ?, ?, ?, ?)",
                    (camera_id, key, kind, label, time.time()))
                self._conn.commit()
            return camera_id

    def known(self, key: str) -> bool:
        with self._lock:
            return key in self._by_key

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None
