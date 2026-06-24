"""
core/goals/models.py — FRIDAY 4.0
Goal data model + reflection record. Pure data structures (no I/O), so they're
trivially testable and serializable.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class GoalStatus(str, Enum):
    PENDING = "pending"
    ACTIVE = "active"
    BLOCKED = "blocked"
    COMPLETED = "completed"
    FAILED = "failed"
    ARCHIVED = "archived"


TERMINAL_STATUSES = {GoalStatus.COMPLETED, GoalStatus.FAILED, GoalStatus.ARCHIVED}


@dataclass
class Goal:
    goal_id: str
    title: str
    description: str = ""
    status: GoalStatus = GoalStatus.PENDING
    priority: int = 3                       # 1 = highest
    created_at: float = 0.0
    updated_at: float = 0.0
    parent_goal: Optional[str] = None
    dependencies: list = field(default_factory=list)   # list[goal_id]
    owner: str = "satvik"
    confidence: float = 0.5
    completion_percent: float = 0.0
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        d = self.__dict__.copy()
        d["status"] = self.status.value
        return d

    # ── SQLite (de)serialization ───────────────────────────────────────────────
    def to_row(self) -> tuple:
        return (
            self.goal_id, self.title, self.description, self.status.value,
            self.priority, self.created_at, self.updated_at, self.parent_goal,
            json.dumps(self.dependencies), self.owner, self.confidence,
            self.completion_percent, json.dumps(self.metadata),
        )

    @staticmethod
    def from_row(r) -> "Goal":
        return Goal(
            goal_id=r["goal_id"],
            title=r["title"],
            description=r["description"],
            status=GoalStatus(r["status"]),
            priority=r["priority"],
            created_at=r["created_at"],
            updated_at=r["updated_at"],
            parent_goal=r["parent_goal"],
            dependencies=_loads(r["dependencies"], []),
            owner=r["owner"],
            confidence=r["confidence"],
            completion_percent=r["completion_percent"],
            metadata=_loads(r["metadata"], {}),
        )


@dataclass
class ReflectionRecord:
    goal_id: str
    status: str
    summary: str
    reason: str = ""
    lesson: str = ""
    duration_s: float = 0.0
    skills_used: list = field(default_factory=list)
    created_at: float = 0.0

    def to_dict(self) -> dict:
        return dict(self.__dict__)


def _loads(text, default):
    try:
        return json.loads(text)
    except (TypeError, ValueError):
        return default
