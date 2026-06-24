"""
core/cognition/loop.py — FRIDAY 4.0 (M5)
The Cognitive Loop: FRIDAY's thinking cycle, wired through the Executive Brain.

One cycle runs ten phases:
  Observe → Build Context → Update World Model → Apply Attention → Reason →
  Plan → Select Action → Execute Skill → Reflect → Store Learning

The loop is **event-driven via the Runtime scheduler** — it is never a `while
True`. `run_cycle()` performs exactly one pass and returns; `start()` schedules it
periodically; `stop()` cancels it. Both are idempotent and safe. Actual skill work
is delegated to the Orchestrator → SkillExecutor, so the loop can never bypass the
M3 security pipeline.
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

log = logging.getLogger("friday.cognition.loop")


class CognitivePhase(str, Enum):
    OBSERVE = "observe"
    CONTEXT = "context"
    WORLD = "world"
    ATTENTION = "attention"
    REASON = "reason"
    PLAN = "plan"
    SELECT = "select"
    EXECUTE = "execute"
    REFLECT = "reflect"
    LEARN = "learn"


class CognitionEvent(str, Enum):
    CYCLE = "cognition.cycle"


@dataclass
class CycleResult:
    cycle_id: str
    ts: float
    phases: list = field(default_factory=list)
    reasoning: Optional[dict] = None
    plan_id: Optional[str] = None
    actions: list = field(default_factory=list)
    notes: str = ""

    def to_dict(self) -> dict:
        return dict(self.__dict__)


class CognitiveLoop:
    def __init__(self, brain, runtime=None, goal_service=None, memory_service=None,
                 world_model=None, interval_s: float = 30.0,
                 auto_execute: bool = True) -> None:
        self._brain = brain
        self._runtime = runtime
        self._goals = goal_service
        self._memory = memory_service
        self._world = world_model
        self._interval = interval_s
        self._auto_execute = auto_execute
        self._running = False
        self._cycles = 0
        self._actions = 0
        self._lock = threading.Lock()
        self._last: Optional[CycleResult] = None

    # ── one pass ───────────────────────────────────────────────────────────────
    def run_cycle(self, trigger: Optional[str] = None) -> CycleResult:
        cycle = CycleResult(cycle_id=uuid.uuid4().hex[:10], ts=time.time())
        try:
            # 1. OBSERVE
            goals = self._observe()
            cycle.phases.append(CognitivePhase.OBSERVE.value)

            objective = trigger or self._brain.state.current_objective or "review active goals"

            # 2. BUILD CONTEXT
            context = self._brain.context_builder.build(objective)
            cycle.phases.append(CognitivePhase.CONTEXT.value)

            # 3. UPDATE WORLD MODEL
            if self._world is not None:
                self._world.observe("runtime", "cognition",
                                    state={"cycle": self._cycles + 1, "goals": len(goals)})
            cycle.phases.append(CognitivePhase.WORLD.value)

            # 4. APPLY ATTENTION
            ranked = self._brain.attention.rank_goals(goals)
            cycle.phases.append(CognitivePhase.ATTENTION.value)

            # 5. REASON
            reasoning = self._brain.reasoner.analyze(context, goals=goals)
            cycle.reasoning = reasoning.to_dict()
            cycle.phases.append(CognitivePhase.REASON.value)

            # 6. PLAN
            plan = None
            if goals:
                plan = self._brain.planner.from_goals(goals, objective=objective)
                cycle.plan_id = plan.plan_id
            cycle.phases.append(CognitivePhase.PLAN.value)

            # 7. SELECT ACTION
            selected = None
            if plan is not None:
                ready = plan.ready_steps()
                selected = ready[0] if ready else None
            cycle.phases.append(CognitivePhase.SELECT.value)

            # 8. EXECUTE SKILL (delegated → SkillExecutor; never bypasses security)
            if selected is not None and self._auto_execute:
                self._brain.orchestrator.execute_step(selected)
                cycle.actions.append(selected.step_id)
                with self._lock:
                    self._actions += 1
            cycle.phases.append(CognitivePhase.EXECUTE.value)

            # 9. REFLECT
            cycle.notes = reasoning.rationale
            cycle.phases.append(CognitivePhase.REFLECT.value)

            # 10. STORE LEARNING
            self._learn(objective, reasoning, cycle)
            cycle.phases.append(CognitivePhase.LEARN.value)

        except Exception:
            log.exception("cognitive cycle failed")
            cycle.notes = "cycle error (contained)"

        with self._lock:
            self._cycles += 1
            self._last = cycle
        self._emit_cycle(cycle)
        return cycle

    # ── lifecycle (event-driven; idempotent) ───────────────────────────────────
    def start(self) -> bool:
        with self._lock:
            if self._running:
                return False
            self._running = True
        if self._runtime is not None:
            self._runtime.schedule("cognition.loop", self.run_cycle, every=self._interval)
            if hasattr(self._runtime, "register_health"):
                self._runtime.register_health("cognition", self.health)
        log.info("cognitive loop started (interval=%ss)", self._interval)
        return True

    def stop(self) -> bool:
        with self._lock:
            if not self._running:
                return False
            self._running = False
        if self._runtime is not None:
            self._runtime.cancel_schedule("cognition.loop")
        log.info("cognitive loop stopped")
        return True

    @property
    def running(self) -> bool:
        return self._running

    # ── diagnostics ────────────────────────────────────────────────────────────
    def status(self) -> dict:
        return {"running": self._running, "cycles": self._cycles,
                "actions": self._actions,
                "last": self._last.to_dict() if self._last else None}

    def metrics(self) -> dict:
        return {"cognition_cycles": self._cycles, "actions_taken": self._actions}

    def health(self) -> dict:
        return {"status": "ok", "running": self._running, "cycles": self._cycles}

    # ── internals ──────────────────────────────────────────────────────────────
    def _observe(self) -> list:
        if self._goals is None:
            return []
        try:
            return self._goals.list_goals()
        except Exception:
            return []

    def _learn(self, objective: str, reasoning, cycle: CycleResult) -> None:
        if self._memory is None:
            return
        try:
            self._memory.remember(
                "system",
                f"Cognitive cycle on '{objective}': {reasoning.rationale}",
                topic="cognition", kind="cognition", importance=0.3,
                metadata={"cycle_id": cycle.cycle_id, "actions": cycle.actions},
            )
        except Exception:
            log.debug("cognition learning write failed", exc_info=True)

    def _emit_cycle(self, cycle: CycleResult) -> None:
        if self._runtime is None:
            return
        try:
            self._runtime.emit(CognitionEvent.CYCLE,
                               data={"cycle_id": cycle.cycle_id, "phases": len(cycle.phases),
                                     "actions": len(cycle.actions)}, source="cognition")
        except Exception:
            log.debug("cognition event emit failed", exc_info=True)
