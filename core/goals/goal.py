"""
core/goals/goal.py — FRIDAY 4.0
Goal domain helpers: factory, validation, readiness logic. Operates on the pure
models in models.py; no I/O here.
"""

from __future__ import annotations

import time
import uuid
from typing import Optional

from .models import Goal, GoalStatus, TERMINAL_STATUSES


def new_goal(title: str, *, description: str = "", priority: int = 3,
             owner: str = "satvik", parent_goal: Optional[str] = None,
             dependencies: Optional[list] = None, confidence: float = 0.5,
             status: GoalStatus = GoalStatus.PENDING,
             metadata: Optional[dict] = None) -> Goal:
    now = time.time()
    return Goal(
        goal_id=uuid.uuid4().hex[:12],
        title=title,
        description=description,
        status=status,
        priority=priority,
        created_at=now,
        updated_at=now,
        parent_goal=parent_goal,
        dependencies=list(dependencies or []),
        owner=owner,
        confidence=max(0.0, min(1.0, confidence)),
        completion_percent=0.0,
        metadata=dict(metadata or {}),
    )


def validate_goal(goal: Goal) -> None:
    if not goal.title or not goal.title.strip():
        raise ValueError("goal title is required")
    if not isinstance(goal.priority, int):
        raise ValueError("goal priority must be an int")
    if not (0.0 <= goal.confidence <= 1.0):
        raise ValueError("goal confidence must be in [0, 1]")


def is_ready(goal: Goal, by_id: dict) -> bool:
    """A PENDING goal is ready when every dependency is COMPLETED (missing
    dependencies are treated as satisfied)."""
    if goal.status != GoalStatus.PENDING:
        return False
    for dep_id in goal.dependencies:
        dep = by_id.get(dep_id)
        if dep is not None and dep.status != GoalStatus.COMPLETED:
            return False
    return True


def is_blocked(goal: Goal, by_id: dict) -> bool:
    """A goal is blocked when any dependency has FAILED."""
    for dep_id in goal.dependencies:
        dep = by_id.get(dep_id)
        if dep is not None and dep.status == GoalStatus.FAILED:
            return True
    return False


def is_terminal(goal: Goal) -> bool:
    return goal.status in TERMINAL_STATUSES
