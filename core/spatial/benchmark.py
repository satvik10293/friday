"""
core/spatial/benchmark.py — FRIDAY V3 (M16)
Performance benchmarks for Spatial Cognition on deterministic synthetic observations (no
camera, no services beyond an in-memory container). Verifies the subsystem sustains long
sessions with thousands of observations at low per-update cost.

Reported:
  • updates_per_s         — scene updates/second (batch of objects each)
  • observations_per_s    — total observations processed/second
  • avg_update_ms         — mean time per update
  • final_nodes           — scene-graph size after the run (bounded by pruning)
  • tracked_objects       — distinct persistent identities maintained
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from .config import SpatialConfig
from .interfaces import SpatialObservation
from .service import SpatialService


@dataclass
class SpatialBenchmarkReport:
    updates: int
    observations: int
    updates_per_s: float
    observations_per_s: float
    avg_update_ms: float
    final_nodes: int
    tracked_objects: int

    def to_dict(self) -> dict:
        return dict(self.__dict__)


def _frame(t: int, n_objects: int = 6) -> list:
    """A synthetic frame of `n_objects` slowly-drifting objects in one room."""
    obs = []
    for i in range(n_objects):
        x = (0.1 + 0.12 * i + 0.0005 * t) % 1.0
        obs.append(SpatialObservation(
            object_class=["laptop", "keyboard", "mouse", "phone", "cup", "monitor"][i % 6],
            label=f"obj{i}", confidence=0.9,
            bbox={"x": x, "y": 0.4, "w": 0.08, "h": 0.08},
            position={"x": x + 0.04, "y": 0.44}, camera_id="cam0", room="office"))
    # a person every few frames
    if t % 3 == 0:
        obs.append(SpatialObservation(object_class="person", label="user", confidence=0.9,
                                      position={"x": 0.5, "y": 0.7}, camera_id="cam0", room="office"))
    return obs


def run_benchmark(updates: int = 500, n_objects: int = 6) -> SpatialBenchmarkReport:
    svc = SpatialService(SpatialConfig.from_dict({"memory": {"persistent": False}}))
    total_obs = 0
    t0 = time.perf_counter()
    for t in range(updates):
        frame = _frame(t, n_objects)
        total_obs += len(frame)
        svc.update_scene(frame, camera_id="cam0")
    elapsed = time.perf_counter() - t0
    counts = svc.engine.scene.counts()
    tracks = len(svc.engine.tracker.tracks())
    svc.close()
    return SpatialBenchmarkReport(
        updates=updates, observations=total_obs,
        updates_per_s=round(updates / elapsed, 1) if elapsed else 0.0,
        observations_per_s=round(total_obs / elapsed, 1) if elapsed else 0.0,
        avg_update_ms=round(elapsed / updates * 1000.0, 4) if updates else 0.0,
        final_nodes=counts["nodes"], tracked_objects=tracks)


if __name__ == "__main__":  # pragma: no cover
    import json
    print(json.dumps(run_benchmark().to_dict(), indent=2))
