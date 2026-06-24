"""
core/memory/migrate.py — FRIDAY 4.0
One-way, idempotent migration from the legacy chronicle.db into the new Memory
Service. Reads legacy memories/facts/preferences and re-remembers them (so they
are embedded + indexed in the new store). Safe to run repeatedly.
"""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path
from typing import Optional

log = logging.getLogger("friday.memory.migrate")

_ROOT = Path(__file__).resolve().parents[2]
_LEGACY_CHRONICLE = _ROOT / "data" / "chronicle.db"

# legacy MemoryType -> new kind
_KIND_MAP = {
    "conversation": "conversation",
    "fact": "fact",
    "preference": "preference",
    "outcome": "outcome",
    "context": "context",
    "world": "world",
}


def _table_exists(con: sqlite3.Connection, name: str) -> bool:
    return con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone() is not None


def migrate_from_chronicle(service, chronicle_path: Optional[str | Path] = None) -> dict:
    """Import legacy chronicle data into `service`. Idempotent via the store's
    `imports` bookkeeping table."""
    path = Path(chronicle_path) if chronicle_path else _LEGACY_CHRONICLE
    store = service._store  # service owns the store; this is a maintenance op

    if store.import_done("chronicle"):
        return {"status": "already-imported"}
    if not path.exists():
        return {"status": "no-source", "path": str(path)}

    src = sqlite3.connect(str(path))
    src.row_factory = sqlite3.Row
    n_mem = n_fact = n_pref = 0
    try:
        if _table_exists(src, "memories"):
            for r in src.execute("SELECT * FROM memories"):
                service.remember(
                    r["role"], r["content"],
                    topic=r["topic"] or "",
                    kind=_KIND_MAP.get(r["type"], "conversation"),
                    importance=r["importance"] if r["importance"] is not None else 0.5,
                    tier="episodic",
                    session_id=r["session_id"] or "",
                    metadata={"legacy_ts": r["timestamp"], "source": "chronicle"},
                )
                n_mem += 1
        if _table_exists(src, "facts"):
            for r in src.execute("SELECT * FROM facts"):
                service.remember(
                    "system", f'{r["subject"]} {r["predicate"]} {r["object"]}',
                    topic=r["subject"], kind="fact",
                    importance=r["confidence"] if r["confidence"] is not None else 0.7,
                    metadata={"source": "chronicle.fact"},
                )
                n_fact += 1
        if _table_exists(src, "preferences"):
            for r in src.execute("SELECT * FROM preferences"):
                service.remember(
                    "system", f'{r["category"]}.{r["key"]} = {r["value"]}',
                    topic=r["category"], kind="preference",
                    importance=min(1.0, r["weight"] if r["weight"] is not None else 1.0),
                    metadata={"source": "chronicle.pref"},
                )
                n_pref += 1
    finally:
        src.close()

    store.mark_import("chronicle")
    result = {"status": "ok", "memories": n_mem, "facts": n_fact, "preferences": n_pref}
    log.info("chronicle migration: %s", result)
    return result
