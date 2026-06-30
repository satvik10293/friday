"""
core/brains/simulation/ — FRIDAY V3 (M19) Simulation Brain.

Predictive cognition + decision intelligence: before FRIDAY takes a significant action,
the Simulation Brain generates scenarios, predicts outcomes, forecasts cost, scores risk,
evaluates + ranks candidate plans, and recommends the safest. It ADVISES the Executive
Brain (never executes), persists only meaningful simulations through the Memory Brain, and
learns from outcomes. Built on the M18 brain framework + M16 services; lives under
core/brains/simulation/ (distinct from the M11 core/simulation engine).

Side-effect-free to import.
"""

from __future__ import annotations

from .config import SimulationConfig
from .events import SimulationEvent
from .interfaces import (Forecast, PlanEvaluation, Prediction, RiskScore, Scenario,
                         SimulationRequest, SimulationResult)
from .service import SimulationService, attach_to_container, get_simulation_service
from .simulation import SimulationBrain

__all__ = [
    "SimulationService", "get_simulation_service", "attach_to_container",
    "SimulationBrain", "SimulationConfig", "SimulationEvent",
    "SimulationRequest", "SimulationResult", "Scenario", "Prediction", "Forecast",
    "RiskScore", "PlanEvaluation",
]
