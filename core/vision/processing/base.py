"""
core/vision/processing/base.py — FRIDAY 6.1 (M14)
The vision-processing plugin contract. A `VisionProcessor` turns one `Frame` into a
`ProcessorResult` (labelled detections + structured data). Every processor is an
independent plugin: it declares the backends it needs, reports whether it is
``available``, and — crucially — NEVER raises. A faulty or missing-backend processor
degrades to an error/unavailable result so a single processor can never crash the
pipeline, the transport, or the Cognitive Core.

Processors perform perception only. They do not build Observations, resolve entities,
or touch the World Model — those are downstream stages.
"""

from __future__ import annotations

import importlib.util
import logging
import time
from dataclasses import dataclass, field
from typing import Optional

import numpy as np

from ..transport.frame import Frame

log = logging.getLogger("friday.vision.processing")


# ── geometry ────────────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class BoundingBox:
    """Axis-aligned box in absolute pixels (origin top-left)."""
    x: int
    y: int
    w: int
    h: int

    @property
    def area(self) -> int:
        return max(0, self.w) * max(0, self.h)

    @property
    def center(self) -> tuple[float, float]:
        return (self.x + self.w / 2.0, self.y + self.h / 2.0)

    def normalized(self, width: int, height: int) -> tuple[float, float, float, float]:
        if width <= 0 or height <= 0:
            return (0.0, 0.0, 0.0, 0.0)
        return (self.x / width, self.y / height, self.w / width, self.h / height)

    def iou(self, other: "BoundingBox") -> float:
        ax2, ay2 = self.x + self.w, self.y + self.h
        bx2, by2 = other.x + other.w, other.y + other.h
        ix1, iy1 = max(self.x, other.x), max(self.y, other.y)
        ix2, iy2 = min(ax2, bx2), min(ay2, by2)
        iw, ih = max(0, ix2 - ix1), max(0, iy2 - iy1)
        inter = iw * ih
        union = self.area + other.area - inter
        return inter / union if union > 0 else 0.0

    def to_dict(self) -> dict:
        return {"x": self.x, "y": self.y, "w": self.w, "h": self.h}


@dataclass
class Detection:
    """One thing a processor noticed in a frame. `kind`/`label` feed entity candidates
    downstream; `track_id` (assigned by the tracker) gives temporal identity."""
    label: str
    confidence: float = 0.5
    kind: str = "object"                      # entity kind hint for resolution
    bbox: Optional[BoundingBox] = None
    track_id: Optional[str] = None
    attributes: dict = field(default_factory=dict)
    processor: str = ""

    def to_dict(self, *, width: int = 0, height: int = 0) -> dict:
        d = {"label": self.label, "confidence": round(float(self.confidence), 4),
             "kind": self.kind, "track_id": self.track_id,
             "attributes": self.attributes, "processor": self.processor}
        if self.bbox is not None:
            d["bbox"] = self.bbox.to_dict()
            if width and height:
                nx, ny, nw, nh = self.bbox.normalized(width, height)
                d["bbox_norm"] = {"x": round(nx, 4), "y": round(ny, 4),
                                  "w": round(nw, 4), "h": round(nh, 4)}
        return d


@dataclass
class ProcessorResult:
    """The output of one processor for one frame."""
    processor: str
    available: bool = True
    detections: list = field(default_factory=list)   # list[Detection]
    data: dict = field(default_factory=dict)          # structured non-detection output
    duration_ms: float = 0.0
    error: Optional[str] = None

    @property
    def ok(self) -> bool:
        return self.error is None and self.available

    def to_dict(self, *, width: int = 0, height: int = 0) -> dict:
        return {"processor": self.processor, "available": self.available,
                "duration_ms": round(self.duration_ms, 3), "error": self.error,
                "detections": [d.to_dict(width=width, height=height) for d in self.detections],
                "data": self.data}


@dataclass
class ProcessingResult:
    """All processor outputs for one frame — the unit the Observation Builder consumes."""
    frame_id: str
    camera_id: str
    frame_number: int
    width: int
    height: int
    timestamp: float
    results: list = field(default_factory=list)       # list[ProcessorResult]
    total_ms: float = 0.0

    def detections(self) -> list:
        out: list = []
        for r in self.results:
            if r.ok:
                out.extend(r.detections)
        return out

    def by_processor(self, name: str) -> Optional[ProcessorResult]:
        for r in self.results:
            if r.processor == name:
                return r
        return None

    def data_for(self, name: str) -> dict:
        r = self.by_processor(name)
        return r.data if r is not None else {}

    def to_dict(self) -> dict:
        return {"frame_id": self.frame_id, "camera_id": self.camera_id,
                "frame_number": self.frame_number, "width": self.width,
                "height": self.height, "timestamp": self.timestamp,
                "total_ms": round(self.total_ms, 3),
                "detection_count": len(self.detections()),
                "results": [r.to_dict(width=self.width, height=self.height)
                            for r in self.results]}


# ── processor base ──────────────────────────────────────────────────────────────────
class VisionProcessor:
    """Base class for all vision processors. Subclasses implement `analyze(frame)`
    returning ``(detections, data)``; the public `process()` wrapper adds timing,
    availability gating, and a hard never-raises guarantee."""

    name: str = "processor"
    kind: str = "generic"
    requires: tuple = ()                      # importable module names this processor needs

    def __init__(self) -> None:
        self._runs = 0
        self._errors = 0
        self._total_ms = 0.0
        self._available_cache: Optional[bool] = None

    # ── availability ─────────────────────────────────────────────────────────────
    def available(self) -> bool:
        """True iff every required backend can be imported. Cached (deps don't appear
        mid-run). Subclasses may override for model-file checks."""
        if self._available_cache is None:
            self._available_cache = all(
                importlib.util.find_spec(m) is not None for m in self.requires)
        return self._available_cache

    def warmup(self) -> None:
        """Optionally pre-load models off the hot path. Default: no-op."""

    # ── public entry (never raises) ──────────────────────────────────────────────
    def process(self, frame: Frame) -> ProcessorResult:
        if not self.available():
            return ProcessorResult(self.name, available=False,
                                   error="backend unavailable: " + ",".join(self.requires))
        if frame is None or frame.data is None:
            return ProcessorResult(self.name, error="no frame data")
        t0 = time.perf_counter()
        try:
            detections, data = self.analyze(frame)
            dt = (time.perf_counter() - t0) * 1000.0
            self._runs += 1
            self._total_ms += dt
            for d in detections:
                if not d.processor:
                    d.processor = self.name
            return ProcessorResult(self.name, detections=list(detections),
                                   data=dict(data or {}), duration_ms=dt)
        except Exception as e:  # noqa: BLE001 — a processor must never crash the pipeline
            self._errors += 1
            dt = (time.perf_counter() - t0) * 1000.0
            log.debug("processor %s failed", self.name, exc_info=True)
            return ProcessorResult(self.name, duration_ms=dt, error=f"{type(e).__name__}: {e}")

    # ── subclass hook ─────────────────────────────────────────────────────────────
    def analyze(self, frame: Frame) -> tuple[list, dict]:  # pragma: no cover - overridden
        raise NotImplementedError

    # ── observability ─────────────────────────────────────────────────────────────
    def metrics(self) -> dict:
        avg = (self._total_ms / self._runs) if self._runs else 0.0
        return {"processor": self.name, "kind": self.kind, "runs": self._runs,
                "errors": self._errors, "avg_ms": round(avg, 3),
                "available": self.available()}


# ── shared helpers ──────────────────────────────────────────────────────────────────
def to_gray(image: np.ndarray) -> np.ndarray:
    """BGR/RGB → 2-D float32 luminance without requiring cv2."""
    arr = np.asarray(image)
    if arr.ndim == 2:
        return arr.astype(np.float32)
    return arr[:, :, :3].astype(np.float32).mean(axis=2)


def downscale(image: np.ndarray, size: int) -> np.ndarray:
    """Nearest-neighbour downscale of a 2-D array to (size, size). Pure numpy so the
    transport core never depends on cv2 for the always-available processors."""
    arr = np.asarray(image)
    h, w = arr.shape[:2]
    if h == 0 or w == 0:
        return arr
    ys = np.linspace(0, h - 1, num=min(size, h)).astype(int)
    xs = np.linspace(0, w - 1, num=min(size, w)).astype(int)
    return arr[np.ix_(ys, xs)]
