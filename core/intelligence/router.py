"""
core/intelligence/router.py — FRIDAY 4.0 (M12)
The Intelligence Router (Parts 1 & 3) — the heart of FRIDAY. Every request enters
here. It classifies the task and complexity, chooses a reasoning strategy and the
models to use, routes the request through the reasoning engine (which retries on a
backup model via the execution manager), estimates confidence, and returns a
structured response. Sub-second routing: classification is keyword + length based,
selection is an O(1) registry lookup.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Optional

from .base import Complexity, InferenceRequest, TaskType, new_id
from .confidence_engine import ConfidenceEngine
from .critic import CriticEngine
from .reasoning_engine import ReasoningEngine, ReasoningStrategy
from .registry import IntelligenceRegistry

# task → keywords for classification
_TASK_KEYWORDS = {
    TaskType.CODING.value: ("code", "bug", "debug", "function", "python", "compile", "refactor"),
    TaskType.MATH.value: ("calculate", "compute", "solve", "equation", "+", "*", "integral"),
    TaskType.PLANNING.value: ("plan", "schedule", "roadmap", "steps", "milestone", "organize"),
    TaskType.RESEARCH.value: ("research", "find out", "investigate", "paper", "explain how"),
    TaskType.WRITING.value: ("write", "draft", "compose", "essay", "summary"),
    TaskType.MEMORY_RETRIEVAL.value: ("remember", "recall", "what did", "previously", "last time"),
    TaskType.SIMULATION.value: ("simulate", "what if", "scale to", "stress test"),
    TaskType.AGENT_COORDINATION.value: ("agents", "team", "coordinate", "delegate"),
    TaskType.SCIENTIFIC.value: ("hypothesis", "experiment", "theory", "scientific"),
    TaskType.VISION.value: ("image", "photo", "see", "detect object"),
    TaskType.OCR.value: ("ocr", "read text", "screenshot text"),
    TaskType.SPEECH.value: ("transcribe", "speak", "say", "voice"),
    TaskType.AUTOMATION.value: ("automate", "workflow", "trigger when"),
    TaskType.WEB.value: ("search the web", "browse", "url", "website"),
    TaskType.ROBOTICS.value: ("move", "actuate", "motor", "navigate"),
}


@dataclass
class RouterResponse:
    task: str
    complexity: str
    strategy: str
    ok: bool = True
    answer: str = ""
    structured: dict = field(default_factory=dict)
    confidence: float = 0.0
    models_used: list = field(default_factory=list)
    agreement: float = 0.0
    trace_id: str = ""
    latency_ms: float = 0.0
    error: str = ""

    def to_dict(self) -> dict:
        return dict(self.__dict__)


class IntelligenceRouter:
    def __init__(self, registry: IntelligenceRegistry, reasoning: ReasoningEngine, *,
                 confidence: Optional[ConfidenceEngine] = None,
                 critic: Optional[CriticEngine] = None) -> None:
        self._registry = registry
        self._reasoning = reasoning
        self._confidence = confidence or ConfidenceEngine()
        self._critic = critic or CriticEngine()

    # ── classification ──────────────────────────────────────────────────────────
    def classify(self, prompt: str) -> tuple[str, str]:
        p = (prompt or "").lower()
        best_task, best_hits = TaskType.GENERAL.value, 0
        for task, kws in _TASK_KEYWORDS.items():
            hits = sum(1 for kw in kws if kw in p)
            if hits > best_hits:
                best_task, best_hits = task, hits
        return best_task, self._complexity(prompt)

    @staticmethod
    def _complexity(prompt: str) -> str:
        n = len(prompt or "")
        markers = sum(1 for m in ("and", "then", "compare", "why", "how", "design", "multiple")
                      if m in (prompt or "").lower())
        if n < 24 and markers == 0:
            return Complexity.TRIVIAL.value
        if n < 80 and markers <= 1:
            return Complexity.SMALL.value
        if markers >= 3 or n > 240:
            return Complexity.LARGE.value
        return Complexity.MEDIUM.value

    def choose_strategy(self, task: str, complexity: str) -> ReasoningStrategy:
        if complexity == Complexity.TRIVIAL.value:
            return ReasoningStrategy.CHAIN_OF_THOUGHT
        if complexity == Complexity.SMALL.value:
            return ReasoningStrategy.SELF_CORRECTION
        if complexity == Complexity.LARGE.value:
            return ReasoningStrategy.CONSENSUS
        return ReasoningStrategy.SELF_CORRECTION

    def select_models(self, task: str) -> dict:
        cands = self._registry.by_capability(task)
        return {"primary": cands[0].info.name if cands else None,
                "backup": cands[1].info.name if len(cands) > 1 else None,
                "available": [m.info.name for m in cands]}

    # ── routing ─────────────────────────────────────────────────────────────────
    def route(self, prompt: str, *, task: Optional[str] = None,
              context: Optional[dict] = None, strategy: Optional[ReasoningStrategy] = None,
              collaborate: bool = False) -> RouterResponse:
        t0 = time.perf_counter()
        context = context or {}
        if task is None:
            task, complexity = self.classify(prompt)
        else:
            complexity = self._complexity(prompt)
        strat = strategy or self.choose_strategy(task, complexity)
        request = InferenceRequest(task=task, prompt=prompt, context=context, trace_id=new_id())

        if collaborate or complexity == Complexity.LARGE.value:
            result = self._reasoning.collaborate(request)
            strat = ReasoningStrategy(result.strategy) if result.strategy in \
                [s.value for s in ReasoningStrategy] else strat
        else:
            result = self._reasoning.reason(request, strat)

        # confidence (blend the reasoning result with the signal model)
        conf = self._confidence.estimate(
            context=context, agreement=result.agreement,
            past_accuracy=result.confidence,
            reasoning_depth=len(result.steps) or 1)
        final_conf = round((result.confidence + conf.score) / 2, 4) if result.confidence \
            else conf.score

        return RouterResponse(
            task=task, complexity=complexity, strategy=result.strategy,
            ok=result.ok, answer=result.answer, structured=result.structured,
            confidence=final_conf, models_used=result.models_used,
            agreement=result.agreement, trace_id=request.trace_id,
            latency_ms=round((time.perf_counter() - t0) * 1000.0, 3), error=result.error)
