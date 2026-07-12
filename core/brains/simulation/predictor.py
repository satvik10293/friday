"""
core/brains/simulation/predictor.py — FRIDAY V3 (M19)
The Prediction Engine. For a candidate scenario it predicts the likely outcome: success
probability, the user's likely intent, likely next actions, task completion, and failure
modes — each rolled up into a confidence. Heuristic and deterministic (action signals +
scenario safety tags); a learned predictor can replace it via the `PredictorProtocol`.
The Simulation Brain also feeds back actual outcomes so accuracy improves over time.

Signals come from `signals.signals_for` (M41): the action title, the Executive's
DECLARED risk tier, and the skill args — never the title alone.
"""

from __future__ import annotations

from .interfaces import Prediction, Scenario, SimulationRequest
from .signals import is_mitigated, signals_for

_INTENT = {
    "delete": "remove data", "remove": "remove data", "send": "communicate",
    "share": "communicate", "open": "access content", "download": "acquire data",
    "backup": "protect data", "search": "find information",
}


class PredictionEngine:
    def __init__(self, *, accuracy_prior: float = 0.5) -> None:
        self._prior = accuracy_prior        # adjusted by learning feedback over time

    @property
    def accuracy_prior(self) -> float:
        return self._prior

    def predict(self, scenario: Scenario, request: SimulationRequest) -> Prediction:
        action = (request.action or "").lower()
        sig = signals_for(request)
        safe = is_mitigated(scenario.tags)
        risky = sig.destructive or sig.external or sig.high_stakes

        # safer scenarios for risky actions are more likely to succeed cleanly
        base_success = 0.9 if safe else (0.6 if risky else 0.8)
        success = max(0.05, min(0.99, base_success))

        failure_modes = []
        if sig.destructive and not safe:
            failure_modes.append("irreversible data loss")
        if (sig.external or sig.sensitive) and not safe:
            failure_modes.append("unintended disclosure")
        if sig.high_stakes and not safe:
            failure_modes.append(f"declared {sig.declared}-risk skill without safeguards")
        if not scenario.steps:
            failure_modes.append("under-specified plan")

        completion = 1.0 if not failure_modes else max(0.4, 1.0 - 0.2 * len(failure_modes))
        confidence = round(0.4 + 0.4 * self._prior + (0.1 if scenario.steps else 0.0), 4)
        return Prediction(
            success_probability=round(success, 4),
            intent=_intent_of(action),
            next_actions=_next_actions(sig, safe),
            completion=round(completion, 4), failure_modes=failure_modes,
            confidence=min(0.99, confidence))

    def set_accuracy_prior(self, value: float) -> None:
        """Learning feedback nudges the prior so predictions calibrate over time."""
        self._prior = max(0.0, min(1.0, float(value)))


def _intent_of(action: str) -> str:
    for k, v in _INTENT.items():
        if k in action:
            return v
    return "perform action"


def _next_actions(sig, safe: bool) -> list:
    if sig.destructive:
        return ["confirm result", "verify backup"] if safe else ["confirm result"]
    if sig.external:
        return ["confirm delivery"]
    return ["observe outcome"]
