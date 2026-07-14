"""
core/observability/decision_log.py — FRIDAY 4.0
The Decision Log. Durable, queryable record of WHY FRIDAY did what it did.

Every cognitive turn ends with one row answering the charter's six questions:
  why (rationale/intent) · what memory · what goal · what tools/skills ·
  which model · how confident — plus latency, cost, outcome, autonomy.

Design rules:
  • SQLite is the source of truth (its own DB, decoupled from chronicle).
  • Migration-gated via a schema_version table from day one.
  • Thread-safe (a single connection guarded by a lock; low write volume).
  • This is also the dataset that finally makes "independence %" truthful and
    gives Reflection (M4) real behaviour to learn from.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
import time
from pathlib import Path
from typing import Optional

log = logging.getLogger("friday.observability.decisions")

_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_PATH = _ROOT / "data" / "decisions.db"
_SCHEMA_VERSION = 1

# Columns stored as JSON text and decoded on read.
_JSON_FIELDS = ("route", "models_used", "skills_invoked", "goals_touched", "memory_used")

# A turn "used the cloud" if an external model produced the answer. The metric
# must stay truthful across BOTH external tiers: the M42 cloud reasoner and the
# M30 Groq teacher each tag their model "groq:…" and route "cloud_reasoner" /
# "groq_teacher". Keying off provider prefixes (the authoritative signal) — not
# a fragile "cloud" route substring — stops a teacher-answered turn being
# miscounted as local, which would silently overstate independence.
_EXTERNAL_MODEL_PREFIXES = ("cloud:", "groq:", "openai:", "gemini:", "google:",
                            "anthropic:")
_EXTERNAL_ROUTE_MARKERS = ("cloud", "external", "groq", "teacher")


def _turn_used_external(models, route) -> bool:
    """True if any external model answered this turn (single source of truth
    for the independence metric)."""
    if any(str(m).lower().startswith(_EXTERNAL_MODEL_PREFIXES) for m in models):
        return True
    return any(any(mark in str(step).lower() for mark in _EXTERNAL_ROUTE_MARKERS)
               for step in route)


class DecisionLog:
    def __init__(self, path: Optional[str | Path] = None) -> None:
        self._path = Path(path) if path else _DEFAULT_PATH
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(self._path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._init_schema()

    # ── schema / migrations ──────────────────────────────────────────────────
    def _init_schema(self) -> None:
        with self._lock:
            self._conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS schema_version (
                    version    INTEGER PRIMARY KEY,
                    applied_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS decisions (
                    id             INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts             REAL    NOT NULL,
                    trace_id       TEXT,
                    turn_id        INTEGER,
                    intent         TEXT,
                    route          TEXT    NOT NULL DEFAULT '[]',
                    models_used    TEXT    NOT NULL DEFAULT '[]',
                    skills_invoked TEXT    NOT NULL DEFAULT '[]',
                    goals_touched  TEXT    NOT NULL DEFAULT '[]',
                    memory_used    TEXT    NOT NULL DEFAULT '[]',
                    confidence     REAL,
                    cost_tokens    INTEGER,
                    latency_ms     INTEGER,
                    outcome        TEXT,
                    rationale      TEXT,
                    was_autonomous INTEGER NOT NULL DEFAULT 0,
                    source         TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_decisions_trace ON decisions(trace_id);
                CREATE INDEX IF NOT EXISTS idx_decisions_ts    ON decisions(ts);
                """
            )
            row = self._conn.execute("SELECT MAX(version) FROM schema_version").fetchone()
            if row[0] is None:
                self._conn.execute(
                    "INSERT INTO schema_version (version, applied_at) VALUES (?, ?)",
                    (_SCHEMA_VERSION, time.time()),
                )
            self._conn.commit()
        log.debug("decision log ready at %s (schema v%d)", self._path, _SCHEMA_VERSION)

    # ── write ─────────────────────────────────────────────────────────────────
    def log(
        self,
        *,
        trace_id: Optional[str] = None,
        turn_id: Optional[int] = None,
        intent: Optional[str] = None,
        route=None,
        models_used=None,
        skills_invoked=None,
        goals_touched=None,
        memory_used=None,
        confidence: Optional[float] = None,
        cost_tokens: Optional[int] = None,
        latency_ms: Optional[int] = None,
        outcome: Optional[str] = None,
        rationale: Optional[str] = None,
        was_autonomous: bool = False,
        source: Optional[str] = None,
    ) -> int:
        row = {
            "ts": time.time(),
            "trace_id": trace_id,
            "turn_id": turn_id,
            "intent": intent,
            "route": json.dumps(route or []),
            "models_used": json.dumps(models_used or []),
            "skills_invoked": json.dumps(skills_invoked or []),
            "goals_touched": json.dumps(goals_touched or []),
            "memory_used": json.dumps(memory_used or []),
            "confidence": confidence,
            "cost_tokens": cost_tokens,
            "latency_ms": latency_ms,
            "outcome": outcome,
            "rationale": rationale,
            "was_autonomous": 1 if was_autonomous else 0,
            "source": source,
        }
        with self._lock:
            cur = self._conn.execute(
                """INSERT INTO decisions
                   (ts, trace_id, turn_id, intent, route, models_used, skills_invoked,
                    goals_touched, memory_used, confidence, cost_tokens, latency_ms,
                    outcome, rationale, was_autonomous, source)
                   VALUES
                   (:ts, :trace_id, :turn_id, :intent, :route, :models_used, :skills_invoked,
                    :goals_touched, :memory_used, :confidence, :cost_tokens, :latency_ms,
                    :outcome, :rationale, :was_autonomous, :source)""",
                row,
            )
            self._conn.commit()
            return int(cur.lastrowid)

    # ── read ──────────────────────────────────────────────────────────────────
    def _decode(self, r: sqlite3.Row) -> dict:
        d = dict(r)
        for f in _JSON_FIELDS:
            try:
                d[f] = json.loads(d[f])
            except (TypeError, ValueError):
                pass
        d["was_autonomous"] = bool(d.get("was_autonomous"))
        return d

    def by_trace(self, trace_id: str) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM decisions WHERE trace_id=? ORDER BY ts", (trace_id,)
            ).fetchall()
        return [self._decode(r) for r in rows]

    def recent(self, limit: int = 50) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM decisions ORDER BY ts DESC LIMIT ?", (limit,)
            ).fetchall()
        return [self._decode(r) for r in rows]

    def stats(self) -> dict:
        with self._lock:
            total = self._conn.execute("SELECT COUNT(*) FROM decisions").fetchone()[0]
            auto = self._conn.execute(
                "SELECT COUNT(*) FROM decisions WHERE was_autonomous=1"
            ).fetchone()[0]
            avg_conf = self._conn.execute(
                "SELECT AVG(confidence) FROM decisions WHERE confidence IS NOT NULL"
            ).fetchone()[0]
        return {
            "total": total,
            "autonomous": auto,
            "avg_confidence": round(avg_conf, 3) if avg_conf is not None else None,
        }

    def independence(self) -> dict:
        """Truthful independence: the share of decisions answered without any
        external model. Both cloud tiers count as external — the M42 cloud
        reasoner AND the M30 Groq teacher (see `_turn_used_external`). Measured
        from real rows — never hardcoded (fixes 3.0 defect #3)."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT models_used, route, was_autonomous FROM decisions"
            ).fetchall()
        total = len(rows)
        local = autonomous = 0
        for r in rows:
            models = json.loads(r["models_used"] or "[]")
            route = json.loads(r["route"] or "[]")
            if not _turn_used_external(models, route):
                local += 1
            if r["was_autonomous"]:
                autonomous += 1
        return {
            "total": total,
            "local_turns": local,
            "independence_pct": round(100.0 * local / total, 1) if total else None,
            "autonomous_pct": round(100.0 * autonomous / total, 1) if total else None,
        }

    def close(self) -> None:
        with self._lock:
            self._conn.close()


# ── singleton ───────────────────────────────────────────────────────────────────
_default_log: Optional[DecisionLog] = None
_dl_lock = threading.Lock()


def get_decision_log() -> DecisionLog:
    global _default_log
    with _dl_lock:
        if _default_log is None:
            _default_log = DecisionLog()
    return _default_log
