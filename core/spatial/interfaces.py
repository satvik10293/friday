"""
core/spatial/interfaces.py — FRIDAY V3 (M16)
The internal contracts of the spatial subsystem. The most important is
`SpatialObservation` — the stable, source-agnostic input the engine consumes. Vision,
audio, or any future sensor produces these (via their services); the spatial engine never
imports a sensor's internals, it only depends on this shape.

Also defines small Protocols (`RelationshipInferencer`, `RoomClassifier`,
`UserStateEstimator`) so those strategies are dependency-injected and individually
mockable/replaceable (e.g. a learned room classifier via the PluginService).
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Optional, Protocol, runtime_checkable


@dataclass
class SpatialObservation:
    """One thing a sensor reports about the environment, in a source-agnostic shape.
    `position` is normalized (0..1) image/world coordinates; `bbox` is optional
    normalized (x, y, w, h)."""
    object_class: str
    label: str = ""
    confidence: float = 1.0
    position: dict = field(default_factory=dict)       # {"x":.., "y":.., "z":..?}
    bbox: Optional[dict] = None                        # {"x","y","w","h"} normalized
    camera_id: str = ""
    room: Optional[str] = None
    track_id: Optional[str] = None                     # sensor-local id (e.g. vision track)
    stable_id: Optional[str] = None                    # permanent entity id if already resolved
    source: str = "vision"
    timestamp: float = field(default_factory=time.time)
    attributes: dict = field(default_factory=dict)

    @property
    def center(self) -> tuple:
        if self.bbox:
            return (self.bbox.get("x", 0.0) + self.bbox.get("w", 0.0) / 2.0,
                    self.bbox.get("y", 0.0) + self.bbox.get("h", 0.0) / 2.0)
        return (float(self.position.get("x", 0.0)), float(self.position.get("y", 0.0)))

    def to_dict(self) -> dict:
        return {"object_class": self.object_class, "label": self.label or self.object_class,
                "confidence": round(float(self.confidence), 4), "position": self.position,
                "bbox": self.bbox, "camera_id": self.camera_id, "room": self.room,
                "track_id": self.track_id, "stable_id": self.stable_id, "source": self.source,
                "timestamp": self.timestamp, "attributes": self.attributes}

    @staticmethod
    def from_dict(d: dict) -> "SpatialObservation":
        return SpatialObservation(
            object_class=d.get("object_class") or d.get("kind") or d.get("label") or "object",
            label=d.get("label", ""), confidence=float(d.get("confidence", 1.0)),
            position=dict(d.get("position") or {}), bbox=d.get("bbox"),
            camera_id=d.get("camera_id", ""), room=d.get("room"),
            track_id=d.get("track_id"), stable_id=d.get("stable_id"),
            source=d.get("source", "vision"),
            timestamp=float(d.get("timestamp") or time.time()),
            attributes=dict(d.get("attributes") or {}))


@runtime_checkable
class RelationshipInferencer(Protocol):
    def infer(self, nodes: list) -> list: ...          # -> list[relationship dicts]


@runtime_checkable
class RoomClassifier(Protocol):
    def room_for(self, *, camera_id: str = "", observation=None) -> str: ...


@runtime_checkable
class UserStateEstimator(Protocol):
    def estimate(self, *, observations: list, audio_events: list, now: float) -> dict: ...
