"""
core/simulation/director.py — FRIDAY 4.0 (M11)
The Simulation Director orchestrates the full workflow:

    Problem → Scenario → (agent team) → Execution → Analysis → Recommendation

It is the observe-analyze-simulate-evaluate-present pipeline: instead of answering a
hard question immediately, FRIDAY builds a scenario, runs it in a sandbox, and
returns a recommendation backed by the simulated evidence.
"""

from __future__ import annotations

from typing import Optional

from .engine import SimulationEngine
from .models import Simulation
from .sandbox import SimulationSandbox
from .scenario import ScenarioBuilder


class SimulationDirector:
    def __init__(self, engine: Optional[SimulationEngine] = None) -> None:
        self._engine = engine if engine is not None else SimulationEngine()

    def direct(self, problem: str, *, params: Optional[dict] = None,
               steps: Optional[int] = None) -> Simulation:
        """Run a full simulation for a free-text problem and attach a recommendation."""
        scenario = ScenarioBuilder.from_problem(problem, params)
        sim = Simulation(name=problem[:80], sim_type=scenario.sim_type, scenario=scenario)
        sandbox = SimulationSandbox(name=sim.name)
        self._engine.run(sim, sandbox=sandbox, steps=steps)
        return sim

    def run(self, simulation: Simulation, *, steps: Optional[int] = None) -> Simulation:
        self._engine.run(simulation, steps=steps)
        return simulation
