"""
core/perception/hub/config.py — FRIDAY V3 (M17)
Configuration for the Multimodal Perception Hub. Typed, serializable, injectable — no
tunable is hardcoded elsewhere. Mirrors the milestone's YAML surface:

    perception:
      enabled: true
      fusion: true
      reasoning: true
      timeline: true
      confidence_engine: true
      minimum_confidence: 0.70
      store_unified_events: true

`from_dict` is tolerant (flat `perception:` block or nested sections; unknown keys
ignored). No I/O, no hardcoded paths. Side-effect-free to import.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Optional


@dataclass
class FusionConfig:
    window_s: float = 1.5               # modality observations within this window co-fuse
    by_location: bool = True            # fuse per room/location
    max_sources_per_event: int = 32


@dataclass
class ConfidenceConfig:
    agreement_boost: float = 0.15       # boost when independent sensors agree
    conflict_penalty: float = 0.25      # penalty when sensors conflict
    min_sources_for_boost: int = 2


@dataclass
class TimelineConfig:
    capacity: int = 5000                # bounded in-memory ring (long sessions, low memory)
    recent_window_s: float = 60.0


@dataclass
class PerceptionHubConfig:
    enabled: bool = True
    fusion: bool = True
    reasoning: bool = True
    timeline: bool = True
    confidence_engine: bool = True
    minimum_confidence: float = 0.70
    store_unified_events: bool = True
    session_id: str = ""
    fusion_cfg: FusionConfig = field(default_factory=FusionConfig)
    confidence_cfg: ConfidenceConfig = field(default_factory=ConfidenceConfig)
    timeline_cfg: TimelineConfig = field(default_factory=TimelineConfig)

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(d: Optional[dict]) -> "PerceptionHubConfig":
        d = dict(d or {})
        if "perception" in d and isinstance(d["perception"], dict):
            d = d["perception"]
        cfg = PerceptionHubConfig()
        for k in ("enabled", "fusion", "reasoning", "timeline", "confidence_engine",
                  "minimum_confidence", "store_unified_events", "session_id"):
            if k in d:
                setattr(cfg, k, d[k])
        for section, attr, klass in (("fusion_cfg", "fusion_cfg", FusionConfig),
                                     ("confidence_cfg", "confidence_cfg", ConfidenceConfig),
                                     ("timeline_cfg", "timeline_cfg", TimelineConfig)):
            sub = d.get(section)
            if isinstance(sub, dict):
                current = asdict(getattr(cfg, attr))
                current.update({k: v for k, v in sub.items() if k in current})
                setattr(cfg, attr, klass(**current))
        return cfg
