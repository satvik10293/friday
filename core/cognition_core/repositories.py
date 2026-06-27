"""
core/cognition_core/repositories.py — FRIDAY 6.0 (M13)
Concrete persistence backends for the entity + belief repositories. SQLite is the
durable default (per-thread connections, WAL, schema_version — the FRIDAY store
discipline); the in-memory backend is the dependency-free option for tests and for
embedding cognition where no DB is wanted. All SQLite knowledge is confined here,
behind the interfaces in `interfaces.py`.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Optional

from .models import Belief, Entity

_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_PATH = _ROOT / "data" / "cognition.db"
_SCHEMA_VERSION = 1


def _loads(text, default):
    try:
        return json.loads(text)
    except (TypeError, ValueError):
        return default


# ── SQLite ────────────────────────────────────────────────────────────────────────
class _SqliteBase:
    def __init__(self, path: Optional[str | Path] = None) -> None:
        self._path = str(Path(path) if path else _DEFAULT_PATH)
        Path(self._path).parent.mkdir(parents=True, exist_ok=True)
        self._local = threading.local()
        self._init_schema()

    def _conn(self) -> sqlite3.Connection:
        c = getattr(self._local, "c", None)
        if c is None:
            c = sqlite3.connect(self._path, check_same_thread=False)
            c.row_factory = sqlite3.Row
            c.execute("PRAGMA journal_mode=WAL")
            c.execute("PRAGMA busy_timeout=5000")
            self._local.c = c
        return c

    def _init_schema(self) -> None:
        c = self._conn()
        c.executescript(
            """
            CREATE TABLE IF NOT EXISTS schema_version (
                version INTEGER PRIMARY KEY, applied_at REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS cognition_meta (
                key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS entities (
                stable_id TEXT PRIMARY KEY, kind TEXT NOT NULL, primary_label TEXT NOT NULL,
                labels TEXT NOT NULL DEFAULT '[]', attributes TEXT NOT NULL DEFAULT '{}',
                confidence REAL NOT NULL DEFAULT 1.0, created_at REAL NOT NULL,
                updated_at REAL NOT NULL, merged_from TEXT NOT NULL DEFAULT '[]');
            CREATE TABLE IF NOT EXISTS entity_aliases (
                normalized TEXT NOT NULL, kind TEXT NOT NULL, stable_id TEXT NOT NULL,
                PRIMARY KEY (normalized, kind));
            CREATE TABLE IF NOT EXISTS beliefs (
                belief_id TEXT PRIMARY KEY, subject TEXT NOT NULL, predicate TEXT NOT NULL,
                value TEXT, confidence REAL NOT NULL DEFAULT 0.5,
                supporting TEXT NOT NULL DEFAULT '[]', contradicting TEXT NOT NULL DEFAULT '[]',
                source TEXT NOT NULL DEFAULT 'system', timestamp REAL NOT NULL,
                last_verification REAL NOT NULL, status TEXT NOT NULL DEFAULT 'active',
                updated_at REAL NOT NULL);
            CREATE INDEX IF NOT EXISTS idx_entities_kind ON entities(kind);
            CREATE INDEX IF NOT EXISTS idx_alias_sid ON entity_aliases(stable_id);
            CREATE INDEX IF NOT EXISTS idx_beliefs_subject ON beliefs(subject);
            CREATE INDEX IF NOT EXISTS idx_beliefs_pred ON beliefs(subject, predicate);
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


class SqliteEntityRepository(_SqliteBase):
    def allocate_id(self) -> str:
        c = self._conn()
        # first allocation seeds the counter at 1; subsequent ones increment it —
        # so ids start at ENT_000001 and survive restarts (matches the in-memory repo)
        c.execute("INSERT INTO cognition_meta (key, value) VALUES ('entity_seq', '1') "
                  "ON CONFLICT(key) DO UPDATE SET value = CAST(value AS INTEGER) + 1")
        seq = int(c.execute("SELECT value FROM cognition_meta WHERE key='entity_seq'").fetchone()[0])
        c.commit()
        return f"ENT_{seq:06d}"

    def add(self, entity: Entity) -> None:
        c = self._conn()
        c.execute("""INSERT OR REPLACE INTO entities
                     (stable_id, kind, primary_label, labels, attributes, confidence,
                      created_at, updated_at, merged_from)
                     VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                  (entity.stable_id, entity.kind, entity.primary_label,
                   json.dumps(entity.labels), json.dumps(entity.attributes),
                   entity.confidence, entity.created_at, entity.updated_at,
                   json.dumps(entity.merged_from)))
        c.commit()

    update = add

    def get(self, stable_id: str) -> Optional[Entity]:
        r = self._conn().execute("SELECT * FROM entities WHERE stable_id=?", (stable_id,)).fetchone()
        return self._row(r) if r else None

    def remove(self, stable_id: str) -> None:
        c = self._conn()
        c.execute("DELETE FROM entities WHERE stable_id=?", (stable_id,))
        c.execute("DELETE FROM entity_aliases WHERE stable_id=?", (stable_id,))
        c.commit()

    def all(self) -> list[Entity]:
        return [self._row(r) for r in self._conn().execute("SELECT * FROM entities").fetchall()]

    def by_kind(self, kind: str) -> list[Entity]:
        rows = self._conn().execute("SELECT * FROM entities WHERE kind=?", (kind,)).fetchall()
        return [self._row(r) for r in rows]

    def find_by_label(self, kind: str, label: str) -> Optional[Entity]:
        r = self._conn().execute(
            "SELECT * FROM entities WHERE kind=? AND primary_label=? LIMIT 1",
            (kind, label)).fetchone()
        return self._row(r) if r else None

    def add_alias(self, normalized: str, stable_id: str, kind: str) -> None:
        c = self._conn()
        c.execute("INSERT OR REPLACE INTO entity_aliases (normalized, kind, stable_id) "
                  "VALUES (?, ?, ?)", (normalized, kind, stable_id))
        c.commit()

    def resolve_alias(self, normalized: str, kind: Optional[str] = None) -> Optional[str]:
        if kind is not None:
            r = self._conn().execute(
                "SELECT stable_id FROM entity_aliases WHERE normalized=? AND kind=?",
                (normalized, kind)).fetchone()
        else:
            r = self._conn().execute(
                "SELECT stable_id FROM entity_aliases WHERE normalized=? LIMIT 1",
                (normalized,)).fetchone()
        return r["stable_id"] if r else None

    def aliases_for(self, stable_id: str) -> list[str]:
        rows = self._conn().execute(
            "SELECT normalized FROM entity_aliases WHERE stable_id=?", (stable_id,)).fetchall()
        return [r["normalized"] for r in rows]

    def counts(self) -> dict:
        c = self._conn()
        return {"entities": c.execute("SELECT COUNT(*) FROM entities").fetchone()[0],
                "aliases": c.execute("SELECT COUNT(*) FROM entity_aliases").fetchone()[0]}

    @staticmethod
    def _row(r) -> Entity:
        return Entity(stable_id=r["stable_id"], kind=r["kind"], primary_label=r["primary_label"],
                      labels=_loads(r["labels"], []), attributes=_loads(r["attributes"], {}),
                      confidence=r["confidence"], created_at=r["created_at"],
                      updated_at=r["updated_at"], merged_from=_loads(r["merged_from"], []))


class SqliteBeliefRepository(_SqliteBase):
    def add(self, belief: Belief) -> None:
        c = self._conn()
        c.execute("""INSERT OR REPLACE INTO beliefs
                     (belief_id, subject, predicate, value, confidence, supporting,
                      contradicting, source, timestamp, last_verification, status, updated_at)
                     VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                  (belief.belief_id, belief.subject, belief.predicate,
                   json.dumps(belief.value), belief.confidence,
                   json.dumps([e.to_dict() for e in belief.supporting_evidence]),
                   json.dumps([e.to_dict() for e in belief.contradicting_evidence]),
                   belief.source, belief.timestamp, belief.last_verification,
                   belief.status, belief.updated_at))
        c.commit()

    update = add

    def get(self, belief_id: str) -> Optional[Belief]:
        r = self._conn().execute("SELECT * FROM beliefs WHERE belief_id=?", (belief_id,)).fetchone()
        return self._row(r) if r else None

    def find(self, *, subject: Optional[str] = None, predicate: Optional[str] = None,
             status: Optional[str] = None) -> list[Belief]:
        clauses, params = [], []
        if subject is not None:
            clauses.append("subject=?"); params.append(subject)
        if predicate is not None:
            clauses.append("predicate=?"); params.append(predicate)
        if status is not None:
            clauses.append("status=?"); params.append(status)
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        rows = self._conn().execute(
            f"SELECT * FROM beliefs{where} ORDER BY updated_at DESC", params).fetchall()
        return [self._row(r) for r in rows]

    def all(self) -> list[Belief]:
        return [self._row(r) for r in self._conn().execute("SELECT * FROM beliefs").fetchall()]

    def counts(self) -> dict:
        c = self._conn()
        return {"beliefs": c.execute("SELECT COUNT(*) FROM beliefs").fetchone()[0],
                "active": c.execute("SELECT COUNT(*) FROM beliefs WHERE status='active'").fetchone()[0]}

    @staticmethod
    def _row(r) -> Belief:
        b = Belief(subject=r["subject"], predicate=r["predicate"], value=_loads(r["value"], None),
                   confidence=r["confidence"], source=r["source"], timestamp=r["timestamp"],
                   last_verification=r["last_verification"], status=r["status"],
                   belief_id=r["belief_id"], updated_at=r["updated_at"])
        from .models import Evidence
        b.supporting_evidence = [Evidence.from_dict(e) for e in _loads(r["supporting"], [])]
        b.contradicting_evidence = [Evidence.from_dict(e) for e in _loads(r["contradicting"], [])]
        return b


# ── in-memory (tests / db-free embedding) ─────────────────────────────────────────
class InMemoryEntityRepository:
    def __init__(self) -> None:
        self._entities: dict[str, Entity] = {}
        self._aliases: dict[tuple, str] = {}
        self._seq = 0

    def allocate_id(self) -> str:
        self._seq += 1
        return f"ENT_{self._seq:06d}"

    def add(self, entity: Entity) -> None:
        self._entities[entity.stable_id] = entity

    update = add

    def get(self, stable_id: str) -> Optional[Entity]:
        return self._entities.get(stable_id)

    def remove(self, stable_id: str) -> None:
        self._entities.pop(stable_id, None)
        self._aliases = {k: v for k, v in self._aliases.items() if v != stable_id}

    def all(self) -> list[Entity]:
        return list(self._entities.values())

    def by_kind(self, kind: str) -> list[Entity]:
        return [e for e in self._entities.values() if e.kind == kind]

    def find_by_label(self, kind: str, label: str) -> Optional[Entity]:
        for e in self._entities.values():
            if e.kind == kind and e.primary_label == label:
                return e
        return None

    def add_alias(self, normalized: str, stable_id: str, kind: str) -> None:
        self._aliases[(normalized, kind)] = stable_id

    def resolve_alias(self, normalized: str, kind: Optional[str] = None) -> Optional[str]:
        if kind is not None:
            return self._aliases.get((normalized, kind))
        for (norm, _k), sid in self._aliases.items():
            if norm == normalized:
                return sid
        return None

    def aliases_for(self, stable_id: str) -> list[str]:
        return [norm for (norm, _k), sid in self._aliases.items() if sid == stable_id]

    def counts(self) -> dict:
        return {"entities": len(self._entities), "aliases": len(self._aliases)}

    def close(self) -> None:
        pass


class InMemoryBeliefRepository:
    def __init__(self) -> None:
        self._beliefs: dict[str, Belief] = {}

    def add(self, belief: Belief) -> None:
        self._beliefs[belief.belief_id] = belief

    update = add

    def get(self, belief_id: str) -> Optional[Belief]:
        return self._beliefs.get(belief_id)

    def find(self, *, subject=None, predicate=None, status=None) -> list[Belief]:
        out = []
        for b in self._beliefs.values():
            if subject is not None and b.subject != subject:
                continue
            if predicate is not None and b.predicate != predicate:
                continue
            if status is not None and b.status != status:
                continue
            out.append(b)
        return sorted(out, key=lambda b: b.updated_at, reverse=True)

    def all(self) -> list[Belief]:
        return list(self._beliefs.values())

    def counts(self) -> dict:
        active = sum(1 for b in self._beliefs.values() if b.status == "active")
        return {"beliefs": len(self._beliefs), "active": active}

    def close(self) -> None:
        pass
