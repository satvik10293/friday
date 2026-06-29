"""
core/vision/config.py — FRIDAY 6.1 (M14)
Configuration + dependency-injection surface for the Vision System.

Every tunable in the vision pipeline lives here as a typed, serializable dataclass —
never hidden inside a module. `VisionConfig` is the single object the `VisionSystem`
facade reads; it is constructed from defaults, overridden from a dict (e.g. a slice of
``friday_config.json``), and injected. No I/O, no global state, side-effect-free.

The split mirrors the pipeline stages so each stage owns exactly its own knobs:
transport · processing · observation · scene · memory.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional

_ROOT = Path(__file__).resolve().parents[2]


# ── per-stage configuration ─────────────────────────────────────────────────────────
@dataclass
class TransportConfig:
    queue_size: int = 2                       # per-camera bounded queue depth
    target_fps: float = 10.0
    overflow: str = "drop_oldest"             # drop_oldest | drop_newest | block
    persistent_registry: bool = False         # True → data/vision.db keeps camera ids
    registry_path: Optional[str] = None


@dataclass
class ProcessingConfig:
    # The default pipeline is dependency-light (numpy + cv2 only) and always-available.
    # Model/heavy processors are opt-in and degrade gracefully when their backend or
    # model file is absent.
    enabled: list = field(default_factory=lambda: [
        "scene_stats", "motion", "segmentation", "tracking"])
    max_processing_fps: float = 8.0           # processing is throttled below transport fps
    workers: int = 2                          # processing thread pool (never transport threads)
    # motion
    motion_threshold: float = 0.04            # mean abs frame delta (0..1) to call it motion
    motion_downscale: int = 64                # work on a WxW gray thumbnail for speed
    motion_min_region: float = 0.01           # min region area (fraction of frame) to report
    # segmentation
    segmentation_grid: int = 8                # GxG grid for the lightweight segmenter
    segmentation_merge_tol: float = 18.0      # mean-color L1 distance to merge cells
    # object detection (optional)
    object_backend: str = "auto"             # auto | ultralytics | onnx | opencv_dnn | none
    object_model_path: Optional[str] = None
    object_labels_path: Optional[str] = None
    object_confidence: float = 0.35
    # tracking
    track_iou_threshold: float = 0.3
    track_max_age: int = 30                   # frames a track survives unmatched
    # heavy/optional
    ocr_languages: list = field(default_factory=lambda: ["en"])
    ocr_min_confidence: float = 0.4
    face_scale_factor: float = 1.1
    face_min_neighbors: int = 5
    pose_min_confidence: float = 0.5


@dataclass
class ObservationConfig:
    source_name: str = "vision"
    min_significance: float = 0.0             # drop frame-observations below this
    emit_per_detection: bool = True           # one observation per tracked object, plus a frame summary
    base_confidence: float = 0.6


@dataclass
class SceneConfig:
    near_fraction: float = 0.12               # centre distance (fraction of diagonal) → "near"
    overlap_relation: float = 0.15            # IoU above which two objects are "touching"
    forget_after_s: float = 30.0             # drop scene objects unseen this long


@dataclass
class VisualMemoryConfig:
    db_path: Optional[str] = None             # default: data/visual_memory.db
    significance_threshold: float = 0.55      # store observations at/above this
    max_object_history: int = 200             # sightings retained per object
    persistent: bool = True


@dataclass
class VisionConfig:
    transport: TransportConfig = field(default_factory=TransportConfig)
    processing: ProcessingConfig = field(default_factory=ProcessingConfig)
    observation: ObservationConfig = field(default_factory=ObservationConfig)
    scene: SceneConfig = field(default_factory=SceneConfig)
    memory: VisualMemoryConfig = field(default_factory=VisualMemoryConfig)

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(d: Optional[dict]) -> "VisionConfig":
        """Build a config from a (partial) dict; unknown keys are ignored, missing
        sections fall back to defaults. Tolerant by design — config is not a schema."""
        d = dict(d or {})
        cfg = VisionConfig()
        for section, klass in (("transport", TransportConfig),
                               ("processing", ProcessingConfig),
                               ("observation", ObservationConfig),
                               ("scene", SceneConfig),
                               ("memory", VisualMemoryConfig)):
            sub = d.get(section)
            if isinstance(sub, dict):
                current = asdict(getattr(cfg, section))
                current.update({k: v for k, v in sub.items() if k in current})
                setattr(cfg, section, klass(**current))
        return cfg

    def visual_memory_path(self) -> str:
        return self.memory.db_path or str(_ROOT / "data" / "visual_memory.db")
