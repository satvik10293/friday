"""
core/brains/simulation/events.py — FRIDAY V3 (M19)
The Simulation Brain event vocabulary, published on the Runtime event bus.

  • simulation.requested   — a simulation was requested for an intended action.
  • simulation.started      — the simulation pipeline began.
  • scenario.generated      — a candidate scenario (plan) was generated.
  • scenario.compared       — scenarios were compared/ranked against each other.
  • risk.calculated         — a quantitative risk score was computed for a scenario.
  • prediction.generated    — an outcome prediction (with confidence) was produced.
  • plan.ranked             — the final plan ranking is available.
  • simulation.completed     — the simulation finished; a recommended plan is ready.
  • simulation.rejected      — the safest plan still exceeds the risk threshold (advise caution).
  • forecast.updated         — a resource/time forecast was produced/updated.
"""

from __future__ import annotations

from enum import Enum


class SimulationEvent(str, Enum):
    SIMULATION_REQUESTED = "simulation.requested"
    SIMULATION_STARTED = "simulation.started"
    SCENARIO_GENERATED = "simulation.scenario.generated"
    SCENARIO_COMPARED = "simulation.scenario.compared"
    RISK_CALCULATED = "simulation.risk.calculated"
    PREDICTION_GENERATED = "simulation.prediction.generated"
    PLAN_RANKED = "simulation.plan.ranked"
    SIMULATION_COMPLETED = "simulation.completed"
    SIMULATION_REJECTED = "simulation.rejected"
    FORECAST_UPDATED = "simulation.forecast.updated"
