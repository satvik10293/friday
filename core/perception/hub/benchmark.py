"""
core/perception/hub/benchmark.py — FRIDAY V3 (M17)
Performance benchmarks for the Perception Hub on deterministic synthetic multimodal
observations (no sensors, in-memory services). Verifies the Hub sustains long sessions
with thousands of observations at low per-cycle cost and bounded memory.

Reported:
  • cycles_per_s          — ingest cycles/second
  • observations_per_s    — modality observations processed/second
  • avg_cycle_ms          — mean time per ingest cycle
  • timeline_size         — bounded timeline size after the run
  • reasoning_rate        — conclusions per cycle
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from .config import PerceptionHubConfig
from .observations import ModalityObservation
from .service import PerceptionService


@dataclass
class HubBenchmarkReport:
    cycles: int
    observations: int
    cycles_per_s: float
    observations_per_s: float
    avg_cycle_ms: float
    timeline_size: int
    reasoning_rate: float

    def to_dict(self) -> dict:
        return dict(self.__dict__)


def _cycle(t: int) -> list:
    """A synthetic multimodal cycle: kitchen activity that should reason to 'breakfast'
    on some cycles, plus background office objects on others."""
    if t % 4 == 0:
        return [
            ModalityObservation(source="vision", category="object", label="bottle",
                                confidence=0.9, location="kitchen", objects=["bottle"]),
            ModalityObservation(source="audio", category="sound", label="running_water",
                                confidence=0.85, location="kitchen"),
            ModalityObservation(source="spatial", category="user_state", label="present",
                                confidence=0.95, location="kitchen",
                                data={"user_state": "present"}),
        ]
    return [
        ModalityObservation(source="vision", category="object", label="laptop",
                            confidence=0.88, location="office", objects=["laptop", "keyboard"]),
        ModalityObservation(source="audio", category="sound", label="keyboard_typing",
                            confidence=0.8, location="office"),
    ]


def run_benchmark(cycles: int = 500) -> HubBenchmarkReport:
    svc = PerceptionService(PerceptionHubConfig.from_dict({}))
    total_obs = 0
    t0 = time.perf_counter()
    for t in range(cycles):
        frame = _cycle(t)
        total_obs += len(frame)
        svc.ingest(frame)
    elapsed = time.perf_counter() - t0
    m = svc.hub.metrics()
    svc.close()
    return HubBenchmarkReport(
        cycles=cycles, observations=total_obs,
        cycles_per_s=round(cycles / elapsed, 1) if elapsed else 0.0,
        observations_per_s=round(total_obs / elapsed, 1) if elapsed else 0.0,
        avg_cycle_ms=round(elapsed / cycles * 1000.0, 4) if cycles else 0.0,
        timeline_size=m["timeline"]["size"],
        reasoning_rate=round(m["reasoner"]["conclusions_fired"] / cycles, 3) if cycles else 0.0)


if __name__ == "__main__":  # pragma: no cover
    import json
    print(json.dumps(run_benchmark().to_dict(), indent=2))
