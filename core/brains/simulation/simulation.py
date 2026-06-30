"""
core/brains/simulation/simulation.py — FRIDAY V3 (M19)
The Simulation Brain — predictive cognition + decision intelligence. Before FRIDAY takes
a significant action, this brain thinks it through:

    generate scenarios → predict outcomes → forecast cost → score risk →
    evaluate + rank plans → recommend the best (safest) plan

It NEVER executes anything; it ADVISES the Executive Brain, which makes the final call. It
persists only meaningful simulations (via the Memory Brain) and learns from outcomes (via
the Learning service), so prediction accuracy improves over time. A Cognitive Brain like
the rest: never-raises, thread-safe, services-only, configuration-driven.
"""

from __future__ import annotations

import logging
import time
from typing import Optional

from ..base import CognitiveBrain, SituationReport
from .comparison import PlanComparison
from .config import SimulationConfig
from .decision_evaluator import DecisionEvaluator
from .events import SimulationEvent
from .forecast import ForecastEngine
from .history import SimulationHistory
from .interfaces import SimulationRequest, SimulationResult
from .predictor import PredictionEngine
from .risk_engine import RiskEngine
from .scenario_generator import ScenarioGenerator

log = logging.getLogger("friday.brains.simulation")


class SimulationBrain(CognitiveBrain):
    name = "simulation_brain"

    def __init__(self, *, services=None, config: Optional[dict] = None, report_bus=None,
                 sim_config: Optional[SimulationConfig] = None) -> None:
        super().__init__(services=services, config=config, report_bus=report_bus)
        self.sim_config = sim_config or SimulationConfig.from_dict(self.config)
        self._runtime = self._service("runtime")
        self._memory = self._service("memory_brain")
        self._learning = self._service("learning")

        self.scenarios = ScenarioGenerator()
        self.predictor = PredictionEngine()
        self.forecaster = ForecastEngine(runtime=self._runtime)
        self.risk = RiskEngine()
        self.evaluator = DecisionEvaluator(self.sim_config)
        self.comparison = PlanComparison()
        self.history = SimulationHistory(self.sim_config, memory_brain=self._memory,
                                         learning=self._learning, predictor=self.predictor)
        self._simulations = 0
        self._rejections = 0
        self._last_summary = ""

    # ── the prediction pipeline (advisory; never executes) ───────────────────────
    def simulate(self, action: str, *, context: Optional[dict] = None,
                 options: Optional[list] = None) -> dict:
        """Think a significant action through and return ranked, risk-scored plans. Never
        raises; never executes."""
        if not self.sim_config.enabled:
            return {"enabled": False}
        request = SimulationRequest(action=action, context=dict(context or {}),
                                    options=list(options or []))
        self._emit(SimulationEvent.SIMULATION_REQUESTED, {"id": request.simulation_id,
                                                          "action": action})
        try:
            return self._run(request).to_dict()
        except Exception as e:  # noqa: BLE001 — a simulation fault never crashes the core
            log.debug("simulation failed", exc_info=True)
            return {"simulation_id": request.simulation_id, "action": action,
                    "error": str(e), "rejected": True}

    def _run(self, request: SimulationRequest) -> SimulationResult:
        t0 = time.perf_counter()
        self._emit(SimulationEvent.SIMULATION_STARTED, {"id": request.simulation_id})
        scenarios = self.scenarios.generate(request, max_scenarios=self.sim_config.max_scenarios)
        evaluations = []
        deadline = t0 + self.sim_config.timeout_seconds
        for sc in scenarios:
            self._emit(SimulationEvent.SCENARIO_GENERATED,
                       {"id": request.simulation_id, "scenario": sc.name})
            pred = self.predictor.predict(sc, request)
            self._emit(SimulationEvent.PREDICTION_GENERATED,
                       {"scenario": sc.name, "success": pred.success_probability})
            fc = self.forecaster.forecast(sc, request)
            self._emit(SimulationEvent.FORECAST_UPDATED,
                       {"scenario": sc.name, "duration_s": fc.duration_s})
            rk = self.risk.assess(sc, pred, fc, request)
            self._emit(SimulationEvent.RISK_CALCULATED, {"scenario": sc.name, "risk": rk.overall})
            evaluations.append(self.evaluator.evaluate(sc, pred, fc, rk, request))
            if time.perf_counter() > deadline:           # incremental: stop at the budget
                break

        ranked = self.comparison.rank(evaluations)
        self._emit(SimulationEvent.SCENARIO_COMPARED, {"id": request.simulation_id,
                                                      "count": len(ranked)})
        summary = self.comparison.summarize(ranked)
        self._emit(SimulationEvent.PLAN_RANKED, {"id": request.simulation_id,
                                                "order": summary.get("order", [])})

        recommended = ranked[0] if ranked else None
        rejected = recommended is None or recommended.risk_level > self.sim_config.risk_threshold
        result = SimulationResult(
            simulation_id=request.simulation_id, action=request.action, ranked_plans=ranked,
            recommended=recommended, rejected=rejected, summary=summary.get("summary", ""))

        self._simulations += 1
        self._last_summary = result.summary
        if rejected:
            self._rejections += 1
            self._emit(SimulationEvent.SIMULATION_REJECTED,
                       {"id": request.simulation_id, "action": request.action,
                        "risk": recommended.risk_level if recommended else 1.0})
        else:
            self._emit(SimulationEvent.SIMULATION_COMPLETED,
                       {"id": request.simulation_id, "recommended": recommended.scenario.name})
        self.history.record(result)
        log.info("[Simulation] '%s' -> %s (rejected=%s)", request.action,
                 recommended.scenario.name if recommended else "none", rejected)
        return result

    # ── quick forecast for an action's default scenario ──────────────────────────
    def forecast(self, action: str, *, context: Optional[dict] = None) -> dict:
        request = SimulationRequest(action=action, context=dict(context or {}))
        scenarios = self.scenarios.generate(request, max_scenarios=1)
        fc = self.forecaster.forecast(scenarios[0], request)
        self._emit(SimulationEvent.FORECAST_UPDATED, {"action": action, **fc.to_dict()})
        return fc.to_dict()

    # ── learning feedback after execution ────────────────────────────────────────
    def record_outcome(self, simulation_id: str, actual: dict) -> dict:
        return self.history.record_outcome(simulation_id, actual)

    # ── Cognitive Brain lifecycle (light, request-driven brain) ──────────────────
    def reason(self, analysis):
        return {"simulations": self._simulations, "rejections": self._rejections}

    def generate_situation_report(self, insight) -> Optional[SituationReport]:
        if not self._last_summary or self._simulations == 0:
            return None
        report = self._report(f"Simulation: {self._last_summary}", confidence=0.7,
                              priority=0.4, category="simulation",
                              data={"simulations": self._simulations,
                                    "rejections": self._rejections,
                                    "history": self.history.stats()})
        self._last_summary = ""                          # report each new summary once
        return report

    # ── internals / observability ────────────────────────────────────────────────
    def _emit(self, event: SimulationEvent, data: dict) -> None:
        if self._runtime is None:
            return
        try:
            self._runtime.publish(event, data, source="simulation")
        except Exception:  # noqa: BLE001
            log.debug("emit failed for %s", event, exc_info=True)

    def metrics(self) -> dict:
        return {**super().metrics(), "simulations": self._simulations,
                "rejections": self._rejections, "history": self.history.stats()}

    def health(self) -> dict:
        return {"status": "ok" if self.sim_config.enabled else "disabled", "brain": self.name,
                "simulations": self._simulations, "rejections": self._rejections}
