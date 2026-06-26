"""
core/intelligence/planner.py — FRIDAY 4.0 (M12)
The planning engine (Part 7). Converts a goal into an executable plan: breaks it
into tasks, estimates complexity and time, and — when an agent society is wired in —
dispatches steps as society tasks (workers spawned/monitored by the M11 coordinator)
and reports progress for Mission Control.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from .base import Complexity, InferenceRequest, TaskType
from .reasoning_engine import ReasoningEngine


@dataclass
class PlanStep:
    index: int
    description: str
    task: str = TaskType.GENERAL.value
    estimated_ms: float = 0.0
    complexity: str = Complexity.SMALL.value
    status: str = "pending"
    result: Optional[dict] = None

    def to_dict(self) -> dict:
        return dict(self.__dict__)


@dataclass
class Plan:
    goal: str
    steps: list = field(default_factory=list)
    estimated_ms: float = 0.0
    complexity: str = Complexity.MEDIUM.value

    def to_dict(self) -> dict:
        return {"goal": self.goal, "complexity": self.complexity,
                "estimated_ms": self.estimated_ms,
                "steps": [s.to_dict() for s in self.steps]}


# rough per-complexity time estimates (ms)
_EST = {Complexity.TRIVIAL.value: 50, Complexity.SMALL.value: 200,
        Complexity.MEDIUM.value: 1000, Complexity.LARGE.value: 5000}


class IntelligencePlanner:
    def __init__(self, reasoning: ReasoningEngine, *, society=None) -> None:
        self._reasoning = reasoning
        self._society = society

    def plan(self, goal: str, *, context: Optional[dict] = None) -> Plan:
        """Use the planning model to break the goal into steps."""
        req = InferenceRequest(task=TaskType.PLANNING.value, prompt=goal,
                               context=context or {})
        result = self._reasoning.chain_of_thought(req)
        raw_steps = result.structured.get("plan", []) or [goal]
        steps = []
        for i, desc in enumerate(raw_steps):
            cx = self._estimate_complexity(desc)
            steps.append(PlanStep(index=i, description=str(desc),
                                  task=self._infer_task(str(desc)),
                                  complexity=cx, estimated_ms=float(_EST[cx])))
        total = sum(s.estimated_ms for s in steps)
        return Plan(goal=goal, steps=steps, estimated_ms=total,
                    complexity=self._overall(steps))

    def execute(self, plan: Plan) -> Plan:
        """Dispatch each step to the agent society (workers spawned + destroyed by
        the coordinator). Without a society, steps are marked planned-only."""
        for step in plan.steps:
            if self._society is None:
                step.status = "planned"
                continue
            try:
                res = self._society.solve(step.description, domain=self._domain(step.task))
                step.status = "done" if res.ok else "failed"
                step.result = {"workers": res.workers_spawned, "leader": res.leader}
            except Exception as e:  # noqa: BLE001
                step.status = "failed"
                step.result = {"error": str(e)}
        return plan

    def progress(self, plan: Plan) -> dict:
        done = sum(1 for s in plan.steps if s.status == "done")
        return {"goal": plan.goal, "total": len(plan.steps), "done": done,
                "fraction": round(done / len(plan.steps), 3) if plan.steps else 0.0}

    # ── heuristics ──────────────────────────────────────────────────────────────
    @staticmethod
    def _estimate_complexity(desc: str) -> str:
        n = len(str(desc))
        if n < 20:
            return Complexity.SMALL.value
        if n < 60:
            return Complexity.MEDIUM.value
        return Complexity.LARGE.value

    @staticmethod
    def _overall(steps) -> str:
        if not steps:
            return Complexity.TRIVIAL.value
        if len(steps) > 5:
            return Complexity.LARGE.value
        return Complexity.MEDIUM.value

    @staticmethod
    def _infer_task(desc: str) -> str:
        d = desc.lower()
        for kw, t in (("code", TaskType.CODING.value), ("research", TaskType.RESEARCH.value),
                      ("math", TaskType.MATH.value), ("write", TaskType.WRITING.value)):
            if kw in d:
                return t
        return TaskType.GENERAL.value

    @staticmethod
    def _domain(task: str) -> str:
        return {TaskType.CODING.value: "coding", TaskType.RESEARCH.value: "research",
                TaskType.PLANNING.value: "planning"}.get(task, "")
