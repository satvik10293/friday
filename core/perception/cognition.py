"""
core/perception/cognition.py — FRIDAY 4.0 (M6)
PerceptiveCognitiveLoop: an additive subclass of the M5 CognitiveLoop that makes
Observe and Fuse first-class phases. The full cycle becomes:

  Observe → Fuse → Context → World → Attention → Reason → Plan → Select →
  Execute → Reflect → Learn

Observe polls real sensors; Fuse corroborates multi-sensor readings; the fused
observations are ingested through perception (which promotes important facts into
the world model) *before* context is built — so the brain reasons over current
reality. Delivered as a subclass to honor M6's "no M1–M5 modification" rule.
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import Optional

from core.cognition.loop import CognitiveLoop, CycleResult

log = logging.getLogger("friday.perception.cognition")

# the expanded phase order (observe + fuse prepended to the M5 ten)
PERCEPTION_PHASES = [
    "observe", "fuse", "context", "world", "attention", "reason",
    "plan", "select", "execute", "reflect", "learn",
]


class PerceptiveCognitiveLoop(CognitiveLoop):
    def __init__(self, brain, sensor_manager=None, perception_manager=None,
                 fusion=None, **kwargs) -> None:
        super().__init__(brain, **kwargs)
        self._sensors = sensor_manager
        self._perception = perception_manager
        self._fusion = fusion

    def run_cycle(self, trigger: Optional[str] = None) -> CycleResult:
        cycle = CycleResult(cycle_id=uuid.uuid4().hex[:10], ts=time.time())
        try:
            # 1. OBSERVE — poll real sensors
            observations = self._sensors.collect() if self._sensors is not None else []
            cycle.phases.append("observe")

            # 2. FUSE — corroborate multi-sensor readings
            if self._fusion is not None and observations:
                observations = self._fusion.fuse_and_merge(observations)
            cycle.phases.append("fuse")

            # ingest perception (dedupe, score, promote to world model)
            if self._perception is not None and observations:
                self._perception.ingest_batch(observations)

            objective = trigger or self._brain.state.current_objective or "review active goals"
            goals = self._observe_goals()

            # 3. CONTEXT
            context = self._brain.context_builder.build(objective)
            cycle.phases.append("context")

            # 4. WORLD
            if self._world is not None:
                self._world.observe("runtime", "cognition",
                                    state={"cycle": self._cycles + 1, "goals": len(goals),
                                           "observations": len(observations)})
            cycle.phases.append("world")

            # 5. ATTENTION
            self._brain.attention.rank_goals(goals)
            cycle.phases.append("attention")

            # 6. REASON — over goals *and* current environment
            reasoning = self._brain.reasoner.analyze(context, goals=goals)
            cycle.reasoning = reasoning.to_dict()
            cycle.phases.append("reason")

            # 7. PLAN
            plan = None
            if goals:
                plan = self._brain.planner.from_goals(goals, objective=objective)
                cycle.plan_id = plan.plan_id
            cycle.phases.append("plan")

            # 8. SELECT
            selected = None
            if plan is not None:
                ready = plan.ready_steps()
                selected = ready[0] if ready else None
            cycle.phases.append("select")

            # 9. EXECUTE (delegated → SkillExecutor)
            if selected is not None and self._auto_execute:
                self._brain.orchestrator.execute_step(selected)
                cycle.actions.append(selected.step_id)
                with self._lock:
                    self._actions += 1
            cycle.phases.append("execute")

            # 10. REFLECT
            cycle.notes = reasoning.rationale
            cycle.phases.append("reflect")

            # 11. LEARN
            self._learn(objective, reasoning, cycle)
            cycle.phases.append("learn")

        except Exception:
            log.exception("perceptive cognitive cycle failed")
            cycle.notes = "cycle error (contained)"

        with self._lock:
            self._cycles += 1
            self._last = cycle
        self._emit_cycle(cycle)
        return cycle

    # ── internals ──────────────────────────────────────────────────────────────
    def _observe_goals(self) -> list:
        if self._goals is None:
            return []
        try:
            return self._goals.list_goals()
        except Exception:
            return []
