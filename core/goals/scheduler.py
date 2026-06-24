"""
core/goals/scheduler.py — FRIDAY 4.0
GoalScheduler: activate ready goals, detect blocked goals (failed dependency),
and surface the next actions. Pure over the store; GoalService wraps each tick
with observability and runs it periodically on the Runtime scheduler.
"""

from __future__ import annotations

import logging
import time

from .goal import is_blocked, is_ready
from .models import Goal, GoalStatus

log = logging.getLogger("friday.goals.scheduler")


class GoalScheduler:
    def __init__(self, store) -> None:
        self._store = store

    def tick(self) -> dict:
        """One scheduling pass. Activates PENDING goals whose dependencies are all
        COMPLETED; marks BLOCKED any whose dependency FAILED. Returns a summary."""
        goals = self._store.list_goals()
        by_id = {g.goal_id: g for g in goals}
        activated: list[str] = []
        blocked: list[str] = []

        for g in goals:
            if g.status != GoalStatus.PENDING:
                continue
            if is_blocked(g, by_id):
                g.status = GoalStatus.BLOCKED
                self._store.update_goal(g)
                self._store.add_event(g.goal_id, "blocked", "dependency failed", {})
                blocked.append(g.goal_id)
            elif is_ready(g, by_id):
                g.status = GoalStatus.ACTIVE
                self._store.update_goal(g)
                self._store.add_event(g.goal_id, "activated", "dependencies satisfied", {})
                activated.append(g.goal_id)

        active = [g.goal_id for g in self._store.list_goals(status=GoalStatus.ACTIVE)]
        return {"activated": activated, "blocked": blocked, "active": active,
                "checked": len(goals), "ts": time.time()}

    def next_actions(self, limit: int = 5) -> list[Goal]:
        """ACTIVE goals, highest priority first — FRIDAY's suggested next work."""
        return self._store.list_goals(status=GoalStatus.ACTIVE)[:limit]

    def ready_goals(self) -> list[Goal]:
        goals = self._store.list_goals()
        by_id = {g.goal_id: g for g in goals}
        return [g for g in goals if is_ready(g, by_id)]
