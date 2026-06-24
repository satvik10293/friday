"""
core/user_model/user_context.py — FRIDAY 4.0 (M9)
The User Context Builder. Assembles a UserContextPackage — the personal lens the
Executive Brain (M5), Knowledge System (M8), and Agent Team reason through:
current goals, active projects, learned preferences, relevant knowledge, and
relevant memories, all centred on who the user is.

Pulls from the injected M4 Goals, M2 Memory, and M7/M8 Knowledge services when
present; degrades gracefully (still useful from the local user model alone) when
they're not. Additive — no M1–M8 file is modified.
"""

from __future__ import annotations

import uuid
from typing import Optional

from .models import UserContextPackage


class UserContextBuilder:
    def __init__(self, service) -> None:
        self._s = service

    def build(self, query: str = "", *, k: int = 5,
              allow_external: bool = False) -> UserContextPackage:
        s = self._s
        profile = s.profile.get()
        pkg = UserContextPackage(trace_id=uuid.uuid4().hex[:12])
        pkg.user = {
            "display_name": profile.display_name(),
            "name": profile.name,
            "education": profile.education,
            "skills": profile.skills,
            "long_term_goals": profile.long_term_goals,
        }

        # preferences + interests (always available, local)
        pkg.preferences = [p.to_dict() for p in s.preferences.strong()]
        pkg.interests = [i.to_dict() for i in s.interests.top(8)]

        # active projects (most relevant first if a query is given)
        projects = s.projects.active()
        if query:
            ql = query.lower()
            projects.sort(key=lambda p: (ql in p.name.lower()
                                         or ql in (p.description or "").lower()),
                          reverse=True)
        pkg.projects = [p.to_dict() for p in projects]

        # approved long-term relationship facts
        for fact in s.relationship.active():
            pkg.user.setdefault("long_term_context", []).append(fact.content)

        # goals (M4) — personalised ranking
        if s.goal_service is not None:
            try:
                from core.goals import GoalStatus
                goals = s.goal_service.list_goals(status=GoalStatus.ACTIVE)
            except Exception:
                goals = s.goal_service.list_goals() if hasattr(s.goal_service, "list_goals") else []
            pkg.goals = s.intelligence.prioritize_goals(goals)

        # knowledge (M8) — interest/project-boosted, explainable
        if query and s.knowledge_service is not None:
            recs = s.intelligence.suggest_knowledge(query, k=k, allow_external=allow_external)
            pkg.knowledge = [r.to_dict() for r in recs]

        # memories (M2)
        if query and s.memory_service is not None:
            try:
                pkg.memories = s.memory_service.recall(query, k=k)
            except Exception:
                pkg.memories = []

        pkg.confidence = self._confidence(pkg)
        return pkg

    @staticmethod
    def _confidence(pkg: UserContextPackage) -> float:
        """Rough 0..1 confidence that we have enough personal context."""
        signals = sum(bool(x) for x in (pkg.goals, pkg.projects, pkg.preferences,
                                        pkg.interests, pkg.knowledge, pkg.memories))
        return min(1.0, signals / 6.0)

    # ── integration helpers ─────────────────────────────────────────────────────
    def augment_context_package(self, context_package, query: str = "", *, k: int = 5):
        """Fold the user context into an M5 ContextPackage (additively, via its
        public list/dict fields), so the Executive Brain reasons with personal
        context without any M5 edit."""
        up = self.build(query, k=k)
        world = dict(getattr(context_package, "world", {}) or {})
        world["user"] = up.user
        world["interests"] = up.interests
        world["projects"] = up.projects
        context_package.world = world
        for pref in up.preferences:
            context_package.lessons.append({
                "source": "preference", "key": pref.get("key"),
                "value": pref.get("value"), "score": pref.get("score")})
        if up.knowledge and not context_package.memories:
            context_package.memories.extend(
                {"source": "user_knowledge", **r["item"]} for r in up.knowledge)
        if up.confidence > context_package.confidence:
            context_package.confidence = up.confidence
        return context_package
