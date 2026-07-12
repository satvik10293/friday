"""
core/brains/simulation/risk_engine.py — FRIDAY V3 (M19)
The Risk Engine. Scores a scenario across eight dimensions — safety, privacy, security,
reliability, performance, resource, user experience, system health — and rolls them into
one quantitative overall risk in [0, 1] (0 safe … 1 dangerous), with human-readable
reasons. Heuristic and deterministic (action semantics + scenario safety tags + the
forecast + the prediction); a learned risk model can replace it via `RiskAssessorProtocol`.
"""

from __future__ import annotations

from .interfaces import Forecast, Prediction, RiskScore, Scenario, SimulationRequest
from .signals import is_mitigated, signals_for


class RiskEngine:
    def assess(self, scenario: Scenario, prediction: Prediction, forecast: Forecast,
               request: SimulationRequest) -> RiskScore:
        tags = set(scenario.tags)
        mitigated = is_mitigated(tags)
        sig = signals_for(request)
        reasons: list = []

        destructive = sig.destructive
        sensitive = sig.sensitive

        safety = 0.0
        if destructive:
            safety = 0.4 if mitigated else 0.9
            reasons.append("destructive action" + (" (mitigated)" if mitigated else ""))
        elif sig.declared == "HIGH":
            # the skills registry outranks keyword guessing: a declared
            # HIGH-risk skill is never a low-risk plan without safeguards
            safety = 0.35 if mitigated else 0.65
            reasons.append("declared HIGH-risk skill"
                           + (" (mitigated)" if mitigated else ""))
        privacy = security = 0.0
        if sensitive:
            privacy = 0.3 if "redact" in tags or "ask_user" in tags else 0.7
            security = 0.3 if mitigated else 0.6
            reasons.append("handles sensitive/external data")

        reliability = max(0.0, 1.0 - prediction.success_probability)
        if prediction.failure_modes:
            reliability = min(1.0, reliability + 0.1 * len(prediction.failure_modes))
            reasons.append("predicted failure modes: " + ", ".join(prediction.failure_modes))

        performance = _band(forecast.duration_s, 1.0, 5.0)        # 1s low, 5s+ high
        resource = max(forecast.cpu, forecast.system_load, _band(forecast.memory_mb, 100, 800))
        if resource > 0.6:
            reasons.append("high resource forecast")
        user_experience = 0.6 if (destructive and not mitigated) else (0.2 if mitigated else 0.3)
        system_health = min(1.0, 0.6 * resource + 0.4 * reliability)

        dims = {"safety": safety, "privacy": privacy, "security": security,
                "reliability": reliability, "performance": performance, "resource": resource,
                "user_experience": user_experience, "system_health": system_health}
        values = list(dims.values())
        overall = round(0.6 * max(values) + 0.4 * (sum(values) / len(values)), 4)
        return RiskScore(overall=overall, reasons=reasons,
                         **{k: round(v, 4) for k, v in dims.items()})


def _band(value: float, low: float, high: float) -> float:
    if value <= low:
        return 0.0
    if value >= high:
        return 1.0
    return round((value - low) / (high - low), 4)
