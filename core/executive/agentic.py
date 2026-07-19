"""
core/executive/agentic.py — FRIDAY 5.x (M59)
The agentic workflow: the missing wire between ACTIVE goals and actual work.

The 2026-07 audit (docs/AUDIT_2026-07.md §1) found every organ of an agentic
loop already built — goal creation/decomposition (M4/M28), scheduling,
context building, executive decide→plan (M5), orchestrated skill execution
under the M3 security pipeline (M47), simulation-backed deliberation (M34) —
and exactly two things missing:

    1. nothing CONSUMED `GoalService.next_actions()` (ACTIVE goals sat idle)
    2. nothing fed EXECUTION RESULTS back into goal state (without which the
       raw CognitiveLoop would re-execute the same goals every cycle)

This module is that wire, and only that wire. It composes the existing
pieces; it redesigns nothing:

    runtime.schedule → AgenticWorkflow.cycle()
        → GoalService.next_actions()                 (priority-ordered ACTIVE)
        → ExecutiveBrain.decide(goal)                (context → reason → Plan)
        → ExecutiveBrain.execute_plan(plan)          (Orchestrator → skills,
                                                      simulation deliberation
                                                      for HIGH/CRITICAL risk)
        → feedback: complete_goal + reflect  |  block_goal (needs approval)
                    |  fail_goal + reflect   (learn from the failure)

AUTONOMY POLICY (owner-directed, 2026-07-18): hands-free execution may run
`Permission.SAFE` skills ONLY — the same posture as the M47 voice policy. The
SafeAutonomyGate enforces this *before* the SkillExecutor's blocking approval
prompt can ever be reached: an above-SAFE step pauses the goal (BLOCKED,
"awaiting your approval") instead of hanging a background thread. Skill
selection is explicit: a goal executes a skill iff its metadata carries
{"skill": name, "args": {...}}; goals without one are thinking/coordination
steps and complete synthetically (the M5 contract).

Every decision lands in the DecisionLog with was_autonomous=True — the same
ledger the independence metric reads.
"""

from __future__ import annotations

import logging
import threading
from typing import Optional

from core.skills.permissions import Permission
from core.skills.results import Result

log = logging.getLogger("friday.executive.agentic")

_NEEDS_APPROVAL = "needs_approval"


def run_one_shot_approved(executor, skill_name: str, args=None, context=None):
    """Run an above-SAFE skill through the FULL M47 pipeline, satisfying ONLY
    its human-approval step, for this one call and this one skill. The caller
    MUST have obtained explicit human approval (a two-step voice confirm) — this
    does not weaken anything else: policy, role clearance, sandbox, and audit
    all still run, so a step the caller's role can't clear still fails. Shared
    by the autonomy gate (approved paused goals) and the conversation bridge
    (approved direct commands). Never leaves the auto-decider installed."""
    appr = getattr(executor, "_approvals", None)
    if appr is None:                              # no approval manager → run plainly
        return executor.execute(skill_name, args, context)
    prev = getattr(appr, "_auto", None)
    fired = [False]

    def _decider(req):
        if not fired[0] and getattr(req, "skill_name", None) == skill_name:
            fired[0] = True
            return True                           # approve THIS request only
        return prev(req) if prev is not None else None

    appr._auto = _decider
    try:
        return executor.execute(skill_name, args, context)
    finally:
        appr._auto = prev                         # always restore


class SafeAutonomyGate:
    """SAFE-only wrapper around the M47 SkillExecutor for autonomous work.

    Above-SAFE skills are refused with error='needs_approval' (never invoking
    the executor, whose approval path BLOCKS on a human) so the workflow can
    pause the goal instead of hanging. The full security pipeline still runs
    for SAFE skills — this gate narrows, never widens.

    One exception, and only one: a `grant_once(skill, args)` — recorded ONLY
    by an explicit human approval upstream (M59.2 two-step voice confirm) —
    lets that exact step run through the executor a SINGLE time. Even then the
    full M47 pipeline still runs (policy → clearance → sandbox → audit): the
    grant satisfies just the human-approval step, and clearance still refuses
    anything above USER_APPROVAL (admin/system are unreachable by voice)."""

    def __init__(self, executor) -> None:
        self._executor = executor
        self._grants: dict[str, dict] = {}       # skill_name → args (one-shot)

    @property
    def registry(self):
        # the Orchestrator's deliberation hook reads .registry for risk levels
        return self._executor.registry

    def grant_once(self, skill_name: str, args: Optional[dict] = None) -> None:
        """Authorize ONE execution of skill_name (human-approved upstream)."""
        self._grants[skill_name] = dict(args or {})

    def execute(self, skill_name: str, args: Optional[dict] = None,
                context=None) -> Result:
        try:
            skill = self._executor.registry.get(skill_name)
        except Exception as e:  # noqa: BLE001 — unknown skill = clean failure
            return Result(success=False, error=f"unknown skill: {e}",
                          error_type="UnknownSkill")
        if skill.permission != Permission.SAFE:
            granted = self._grants.pop(skill_name, None)   # one-shot: consume
            if granted is None:
                return Result(
                    success=False, error=_NEEDS_APPROVAL,
                    error_type="AutonomyPolicy",
                    metadata={"skill": skill_name,
                              "permission": skill.permission.name})
            return self._run_preapproved(skill_name, args, context)
        return self._executor.execute(skill_name, args, context)

    def _run_preapproved(self, skill_name: str, args, context) -> Result:
        """Run a human-approved above-SAFE step through the FULL M47 pipeline,
        satisfying only its human-approval step (for this one call, this one
        skill) — policy, clearance, sandbox, and audit all still apply."""
        return run_one_shot_approved(self._executor, skill_name, args, context)


class AgenticWorkflow:
    """Consumes ACTIVE goals and drives them to an outcome through the
    existing executive pipeline. Bounded per cycle; never raises."""

    def __init__(self, goals, skills=None, *, memory=None, decision_log=None,
                 deliberator=None, world_model=None,
                 goals_per_cycle: int = 2) -> None:
        self.goals = goals
        self.gate = SafeAutonomyGate(skills) if skills is not None else None
        self.goals_per_cycle = max(1, int(goals_per_cycle))
        # the M5 ExecutiveBrain supplies context (memory + goals + world model),
        # attention, reasoning, planning, and the orchestrator — all existing
        from core.executive.executive import ExecutiveBrain
        self.executive = ExecutiveBrain(
            memory_service=memory, goal_service=goals,
            skill_executor=self.gate, decision_log=decision_log,
            world_model=world_model, deliberator=deliberator)
        self.cycles = 0
        self.executed = 0
        self.completed = 0
        self.paused = 0
        self.failed = 0
        self.approved_resumes = 0
        self.rejected = 0
        self._lock = threading.Lock()
        self._last: dict = {}

    # ── one scheduled pass ───────────────────────────────────────────────────────
    def cycle(self) -> dict:
        """Work up to `goals_per_cycle` ACTIVE goals to an outcome. Quiet,
        bounded, never raises — safe to run on the runtime scheduler forever."""
        summary = {"worked": [], "completed": [], "paused": [], "failed": []}
        try:
            for brief in (self.goals.next_actions(self.goals_per_cycle) or []):
                gid = brief.get("goal_id") if isinstance(brief, dict) else None
                if not gid:
                    continue
                outcome = self._work_goal(gid)
                summary["worked"].append(gid)
                summary[outcome].append(gid)
        except Exception:  # noqa: BLE001 — the loop must survive anything
            log.debug("agentic cycle failed", exc_info=True)
        with self._lock:
            self.cycles += 1
            self._last = summary
        return summary

    def _work_goal(self, goal_id: str) -> str:
        """Drive one goal through decide → execute → feedback. Returns
        'completed' | 'paused' | 'failed'."""
        goal = self.goals.get_goal(goal_id)
        if goal is None:
            return "failed"
        try:
            plan = self.executive.decide(goal.title, goals=[goal])
            result = self.executive.execute_plan(plan)
            with self._lock:
                self.executed += 1
        except Exception as e:  # noqa: BLE001 — a broken plan fails the goal
            log.debug("goal execution crashed: %s", goal_id, exc_info=True)
            self._fail(goal_id, f"execution error: {e}")
            return "failed"

        # feedback into goal state — the piece the audit found missing
        pause = self._approval_needed(plan)
        if pause is not None:
            self.goals.block_goal(
                goal_id, reason=f"awaiting your approval: {pause}")
            with self._lock:
                self.paused += 1
            log.info("goal paused for approval: %s (%s)", goal.title, pause)
            return "paused"
        if result.success:
            self.goals.complete_goal(goal_id, note="completed autonomously")
            self._reflect(goal_id)
            with self._lock:
                self.completed += 1
            return "completed"
        self._fail(goal_id, "one or more steps failed")
        return "failed"

    # ── helpers ──────────────────────────────────────────────────────────────────
    @staticmethod
    def _approval_needed(plan) -> Optional[str]:
        """If any step was refused by the autonomy gate, describe it."""
        for step in getattr(plan, "steps", []) or []:
            r = step.result or {}
            if r.get("error") == _NEEDS_APPROVAL:
                meta = r.get("metadata") or {}
                return (f"{meta.get('skill', step.skill)} "
                        f"({meta.get('permission', 'above SAFE')})")
        return None

    def _fail(self, goal_id: str, reason: str) -> None:
        try:
            self.goals.fail_goal(goal_id, reason=reason)
            self._reflect(goal_id)                 # learn from the failure too
        except Exception:  # noqa: BLE001
            log.debug("goal fail-feedback failed", exc_info=True)
        with self._lock:
            self.failed += 1

    def _reflect(self, goal_id: str) -> None:
        """Learn-back: the goal's reflection writes the lesson into memory."""
        try:
            self.goals.reflect(goal_id)
        except Exception:  # noqa: BLE001 — reflection is best-effort
            log.debug("goal reflection failed", exc_info=True)

    # ── human-in-the-loop: resume a paused goal (M59.2) ──────────────────────────
    def _skill_permission(self, skill_name: str) -> str:
        if self.gate is None:
            return "SAFE"
        try:
            return self.gate.registry.get(skill_name).permission.name
        except Exception:  # noqa: BLE001
            return "SAFE"

    def list_paused(self) -> list[dict]:
        """The goals paused awaiting the owner's approval, with the exact skill
        each one needs. Reads the goal store (survives restarts) and reports
        only above-SAFE, skill-bearing blocks — a dependency-failed block on a
        SAFE goal is not an approval pause. Never raises."""
        out: list[dict] = []
        try:
            from core.goals import GoalStatus
            for g in self.goals.list_goals(status=GoalStatus.BLOCKED):
                meta = getattr(g, "metadata", None) or {}
                skill = meta.get("skill")
                if not skill:
                    continue
                perm = self._skill_permission(skill)
                if perm == "SAFE":
                    continue                        # SAFE never pauses for approval
                out.append({"goal_id": g.goal_id, "title": g.title,
                            "skill": skill, "args": dict(meta.get("args") or {}),
                            "permission": perm})
        except Exception:  # noqa: BLE001
            log.debug("list_paused failed", exc_info=True)
        return out

    def approve_paused(self, goal_id: str) -> Optional[dict]:
        """The owner approved a paused goal (two-step voice confirm upstream).
        Grant its step ONE execution and resume the goal (BLOCKED→PENDING→,
        via tick, ACTIVE — the next cycle runs it). Returns {skill, title} on
        success, else None. ONLY USER_APPROVAL-tier is voice-approvable here;
        admin/system are refused (and clearance would reject them anyway)."""
        goal = self.goals.get_goal(goal_id)
        if goal is None or self.gate is None:
            return None
        meta = getattr(goal, "metadata", None) or {}
        skill = meta.get("skill")
        if not skill or self._skill_permission(skill) != "USER_APPROVAL":
            return None
        self.gate.grant_once(skill, meta.get("args") or {})
        self.goals.resume_goal(goal_id)             # BLOCKED → PENDING
        try:
            self.goals.tick()                       # → ACTIVE now; runs next cycle
        except Exception:  # noqa: BLE001 — the scheduler tick is best-effort
            log.debug("tick after approval failed", exc_info=True)
        with self._lock:
            self.approved_resumes += 1
        log.info("paused goal approved by owner: %s (%s)", goal.title, skill)
        return {"skill": skill, "title": goal.title}

    def reject_paused(self, goal_id: str) -> bool:
        """The owner declined a paused goal — fail it (with reflection) so it
        stops waiting. Returns whether a goal was dropped."""
        goal = self.goals.get_goal(goal_id)
        if goal is None:
            return False
        self._fail(goal_id, "approval declined by owner")
        with self._lock:
            self.rejected += 1
        return True

    # ── observability ────────────────────────────────────────────────────────────
    def status(self) -> dict:
        with self._lock:
            return {"cycles": self.cycles, "goals_executed": self.executed,
                    "completed": self.completed, "paused": self.paused,
                    "failed": self.failed, "approved_resumes": self.approved_resumes,
                    "rejected": self.rejected, "last": dict(self._last),
                    "policy": "safe_only",
                    "gated": self.gate is not None}

    def health(self) -> dict:
        return {"status": "ok", **self.status()}


def build_agentic_workflow(*, goals, skills=None, memory=None,
                           decision_log=None, deliberator=None,
                           world_model=None, goals_per_cycle: int = 2
                           ) -> Optional[AgenticWorkflow]:
    """Factory used at boot. None when goals are absent; never raises."""
    if goals is None:
        return None
    try:
        return AgenticWorkflow(
            goals, skills, memory=memory, decision_log=decision_log,
            deliberator=deliberator, world_model=world_model,
            goals_per_cycle=goals_per_cycle)
    except Exception:  # noqa: BLE001 — the workflow is optional at boot
        log.debug("agentic workflow build failed", exc_info=True)
        return None
