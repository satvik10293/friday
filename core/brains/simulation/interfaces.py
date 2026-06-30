"""
core/brains/simulation/interfaces.py — FRIDAY V3 (M19)
The data model + strategy contracts of the Simulation Brain. The data classes flow
through the prediction pipeline (request → scenarios → predictions → forecasts → risk →
evaluations → result). The Protocols make every pipeline stage dependency-injected and
replaceable (a learned predictor / risk model / scenario generator can be plugged via the
PluginService without changing the brain). Pure data — no I/O.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Optional, Protocol, runtime_checkable


def _sid() -> str:
    return "SIM_" + uuid.uuid4().hex[:12]


# ── pipeline data ───────────────────────────────────────────────────────────────────
@dataclass
class SimulationRequest:
    action: str                                  # the intended action, e.g. "delete folder"
    context: dict = field(default_factory=dict)  # situation/context from the Executive
    options: list = field(default_factory=list)  # optional explicit candidate actions
    constraints: dict = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)
    simulation_id: str = field(default_factory=_sid)

    def to_dict(self) -> dict:
        return {"simulation_id": self.simulation_id, "action": self.action,
                "context": self.context, "options": self.options,
                "constraints": self.constraints, "timestamp": self.timestamp}


@dataclass
class Scenario:
    name: str
    steps: list = field(default_factory=list)
    description: str = ""
    tags: list = field(default_factory=list)     # e.g. ["destructive", "backup", "ask_user"]
    scenario_id: str = field(default_factory=lambda: "SC_" + uuid.uuid4().hex[:8])

    def to_dict(self) -> dict:
        return {"scenario_id": self.scenario_id, "name": self.name, "steps": self.steps,
                "description": self.description, "tags": self.tags}


@dataclass
class Prediction:
    success_probability: float = 0.5
    intent: str = ""
    next_actions: list = field(default_factory=list)
    completion: float = 1.0                      # expected task completion fraction
    failure_modes: list = field(default_factory=list)
    confidence: float = 0.5

    def to_dict(self) -> dict:
        return {k: (round(v, 4) if isinstance(v, float) else v)
                for k, v in self.__dict__.items()}


@dataclass
class Forecast:
    cpu: float = 0.0                             # 0..1 estimated load contribution
    memory_mb: float = 0.0
    storage_mb: float = 0.0
    network: float = 0.0                         # 0..1
    duration_s: float = 0.0
    automation_complexity: float = 0.0           # 0..1
    system_load: float = 0.0                     # 0..1
    confidence: float = 0.5

    def to_dict(self) -> dict:
        return {k: round(float(v), 4) for k, v in self.__dict__.items()}


@dataclass
class RiskScore:
    overall: float = 0.0                         # 0 (safe) .. 1 (dangerous)
    safety: float = 0.0
    privacy: float = 0.0
    security: float = 0.0
    reliability: float = 0.0
    performance: float = 0.0
    resource: float = 0.0
    user_experience: float = 0.0
    system_health: float = 0.0
    reasons: list = field(default_factory=list)

    def to_dict(self) -> dict:
        d = {k: (round(v, 4) if isinstance(v, float) else v)
             for k, v in self.__dict__.items()}
        return d


@dataclass
class PlanEvaluation:
    scenario: Scenario
    expected_success: float = 0.5
    expected_time_s: float = 0.0
    expected_cost: float = 0.0
    expected_resource: float = 0.0
    risk_level: float = 0.0
    confidence: float = 0.5
    dependencies: list = field(default_factory=list)
    policy_compliant: bool = True
    reasoning: str = ""
    score: float = 0.0                           # composite rank score (higher = better)
    prediction: Optional[Prediction] = None
    forecast: Optional[Forecast] = None
    risk: Optional[RiskScore] = None

    def to_dict(self) -> dict:
        return {"scenario": self.scenario.to_dict(), "expected_success": round(self.expected_success, 4),
                "expected_time_s": round(self.expected_time_s, 4),
                "expected_cost": round(self.expected_cost, 4),
                "expected_resource": round(self.expected_resource, 4),
                "risk_level": round(self.risk_level, 4), "confidence": round(self.confidence, 4),
                "dependencies": self.dependencies, "policy_compliant": self.policy_compliant,
                "reasoning": self.reasoning, "score": round(self.score, 4),
                "prediction": self.prediction.to_dict() if self.prediction else None,
                "forecast": self.forecast.to_dict() if self.forecast else None,
                "risk": self.risk.to_dict() if self.risk else None}


@dataclass
class SimulationResult:
    simulation_id: str
    action: str
    ranked_plans: list = field(default_factory=list)     # list[PlanEvaluation], best first
    recommended: Optional[PlanEvaluation] = None
    rejected: bool = False                               # all plans exceed the risk threshold
    summary: str = ""
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {"simulation_id": self.simulation_id, "action": self.action,
                "rejected": self.rejected, "summary": self.summary, "timestamp": self.timestamp,
                "recommended": self.recommended.to_dict() if self.recommended else None,
                "ranked_plans": [p.to_dict() for p in self.ranked_plans]}


# ── strategy protocols (DI / extensibility) ─────────────────────────────────────────
@runtime_checkable
class ScenarioGeneratorProtocol(Protocol):
    def generate(self, request: SimulationRequest, *, max_scenarios: int) -> list: ...


@runtime_checkable
class PredictorProtocol(Protocol):
    def predict(self, scenario: Scenario, request: SimulationRequest) -> Prediction: ...


@runtime_checkable
class ForecasterProtocol(Protocol):
    def forecast(self, scenario: Scenario, request: SimulationRequest) -> Forecast: ...


@runtime_checkable
class RiskAssessorProtocol(Protocol):
    def assess(self, scenario: Scenario, prediction: Prediction, forecast: Forecast,
               request: SimulationRequest) -> RiskScore: ...
