"""
core/spatial/config.py — FRIDAY V3 (M16)
Configuration for Spatial Cognition. Typed, serializable, injectable — nothing in the
subsystem hardcodes a value. Mirrors the milestone's YAML surface:

    spatial:
      enabled: true
      tracking: true
      scene_graph: true
      relationship_reasoning: true
      remember_locations: true
      camera_timeout: 5
      confidence_threshold: 0.70
      object_timeout: 120

`from_dict` is tolerant (flat `spatial:` block or nested sections; unknown keys ignored).
No I/O, no hardcoded paths (the DB path resolves to the project root unless overridden).
Side-effect-free to import.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional

_ROOT = Path(__file__).resolve().parents[2]


@dataclass
class TrackerConfig:
    match_distance: float = 0.18        # normalized centre distance to match same object
    match_iou: float = 0.2              # bbox IoU that also confirms a match
    lost_after_s: float = 5.0           # unseen → LOST (camera_timeout-aligned)
    forget_after_s: float = 120.0       # LOST longer than this → REMOVED (object_timeout)
    min_confidence: float = 0.70        # below this a detection is ignored


@dataclass
class RelationshipConfig:
    enabled: bool = True
    near_fraction: float = 0.15         # centre distance (norm) below which two are "near"
    touch_iou: float = 0.12             # IoU above which two are "touching"
    on_overlap: float = 0.30            # horizontal overlap to infer "on/under"


@dataclass
class RoomConfig:
    default_room: str = "unknown"       # never a hardcoded real room name
    camera_rooms: dict = field(default_factory=dict)   # camera_id -> room (configurable)


@dataclass
class LocalizationConfig:
    enabled: bool = True
    idle_after_s: float = 60.0          # no activity → idle
    away_after_s: float = 300.0         # no presence → unavailable
    desk_objects: list = field(default_factory=lambda: ["keyboard", "mouse", "laptop", "monitor"])


@dataclass
class SpatialMemoryConfig:
    remember_locations: bool = True
    db_path: Optional[str] = None       # default: data/spatial.db
    persistent: bool = True
    significance_threshold: float = 0.7
    max_movement_history: int = 200
    dedup_window_s: float = 2.0         # suppress redundant identical events within this


@dataclass
class SpatialConfig:
    enabled: bool = True
    tracking: bool = True
    scene_graph: bool = True
    relationship_reasoning: bool = True
    camera_timeout: float = 5.0
    confidence_threshold: float = 0.70
    object_timeout: float = 120.0
    session_id: str = ""
    tracker: TrackerConfig = field(default_factory=TrackerConfig)
    relationships: RelationshipConfig = field(default_factory=RelationshipConfig)
    rooms: RoomConfig = field(default_factory=RoomConfig)
    localization: LocalizationConfig = field(default_factory=LocalizationConfig)
    memory: SpatialMemoryConfig = field(default_factory=SpatialMemoryConfig)

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(d: Optional[dict]) -> "SpatialConfig":
        d = dict(d or {})
        # a "spatial:" wrapper is accepted as well as a bare dict
        if "spatial" in d and isinstance(d["spatial"], dict):
            d = d["spatial"]
        cfg = SpatialConfig()
        for k in ("enabled", "tracking", "scene_graph", "relationship_reasoning",
                  "camera_timeout", "confidence_threshold", "object_timeout", "session_id"):
            if k in d:
                setattr(cfg, k, d[k])
        if "remember_locations" in d:
            cfg.memory.remember_locations = bool(d["remember_locations"])
        # keep the propagated thresholds in sync
        cfg.tracker.min_confidence = cfg.confidence_threshold
        cfg.tracker.lost_after_s = float(d.get("camera_timeout", cfg.camera_timeout))
        cfg.tracker.forget_after_s = float(d.get("object_timeout", cfg.object_timeout))
        for section, klass in (("tracker", TrackerConfig), ("relationships", RelationshipConfig),
                               ("rooms", RoomConfig), ("localization", LocalizationConfig),
                               ("memory", SpatialMemoryConfig)):
            sub = d.get(section)
            if isinstance(sub, dict):
                current = asdict(getattr(cfg, section))
                current.update({k: v for k, v in sub.items() if k in current})
                setattr(cfg, section, klass(**current))
        return cfg

    def spatial_db_path(self) -> str:
        return self.memory.db_path or str(_ROOT / "data" / "spatial.db")
