"""
core/vision/processing/pipeline.py — FRIDAY 6.1 (M14)
The Vision Processing Pipeline. Runs an ordered set of independent processor plugins
over a single `Frame` and assembles their outputs into one `ProcessingResult`.

Design rules honoured here:
  • Modular: processors are plugins, assembled by name from config via the registry.
  • Isolated failure: each `processor.process()` is already never-raises; the pipeline
    adds a second guard so even assembly bugs can't crash a frame.
  • Off the transport thread: the pipeline is pure compute and is always invoked by the
    VisionSystem on its processing pool — never on a transport/socket worker.
  • Intra-frame sharing: detectors run before the tracker; the tracker reads the
    frame's accumulated detections from the Frame's reserved `ai_metadata` scratch
    channel (declared for exactly this kind of later-stage attachment).
"""

from __future__ import annotations

import logging
import time
from typing import Optional

from ..transport.frame import Frame
from .base import ProcessingResult, ProcessorResult, VisionProcessor

log = logging.getLogger("friday.vision.pipeline")

_SCRATCH_KEY = "_pipeline_detections"


class VisionPipeline:
    def __init__(self, processors: Optional[list] = None) -> None:
        self._processors: list[VisionProcessor] = list(processors or [])
        self._frames = 0
        self._total_ms = 0.0

    # ── assembly ─────────────────────────────────────────────────────────────────
    def add(self, processor: VisionProcessor) -> "VisionPipeline":
        self._processors.append(processor)
        return self

    def processors(self) -> list[VisionProcessor]:
        return list(self._processors)

    def names(self) -> list[str]:
        return [p.name for p in self._processors]

    def warmup(self) -> None:
        for p in self._processors:
            try:
                if p.available():
                    p.warmup()
            except Exception:  # noqa: BLE001
                log.debug("warmup failed for %s", p.name, exc_info=True)

    # ── run ──────────────────────────────────────────────────────────────────────
    def process(self, frame: Frame) -> ProcessingResult:
        t0 = time.perf_counter()
        results: list[ProcessorResult] = []
        accumulated: list = []
        # expose the running detection list so order-dependent processors (the tracker)
        # can consume what earlier detectors produced, within this frame only.
        frame.ai_metadata[_SCRATCH_KEY] = accumulated
        for p in self._processors:
            try:
                r = p.process(frame)
            except Exception as e:  # noqa: BLE001 — belt-and-suspenders
                r = ProcessorResult(getattr(p, "name", "?"), error=f"pipeline: {e}")
            results.append(r)
            if r.ok and r.detections:
                accumulated.extend(r.detections)
        frame.ai_metadata.pop(_SCRATCH_KEY, None)

        total_ms = (time.perf_counter() - t0) * 1000.0
        self._frames += 1
        self._total_ms += total_ms
        return ProcessingResult(
            frame_id=frame.frame_id, camera_id=frame.camera_id,
            frame_number=frame.frame_number, width=frame.width, height=frame.height,
            timestamp=frame.timestamp, results=results, total_ms=total_ms)

    # ── observability ────────────────────────────────────────────────────────────
    def metrics(self) -> dict:
        avg = (self._total_ms / self._frames) if self._frames else 0.0
        return {"frames_processed": self._frames, "avg_total_ms": round(avg, 3),
                "processors": [p.metrics() for p in self._processors]}

    def health(self) -> dict:
        unavailable = [p.name for p in self._processors if not p.available()]
        return {"status": "ok", "processors": len(self._processors),
                "active": len(self._processors) - len(unavailable),
                "unavailable": unavailable}

    @staticmethod
    def pipeline_detections(frame: Frame) -> list:
        """Read the running detection list a processor may consume mid-frame."""
        return list(frame.ai_metadata.get(_SCRATCH_KEY, []))
