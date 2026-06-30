"""
core/brains/simulation/history.py — FRIDAY V3 (M19)
Simulation history + learning feedback. Stores only *meaningful* simulations (successful
strategies, repeated failures, frequently-selected plans, high-value predictions) — never
temporary ones — and persists them through the Memory Brain (no direct DB). After an
action executes, `record_outcome` compares the predicted vs the actual result, feeds the
difference to the Learning service, and nudges the predictor's accuracy prior so future
predictions calibrate. Bounded + thread-safe.
"""

from __future__ import annotations

import logging
import threading
from collections import Counter, deque

log = logging.getLogger("friday.brains.simulation.history")


class SimulationHistory:
    def __init__(self, config, *, memory_brain=None, learning=None, predictor=None) -> None:
        self.config = config
        self._memory = memory_brain
        self._learning = learning
        self._predictor = predictor
        self._by_id: dict[str, object] = {}
        self._recent: deque = deque(maxlen=getattr(config, "history_capacity", 500))
        self._selected: Counter = Counter()
        self._failures: Counter = Counter()
        self._lock = threading.Lock()
        self._stored = 0

    # ── record a completed simulation (meaningful only) ──────────────────────────
    def record(self, result) -> bool:
        with self._lock:
            self._by_id[result.simulation_id] = result
            self._recent.append(result.to_dict())
            if result.recommended is not None:
                self._selected[result.recommended.scenario.name] += 1
        meaningful = self._is_meaningful(result)
        if meaningful and self.config.store_successful_simulations and self._memory is not None:
            self._persist(result)
            self._stored += 1
        return meaningful

    def _is_meaningful(self, result) -> bool:
        if result.rejected:
            return True                                  # rejections are worth remembering
        rec = result.recommended
        if rec is None:
            return False
        return (rec.expected_success >= 0.8 or rec.risk_level >= self.config.risk_threshold
                or self._selected[rec.scenario.name] >= 3)   # frequently selected

    def _persist(self, result) -> None:
        rec = result.recommended
        if rec is None:
            text = f"Simulation rejected all plans for '{result.action}' (too risky)."
            importance = 0.6
        else:
            text = (f"For '{result.action}', chose '{rec.scenario.name}' "
                    f"(success {int(rec.expected_success * 100)}%, risk {rec.risk_level:.2f}).")
            importance = min(0.9, 0.5 + rec.expected_success * 0.4)
        try:
            self._memory.remember(text, importance=importance, confidence=rec.confidence
                                  if rec else 0.6, kind="simulation")
        except Exception:  # noqa: BLE001
            log.debug("memory persist failed", exc_info=True)

    # ── learning feedback (predicted vs actual) ──────────────────────────────────
    def record_outcome(self, simulation_id: str, actual: dict) -> dict:
        with self._lock:
            result = self._by_id.get(simulation_id)
        if result is None or result.recommended is None:
            return {"error": None, "reason": "unknown simulation"}
        pred = result.recommended.prediction
        predicted = pred.success_probability if pred is not None else 0.5
        succeeded = bool(actual.get("success", actual.get("succeeded", False)))
        error = round(abs(predicted - (1.0 if succeeded else 0.0)), 4)

        if self.config.learning_feedback:
            if self._predictor is not None and hasattr(self._predictor, "set_accuracy_prior"):
                # nudge the prior toward calibration (lower error → higher prior)
                self._predictor.set_accuracy_prior(0.7 * getattr(self._predictor, "_prior", 0.5)
                                                    + 0.3 * (1.0 - error))
            if self._learning is not None:
                try:
                    self._learning.record("prediction_outcome", {
                        "action": result.action, "predicted": predicted,
                        "succeeded": succeeded, "error": error})
                except Exception:  # noqa: BLE001
                    log.debug("learning feedback failed", exc_info=True)
        if not succeeded:
            with self._lock:
                self._failures[result.action] += 1
                repeats = self._failures[result.action]
            if repeats >= 3 and self._memory is not None:
                try:
                    self._memory.remember(f"Repeated failures executing '{result.action}' "
                                          f"({repeats}x) — reconsider the approach.",
                                          importance=0.8, confidence=0.8, kind="simulation")
                except Exception:  # noqa: BLE001
                    log.debug("failure persist failed", exc_info=True)
        return {"error": error, "predicted": predicted, "succeeded": succeeded}

    # ── queries ──────────────────────────────────────────────────────────────────
    def get(self, simulation_id: str):
        with self._lock:
            return self._by_id.get(simulation_id)

    def recent(self, limit: int = 20) -> list:
        with self._lock:
            return list(self._recent)[-limit:][::-1]

    def stats(self) -> dict:
        with self._lock:
            return {"stored": self._stored, "tracked": len(self._by_id),
                    "top_plans": self._selected.most_common(3),
                    "repeated_failures": [k for k, v in self._failures.items() if v >= 3]}
