"""
core/cognition_core/benchmark.py — FRIDAY 6.0 (M13)
Benchmarks for the cognition core: entity-resolution accuracy + duplicate-entity rate
+ resolver throughput + belief-update latency, on a deterministic synthetic stream of
observations with name variants. Used by tests and Mission Control to measure quality
over time (charter: "every subsystem publishes metrics").
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from .repositories import InMemoryBeliefRepository, InMemoryEntityRepository
from .service import CognitionCore


@dataclass
class BenchmarkReport:
    observations: int
    expected_entities: int
    resolved_entities: int
    duplicate_rate: float
    resolution_accuracy: float
    throughput_per_s: float
    avg_belief_update_ms: float

    def to_dict(self) -> dict:
        return dict(self.__dict__)


# A small ground-truth set: each canonical thing + the *surface* variants it appears
# as (case, executable suffix, whitespace, minor edits). String resolution handles
# these; true semantic aliases ("Visual Studio Code" == "VSCode") need explicit
# aliasing or a semantic model and are deliberately out of scope for M13.
_GROUND_TRUTH = {
    ("application", "Chrome"): ["Chrome", "chrome.exe", "chrome", " CHROME "],
    ("application", "VSCode"): ["VSCode", "vscode.exe", "VS Code", "vscode"],
    ("person", "Satvik"): ["Satvik", "satvik", "SATVIK"],
    ("device", "Webcam"): ["Webcam", "webcam", "web cam"],
}


def run_benchmark(repeats: int = 25) -> BenchmarkReport:
    core = CognitionCore(entity_repository=InMemoryEntityRepository(),
                         belief_repository=InMemoryBeliefRepository())
    stream = []
    for (kind, _canon), variants in _GROUND_TRUTH.items():
        for _ in range(repeats):
            for v in variants:
                stream.append((kind, v))
    # deterministic shuffle (stable) — interleave without RNG dependency
    stream.sort(key=lambda kv: hash(kv) & 0xffff)

    t0 = time.perf_counter()
    for kind, name in stream:
        core.resolve(kind, name)
    elapsed = time.perf_counter() - t0

    expected = len(_GROUND_TRUTH)
    resolved = len(core.entities())
    # exercise belief updates to measure their latency
    for e in core.entities():
        core.assert_belief(e.stable_id, "exists", True, confidence=0.9)
    snap = core.metrics_snapshot()
    accuracy = round(min(expected, resolved) / max(expected, resolved), 4)
    report = BenchmarkReport(
        observations=len(stream), expected_entities=expected, resolved_entities=resolved,
        duplicate_rate=round(max(0, resolved - expected) / expected, 4),
        resolution_accuracy=accuracy,
        throughput_per_s=round(len(stream) / elapsed, 1) if elapsed else 0.0,
        avg_belief_update_ms=snap["avg_belief_update_ms"])
    core.close()
    return report
