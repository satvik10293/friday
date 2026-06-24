"""
core/perception/models.py — FRIDAY 4.0 (M6)
Perception primitives. An Observation is one thing a sensor noticed about reality
at a point in time. These are pure, serializable data structures — no I/O — so the
whole perception pipeline is trivially testable and survives a round-trip to SQLite.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Union


class ObservationType(str, Enum):
    SYSTEM = "system"
    SCREEN = "screen"
    VISION = "vision"
    AUDIO = "audio"
    USER_ACTIVITY = "user_activity"
    FILESYSTEM = "filesystem"
    NETWORK = "network"
    APPLICATION = "application"
    TIME = "time"
    CUSTOM = "custom"


class ObservationConfidence:
    """Named confidence bands + helpers. Confidence is always stored as a float in
    [0, 1]; these constants and `level()` keep callers/readouts consistent."""
    UNKNOWN = 0.0
    LOW = 0.25
    MEDIUM = 0.5
    HIGH = 0.8
    CERTAIN = 1.0

    @staticmethod
    def clamp(x: float) -> float:
        return max(0.0, min(1.0, float(x)))

    @staticmethod
    def level(score: float) -> str:
        s = ObservationConfidence.clamp(score)
        if s >= 0.8:
            return "high"
        if s >= 0.5:
            return "medium"
        if s >= 0.25:
            return "low"
        return "unknown"


@dataclass
class ObservationSource:
    name: str
    kind: str = "sensor"
    version: str = "1.0.0"

    def to_dict(self) -> dict:
        return dict(self.__dict__)

    @staticmethod
    def from_dict(d) -> "ObservationSource":
        if isinstance(d, str):
            return ObservationSource(name=d)
        return ObservationSource(name=d.get("name", "?"), kind=d.get("kind", "sensor"),
                                 version=d.get("version", "1.0.0"))


@dataclass
class Observation:
    id: str
    timestamp: float
    source: ObservationSource
    type: ObservationType
    confidence: float = 0.5
    payload: dict = field(default_factory=dict)
    metadata: dict = field(default_factory=dict)

    # ── identity ───────────────────────────────────────────────────────────────
    def subject(self) -> str:
        """The logical thing this observation is *about* (used for dedup/merge).
        Sensors may pin it via metadata['subject']; otherwise it's type:source."""
        return self.metadata.get("subject") or f"{self.type.value}:{self.source.name}"

    def value_signature(self) -> str:
        """A stable string of the payload values — two observations of the same
        subject with equal signatures are duplicates; differing ones are changes."""
        return repr(sorted((str(k), str(v)) for k, v in self.payload.items()))

    # ── serialization ──────────────────────────────────────────────────────────
    def to_dict(self) -> dict:
        return {
            "id": self.id, "timestamp": self.timestamp,
            "source": self.source.to_dict(), "type": self.type.value,
            "confidence": self.confidence, "payload": self.payload, "metadata": self.metadata,
        }

    @staticmethod
    def from_dict(d: dict) -> "Observation":
        return Observation(
            id=d["id"], timestamp=d["timestamp"],
            source=ObservationSource.from_dict(d["source"]),
            type=ObservationType(d["type"]), confidence=d.get("confidence", 0.5),
            payload=dict(d.get("payload") or {}), metadata=dict(d.get("metadata") or {}),
        )

    def attention_dict(self, novelty: float = 0.5, goal_relevance: float = 0.0) -> dict:
        """Project this observation into the shape M5 AttentionSystem.rank_observations
        consumes (importance/priority/recency/urgency)."""
        impact = ObservationConfidence.clamp(self.metadata.get("impact", 0.5))
        return {
            "id": self.id,
            "name": self.subject(),
            "ts": self.timestamp,
            "importance": ObservationConfidence.clamp(0.5 * self.confidence + 0.5 * novelty),
            "priority": ObservationConfidence.clamp(goal_relevance),
            "urgency": impact,
        }


@dataclass
class ObservationBatch:
    observations: list = field(default_factory=list)
    sensor: str = ""
    timestamp: float = field(default_factory=time.time)

    def add(self, obs: Observation) -> None:
        self.observations.append(obs)

    def by_type(self, t: ObservationType) -> list:
        return [o for o in self.observations if o.type == t]

    def __len__(self) -> int:
        return len(self.observations)

    def __iter__(self):
        return iter(self.observations)

    def to_dict(self) -> dict:
        return {"sensor": self.sensor, "timestamp": self.timestamp,
                "observations": [o.to_dict() for o in self.observations]}


def new_observation(type: ObservationType, source: Union[str, ObservationSource],
                    payload: Optional[dict] = None, *, confidence: float = 0.5,
                    metadata: Optional[dict] = None,
                    timestamp: Optional[float] = None) -> Observation:
    src = source if isinstance(source, ObservationSource) else ObservationSource(name=str(source))
    return Observation(
        id=uuid.uuid4().hex[:12],
        timestamp=timestamp if timestamp is not None else time.time(),
        source=src, type=type, confidence=ObservationConfidence.clamp(confidence),
        payload=dict(payload or {}), metadata=dict(metadata or {}),
    )
