"""
core/world/world_model.py — FRIDAY 4.0 (M5)
The World Model: FRIDAY's persistent internal model of reality.

Tracks the user, the project, the runtime, and the system as typed entities with
mutable state, plus relationships between them. SQLite-backed (per-thread conns +
WAL + migration gate — same discipline as M2/M4) so the model survives restart.
Snapshots + diffs make change detection a first-class operation.

Import is side-effect free: nothing is opened until a WorldModel is constructed.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
import time
from pathlib import Path
from typing import Optional

from .entities import WorldEntity, WorldRelationship, new_entity
from .snapshots import WorldSnapshot, diff_snapshots, new_snapshot

log = logging.getLogger("friday.world.model")

_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_PATH = _ROOT / "data" / "world.db"
_SCHEMA_VERSION = 1


class WorldModel:
    def __init__(self, path: Optional[str | Path] = None) -> None:
        self._path = str(Path(path) if path else _DEFAULT_PATH)
        Path(self._path).parent.mkdir(parents=True, exist_ok=True)
        self._local = threading.local()
        self._observations = 0
        self._init_schema()

    # ── connection (one per thread) ────────────────────────────────────────────
    def _conn(self) -> sqlite3.Connection:
        c = getattr(self._local, "conn", None)
        if c is None:
            c = sqlite3.connect(self._path, check_same_thread=False)
            c.row_factory = sqlite3.Row
            c.execute("PRAGMA journal_mode=WAL")
            c.execute("PRAGMA synchronous=NORMAL")
            c.execute("PRAGMA busy_timeout=5000")
            self._local.conn = c
        return c

    def _init_schema(self) -> None:
        c = self._conn()
        c.executescript(
            """
            CREATE TABLE IF NOT EXISTS schema_version (
                version INTEGER PRIMARY KEY, applied_at REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS entities (
                entity_id   TEXT PRIMARY KEY,
                kind        TEXT NOT NULL,
                name        TEXT NOT NULL,
                state       TEXT NOT NULL DEFAULT '{}',
                attributes  TEXT NOT NULL DEFAULT '{}',
                confidence  REAL NOT NULL DEFAULT 1.0,
                created_at  REAL NOT NULL,
                updated_at  REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS relationships (
                source_id TEXT NOT NULL,
                target_id TEXT NOT NULL,
                kind      TEXT NOT NULL,
                weight    REAL NOT NULL DEFAULT 1.0,
                metadata  TEXT NOT NULL DEFAULT '{}',
                PRIMARY KEY (source_id, target_id, kind)
            );
            CREATE INDEX IF NOT EXISTS idx_entities_kind ON entities(kind);
            """
        )
        if c.execute("SELECT MAX(version) FROM schema_version").fetchone()[0] is None:
            c.execute("INSERT INTO schema_version (version, applied_at) VALUES (?, ?)",
                      (_SCHEMA_VERSION, time.time()))
        c.commit()

    # ── entities ───────────────────────────────────────────────────────────────
    def update_entity(self, entity: WorldEntity) -> str:
        entity.touch()
        c = self._conn()
        c.execute(
            """INSERT INTO entities
               (entity_id, kind, name, state, attributes, confidence, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(entity_id) DO UPDATE SET
                 kind=excluded.kind, name=excluded.name, state=excluded.state,
                 attributes=excluded.attributes, confidence=excluded.confidence,
                 updated_at=excluded.updated_at""",
            (entity.entity_id, entity.kind, entity.name, json.dumps(entity.state),
             json.dumps(entity.attributes), entity.confidence,
             entity.created_at or time.time(), entity.updated_at),
        )
        c.commit()
        return entity.entity_id

    def observe(self, kind: str, name: str, state: Optional[dict] = None,
                attributes: Optional[dict] = None, confidence: float = 1.0) -> WorldEntity:
        """Record/refresh an observation about a thing. Merges into existing state
        rather than clobbering it, so partial updates accumulate."""
        existing = self.get_entity(f"{kind}:{name}")
        if existing is not None:
            if state:
                existing.state.update(state)
            if attributes:
                existing.attributes.update(attributes)
            existing.confidence = confidence
            self.update_entity(existing)
            self._observations += 1
            return existing
        ent = new_entity(kind, name, state=state, attributes=attributes, confidence=confidence)
        self.update_entity(ent)
        self._observations += 1
        return ent

    def get_entity(self, entity_id: str) -> Optional[WorldEntity]:
        r = self._conn().execute(
            "SELECT * FROM entities WHERE entity_id=?", (entity_id,)).fetchone()
        return self._row_to_entity(r) if r else None

    def remove_entity(self, entity_id: str) -> None:
        c = self._conn()
        c.execute("DELETE FROM entities WHERE entity_id=?", (entity_id,))
        c.execute("DELETE FROM relationships WHERE source_id=? OR target_id=?",
                  (entity_id, entity_id))
        c.commit()

    def entities_by_kind(self, kind: str) -> list[WorldEntity]:
        rows = self._conn().execute(
            "SELECT * FROM entities WHERE kind=? ORDER BY updated_at DESC", (kind,)).fetchall()
        return [self._row_to_entity(r) for r in rows]

    def all_entities(self) -> list[WorldEntity]:
        rows = self._conn().execute("SELECT * FROM entities ORDER BY kind, name").fetchall()
        return [self._row_to_entity(r) for r in rows]

    # ── relationships ──────────────────────────────────────────────────────────
    def add_relationship(self, rel: WorldRelationship) -> None:
        c = self._conn()
        c.execute(
            """INSERT INTO relationships (source_id, target_id, kind, weight, metadata)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(source_id, target_id, kind) DO UPDATE SET
                 weight=excluded.weight, metadata=excluded.metadata""",
            (rel.source_id, rel.target_id, rel.kind, rel.weight, json.dumps(rel.metadata)),
        )
        c.commit()

    def relationships_for(self, entity_id: str) -> list[WorldRelationship]:
        rows = self._conn().execute(
            "SELECT * FROM relationships WHERE source_id=? OR target_id=?",
            (entity_id, entity_id)).fetchall()
        return [self._row_to_rel(r) for r in rows]

    def all_relationships(self) -> list[WorldRelationship]:
        rows = self._conn().execute("SELECT * FROM relationships").fetchall()
        return [self._row_to_rel(r) for r in rows]

    # ── snapshots ──────────────────────────────────────────────────────────────
    def snapshot(self, label: str = "") -> WorldSnapshot:
        entities = {e.entity_id: e.to_dict() for e in self.all_entities()}
        rels = [r.to_dict() for r in self.all_relationships()]
        return new_snapshot(entities, rels, label=label)

    def compare(self, before: WorldSnapshot, after: Optional[WorldSnapshot] = None) -> dict:
        """Diff two snapshots; if `after` is omitted, diff `before` against now."""
        after = after or self.snapshot()
        return diff_snapshots(before, after)

    def restore(self, snapshot: WorldSnapshot) -> int:
        """Replace current entities with those in `snapshot`. Returns count restored."""
        c = self._conn()
        c.execute("DELETE FROM entities")
        c.execute("DELETE FROM relationships")
        c.commit()
        for d in snapshot.entities.values():
            self.update_entity(WorldEntity.from_dict(d))
        for rd in snapshot.relationships:
            self.add_relationship(WorldRelationship.from_dict(rd))
        return len(snapshot.entities)

    # ── diagnostics ────────────────────────────────────────────────────────────
    def counts(self) -> dict:
        c = self._conn()
        ents = c.execute("SELECT COUNT(*) FROM entities").fetchone()[0]
        rels = c.execute("SELECT COUNT(*) FROM relationships").fetchone()[0]
        by_kind = {k: n for k, n in c.execute(
            "SELECT kind, COUNT(*) FROM entities GROUP BY kind")}
        return {"entities": ents, "relationships": rels, "by_kind": by_kind}

    def health(self) -> dict:
        c = self.counts()
        return {"status": "ok", "entities": c["entities"],
                "relationships": c["relationships"], "observations": self._observations}

    def close(self) -> None:
        conn = getattr(self._local, "conn", None)
        if conn is not None:
            conn.close()
            self._local.conn = None

    # ── helpers ────────────────────────────────────────────────────────────────
    @staticmethod
    def _row_to_entity(r: sqlite3.Row) -> WorldEntity:
        return WorldEntity(
            entity_id=r["entity_id"], kind=r["kind"], name=r["name"],
            state=_loads(r["state"], {}), attributes=_loads(r["attributes"], {}),
            confidence=r["confidence"], created_at=r["created_at"], updated_at=r["updated_at"],
        )

    @staticmethod
    def _row_to_rel(r: sqlite3.Row) -> WorldRelationship:
        return WorldRelationship(
            source_id=r["source_id"], target_id=r["target_id"], kind=r["kind"],
            weight=r["weight"], metadata=_loads(r["metadata"], {}),
        )


def _loads(text, default):
    try:
        return json.loads(text)
    except (TypeError, ValueError):
        return default
