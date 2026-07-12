"""
core/intelligence/service.py — FRIDAY 4.0 (M12)
The Intelligence Operating System facade. Wires every component — registry, model
manager, cache, execution manager, reasoning engine, context builder, confidence,
critic, planner, trace manager, reflection, learning, health, benchmark, optimizer,
router — behind one entry point: `think()`.

Local-first: the builtin local model team is always loaded, so the IOS works with no
external dependencies and never requires cloud AI. Cloud models, if ever registered,
are opt-in plugins behind the same protocol. Side-effect-free to import (the store /
models load only when the OS is constructed/bootstrapped).
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from typing import Optional

from .base import TaskType
from .benchmark import BenchmarkSystem
from .cache import IntelligenceCache
from .confidence_engine import ConfidenceEngine
from .context_builder import ContextBuilder
from .critic import CriticEngine
from .execution_manager import ExecutionManager
from .health_monitor import HealthMonitor
from .learning_engine import IntelligenceLearningEngine
from .model_manager import ModelManager
from .optimizer import Optimizer
from .planner import IntelligencePlanner
from .reasoning_engine import ReasoningEngine, ReasoningStrategy
from .reflection_engine import ReflectionEngine
from .registry import IntelligenceRegistry
from .router import IntelligenceRouter, RouterResponse
from .store import IntelligenceStore
from .trace_manager import TraceManager

log = logging.getLogger("friday.intelligence")


class IntelligenceOS:
    def __init__(self, store: Optional[IntelligenceStore] = None, *,
                 memory_service=None, knowledge_service=None, goal_service=None,
                 user_model=None, society=None, simulation_service=None,
                 core_memory=None,
                 cache_capacity: int = 1024, bootstrap: bool = True,
                 discover_optional: bool = False) -> None:
        self._store = store if store is not None else IntelligenceStore()
        # core
        self.registry = IntelligenceRegistry(self._store)
        self.cache = IntelligenceCache(capacity=cache_capacity)
        self.health = HealthMonitor()
        self.models = ModelManager(self.registry, health=self.health)
        self.execution = ExecutionManager(self.registry, health=self.health, cache=self.cache)
        self.confidence = ConfidenceEngine()
        self.critic = CriticEngine()
        self.reasoning = ReasoningEngine(
            self.registry, executor=self.execution.run,
            task_executor=self.execution.execute, critic=self.critic,
            confidence=self.confidence)
        self.router = IntelligenceRouter(self.registry, self.reasoning,
                                         confidence=self.confidence, critic=self.critic)
        # context + provenance + improvement
        self.context_builder = ContextBuilder(
            memory_service=memory_service, knowledge_service=knowledge_service,
            goal_service=goal_service, user_model=user_model, society=society,
            simulation_service=simulation_service, core_memory=core_memory)
        self.traces = TraceManager(self._store)
        self.planner = IntelligencePlanner(self.reasoning, society=society)
        self.reflection = ReflectionEngine(knowledge_service)
        self.learning = IntelligenceLearningEngine(knowledge_service)
        self.benchmark = BenchmarkSystem(self._store)
        self.optimizer = Optimizer(cache=self.cache, model_manager=self.models,
                                   health=self.health)
        # M33: deterministic fast path — specialist mini brains answer common
        # task shapes in milliseconds before the model team is consulted.
        # RecallBrain shares One Memory so "do you remember…" sees everything
        # the learning gate stored (including taught knowledge).
        from .mini_brains import MiniBrainCortex
        self.cortex = MiniBrainCortex(memory=memory_service)
        if bootstrap:
            self.models.bootstrap(discover_optional=discover_optional)

    # ── the main entry point ────────────────────────────────────────────────────
    def think(self, prompt: str, *, task: Optional[str] = None,
              context: Optional[dict] = None, strategy: Optional[ReasoningStrategy] = None,
              collaborate: bool = False, learn: bool = True,
              build_context: bool = True, use_mini_brains: bool = True) -> RouterResponse:
        """Mini-brain fast path → build context → route through the model team →
        record a trace → reflect and learn. The single way the rest of FRIDAY
        asks the IOS to think."""
        t0 = time.perf_counter()
        ctx = dict(context or {})

        # M33 fast path: a specialist that can answer EXACTLY does so in
        # milliseconds, before context building or model routing. Misses fall
        # through with zero behaviour change.
        if use_mini_brains and not collaborate:
            mini = self.cortex.try_answer(prompt)
            if mini is not None:
                classified_task = task or self.router.classify(prompt)[0]
                trace = self.traces.start(prompt, classified_task, context=ctx)
                response = RouterResponse(
                    task=classified_task, complexity="trivial",
                    strategy=f"mini:{mini.brain}", ok=True, answer=mini.answer,
                    confidence=mini.confidence, models_used=[],
                    latency_ms=mini.elapsed_ms, context_used=ctx)
                elapsed = (time.perf_counter() - t0) * 1000.0
                self.traces.finish(trace, outcome=response.answer,
                                   confidence=response.confidence,
                                   models=[], execution_ms=elapsed,
                                   reasoning={"strategy": response.strategy,
                                              "complexity": "trivial"})
                response.trace_id = trace.id
                return response

        if build_context:
            ctx = {**self.context_builder.build(prompt, seed=ctx), **ctx}
        classified_task = task or self.router.classify(prompt)[0]
        trace = self.traces.start(prompt, classified_task, context=ctx)

        response = self.router.route(prompt, task=classified_task, context=ctx,
                                     strategy=strategy, collaborate=collaborate)

        elapsed = (time.perf_counter() - t0) * 1000.0
        self.traces.finish(trace, outcome=response.answer, confidence=response.confidence,
                           models=response.models_used, execution_ms=elapsed,
                           reasoning={"strategy": response.strategy,
                                      "complexity": response.complexity})
        response.trace_id = trace.id

        if learn:
            self.reflection.reflect(task=classified_task, success=response.ok,
                                    duration_ms=elapsed, models=response.models_used,
                                    outcome=response.answer)
            if response.confidence >= 0.6 and response.ok:
                self.learning.learn_from_reasoning(trace.to_dict())
        return response

    async def think_async(self, prompt: str, **kw) -> RouterResponse:
        """Async wrapper for concurrent requests (offloads the CPU-bound reasoning
        to a worker thread)."""
        return await asyncio.to_thread(self.think, prompt, **kw)

    # ── planning ────────────────────────────────────────────────────────────────
    def plan(self, goal: str, *, execute: bool = False):
        plan = self.planner.plan(goal, context=self.context_builder.build(goal))
        if execute:
            self.planner.execute(plan)
        return plan

    # ── benchmarking / optimization ─────────────────────────────────────────────
    def benchmark_all(self) -> dict:
        results = {m.info.name: self.benchmark.run_all(m) for m in self.registry.all()}
        ranking = self.benchmark.rank(self.registry.all(), "overall")
        return {"results": results, "ranking": ranking}

    def optimize(self) -> dict:
        return self.optimizer.self_improvement()

    # ── observability ───────────────────────────────────────────────────────────
    def dashboard(self) -> dict:
        from .dashboard import IntelligenceDashboard
        return IntelligenceDashboard(self).snapshot()

    def status(self) -> dict:
        return {"models": self.models.status(), "cache": self.cache.stats(),
                "traces": self._store.counts()["traces"],
                "registry": self.registry.health(),
                "mini_brains": self.cortex.stats()}

    def health_report(self) -> dict:
        return {"status": "ok", "local_first": True,
                "models_loaded": len(self.models.loaded_models()),
                "health": self.health.health(), "cache": self.cache.stats()}

    def attach(self, runtime) -> None:
        try:
            runtime.register_health("intelligence", self.health_report)
        except Exception:  # noqa: BLE001
            log.debug("attach failed", exc_info=True)

    def close(self) -> None:
        self._store.close()


_os: Optional[IntelligenceOS] = None
_lock = threading.Lock()


def get_intelligence_os(**kw) -> IntelligenceOS:
    global _os
    with _lock:
        if _os is None:
            _os = IntelligenceOS(**kw)
    return _os


def think_text(prompt: str, *, task: Optional[str] = None,
               context: Optional[dict] = None) -> str:
    """
    One-shot think through the Intelligence OS, returning plain text. The
    drop-in replacement for the legacy `friday_neural.think()` in callers that
    just want an answer string (proactive nudges, PDF notes, HUD turns).
    """
    response = get_intelligence_os().think(prompt, task=task, context=context)
    return (getattr(response, "answer", "") or "").strip()
