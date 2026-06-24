"""
core/executive/planner.py — FRIDAY 4.0 (M5)
The executive Planner: turn an objective (or a set of M4 goals) into an
executable Plan — an ordered graph of PlanSteps with dependencies. Distinct from
the M4 goals.Planner (which decomposes objectives into *goal trees*): this layer
turns goals/objectives into concrete *executable steps* with optional skills.

Supports short-term, long-term, nested (recursive), and goal-derived planning.
Pure data + logic; no I/O.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class PlanStepStatus(str, Enum):
    PENDING = "pending"
    READY = "ready"
    ACTIVE = "active"
    DONE = "done"
    FAILED = "failed"
    BLOCKED = "blocked"
    SKIPPED = "skipped"


_TERMINAL_STEP = {PlanStepStatus.DONE, PlanStepStatus.FAILED, PlanStepStatus.SKIPPED}


@dataclass
class PlanStep:
    step_id: str
    action: str
    skill: Optional[str] = None              # skill name to route through SkillExecutor
    args: dict = field(default_factory=dict)
    depends_on: list = field(default_factory=list)   # list[step_id]
    status: PlanStepStatus = PlanStepStatus.PENDING
    goal_id: Optional[str] = None            # provenance: which M4 goal this came from
    result: Optional[dict] = None
    sub_plan: Optional[str] = None           # plan_id of a nested expansion

    def to_dict(self) -> dict:
        d = dict(self.__dict__)
        d["status"] = self.status.value
        return d


@dataclass
class PlanDependency:
    step_id: str
    depends_on_id: str
    kind: str = "finish-to-start"


@dataclass
class Plan:
    plan_id: str
    objective: str
    steps: list = field(default_factory=list)        # list[PlanStep]
    created_at: float = field(default_factory=time.time)
    horizon: str = "short"                            # "short" | "long"
    parent_plan: Optional[str] = None
    metadata: dict = field(default_factory=dict)

    def step(self, step_id: str) -> Optional[PlanStep]:
        return next((s for s in self.steps if s.step_id == step_id), None)

    def ready_steps(self) -> list[PlanStep]:
        """Steps not yet started whose dependencies are all DONE."""
        done = {s.step_id for s in self.steps if s.status == PlanStepStatus.DONE}
        out = []
        for s in self.steps:
            if s.status in (PlanStepStatus.PENDING, PlanStepStatus.READY) \
                    and all(d in done for d in s.depends_on):
                out.append(s)
        return out

    def blocked_steps(self) -> list[PlanStep]:
        failed = {s.step_id for s in self.steps if s.status == PlanStepStatus.FAILED}
        return [s for s in self.steps
                if s.status not in _TERMINAL_STEP and any(d in failed for d in s.depends_on)]

    def is_complete(self) -> bool:
        return bool(self.steps) and all(s.status in _TERMINAL_STEP for s in self.steps)

    def dependencies(self) -> list[PlanDependency]:
        return [PlanDependency(step_id=s.step_id, depends_on_id=d)
                for s in self.steps for d in s.depends_on]

    def to_dict(self) -> dict:
        return {
            "plan_id": self.plan_id, "objective": self.objective,
            "steps": [s.to_dict() for s in self.steps],
            "created_at": self.created_at, "horizon": self.horizon,
            "parent_plan": self.parent_plan, "metadata": self.metadata,
        }


@dataclass
class PlanResult:
    plan_id: str
    success: bool
    steps_total: int = 0
    completed: list = field(default_factory=list)
    failed: list = field(default_factory=list)
    skipped: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return dict(self.__dict__)


def _sid() -> str:
    return uuid.uuid4().hex[:10]


class ExecutivePlanner:
    def __init__(self) -> None:
        self._created = 0

    # ── from objective ─────────────────────────────────────────────────────────
    def build_plan(self, objective: str, *, horizon: str = "short",
                   steps: Optional[list[dict]] = None) -> Plan:
        """Build a plan from an objective. If `steps` (action specs) are given they
        are used directly; otherwise a minimal analyze→act→verify scaffold."""
        plan = Plan(plan_id=_sid(), objective=objective, horizon=horizon)
        specs = steps if steps is not None else self._scaffold(objective)
        prev_id: Optional[str] = None
        for spec in specs:
            step = PlanStep(
                step_id=spec.get("step_id") or _sid(),
                action=spec["action"], skill=spec.get("skill"),
                args=dict(spec.get("args") or {}),
                depends_on=list(spec.get("depends_on", [])) or ([prev_id] if prev_id else []),
                goal_id=spec.get("goal_id"),
            )
            plan.steps.append(step)
            prev_id = step.step_id
        self._created += 1
        return plan

    # ── from M4 goals ──────────────────────────────────────────────────────────
    def from_goals(self, goals: list, objective: str = "",
                   horizon: str = "long") -> Plan:
        """Convert a set of M4 Goal objects into a Plan. Goal ids become step ids
        and goal dependencies become step dependencies — so the plan inherits the
        goal tree's ordering exactly."""
        from core.goals import GoalStatus
        objective = objective or (goals[0].title if goals else "plan")
        plan = Plan(plan_id=_sid(), objective=objective, horizon=horizon,
                    metadata={"derived_from": "goals"})
        ids = {g.goal_id for g in goals}
        for g in goals:
            status = PlanStepStatus.DONE if g.status == GoalStatus.COMPLETED \
                else PlanStepStatus.FAILED if g.status == GoalStatus.FAILED \
                else PlanStepStatus.PENDING
            plan.steps.append(PlanStep(
                step_id=g.goal_id, action=g.title,
                skill=(g.metadata or {}).get("skill"),
                args=dict((g.metadata or {}).get("args") or {}),
                depends_on=[d for d in (g.dependencies or []) if d in ids],
                status=status, goal_id=g.goal_id,
            ))
        self._created += 1
        return plan

    # ── recursive ──────────────────────────────────────────────────────────────
    def expand_step(self, plan: Plan, step_id: str, sub_specs: list[dict]) -> Plan:
        """Recursively expand a step into its own sub-plan; link them by id."""
        parent_step = plan.step(step_id)
        if parent_step is None:
            raise ValueError(f"no step {step_id} in plan {plan.plan_id}")
        sub = self.build_plan(parent_step.action, steps=sub_specs)
        sub.parent_plan = plan.plan_id
        parent_step.sub_plan = sub.plan_id
        return sub

    # ── diagnostics ────────────────────────────────────────────────────────────
    def metrics(self) -> dict:
        return {"plans_created": self._created}

    # ── internals ──────────────────────────────────────────────────────────────
    @staticmethod
    def _scaffold(objective: str) -> list[dict]:
        return [
            {"action": f"analyze: {objective}"},
            {"action": f"act on: {objective}"},
            {"action": f"verify: {objective}"},
        ]
