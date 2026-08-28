"""
core/intelligence/benchmark.py — FRIDAY 4.0 (M12)
The benchmark system (Part 13). Runs deterministic capability suites against models,
scores correctness + speed, persists results, and ranks models automatically. The
ranking feeds the router's model selection and Mission Control.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from .base import InferenceRequest, Model, TaskType
from .store import IntelligenceStore


@dataclass
class BenchmarkCase:
    task: str
    prompt: str
    context: dict = field(default_factory=dict)
    check: Optional[object] = None     # callable(result)->bool; None = ok if produced


# Deterministic suites. `check` validates the structured output.
_SUITES: dict[str, list[BenchmarkCase]] = {
    "math": [
        BenchmarkCase(TaskType.MATH.value, "compute 2 + 3 * 4", {"expression": "2 + 3 * 4"},
                      check=lambda r: r.structured.get("value") == 14),
        BenchmarkCase(TaskType.MATH.value, "compute 10 / 2", {"expression": "10 / 2"},
                      check=lambda r: r.structured.get("value") == 5),
    ],
    "coding": [
        BenchmarkCase(TaskType.CODING.value, "review", {"code": "x == None"},
                      check=lambda r: bool(r.structured.get("issues"))),
    ],
    "reasoning": [
        BenchmarkCase(TaskType.GENERAL.value, "why does the sky appear blue at noon",
                      check=lambda r: bool(r.structured.get("steps"))),
    ],
    "research": [
        BenchmarkCase(TaskType.RESEARCH.value,
                      "Summarise: Flask routes URLs to functions. It is a microframework. "
                      "It uses Werkzeug and Jinja for templating and routing.",
                      check=lambda r: len(r.text) > 0),
    ],
}


class BenchmarkSystem:
    def __init__(self, store: Optional[IntelligenceStore] = None) -> None:
        self._store = store

    def suites(self) -> list[str]:
        return list(_SUITES)

    def run(self, model: Model, suite: str) -> dict:
        cases = _SUITES.get(suite, [])
        if not cases:
            return {"model": model.info.name, "suite": suite, "score": 0.0, "cases": 0}
        passed, total_latency = 0, 0.0
        for case in cases:
            res = model.infer(InferenceRequest(task=case.task, prompt=case.prompt,
                                               context=dict(case.context)))
            total_latency += res.latency_ms
            ok = res.ok and (case.check is None or bool(case.check(res)))
            if ok:
                passed += 1
        score = passed / len(cases)
        detail = {"passed": passed, "cases": len(cases),
                  "avg_latency_ms": round(total_latency / len(cases), 3)}
        if self._store is not None:
            self._store.save_benchmark(model.info.name, suite, score, detail)
        model.info.benchmark_scores[suite] = round(score, 3)
        return {"model": model.info.name, "suite": suite, "score": round(score, 3), **detail}

    def run_all(self, model: Model) -> dict:
        """Benchmark a model across every suite its capabilities cover."""
        results = {}
        for suite in self.suites():
            results[suite] = self.run(model, suite)
        overall = round(sum(r["score"] for r in results.values()) / max(1, len(results)), 3)
        model.info.benchmark_scores["overall"] = overall
        return {"model": model.info.name, "overall": overall, "suites": results}

    def rank(self, models: list[Model], suite: str = "overall") -> list[dict]:
        """Rank models by a suite score (default overall)."""
        scored = [{"model": m.info.name,
                   "score": m.info.benchmark_scores.get(suite, 0.0)} for m in models]
        scored.sort(key=lambda x: x["score"], reverse=True)
        return scored
