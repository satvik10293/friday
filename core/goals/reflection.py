"""
core/goals/reflection.py — FRIDAY 4.0
ReflectionEngine: after a goal reaches a terminal state, analyze the outcome and
produce a ReflectionRecord (summary, reason, lesson, duration, skills used).

The analyzer is heuristic + pluggable (an LLM analyzer slots in later). GoalService
persists the record into the MemoryService so lessons are recallable
("what failed recently?", "what lessons did I learn?").
"""

from __future__ import annotations

import logging
import time
from typing import Optional

from .models import Goal, GoalStatus, ReflectionRecord

log = logging.getLogger("friday.goals.reflection")

# crude reason -> lesson mapping; extend or replace with an LLM analyzer later
_LESSON_RULES = [
    (("credential", "auth", "token", "api key", "unauthorized"),
     "Request and verify credentials before starting API integration."),
    (("timeout", "slow", "performance"),
     "Add timeouts and performance budgets up front."),
    (("dependency", "blocked", "missing"),
     "Resolve dependencies before activating dependent goals."),
    (("scope", "unclear", "ambiguous"),
     "Clarify scope and success criteria before execution."),
]


def _lesson_for(reason: str) -> str:
    low = (reason or "").lower()
    for keywords, lesson in _LESSON_RULES:
        if any(k in low for k in keywords):
            return lesson
    if reason:
        return f"Anticipate '{reason}' earlier next time."
    return "Capture what worked and repeat the approach."


class ReflectionEngine:
    def __init__(self, store) -> None:
        self._store = store

    def generate(self, goal: Goal) -> ReflectionRecord:
        duration = max(0.0, goal.updated_at - goal.created_at)
        skills = list(goal.metadata.get("skills", []))

        if goal.status == GoalStatus.FAILED:
            reason = goal.metadata.get("failure_reason", "unknown failure")
            lesson = _lesson_for(reason)
            summary = f"Goal '{goal.title}' failed: {reason}"
        elif goal.status == GoalStatus.COMPLETED:
            reason = ""
            lesson = f"Completed '{goal.title}' in {duration:.0f}s — repeat this approach."
            summary = f"Goal '{goal.title}' completed ({goal.completion_percent:.0f}%)."
        else:
            reason = ""
            lesson = f"Goal '{goal.title}' is {goal.status.value}; review before proceeding."
            summary = f"Goal '{goal.title}' status: {goal.status.value}"

        return ReflectionRecord(
            goal_id=goal.goal_id,
            status=goal.status.value,
            summary=summary,
            reason=reason,
            lesson=lesson,
            duration_s=round(duration, 2),
            skills_used=skills,
            created_at=time.time(),
        )
