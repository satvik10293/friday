"""
core/simulation/ — FRIDAY 4.0 (M11) Cognitive Simulation Engine.

Lets FRIDAY *simulate* solutions before recommending them — the observe → analyze →
simulate → evaluate → present philosophy. Every simulation runs in a fully isolated
**sandbox** (virtual agents / goals / knowledge / tasks) that can never touch
production state.

Workflow: Problem → Director → Scenario → (agent team) → Execution → Analysis →
Recommendation. Simulations are stepwise and snapshotted, so they can be paused,
replayed, forked, and compared.

Side-effect-free to import.
"""

from __future__ import annotations

from .controls import SimulationControls
from .director import SimulationDirector
from .engine import SimulationEngine
from .models import (Recommendation, Scenario, Simulation, SimulationType, SimResult,
                     SimStep, VirtualAgent, VirtualGoal, VirtualKnowledge, VirtualTask)
from .sandbox import SandboxViolation, SimulationSandbox
from .scenario import ScenarioBuilder
from .service import SimulationService, get_simulation_service
from .timeline import Timeline

__all__ = [
    "SimulationService", "get_simulation_service", "SimulationDirector",
    "SimulationEngine", "SimulationControls", "Timeline", "ScenarioBuilder",
    "SimulationSandbox", "SandboxViolation", "Simulation", "SimulationType",
    "Scenario", "SimStep", "SimResult", "Recommendation", "VirtualAgent",
    "VirtualGoal", "VirtualKnowledge", "VirtualTask",
]
