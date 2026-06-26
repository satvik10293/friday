"""
core/simulation/scenario.py — FRIDAY 4.0 (M11)
Turns a problem into a runnable Scenario. `from_problem` heuristically picks a
simulation type from the question; `build` constructs an explicit scenario.
"""

from __future__ import annotations

from .models import Scenario, SimulationType

_KEYWORDS = {
    "scale": SimulationType.AGENT_SOCIETY, "agents": SimulationType.AGENT_SOCIETY,
    "stress": SimulationType.AGENT_SOCIETY, "throughput": SimulationType.AGENT_SOCIETY,
    "architecture": SimulationType.ARCHITECTURE, "design": SimulationType.SOFTWARE_DESIGN,
    "research": SimulationType.RESEARCH, "experiment": SimulationType.SCIENTIFIC,
    "project": SimulationType.PROJECT_PLANNING, "plan": SimulationType.PROJECT_PLANNING,
    "goal": SimulationType.GOAL_ACHIEVEMENT, "business": SimulationType.BUSINESS,
    "startup": SimulationType.BUSINESS, "learn": SimulationType.LEARNING,
    "science": SimulationType.SCIENTIFIC,
}


class ScenarioBuilder:
    @staticmethod
    def build(sim_type, name: str = "", params=None) -> Scenario:
        t = sim_type.value if isinstance(sim_type, SimulationType) else str(sim_type)
        return Scenario(sim_type=t, name=name or t, params=dict(params or {}))

    @staticmethod
    def from_problem(question: str, params=None) -> Scenario:
        q = (question or "").lower()
        sim_type = SimulationType.CUSTOM
        for kw, t in _KEYWORDS.items():
            if kw in q:
                sim_type = t
                break
        return ScenarioBuilder.build(sim_type, name=question[:80], params=params)
