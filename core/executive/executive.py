"""
core/executive/executive.py — FRIDAY 4.0 (M5)
The Executive Brain: FRIDAY's central cognition layer. It sits between Goals and
Skills in the pipeline

    Runtime → Memory → Goals → Executive Brain → Skills → Security → Audit

and turns intent into action: it builds context (Context Engine), prioritizes
(Attention), reasons (Reasoner), plans (executive Planner), and delegates
execution (Orchestrator → SkillExecutor) — recording every decision to the
Decision Log, storing learning to the Memory Service, and emitting events on the
Runtime bus.

Every dependency is injected and optional; defaults are constructed lazily so the
brain works standalone in tests and fully wired in production. Import is
side-effect free.
"""

from __future__ import annotations

import logging
import threading
import time
from enum import Enum
from typing import Optional

from .orchestrator import Orchestrator
from .planner import ExecutivePlanner, Plan, PlanResult
from .reasoner import Reasoner, ReasoningResult
from .state import CognitiveState, CognitiveStateStore, FocusState

log = logging.getLogger("friday.executive.brain")


class ExecEvent(str, Enum):
    THOUGHT = "executive.thought"
    DECISION = "executive.decision"
    PLAN_CREATED = "executive.plan_created"
    PLAN_COMPLETED = "executive.plan_completed"
    PLAN_FAILED = "executive.plan_failed"


class ExecutiveBrain:
    def __init__(self, *, runtime=None, memory_service=None, goal_service=None,
                 skill_executor=None, decision_log=None, context_builder=None,
                 attention=None, world_model=None, reasoner=None, planner=None,
                 orchestrator=None, state_store=None) -> None:
        self._runtime = runtime
        self._memory = memory_service
        self._goals = goal_service
        self._decision = decision_log

        self._attention = attention if attention is not None else self._default_attention()
        self._world = world_model
        self._context = context_builder if context_builder is not None \
            else self._default_context()
        self._reasoner = reasoner if reasoner is not None else Reasoner()
        self._planner = planner if planner is not None else ExecutivePlanner()
        self._orchestrator = orchestrator if orchestrator is not None else Orchestrator(
            skill_executor=skill_executor, goal_service=goal_service,
            memory_service=memory_service, runtime=runtime, decision_log=decision_log)
        self._state_store = state_store
        self._state = state_store.load() if state_store is not None else CognitiveState()

        self._metrics = {
            "thoughts": 0, "plans_created": 0, "plans_completed": 0,
            "plans_failed": 0, "reasoning_cycles": 0,
        }
        self._lock = threading.Lock()

    # ── public API ─────────────────────────────────────────────────────────────
    def think(self, query: str) -> ReasoningResult:
        """Build context for `query`, reason over it, update focus, and record."""
        from core.observability import new_trace_id
        trace_id = new_trace_id()
        goals = self._all_goals()
        context = self._context.build(query, trace_id=trace_id)
        if self._world is not None:
            self._world.observe("runtime", "thought", state={"query": query})
        reasoning = self._reasoner.analyze(context, goals=goals)

        focus = reasoning.recommended_focus
        if focus:
            self._set_focus(FocusState(
                target_id=focus.get("target_id", ""), kind="goal",
                label=focus.get("label", ""), score=focus.get("score", 0.0)),
                objective=query)

        with self._lock:
            self._metrics["thoughts"] += 1
            self._metrics["reasoning_cycles"] += 1
        self._observe("executive.think", reasoning.rationale, reasoning.confidence,
                      trace_id=trace_id)
        self._emit(ExecEvent.THOUGHT, {"query": query, "confidence": reasoning.confidence,
                                       "rationale": reasoning.rationale})
        return reasoning

    def decide(self, objective: str, goals: Optional[list] = None) -> Plan:
        """Reason about an objective and produce an executable plan."""
        self.think(objective)
        goal_list = goals if goals is not None else self._all_goals()
        if goal_list:
            plan = self._planner.from_goals(goal_list, objective=objective)
        else:
            plan = self._planner.build_plan(objective)
        self._state.active_plan = plan.plan_id
        self._state.current_objective = objective
        self._persist_state()
        with self._lock:
            self._metrics["plans_created"] += 1
        self._observe("executive.decide", f"plan {plan.plan_id}: {objective}", 0.8,
                      goals=[g.goal_id for g in goal_list])
        self._emit(ExecEvent.PLAN_CREATED, {"plan_id": plan.plan_id, "objective": objective,
                                            "steps": len(plan.steps)})
        return plan

    def evaluate(self, plan: Plan) -> dict:
        """Assess a plan's readiness and feasibility before committing to run it."""
        decision = self._orchestrator.decide(plan)
        total = len(plan.steps)
        ready = len(decision["execute"])
        blocked = len(decision["blocked"])
        feasible = blocked == 0 and total > 0
        confidence = round((ready / total) if total else 0.0, 3)
        return {
            "plan_id": plan.plan_id, "feasible": feasible, "steps_total": total,
            "ready": ready, "blocked": blocked, "waiting": len(decision["wait"]),
            "confidence": confidence,
        }

    def execute_plan(self, plan: Plan, context=None) -> PlanResult:
        """Delegate execution to the Orchestrator (→ SkillExecutor) and learn."""
        result = self._orchestrator.execute_plan(plan, context)
        with self._lock:
            if result.success:
                self._metrics["plans_completed"] += 1
            else:
                self._metrics["plans_failed"] += 1
        self._learn(plan, result)
        event = ExecEvent.PLAN_COMPLETED if result.success else ExecEvent.PLAN_FAILED
        self._observe("executive.execute_plan",
                      f"{len(result.completed)}/{result.steps_total} steps done",
                      1.0 if result.success else 0.3)
        self._emit(event, {"plan_id": plan.plan_id, "success": result.success,
                           "completed": len(result.completed), "failed": len(result.failed)})
        return result

    def status(self) -> dict:
        return {
            "state": self._state.to_dict(),
            "metrics": dict(self._metrics),
            "attention": self._attention.metrics(),
        }

    def health(self) -> dict:
        h = {
            "status": "ok",
            "thoughts": self._metrics["thoughts"],
            "plans_created": self._metrics["plans_created"],
            "context": self._context.health(),
            "attention": self._attention.health(),
            "reasoner": self._reasoner.health(),
            "orchestrator": self._orchestrator.health(),
        }
        if self._world is not None:
            h["world"] = self._world.health()
        return h

    def metrics(self) -> dict:
        m = dict(self._metrics)
        m.update({"attention_evaluations": self._attention.metrics()["evaluations"],
                  "steps_executed": self._orchestrator.metrics()["steps_executed"]})
        return m

    def attach(self, runtime) -> None:
        """Wire the brain (and its subsystems) into the Runtime health surface."""
        self._runtime = runtime
        self._orchestrator._runtime = runtime
        runtime.register_health("executive", self.health)
        runtime.register_health("context", self._context.health)
        runtime.register_health("attention", self._attention.health)
        if self._world is not None:
            runtime.register_health("world", self._world.health)

    # ── accessors (used by the cognitive loop) ─────────────────────────────────
    @property
    def context_builder(self):
        return self._context

    @property
    def reasoner(self):
        return self._reasoner

    @property
    def planner(self):
        return self._planner

    @property
    def orchestrator(self):
        return self._orchestrator

    @property
    def attention(self):
        return self._attention

    @property
    def state(self) -> CognitiveState:
        return self._state

    # ── internals ──────────────────────────────────────────────────────────────
    def _all_goals(self) -> list:
        if self._goals is None:
            return []
        try:
            return self._goals.list_goals()
        except Exception:
            return []

    def _set_focus(self, focus: FocusState, objective: str = "") -> None:
        self._state.current_focus = focus
        self._state.active_goal = focus.target_id or self._state.active_goal
        if objective:
            self._state.current_objective = objective
        self._persist_state()

    def _persist_state(self) -> None:
        if self._state_store is not None:
            try:
                self._state_store.save(self._state)
            except Exception:
                log.debug("cognitive-state save failed", exc_info=True)

    def _learn(self, plan: Plan, result: PlanResult) -> None:
        if self._memory is None:
            return
        verdict = "succeeded" if result.success else "had failures"
        content = (f"Executed plan for '{plan.objective}' — {verdict}: "
                   f"{len(result.completed)} done, {len(result.failed)} failed.")
        try:
            self._memory.remember("system", content, topic=plan.objective,
                                  kind="plan_outcome", importance=0.6,
                                  metadata={"plan_id": plan.plan_id, "success": result.success})
        except Exception:
            log.debug("plan-learning write failed", exc_info=True)

    def _observe(self, intent: str, rationale: str, confidence: float,
                 goals: Optional[list] = None, trace_id: Optional[str] = None) -> None:
        if self._decision is None:
            return
        try:
            from core.observability import new_trace_id
            self._decision.log(
                trace_id=trace_id or new_trace_id(), intent=intent,
                route=["executive"], goals_touched=goals or [],
                outcome="ok", rationale=rationale, confidence=confidence,
                was_autonomous=True, source="executive.brain",
            )
        except Exception:
            log.debug("executive decision-log write failed", exc_info=True)

    def _emit(self, event: ExecEvent, data: dict) -> None:
        if self._runtime is None:
            return
        try:
            self._runtime.emit(event, data=data, source="executive")
        except Exception:
            log.debug("executive event emit failed", exc_info=True)

    # ── lazy defaults ──────────────────────────────────────────────────────────
    def _default_attention(self):
        from core.attention import AttentionSystem
        return AttentionSystem()

    def _default_context(self):
        from core.context import ContextBuilder
        return ContextBuilder(memory_service=self._memory, goal_service=self._goals,
                              attention=self._attention, world_model=self._world)


# ── singleton ───────────────────────────────────────────────────────────────────
_brain: Optional[ExecutiveBrain] = None
_brain_lock = threading.Lock()


def get_executive_brain() -> ExecutiveBrain:
    global _brain
    with _brain_lock:
        if _brain is None:
            _brain = ExecutiveBrain()
    return _brain
