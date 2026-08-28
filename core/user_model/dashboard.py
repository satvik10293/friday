"""
core/user_model/dashboard.py — FRIDAY 4.0 (M9)
Personal-dashboard data APIs, prepared for M10 Mission Control. This module is
**data only** — it returns JSON-serialisable widget payloads; there is no UI here.

Widgets: active projects, active goals, learning progress, interests, knowledge
growth, personal statistics.
"""

from __future__ import annotations



class UserDashboard:
    def __init__(self, service) -> None:
        self._s = service

    # ── individual widgets ──────────────────────────────────────────────────────
    def widget_active_projects(self) -> dict:
        projects = self._s.projects.active()
        return {"widget": "active_projects", "count": len(projects),
                "items": [{"id": p.id, "name": p.name,
                           "progress": round(self._s.projects.progress(p.id), 3),
                           "milestones": len(p.milestones)} for p in projects]}

    def widget_active_goals(self) -> dict:
        gs = self._s.goal_service
        if gs is None:
            return {"widget": "active_goals", "count": 0, "items": []}
        try:
            from core.goals import GoalStatus
            goals = gs.list_goals(status=GoalStatus.ACTIVE)
        except Exception:
            goals = []
        ranked = self._s.intelligence.prioritize_goals(goals)
        return {"widget": "active_goals", "count": len(ranked), "items": ranked[:10]}

    def widget_learning_progress(self) -> dict:
        return {"widget": "learning_progress", **self._s.learning.profile()}

    def widget_interests(self) -> dict:
        interests = self._s.interests.list()
        return {"widget": "interests", "count": len(interests),
                "items": [{"name": i.name, "weight": round(i.weight, 3),
                           "count": i.count} for i in interests[:15]]}

    def widget_knowledge_growth(self) -> dict:
        ks = self._s.knowledge_service
        if ks is None:
            return {"widget": "knowledge_growth", "total": 0}
        try:
            stats = ks.stats()
        except Exception:
            stats = {}
        return {"widget": "knowledge_growth", "total": stats.get("total", 0),
                "by_category": stats.get("by_category", {})}

    def widget_personal_stats(self) -> dict:
        return {"widget": "personal_stats", **self._s.metrics()}

    def widget_communication_style(self) -> dict:
        return {"widget": "communication_style", "style": self._s.communication.style()}

    # ── full dashboard ──────────────────────────────────────────────────────────
    def all_widgets(self) -> dict:
        return {
            "user": self._s.profile.get().display_name(),
            "widgets": [
                self.widget_active_projects(),
                self.widget_active_goals(),
                self.widget_learning_progress(),
                self.widget_interests(),
                self.widget_knowledge_growth(),
                self.widget_communication_style(),
                self.widget_personal_stats(),
            ],
            "health": self._s.health(),
        }
