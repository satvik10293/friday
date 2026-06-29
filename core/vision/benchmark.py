"""
core/vision/benchmark.py — FRIDAY 6.1 (M14)
Performance benchmarks for the Vision System on a deterministic synthetic camera (no
hardware, no sockets, no models). Measures end-to-end throughput and per-stage latency
so quality is tracked over time (charter: "every subsystem publishes benchmarks").

Reported:
  • pipeline_fps              — frames/second through the processing pipeline
  • avg_pipeline_ms           — mean processing time per frame
  • end_to_end_fps            — frames/second through process_camera (pipeline + builder + bridge)
  • avg_end_to_end_ms         — mean process_camera latency
  • observations_per_frame    — mean Observations produced per frame
  • detection_recall          — fraction of motion frames where a moving region was found
"""

from __future__ import annotations

import time
from dataclasses import dataclass

import numpy as np

from .config import VisionConfig
from .processing.pipeline import VisionPipeline
from .processing.registry import default_registry
from .service import VisionSystem
from .transport.frame import frame_from_array


@dataclass
class VisionBenchmarkReport:
    frames: int
    pipeline_fps: float
    avg_pipeline_ms: float
    end_to_end_fps: float
    avg_end_to_end_ms: float
    observations_per_frame: float
    detection_recall: float

    def to_dict(self) -> dict:
        return dict(self.__dict__)


def _synthetic_frames(n: int, w: int = 160, h: int = 120) -> list:
    """A deterministic moving-square sequence: every frame after the first contains a
    bright block that translates, guaranteeing inter-frame motion."""
    frames = []
    positions = [10, 55, 100]                      # cycle distinct, non-overlapping spots
    for i in range(n):
        img = np.full((h, w, 3), 30, dtype=np.uint8)
        if i > 0:
            x = positions[i % len(positions)]
            img[30:100, x:x + 55] = 200            # a large block → clear inter-frame motion
        frames.append(img)
    return frames


def run_benchmark(frames: int = 60) -> VisionBenchmarkReport:
    images = _synthetic_frames(frames)

    # ── pipeline-only throughput ─────────────────────────────────────────────────
    cfg = VisionConfig()
    reg = default_registry(cfg.processing)
    pipe = VisionPipeline([reg.create(n) for n in cfg.processing.enabled])
    motion_hits = 0
    t0 = time.perf_counter()
    for i, img in enumerate(images):
        frame = frame_from_array("CAMERA_BENCH", img, frame_number=i + 1)
        result = pipe.process(frame)
        if result.data_for("motion").get("motion"):
            motion_hits += 1
    pipe_elapsed = time.perf_counter() - t0
    pmetrics = pipe.metrics()

    # ── end-to-end through the full system (no cognition wired = pure vision cost) ─
    sys = VisionSystem(config=VisionConfig.from_dict({"memory": {"persistent": False}}))
    cid = sys.add_array_camera("bench", images, label="bench")
    obs_total = 0
    t1 = time.perf_counter()
    processed = 0
    for _ in range(frames):
        r = sys.process_camera(cid)
        if r.get("frame"):
            processed += 1
            obs_total += r.get("observations", 0)
    e2e_elapsed = time.perf_counter() - t1
    sys.close()

    motion_frames = frames - 1                     # first frame has no predecessor
    return VisionBenchmarkReport(
        frames=frames,
        pipeline_fps=round(frames / pipe_elapsed, 2) if pipe_elapsed else 0.0,
        avg_pipeline_ms=round(pmetrics["avg_total_ms"], 3),
        end_to_end_fps=round(processed / e2e_elapsed, 2) if e2e_elapsed else 0.0,
        avg_end_to_end_ms=round((e2e_elapsed / processed) * 1000.0, 3) if processed else 0.0,
        observations_per_frame=round(obs_total / processed, 3) if processed else 0.0,
        detection_recall=round(motion_hits / motion_frames, 3) if motion_frames else 0.0,
    )


if __name__ == "__main__":  # pragma: no cover
    import json
    print(json.dumps(run_benchmark().to_dict(), indent=2))
