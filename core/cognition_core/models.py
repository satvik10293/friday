"""
core/cognition_core/models.py — FRIDAY 6.0 (M13)
Pure data models for the Persistent Entity & Belief Foundation. No I/O.

Entities have an **opaque, permanent stable id** (ENT_000001) decoupled from any
name — identity persists independently of labels. Beliefs are first-class, evolving
cognitive objects carrying supporting *and* contradicting evidence, confidence, and
provenance. These types are the substrate the rest of the cognitive OS references.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


def now() -> float:
    return time.time()


def new_belief_id() -> str:
    return "BEL_" + uuid.uuid4().hex[:12]


class BeliefStatus(str, Enum):
    ACTIVE = "active"
    SUPERSEDED = "superseded"
    RETRACTED = "retracted"


class ResolveMethod(str, Enum):
    EXACT = "exact"
    ALIAS = "alias"
    NORMALIZED = "normalized"
    SIMILARITY = "similarity"
    CREATED = "created"


# ── entity ────────────────────────────────────────────────────────────────────────
@dataclass
class Entity:
    """A real-world thing with a permanent identity. `stable_id` never changes;
    `primary_label`/`labels` are human-readable metadata that may evolve."""
    stable_id: str
    kind: str
    primary_label: str
    labels: list = field(default_factory=list)        # all human-readable names seen
    attributes: dict = field(default_factory=dict)    # stable facts
    confidence: float = 1.0
    created_at: float = field(default_factory=now)
    updated_at: float = field(default_factory=now)
    merged_from: list = field(default_factory=list)   # stable_ids merged into this one

    def add_label(self, label: str) -> None:
        if label and label not in self.labels:
            self.labels.append(label)

    def touch(self) -> None:
        self.updated_at = now()

    def to_dict(self) -> dict:
        return dict(self.__dict__)

    @staticmethod
    def from_dict(d: dict) -> "Entity":
        return Entity(
            stable_id=d["stable_id"], kind=d["kind"], primary_label=d["primary_label"],
            labels=list(d.get("labels") or []), attributes=dict(d.get("attributes") or {}),
            confidence=d.get("confidence", 1.0),
            created_at=d.get("created_at", 0.0), updated_at=d.get("updated_at", 0.0),
            merged_from=list(d.get("merged_from") or []))


@dataclass
class ResolveResult:
    stable_id: str
    created: bool
    method: str                # ResolveMethod value
    score: float
    entity: Optional[Entity] = None

    def to_dict(self) -> dict:
        d = dict(self.__dict__)
        d["entity"] = self.entity.to_dict() if self.entity else None
        return d


# ── belief ────────────────────────────────────────────────────────────────────────
@dataclass
class Evidence:
    source: str
    detail: str = ""
    weight: float = 1.0
    timestamp: float = field(default_factory=now)

    def to_dict(self) -> dict:
        return dict(self.__dict__)

    @staticmethod
    def from_dict(d: dict) -> "Evidence":
        return Evidence(source=d.get("source", ""), detail=d.get("detail", ""),
                        weight=d.get("weight", 1.0), timestamp=d.get("timestamp", 0.0))


@dataclass
class Belief:
    """An evolving claim about a subject. Never an immutable fact: it accumulates
    evidence, its confidence is recomputed, and it can be revised, superseded, or
    retracted — always with provenance."""
    subject: str                                       # stable entity id (or any subject)
    predicate: str
    value: Any
    confidence: float = 0.5
    supporting_evidence: list = field(default_factory=list)     # list[Evidence]
    contradicting_evidence: list = field(default_factory=list)  # list[Evidence]
    source: str = "system"
    timestamp: float = field(default_factory=now)      # first asserted
    last_verification: float = field(default_factory=now)
    status: str = BeliefStatus.ACTIVE.value
    belief_id: str = field(default_factory=new_belief_id)
    updated_at: float = field(default_factory=now)

    @property
    def key(self) -> tuple:
        return (self.subject, self.predicate)

    def to_dict(self) -> dict:
        d = dict(self.__dict__)
        d["supporting_evidence"] = [e.to_dict() for e in self.supporting_evidence]
        d["contradicting_evidence"] = [e.to_dict() for e in self.contradicting_evidence]
        return d

    @staticmethod
    def from_dict(d: dict) -> "Belief":
        b = Belief(subject=d["subject"], predicate=d["predicate"], value=d.get("value"),
                   confidence=d.get("confidence", 0.5), source=d.get("source", "system"),
                   timestamp=d.get("timestamp", 0.0),
                   last_verification=d.get("last_verification", 0.0),
                   status=d.get("status", BeliefStatus.ACTIVE.value),
                   belief_id=d.get("belief_id") or new_belief_id(),
                   updated_at=d.get("updated_at", 0.0))
        b.supporting_evidence = [Evidence.from_dict(e) for e in d.get("supporting_evidence", [])]
        b.contradicting_evidence = [Evidence.from_dict(e) for e in d.get("contradicting_evidence", [])]
        return b


# ── self model ────────────────────────────────────────────────────────────────────
@dataclass
class SelfModelSnapshot:
    """FRIDAY's live model of herself, aggregated from existing subsystems."""
    active_goals: list = field(default_factory=list)
    current_task: str = ""
    current_plan: Optional[str] = None
    sensors: list = field(default_factory=list)
    active_agents: int = 0
    compute: dict = field(default_factory=dict)        # cpu/ram/etc.
    workload: dict = field(default_factory=dict)       # queued/active counts
    confidence: float = 1.0
    limitations: list = field(default_factory=list)
    ts: float = field(default_factory=now)

    def to_dict(self) -> dict:
        return dict(self.__dict__)
