"""
core/intelligence/reasoning_engine.py — FRIDAY 4.0 (M12)
The reasoning engine (Part 5). Orchestrates one or many local models into a
reasoning strategy — chain-of-thought, tree-of-thought, consensus, debate,
self-correction, parallel, recursive — and the "engineering team" collaboration
(research → planning → coding → critic → executive). No single model dominates;
every model contributes.

Models are run through an injected executor (default: direct inference), so the
execution manager's retry/health/trace wraps every call uniformly.
"""

from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Optional

from .base import InferenceRequest, InferenceResult, Model, TaskType
from .confidence_engine import ConfidenceEngine
from .critic import CriticEngine
from .registry import IntelligenceRegistry


class ReasoningStrategy(str, Enum):
    CHAIN_OF_THOUGHT = "chain_of_thought"
    TREE_OF_THOUGHT = "tree_of_thought"
    CONSENSUS = "consensus"
    DEBATE = "debate"
    SELF_CORRECTION = "self_correction"
    PARALLEL = "parallel"
    RECURSIVE = "recursive"
    SEQUENTIAL = "sequential"


@dataclass
class ReasoningResult:
    strategy: str
    ok: bool
    answer: str = ""
    structured: dict = field(default_factory=dict)
    confidence: float = 0.0
    models_used: list = field(default_factory=list)
    agreement: float = 0.0
    steps: list = field(default_factory=list)
    error: str = ""

    def to_dict(self) -> dict:
        return dict(self.__dict__)


def _direct_executor(model: Model, request: InferenceRequest) -> InferenceResult:
    return model.infer(request)


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())[:60]


class ReasoningEngine:
    def __init__(self, registry: IntelligenceRegistry, *,
                 executor: Optional[Callable[[Model, InferenceRequest], InferenceResult]] = None,
                 task_executor: Optional[Callable[[InferenceRequest], InferenceResult]] = None,
                 critic: Optional[CriticEngine] = None,
                 confidence: Optional[ConfidenceEngine] = None,
                 max_parallel: int = 4) -> None:
        self._registry = registry
        self._run = executor or _direct_executor
        # task-level executor with automatic backup-model fallback (Part 3)
        self._task_exec = task_executor
        self._critic = critic or CriticEngine()
        self._confidence = confidence or ConfidenceEngine()
        self._max_parallel = max_parallel

    # ── primitives ──────────────────────────────────────────────────────────────
    def _models_for(self, task: str, n: int = 1) -> list[Model]:
        return self._registry.by_capability(task)[:n]

    def reason(self, request: InferenceRequest,
               strategy: ReasoningStrategy = ReasoningStrategy.CHAIN_OF_THOUGHT
               ) -> ReasoningResult:
        fn = {
            ReasoningStrategy.CHAIN_OF_THOUGHT: self.chain_of_thought,
            ReasoningStrategy.SEQUENTIAL: self.chain_of_thought,
            ReasoningStrategy.TREE_OF_THOUGHT: self.tree_of_thought,
            ReasoningStrategy.CONSENSUS: self.consensus,
            ReasoningStrategy.DEBATE: self.debate,
            ReasoningStrategy.SELF_CORRECTION: self.self_correction,
            ReasoningStrategy.RECURSIVE: self.recursive,
        }.get(strategy, self.chain_of_thought)
        return fn(request)

    # ── strategies ──────────────────────────────────────────────────────────────
    def chain_of_thought(self, request: InferenceRequest) -> ReasoningResult:
        # the task executor picks the best model and retries a backup on failure
        if self._task_exec is not None:
            res = self._task_exec(request)
        else:
            models = self._models_for(request.task, 1)
            if not models:
                return ReasoningResult(strategy="chain_of_thought", ok=False,
                                       error=f"no model for task {request.task}")
            res = self._run(models[0], request)
        return ReasoningResult(strategy="chain_of_thought", ok=res.ok, answer=res.text,
                               structured=res.structured, confidence=res.confidence,
                               models_used=[res.model], agreement=1.0,
                               steps=res.structured.get("steps", []), error=res.error)

    def consensus(self, request: InferenceRequest, *, n: int = 3) -> ReasoningResult:
        models = self._models_for(request.task, n) or self._registry.all()[:n]
        results = [self._run(m, request) for m in models]
        ok_results = [r for r in results if r.ok and r.text]
        if not ok_results:
            return ReasoningResult(strategy="consensus", ok=False, error="all models failed")
        clusters: dict[str, list] = {}
        for r in ok_results:
            clusters.setdefault(_norm(r.text), []).append(r)
        best = max(clusters.values(), key=len)
        agreement = len(best) / len(ok_results)
        top = max(best, key=lambda r: r.confidence)
        return ReasoningResult(strategy="consensus", ok=True, answer=top.text,
                               structured=top.structured,
                               confidence=round(top.confidence * (0.6 + 0.4 * agreement), 4),
                               models_used=[r.model for r in ok_results], agreement=round(agreement, 4))

    def debate(self, request: InferenceRequest) -> ReasoningResult:
        models = self._models_for(request.task, 2)
        if len(models) < 2:
            models = self._registry.all()[:2]      # borrow from the roster for a 2nd voice
        if len(models) < 2:
            return self.chain_of_thought(request)
        a, b = self._run(models[0], request), self._run(models[1], request)
        ra = self._critic.review(a.text, structured=a.structured, context=request.context,
                                 confidence=a.confidence)
        rb = self._critic.review(b.text, structured=b.structured, context=request.context,
                                 confidence=b.confidence)
        winner, wr = (a, ra) if ra.confidence_delta >= rb.confidence_delta else (b, rb)
        return ReasoningResult(strategy="debate", ok=winner.ok, answer=winner.text,
                               structured=winner.structured,
                               confidence=round(max(0.0, winner.confidence + wr.confidence_delta), 4),
                               models_used=[a.model, b.model], agreement=0.5,
                               steps=wr.suggestions)

    def tree_of_thought(self, request: InferenceRequest, *, branches: int = 3) -> ReasoningResult:
        model = (self._models_for(request.task, 1) or [None])[0]
        if model is None:
            return ReasoningResult(strategy="tree_of_thought", ok=False, error="no model")
        candidates = []
        for i in range(branches):
            req = InferenceRequest(task=request.task, prompt=request.prompt,
                                   context=request.context, max_tokens=request.max_tokens,
                                   temperature=min(1.0, 0.2 + 0.3 * i), trace_id=request.trace_id)
            r = self._run(model, req)
            score = (r.confidence + (0.2 if r.structured else 0.0) + min(0.2, len(r.text) / 500))
            candidates.append((score, r))
        candidates.sort(key=lambda t: t[0], reverse=True)
        best = candidates[0][1]
        return ReasoningResult(strategy="tree_of_thought", ok=best.ok, answer=best.text,
                               structured=best.structured, confidence=best.confidence,
                               models_used=[best.model], agreement=1.0,
                               steps=[f"explored {branches} branches"])

    def self_correction(self, request: InferenceRequest) -> ReasoningResult:
        first = self.chain_of_thought(request)
        if not first.ok:
            return first
        report = self._critic.review(first.answer, structured=first.structured,
                                     context=request.context, confidence=first.confidence)
        if report.ok and not report.issues:
            first.steps = first.steps + ["critic: passed"]
            return first
        # re-run with the critic's suggestions appended
        improved_prompt = (request.prompt + "\n\nAddress: " + "; ".join(report.suggestions))
        req2 = InferenceRequest(task=request.task, prompt=improved_prompt,
                                context=request.context, trace_id=request.trace_id)
        second = self.chain_of_thought(req2)
        second.strategy = "self_correction"
        second.steps = ["draft", "critic"] + report.suggestions + ["revised"]
        second.confidence = round(max(second.confidence, first.confidence + report.confidence_delta), 4)
        return second

    def recursive(self, request: InferenceRequest, *, subtasks: Optional[list] = None
                  ) -> ReasoningResult:
        subtasks = subtasks or request.context.get("subtasks") or []
        if not subtasks:
            return self.chain_of_thought(request)
        parts = []
        for st in subtasks:
            req = InferenceRequest(task=request.task, prompt=str(st),
                                   context=request.context, trace_id=request.trace_id)
            parts.append(self.chain_of_thought(req))
        answer = " | ".join(p.answer for p in parts if p.ok)
        conf = sum(p.confidence for p in parts) / len(parts)
        return ReasoningResult(strategy="recursive", ok=any(p.ok for p in parts),
                               answer=answer, structured={"subresults": [p.to_dict() for p in parts]},
                               confidence=round(conf, 4),
                               models_used=sorted({m for p in parts for m in p.models_used}),
                               steps=[f"{len(subtasks)} subtasks"])

    def parallel(self, requests: list[InferenceRequest]) -> list[ReasoningResult]:
        if not requests:
            return []
        with ThreadPoolExecutor(max_workers=min(self._max_parallel, len(requests))) as ex:
            return list(ex.map(self.chain_of_thought, requests))

    # ── the engineering team (collaboration) ────────────────────────────────────
    def collaborate(self, request: InferenceRequest) -> ReasoningResult:
        """Research → Planning → (task model) → Critic → Executive synthesis.
        Every stage contributes; the executive synthesises, no model dominates."""
        steps, used = [], []

        def stage(task: str, prompt: str):
            models = self._models_for(task, 1)
            if not models:
                return None
            r = self._run(models[0], InferenceRequest(task=task, prompt=prompt,
                                                      context=request.context,
                                                      trace_id=request.trace_id))
            used.append(r.model)
            steps.append({"stage": task, "model": r.model, "ok": r.ok})
            return r

        research = stage(TaskType.RESEARCH.value, request.prompt)
        plan = stage(TaskType.PLANNING.value, request.prompt)
        worker = stage(request.task, request.prompt)
        primary = worker or research or plan
        if primary is None:
            return ReasoningResult(strategy="collaborate", ok=False, error="no models available")

        report = self._critic.review(primary.text, structured=primary.structured,
                                     context=request.context, confidence=primary.confidence)
        agreement = sum(1 for r in (research, plan, worker) if r and r.ok) / 3.0
        conf = self._confidence.estimate(context=request.context, agreement=agreement,
                                         past_accuracy=primary.confidence,
                                         reasoning_depth=len(steps))
        final_conf = round(max(0.0, min(1.0, conf.score + report.confidence_delta)), 4)
        return ReasoningResult(
            strategy="collaborate", ok=primary.ok,
            answer=primary.text,
            structured={"research": research.structured if research else {},
                        "plan": plan.structured if plan else {},
                        "result": primary.structured, "critic": report.to_dict(),
                        "confidence": conf.to_dict()},
            confidence=final_conf, models_used=used, agreement=round(agreement, 4), steps=steps)
