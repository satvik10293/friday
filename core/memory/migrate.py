"""
core/memory/migrate.py — FRIDAY 4.0 / 5.x (Phase C: One Memory)
One-way, idempotent migrations from every legacy store into the new Memory
Service: chronicle.db (memories/facts/preferences), the local QA corpus
(data/local_qa.json) and the Obsidian vault. Legacy sources are only ever
READ — they stay untouched as archives. Each source is imported once via the
store's `imports` bookkeeping table; `migrate_all()` backs up data/ first and
is safe to run on every boot.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import sqlite3
import time
from pathlib import Path
from typing import Optional

log = logging.getLogger("friday.memory.migrate")

_ROOT = Path(__file__).resolve().parents[2]
_LEGACY_CHRONICLE = _ROOT / "data" / "chronicle.db"
_LOCAL_QA = _ROOT / "data" / "local_qa.json"

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


def migrate_local_qa(service, qa_path: Optional[str | Path] = None) -> dict:
    """Import the learned QA corpus (data/local_qa.json) as semantic memories."""
    path = Path(qa_path) if qa_path else _LOCAL_QA
    store = service._store
    if store.import_done("local_qa"):
        return {"status": "already-imported"}
    if not path.exists():
        return {"status": "no-source", "path": str(path)}
    try:
        items = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        return {"status": "unreadable", "error": str(e)}
    n = 0
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict):
            continue
        question = (item.get("question") or "").strip()
        answer = (item.get("answer") or "").strip()
        if not answer:
            continue
        content = f"Q: {question}\nA: {answer}" if question else answer
        service.remember("friday", content, topic=question[:80], kind="qa",
                         tier="semantic", importance=0.6,
                         metadata={"source": "local_qa"})
        n += 1
    store.mark_import("local_qa")
    result = {"status": "ok", "qa_pairs": n}
    log.info("local_qa migration: %s", result)
    return result


def migrate_vault(service, vault_dir: Optional[str | Path] = None,
                  max_notes: int = 2000) -> dict:
    """Import Obsidian vault notes as semantic knowledge memories. The vault
    stays the human-readable source; this makes its facts recallable."""
    vault = Path(vault_dir) if vault_dir else \
        Path(os.environ.get("FRIDAY_VAULT", r"C:\VAULT\satvik"))
    store = service._store
    if store.import_done("vault"):
        return {"status": "already-imported"}
    if not vault.is_dir():
        return {"status": "no-source", "path": str(vault)}
    n = 0
    for note in sorted(vault.glob("*.md")):
        if n >= max_notes:
            break
        try:
            text = note.read_text(encoding="utf-8", errors="replace").strip()
        except OSError:
            continue
        if not text:
            continue
        service.remember("friday", text[:4000], topic=note.stem[:80],
                         kind="knowledge", tier="semantic", importance=0.6,
                         metadata={"source": "vault", "note": note.name})
        n += 1
    store.mark_import("vault")
    result = {"status": "ok", "notes": n}
    log.info("vault migration: %s", result)
    return result


def backup_data(data_dir: Optional[str | Path] = None) -> Optional[Path]:
    """Copy the legacy stores aside before the first migration touches anything."""
    data = Path(data_dir) if data_dir else (_ROOT / "data")
    if not data.is_dir():
        return None
    dest = data / "backups" / f"pre_m2_migration_{int(time.time())}"
    copied = False
    for name in ("chronicle.db", "local_qa.json", "local_qa.npz",
                 "psyche.json", "learning.jsonl", "sovereign_stats.json"):
        src = data / name
        if src.exists():
            dest.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest / name)
            copied = True
    return dest if copied else None


def migrate_all(service, *, chronicle_path=None, qa_path=None,
                vault_dir=None) -> dict:
    """Run every migration once (idempotent). Backs up data/ before the first
    real import. Never raises — a failed source is reported, not fatal."""
    store = service._store
    pending = [s for s in ("chronicle", "local_qa", "vault")
               if not store.import_done(s)]
    report: dict = {"pending": pending}
    if pending:
        try:
            backup = backup_data()
            report["backup"] = str(backup) if backup else None
        except Exception as e:  # noqa: BLE001
            report["backup_error"] = str(e)
    for name, fn, arg in (("chronicle", migrate_from_chronicle, chronicle_path),
                          ("local_qa", migrate_local_qa, qa_path),
                          ("vault", migrate_vault, vault_dir)):
        try:
            report[name] = fn(service, arg)
        except Exception as e:  # noqa: BLE001 — one bad source never blocks the rest
            log.debug("%s migration failed", name, exc_info=True)
            report[name] = {"status": "failed", "error": str(e)}
    return report


if __name__ == "__main__":
    import argparse

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description="Migrate legacy stores into the Memory Service")
    parser.add_argument("--vault", default=None, help="override the vault directory")
    args = parser.parse_args()
    from core.memory.service import get_memory_service
    print(json.dumps(migrate_all(get_memory_service(), vault_dir=args.vault), indent=2))
