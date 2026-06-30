"""
core/perception/hub/observations.py — FRIDAY V3 (M17)
The unified observation model. Two shapes:

  • `ModalityObservation` — a single-sensor report (vision/audio/spatial/runtime/memory),
    normalized into a common contract so the Hub never imports a sensor's internals.
  • `UnifiedObservation` — the fused, multimodal cognitive event the Hub produces: one
    thing FRIDAY understands, carrying every mandated field (timestamp, session, source
    modules, confidence, location, related objects/people, audio/spatial/previous context,
    importance, event category, reasoning conclusions).

Pure, serializable data — no I/O — so the whole pipeline is testable and survives a
round-trip to memory.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field


@dataclass
class ModalityObservation:
    """One sensor's normalized observation."""
    source: str                          # "vision" | "audio" | "spatial" | "runtime" | "memory"
    category: str                        # "object" | "sound" | "user_state" | "scene" | ...
    label: str = ""
    confidence: float = 1.0
    location: str = ""                   # room
    objects: list = field(default_factory=list)
    people: list = field(default_factory=list)
    timestamp: float = field(default_factory=time.time)
    data: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {"source": self.source, "category": self.category, "label": self.label,
                "confidence": round(float(self.confidence), 4), "location": self.location,
                "objects": self.objects, "people": self.people, "timestamp": self.timestamp,
                "data": self.data}

    @staticmethod
    def from_dict(d: dict) -> "ModalityObservation":
        return ModalityObservation(
            source=d.get("source", "unknown"), category=d.get("category", "generic"),
            label=d.get("label", ""), confidence=float(d.get("confidence", 1.0)),
            location=d.get("location") or d.get("room", ""),
            objects=list(d.get("objects") or []), people=list(d.get("people") or []),
            timestamp=float(d.get("timestamp") or time.time()), data=dict(d.get("data") or {}))


def new_observation_id() -> str:
    return "UOB_" + uuid.uuid4().hex[:12]


@dataclass
class UnifiedObservation:
    """One fused, multimodal cognitive event — the only thing the Hub forwards."""
    id: str = field(default_factory=new_observation_id)
    timestamp: float = field(default_factory=time.time)
    session_id: str = ""
    source_modules: list = field(default_factory=list)
    confidence: float = 0.0
    location: str = ""
    related_objects: list = field(default_factory=list)
    related_people: list = field(default_factory=list)
    audio_context: dict = field(default_factory=dict)
    spatial_context: dict = field(default_factory=dict)
    previous_context: dict = field(default_factory=dict)
    importance: float = 0.0
    event_category: str = "observation"
    conclusions: list = field(default_factory=list)       # reasoning outputs
    sources: list = field(default_factory=list)           # compact source modality dicts

    def subject(self) -> str:
        """A stable identity for dedup/compression: category @ location + sorted objects."""
        objs = ",".join(sorted(self.related_objects))
        return f"{self.event_category}:{self.location}:{objs}"

    def signature(self) -> str:
        """Value signature — two observations with the same subject + signature are
        semantically identical (used to compress repetitive events)."""
        people = ",".join(sorted(self.related_people))
        sounds = ",".join(sorted(self.audio_context.get("sounds", [])))
        return f"{people}|{sounds}|{self.spatial_context.get('user_state', '')}"

    def to_dict(self) -> dict:
        return {"id": self.id, "timestamp": self.timestamp, "session_id": self.session_id,
                "source_modules": self.source_modules, "confidence": round(self.confidence, 4),
                "location": self.location, "related_objects": self.related_objects,
                "related_people": self.related_people, "audio_context": self.audio_context,
                "spatial_context": self.spatial_context, "previous_context": self.previous_context,
                "importance": round(self.importance, 4), "event_category": self.event_category,
                "conclusions": self.conclusions, "sources": self.sources}
