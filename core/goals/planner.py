"""
core/goals/planner.py — FRIDAY 4.0
The Planner: decompose a user objective into a goal tree (root + ordered
sub-goals with dependencies, priorities, and confidence estimates).

The decomposer is injectable so a future LLM-backed planner slots in behind the
same interface; the default is a dependency-free heuristic that recognizes
common "build X" objectives and otherwise falls back to a generic phase plan.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional

from .goal import new_goal
from .models import Goal

# A spec: title + indices of prerequisite specs + priority/confidence.
Decomposer = Callable[[str], list[dict]]


@dataclass
class GoalTree:
    root: Goal
    children: list = field(default_factory=list)

    def all_goals(self) -> list[Goal]:
        return [self.root] + list(self.children)


_BUILD_PHASES = [
    ("Research APIs", 0.7),
    ("Design Architecture", 0.65),
    ("Build Backend", 0.6),
    ("Build Frontend", 0.6),
    ("Testing", 0.55),
    ("Deployment", 0.5),
]
_GENERIC_PHASES = [
    ("Research", 0.7),
    ("Plan", 0.65),
    ("Execute", 0.55),
    ("Review", 0.6),
]


def default_decompose(objective: str) -> list[dict]:
    low = (objective or "").lower()
    phases = _BUILD_PHASES if any(
        kw in low for kw in ("build", "dashboard", "app", "website", "platform", "system")
    ) else _GENERIC_PHASES
    specs: list[dict] = []
    for i, (title, conf) in enumerate(phases):
        specs.append({
            "title": title,
            "depends_on": [i - 1] if i > 0 else [],   # linear pipeline
            "priority": i + 1,
            "confidence": conf,
        })
    return specs


class Planner:
    def __init__(self, decomposer: Optional[Decomposer] = None) -> None:
        self._decompose = decomposer or default_decompose

    def plan(self, objective: str, owner: str = "satvik") -> GoalTree:
        root = new_goal(
            objective, description=f"Objective: {objective}", owner=owner,
            priority=1, confidence=0.6, metadata={"kind": "root"},
        )
        specs = self._decompose(objective)
        children: list[Goal] = []
        index_to_id: dict[int, str] = {}
        for i, spec in enumerate(specs):
            child = new_goal(
                spec["title"], parent_goal=root.goal_id, owner=owner,
                priority=spec.get("priority", 3), confidence=spec.get("confidence", 0.5),
                metadata={"kind": "phase", "objective": objective},
            )
            index_to_id[i] = child.goal_id
            children.append(child)
        # resolve dependency indices -> goal_ids
        for i, spec in enumerate(specs):
            children[i].dependencies = [index_to_id[j] for j in spec.get("depends_on", [])
                                        if j in index_to_id]
        return GoalTree(root=root, children=children)
