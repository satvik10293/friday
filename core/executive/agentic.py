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
                 goals_per_cycle: int = 2, runtime=None,
                 max_concurrency: int = 1) -> None:
        self.goals = goals
        self.gate = SafeAutonomyGate(skills) if skills is not None else None
        self.goals_per_cycle = max(1, int(goals_per_cycle))
        # deps kept so each concurrent worker can build its OWN ExecutiveBrain
        # (no shared cognitive state races when goals run in parallel)
        self._memory = memory
        self._decision_log = decision_log
        self._deliberator = deliberator
        self._world_model = world_model
        # "many tasks at once": run up to N goals concurrently on the runtime's
        # thread pool. Default 1 == today's exact serial behaviour (opt-in only).
        self._runtime = runtime
        self._max_concurrency = max(1, min(int(max_concurrency), self.goals_per_cycle))
        self._inflight: set = set()               # goal_ids currently being worked
        # the M5 ExecutiveBrain supplies context (memory + goals + world model),
        # attention, reasoning, planning, and the orchestrator — all existing.
        # This shared brain still drives the serial (default) path unchanged.
        self.executive = self._new_executive()
        self.cycles = 0
        self.executed = 0
        self.completed = 0
        self.paused = 0
        self.failed = 0
        self.approved_resumes = 0
        self.rejected = 0
        self._lock = threading.Lock()
        self._last: dict = {}

    def _new_executive(self):
        """A fresh ExecutiveBrain from the shared services — in-memory state only
        (state_store=None), so concurrent workers never clobber one shared row."""
        from core.executive.executive import ExecutiveBrain
        return ExecutiveBrain(
            memory_service=self._memory, goal_service=self.goals,
            skill_executor=self.gate, decision_log=self._decision_log,
            world_model=self._world_model, deliberator=self._deliberator)

    # ── one scheduled pass ───────────────────────────────────────────────────────
    def cycle(self) -> dict:
        """Work up to `goals_per_cycle` ACTIVE goals to an outcome. Quiet,
        bounded, never raises — safe to run on the runtime scheduler forever.

        With max_concurrency == 1 (default) this is the original serial loop.
        Above that, SAFE-only goals run in parallel on the runtime pool while any
        goal needing approval stays on a single serial lane (the approval path is
        not reentrant), so parallelism never weakens the security posture."""
        summary = {"worked": [], "completed": [], "paused": [], "failed": []}
        try:
            gids = []
            for brief in (self.goals.next_actions(self.goals_per_cycle) or []):
                gid = brief.get("goal_id") if isinstance(brief, dict) else None
                if gid and self._claim(gid):
                    gids.append(gid)
            try:
                if self._max_concurrency <= 1 or self._runtime is None:
                    for gid in gids:                       # serial — unchanged
                        self._run_and_record(gid, summary)
                else:
                    self._cycle_concurrent(gids, summary)
            finally:
                self._release(gids)
        except Exception:  # noqa: BLE001 — the loop must survive anything
            log.debug("agentic cycle failed", exc_info=True)
        with self._lock:
            self.cycles += 1
            self._last = summary
        return summary

    def _claim(self, gid: str) -> bool:
        """Reserve a goal so overlapping cycles / lanes never work it twice."""
        with self._lock:
            if gid in self._inflight:
                return False
            self._inflight.add(gid)
            return True

    def _release(self, gids) -> None:
        with self._lock:
            self._inflight.difference_update(gids)

    def _run_and_record(self, gid: str, summary: dict, *, fresh: bool = False) -> None:
        """Work one goal and record its outcome. `fresh` gives it its own
        ExecutiveBrain (for the concurrent lane). Summary writes are locked."""
        executive = self._new_executive() if fresh else None
        outcome = self._work_goal(gid, executive=executive)
        with self._lock:
            summary["worked"].append(gid)
            summary[outcome].append(gid)

    def _cycle_concurrent(self, gids: list, summary: dict) -> None:
        """SAFE-only goals in parallel (bounded); approval-needing goals serial."""
        import concurrent.futures as cf
        safe = [g for g in gids if self._is_safe_only(g)]
        serial = [g for g in gids if g not in safe]
        for i in range(0, len(safe), self._max_concurrency):      # bounded waves
            wave = safe[i:i + self._max_concurrency]
            futures = [self._runtime.submit(self._run_and_record, g, summary, fresh=True)
                       for g in wave]
            for f in cf.as_completed(futures):
                try:
                    f.result()
                except Exception:  # noqa: BLE001 — one worker can't sink the cycle
                    log.debug("concurrent goal failed", exc_info=True)
        for gid in serial:                                        # non-reentrant path
            self._run_and_record(gid, summary)

    def _is_safe_only(self, goal_id: str) -> bool:
        """True if the goal's skill is SAFE (or it has no skill — a thinking
        step). Anything unprovable falls to the serial lane (conservative)."""
        if self.gate is None:
            return True
        goal = self.goals.get_goal(goal_id)
        meta = getattr(goal, "metadata", None) or {}
        skill = meta.get("skill") if isinstance(meta, dict) else None
        if not skill:
            return True
        try:
            return self.gate.registry.get(skill).permission == Permission.SAFE
        except Exception:  # noqa: BLE001 — unknown skill → play it safe, serialize
            return False

    def _work_goal(self, goal_id: str, executive=None) -> str:
        """Drive one goal through decide → execute → feedback. Returns
        'completed' | 'paused' | 'failed'. `executive` lets a concurrent worker
        use its own brain; None uses the shared one (the serial default)."""
        ex = executive if executive is not None else self.executive
        goal = self.goals.get_goal(goal_id)
        if goal is None:
            return "failed"
        try:
            plan = ex.decide(goal.title, goals=[goal])
            result = ex.execute_plan(plan)
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
                    "gated": self.gate is not None,
                    "max_concurrency": self._max_concurrency,
                    "inflight": len(self._inflight)}

    def health(self) -> dict:
        return {"status": "ok", **self.status()}


def build_agentic_workflow(*, goals, skills=None, memory=None,
                           decision_log=None, deliberator=None,
                           world_model=None, goals_per_cycle: int = 2,
                           runtime=None, max_concurrency: int = 1
                           ) -> Optional[AgenticWorkflow]:
    """Factory used at boot. None when goals are absent; never raises.
    max_concurrency>1 (opt-in) lets her work several SAFE goals at once."""
    if goals is None:
        return None
    try:
        return AgenticWorkflow(
            goals, skills, memory=memory, decision_log=decision_log,
            deliberator=deliberator, world_model=world_model,
            goals_per_cycle=goals_per_cycle, runtime=runtime,
            max_concurrency=max_concurrency)
    except Exception:  # noqa: BLE001 — the workflow is optional at boot
        log.debug("agentic workflow build failed", exc_info=True)
        return None
