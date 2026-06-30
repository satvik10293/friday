"""
core/brains/simulation/benchmark.py — FRIDAY V3 (M19)
Performance benchmark for the Simulation Brain on deterministic synthetic actions (no
services). Verifies the predict→simulate→risk→rank pipeline runs at low latency for
long-running sessions.

Reported:
  • simulations_per_s   — full simulations/second
  • avg_simulation_ms   — mean time per simulation
  • avg_scenarios       — mean candidate plans evaluated per simulation
  • rejection_rate      — fraction of actions whose safest plan still exceeded the threshold
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from .config import SimulationConfig
from .simulation import SimulationBrain

_ACTIONS = ["delete the project folder", "send the report to the team", "open the file",
            "back up the database", "download the dataset", "format the disk",
            "search the archive", "share the document"]


@dataclass
class SimBenchmarkReport:
    simulations: int
    simulations_per_s: float
    avg_simulation_ms: float
    avg_scenarios: float
    rejection_rate: float

    def to_dict(self) -> dict:
        return dict(self.__dict__)


def run_benchmark(simulations: int = 400) -> SimBenchmarkReport:
    brain = SimulationBrain(config=SimulationConfig.from_dict({}).to_dict())
    total_scenarios = 0
    rejections = 0
    t0 = time.perf_counter()
    for i in range(simulations):
        result = brain.simulate(_ACTIONS[i % len(_ACTIONS)])
        total_scenarios += len(result.get("ranked_plans", []))
        if result.get("rejected"):
            rejections += 1
    elapsed = time.perf_counter() - t0
    return SimBenchmarkReport(
        simulations=simulations,
        simulations_per_s=round(simulations / elapsed, 1) if elapsed else 0.0,
        avg_simulation_ms=round(elapsed / simulations * 1000.0, 4) if simulations else 0.0,
        avg_scenarios=round(total_scenarios / simulations, 2) if simulations else 0.0,
        rejection_rate=round(rejections / simulations, 3) if simulations else 0.0)


if __name__ == "__main__":  # pragma: no cover
    import json
    print(json.dumps(run_benchmark().to_dict(), indent=2))
