"""
core/goals/events.py — FRIDAY 4.0
Goal event namespace. These are str-valued so they work directly as keys on the
M1 runtime bus (which dispatches on any hashable signal), giving goals a
first-class event vocabulary without modifying the legacy Signal enum.
"""

from __future__ import annotations

from enum import Enum


class GoalEvent(str, Enum):
    CREATED = "goal.created"
    STARTED = "goal.started"
    COMPLETED = "goal.completed"
    FAILED = "goal.failed"
    BLOCKED = "goal.blocked"
    REFLECTED = "goal.reflected"
