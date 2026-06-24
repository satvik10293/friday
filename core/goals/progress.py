"""
core/goals/progress.py — FRIDAY 4.0
Progress Engine: mutate goal completion/state and roll progress up to parents.
Records every change in the goal_events history table.
"""

from __future__ import annotations

import logging
import time
from typing import Optional

from .models import Goal, GoalStatus

log = logging.getLogger("friday.goals.progress")


class ProgressEngine:
    def __init__(self, store) -> None:
        self._store = store

    def update_progress(self, goal_id: str, percent: float, note: str = "") -> Optional[Goal]:
        g = self._store.get_goal(goal_id)
        if g is None:
            return None
        g.completion_percent = max(0.0, min(100.0, float(percent)))
        self._store.update_goal(g)
        self._store.add_event(goal_id, "progress", note, {"percent": g.completion_percent})
        self._recompute_parent(g)
        return g

    def mark_complete(self, goal_id: str, note: str = "") -> Optional[Goal]:
        return self._set_status(goal_id, GoalStatus.COMPLETED, completion=100.0,
                                kind="completed", detail=note)

    def mark_failed(self, goal_id: str, reason: str = "") -> Optional[Goal]:
        g = self._store.get_goal(goal_id)
        if g is None:
            return None
        g.status = GoalStatus.FAILED
        g.metadata["failure_reason"] = reason
        self._store.update_goal(g)
        self._store.add_event(goal_id, "failed", reason, {"reason": reason})
        self._recompute_parent(g)
        return g

    def mark_blocked(self, goal_id: str, reason: str = "") -> Optional[Goal]:
        return self._set_status(goal_id, GoalStatus.BLOCKED, kind="blocked", detail=reason)

    def resume_goal(self, goal_id: str) -> Optional[Goal]:
        g = self._store.get_goal(goal_id)
        if g is None:
            return None
        if g.status in (GoalStatus.BLOCKED, GoalStatus.FAILED):
            g.status = GoalStatus.PENDING
            self._store.update_goal(g)
            self._store.add_event(goal_id, "resumed", "", {})
        return g

    # ── internals ──────────────────────────────────────────────────────────────
    def _set_status(self, goal_id, status, *, completion=None, kind="status", detail=""):
        g = self._store.get_goal(goal_id)
        if g is None:
            return None
        g.status = status
        if completion is not None:
            g.completion_percent = completion
        self._store.update_goal(g)
        self._store.add_event(goal_id, kind, detail, {"status": status.value})
        self._recompute_parent(g)
        return g

    def _recompute_parent(self, child: Goal) -> None:
        if not child.parent_goal:
            return
        parent = self._store.get_goal(child.parent_goal)
        if parent is None:
            return
        siblings = self._store.list_goals(parent=child.parent_goal)
        if not siblings:
            return
        avg = sum(s.completion_percent for s in siblings) / len(siblings)
        parent.completion_percent = round(avg, 2)
        if all(s.status == GoalStatus.COMPLETED for s in siblings):
            parent.status = GoalStatus.COMPLETED
            parent.completion_percent = 100.0
            self._store.add_event(parent.goal_id, "completed", "all sub-goals complete", {})
        self._store.update_goal(parent)
