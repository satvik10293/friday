"""
core/brains/simulation/decision_evaluator.py — FRIDAY V3 (M19)
The Decision Evaluator. Turns the prediction + forecast + risk for a scenario into a full
plan evaluation — expected success, time, cost, resource usage, risk level, confidence,
dependencies, policy compliance, and a reasoning summary — plus a single composite score
used to rank plans. Weights are configuration-driven (never hardcoded). A policy gate
flags non-compliant plans (sensitive/destructive actions without mitigation).
"""

from __future__ import annotations

from .config import SimulationConfig
from .interfaces import (Forecast, PlanEvaluation, Prediction, RiskScore, Scenario,
                         SimulationRequest)


class DecisionEvaluator:
    def __init__(self, config: SimulationConfig) -> None:
        self.config = config

    def evaluate(self, scenario: Scenario, prediction: Prediction, forecast: Forecast,
                 risk: RiskScore, request: SimulationRequest) -> PlanEvaluation:
        expected_success = prediction.success_probability
        expected_time = forecast.duration_s
        expected_cost = round(min(1.0, 0.5 * forecast.cpu + 0.3 * _norm(forecast.memory_mb, 800)
                                  + 0.2 * forecast.automation_complexity), 4)
        expected_resource = round(max(forecast.cpu, forecast.system_load,
                                      _norm(forecast.memory_mb, 800)), 4)
        confidence = round(0.5 * prediction.confidence + 0.5 * forecast.confidence, 4)
        policy_compliant = self._policy(scenario, risk)
        dependencies = [s for s in scenario.steps[:-1]] if len(scenario.steps) > 1 else []

        c = self.config
        time_norm = _norm(expected_time, 5.0)
        score = (c.weight_success * expected_success
                 - c.weight_risk * risk.overall
                 - c.weight_time * time_norm
                 - c.weight_cost * expected_cost)
        if not policy_compliant:
            score -= 0.5
        reasoning = self._reasoning(scenario, prediction, risk, policy_compliant)
        return PlanEvaluation(
            scenario=scenario, expected_success=expected_success, expected_time_s=expected_time,
            expected_cost=expected_cost, expected_resource=expected_resource,
            risk_level=risk.overall, confidence=confidence, dependencies=dependencies,
            policy_compliant=policy_compliant, reasoning=reasoning, score=round(score, 4),
            prediction=prediction, forecast=forecast, risk=risk)

    def _policy(self, scenario: Scenario, risk: RiskScore) -> bool:
        mitigated = bool(set(scenario.tags) & {"backup", "ask_user", "dry_run", "redact",
                                               "cautious"})
        # high safety/privacy/security risk without mitigation violates policy
        if (risk.safety >= 0.7 or risk.privacy >= 0.7 or risk.security >= 0.7) and not mitigated:
            return False
        return True

    @staticmethod
    def _reasoning(scenario: Scenario, prediction: Prediction, risk: RiskScore,
                   compliant: bool) -> str:
        bits = [f"{int(prediction.success_probability * 100)}% expected success",
                f"risk {risk.overall:.2f}"]
        if risk.reasons:
            bits.append(risk.reasons[0])
        if not compliant:
            bits.append("policy: needs mitigation/confirmation")
        return f"{scenario.name}: " + "; ".join(bits) + "."


def _norm(value: float, ceiling: float) -> float:
    if ceiling <= 0:
        return 0.0
    return round(max(0.0, min(1.0, value / ceiling)), 4)
