"""
core/goals — FRIDAY 4.0 goal-driven cognition layer.

Goals are first-class, persistent, and observable: FRIDAY can take an objective,
decompose it into a dependency-ordered plan, schedule the ready work, track
progress, and reflect on outcomes — writing every lesson back into memory.

Import is side-effect free (no DB or runtime is opened at import time).

    from core.goals import get_goal_service
    svc = get_goal_service()
    root = svc.plan("build a weather dashboard")
    svc.tick()                      # activate ready sub-goals
    svc.next_actions()              # what FRIDAY should do next
"""

from .models import Goal, GoalStatus, ReflectionRecord, TERMINAL_STATUSES
from .goal import (new_goal, validate_goal, is_ready, is_blocked, is_terminal,
                   is_awaiting_approval)
from .events import GoalEvent
from .metrics import GoalMetrics
from .storage import GoalStore
from .planner import Planner, GoalTree, default_decompose
from .progress import ProgressEngine
from .scheduler import GoalScheduler
from .reflection import ReflectionEngine
from .generator import GoalGenerator
from .service import GoalService, get_goal_service

__all__ = [
    "Goal", "GoalStatus", "ReflectionRecord", "TERMINAL_STATUSES",
    "new_goal", "validate_goal", "is_ready", "is_blocked", "is_terminal",
    "is_awaiting_approval",
    "GoalEvent", "GoalMetrics", "GoalStore",
    "Planner", "GoalTree", "default_decompose",
    "ProgressEngine", "GoalScheduler", "ReflectionEngine", "GoalGenerator",
    "GoalService", "get_goal_service",
]
