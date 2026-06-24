"""
core/executive/orchestrator.py — FRIDAY 4.0 (M5)
The Orchestrator: FRIDAY's executive coordinator. Given a Plan, it decides what
to execute now, what must wait, and drives execution — always routing actual
skill work through the M3 SkillExecutor (the single approved execution path).

It coordinates the existing layers (Goals, Memory, Skills, Runtime) without
duplicating them. Steps without a skill are "thinking" steps and complete
synthetically; steps with a skill execute under the full permission/audit
pipeline.
"""

from __future__ import annotations

import logging
import time
from typing import Optional

from .planner import Plan, PlanResult, PlanStep, PlanStepStatus

log = logging.getLogger("friday.executive.orchestrator")


class Orchestrator:
    def __init__(self, skill_executor=None, goal_service=None, memory_service=None,
                 runtime=None, decision_log=None) -> None:
        self._executor = skill_executor
        self._goals = goal_service
        self._memory = memory_service
        self._runtime = runtime
        self._decision = decision_log
        self._executed = 0

    # ── decisions ──────────────────────────────────────────────────────────────
    def decide(self, plan: Plan) -> dict:
        """Split the plan into what can run now vs. what must wait vs. what's blocked."""
        ready = plan.ready_steps()
        blocked = plan.blocked_steps()
        waiting = [s for s in plan.steps
                   if s.status in (PlanStepStatus.PENDING, PlanStepStatus.READY)
                   and s not in ready and s not in blocked]
        return {
            "execute": [s.step_id for s in ready],
            "wait": [s.step_id for s in waiting],
            "blocked": [s.step_id for s in blocked],
        }

    # ── execution ──────────────────────────────────────────────────────────────
    def execute_step(self, step: PlanStep, context=None) -> PlanStep:
        """Execute a single step. Routes through SkillExecutor when the step names a
        skill and an executor is available; otherwise completes synthetically."""
        step.status = PlanStepStatus.ACTIVE
        if step.skill and self._executor is not None:
            ctx = context or self._make_context()
            result = self._executor.execute(step.skill, step.args, ctx)
            step.result = result.to_dict() if hasattr(result, "to_dict") else {"raw": str(result)}
            step.status = PlanStepStatus.DONE if getattr(result, "success", False) \
                else PlanStepStatus.FAILED
        else:
            # thinking/coordination step — no external action to take
            step.result = {"success": True, "synthetic": True, "action": step.action}
            step.status = PlanStepStatus.DONE
        self._executed += 1
        self._observe(step)
        return step

    def execute_plan(self, plan: Plan, context=None, max_steps: int = 200) -> PlanResult:
        """Drive a plan to completion, honoring dependencies. Bounded by `max_steps`
        so a malformed dependency graph can never loop forever."""
        steps_run = 0
        # advance until no ready steps remain (completion, or fully blocked)
        while steps_run < max_steps:
            ready = plan.ready_steps()
            if not ready:
                break
            for step in ready:
                self.execute_step(step, context)
                steps_run += 1
                if steps_run >= max_steps:
                    break

        completed = [s.step_id for s in plan.steps if s.status == PlanStepStatus.DONE]
        failed = [s.step_id for s in plan.steps if s.status == PlanStepStatus.FAILED]
        # anything still pending after we ran out of ready work is effectively skipped
        skipped = [s.step_id for s in plan.steps
                   if s.status in (PlanStepStatus.PENDING, PlanStepStatus.READY,
                                   PlanStepStatus.BLOCKED)]
        for s in plan.steps:
            if s.step_id in skipped:
                s.status = PlanStepStatus.SKIPPED
        result = PlanResult(
            plan_id=plan.plan_id, success=(not failed and not skipped),
            steps_total=len(plan.steps), completed=completed, failed=failed, skipped=skipped,
        )
        return result

    # ── diagnostics ────────────────────────────────────────────────────────────
    def metrics(self) -> dict:
        return {"steps_executed": self._executed}

    def health(self) -> dict:
        return {"status": "ok", "steps_executed": self._executed,
                "executor": self._executor is not None}

    # ── internals ──────────────────────────────────────────────────────────────
    def _make_context(self):
        from core.skills.context import SkillContext
        return SkillContext(runtime=self._runtime, memory_service=self._memory,
                            decision_log=self._decision, caller="executive")

    def _observe(self, step: PlanStep) -> None:
        if self._decision is None:
            return
        try:
            from core.observability import new_trace_id
            self._decision.log(
                trace_id=new_trace_id(), intent="executive.execute_step",
                route=["executive", "orchestrator"],
                skills_invoked=[step.skill] if step.skill else [],
                goals_touched=[step.goal_id] if step.goal_id else [],
                outcome=step.status.value, rationale=step.action,
                confidence=1.0 if step.status == PlanStepStatus.DONE else 0.0,
                was_autonomous=True, source="executive.orchestrator",
            )
        except Exception:
            log.debug("orchestrator decision-log write failed", exc_info=True)
