"""
core/world/entities.py — FRIDAY 4.0 (M5)
World-model primitives. An internal model of reality is a graph of typed
entities (user, project, runtime, system, …) and weighted relationships between
them. These are pure, serializable data structures — no I/O.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class WorldEntity:
    """A single tracked thing in FRIDAY's model of the world."""
    entity_id: str
    kind: str                              # "user" | "project" | "runtime" | "system" | ...
    name: str
    state: dict = field(default_factory=dict)        # mutable facts ("focus", "mood", "cpu")
    attributes: dict = field(default_factory=dict)   # stable facts ("os", "owner")
    confidence: float = 1.0
    created_at: float = 0.0
    updated_at: float = 0.0

    def touch(self) -> None:
        self.updated_at = time.time()

    def update_state(self, **changes) -> "WorldEntity":
        self.state.update(changes)
        self.touch()
        return self

    def to_dict(self) -> dict:
        return dict(self.__dict__)

    @staticmethod
    def from_dict(d: dict) -> "WorldEntity":
        return WorldEntity(
            entity_id=d["entity_id"], kind=d["kind"], name=d["name"],
            state=dict(d.get("state") or {}), attributes=dict(d.get("attributes") or {}),
            confidence=d.get("confidence", 1.0),
            created_at=d.get("created_at", 0.0), updated_at=d.get("updated_at", 0.0),
        )


@dataclass
class WorldRelationship:
    """A directed, weighted edge between two entities (e.g. user --owns--> project)."""
    source_id: str
    target_id: str
    kind: str
    weight: float = 1.0
    metadata: dict = field(default_factory=dict)

    @property
    def key(self) -> tuple:
        return (self.source_id, self.target_id, self.kind)

    def to_dict(self) -> dict:
        return dict(self.__dict__)

    @staticmethod
    def from_dict(d: dict) -> "WorldRelationship":
        return WorldRelationship(
            source_id=d["source_id"], target_id=d["target_id"], kind=d["kind"],
            weight=d.get("weight", 1.0), metadata=dict(d.get("metadata") or {}),
        )


def new_entity(kind: str, name: str, *, state: Optional[dict] = None,
               attributes: Optional[dict] = None, confidence: float = 1.0,
               entity_id: Optional[str] = None) -> WorldEntity:
    """Factory. The default id is deterministic (`kind:name`) so re-observing the
    same thing updates it in place rather than creating duplicates."""
    now = time.time()
    return WorldEntity(
        entity_id=entity_id or f"{kind}:{name}",
        kind=kind, name=name,
        state=dict(state or {}), attributes=dict(attributes or {}),
        confidence=max(0.0, min(1.0, confidence)),
        created_at=now, updated_at=now,
    )
