"""
core/executive/state.py — FRIDAY 4.0 (M5)
Cognitive state: what FRIDAY is currently focused on. Persistent (SQLite, single
authoritative row) and observable, so the HUD and health surface can show — and a
restart can recover — the active objective, goal, plan, task, and focus.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional

log = logging.getLogger("friday.executive.state")

_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_PATH = _ROOT / "data" / "cognition.db"
_SCHEMA_VERSION = 1


@dataclass
class AttentionTarget:
    target_id: str
    kind: str
    score: float = 0.0
    reason: str = ""


@dataclass
class FocusState:
    target_id: str = ""
    kind: str = ""
    label: str = ""
    score: float = 0.0


@dataclass
class ActiveContext:
    objective: str = ""
    goal_id: Optional[str] = None
    plan_id: Optional[str] = None
    task: str = ""
    updated_at: float = 0.0


@dataclass
class CognitiveState:
    active_goal: Optional[str] = None
    current_objective: str = ""
    current_focus: Optional[FocusState] = None
    active_plan: Optional[str] = None
    current_task: str = ""
    updated_at: float = field(default_factory=time.time)
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        d = asdict(self)
        return d

    @staticmethod
    def from_dict(d: dict) -> "CognitiveState":
        focus = d.get("current_focus")
        return CognitiveState(
            active_goal=d.get("active_goal"),
            current_objective=d.get("current_objective", ""),
            current_focus=FocusState(**focus) if focus else None,
            active_plan=d.get("active_plan"),
            current_task=d.get("current_task", ""),
            updated_at=d.get("updated_at", time.time()),
            metadata=dict(d.get("metadata") or {}),
        )


class CognitiveStateStore:
    """Persists the single current CognitiveState (id=1) so focus survives restart."""

    def __init__(self, path: Optional[str | Path] = None) -> None:
        self._path = str(Path(path) if path else _DEFAULT_PATH)
        Path(self._path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(self._path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._init_schema()

    def _init_schema(self) -> None:
        with self._lock:
            self._conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS schema_version (
                    version INTEGER PRIMARY KEY, applied_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS cognitive_state (
                    id   INTEGER PRIMARY KEY CHECK (id = 1),
                    data TEXT NOT NULL,
                    ts   REAL NOT NULL
                );
                """
            )
            if self._conn.execute("SELECT MAX(version) FROM schema_version").fetchone()[0] is None:
                self._conn.execute(
                    "INSERT INTO schema_version (version, applied_at) VALUES (?, ?)",
                    (_SCHEMA_VERSION, time.time()))
            self._conn.commit()

    def save(self, state: CognitiveState) -> None:
        state.updated_at = time.time()
        with self._lock:
            self._conn.execute(
                """INSERT INTO cognitive_state (id, data, ts) VALUES (1, ?, ?)
                   ON CONFLICT(id) DO UPDATE SET data=excluded.data, ts=excluded.ts""",
                (json.dumps(state.to_dict()), state.updated_at),
            )
            self._conn.commit()

    def load(self) -> CognitiveState:
        with self._lock:
            row = self._conn.execute(
                "SELECT data FROM cognitive_state WHERE id=1").fetchone()
        if not row:
            return CognitiveState()
        try:
            return CognitiveState.from_dict(json.loads(row["data"]))
        except (TypeError, ValueError):
            return CognitiveState()

    def health(self) -> dict:
        st = self.load()
        return {"status": "ok", "objective": st.current_objective,
                "active_goal": st.active_goal, "active_plan": st.active_plan}

    def close(self) -> None:
        with self._lock:
            self._conn.close()
