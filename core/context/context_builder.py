"""
core/context/context_builder.py — FRIDAY 4.0 (M5)
The Context Engine. Builds the best reasoning context for a query by combining
the existing layers — it owns no data of its own:

  • relevant memories     ← M2 MemoryService.recall
  • active goals          ← M4 GoalService.list_goals
  • lessons / reflections ← M2 recall over reflection memories
  • focus items           ← M5 AttentionSystem ranking
  • world state           ← M5 WorldModel snapshot summary

Every dependency is injected and optional, so the builder degrades gracefully
(an absent layer simply contributes nothing) and is trivially testable.
"""

from __future__ import annotations

import logging
from typing import Optional

from .context_package import ContextPackage

log = logging.getLogger("friday.context.builder")


class ContextBuilder:
    def __init__(self, memory_service=None, goal_service=None,
                 attention=None, world_model=None) -> None:
        self._memory = memory_service
        self._goals = goal_service
        self._attention = attention
        self._world = world_model
        self._builds = 0

    def build(self, query: str, *, k_memories: int = 5, k_goals: int = 5,
              k_lessons: int = 3, trace_id: Optional[str] = None) -> ContextPackage:
        pkg = ContextPackage(query=query, trace_id=trace_id)

        memories = self._recall(query, k_memories)
        pkg.memories = memories
        pkg.lessons = self._recall_lessons(query, k_lessons)

        goals = self._active_goals(k_goals)
        pkg.goals = [self._goal_dict(g) for g in goals]

        if self._attention is not None:
            focus = []
            focus += self._attention.rank_goals(goals)
            focus += self._attention.rank_memories(memories)
            focus = self._attention.top(self._attention._sorted(focus), n=k_goals)
            pkg.focus_items = [f.to_dict() for f in focus]

        if self._world is not None:
            try:
                pkg.world = self._world.counts()
            except Exception:
                log.debug("world summary failed", exc_info=True)

        pkg.confidence = self._confidence(pkg)
        self._builds += 1
        return pkg

    # ── sources ────────────────────────────────────────────────────────────────
    def _recall(self, query: str, k: int) -> list[dict]:
        if self._memory is None:
            return []
        try:
            return list(self._memory.recall(query, k=k))
        except Exception:
            log.debug("memory recall failed", exc_info=True)
            return []

    def _recall_lessons(self, query: str, k: int) -> list[dict]:
        if self._memory is None:
            return []
        try:
            hits = self._memory.recall(f"lesson {query}", k=k * 2)
        except Exception:
            return []
        lessons = [h for h in hits if (h.get("kind") == "reflection"
                                       or "lesson" in str(h.get("content", "")).lower())]
        return lessons[:k]

    def _active_goals(self, k: int) -> list:
        if self._goals is None:
            return []
        try:
            from core.goals import GoalStatus
            active = self._goals.list_goals(status=GoalStatus.ACTIVE)
            if len(active) < k:
                active = active + self._goals.list_goals(status=GoalStatus.PENDING)
            return active[:k]
        except Exception:
            log.debug("goal lookup failed", exc_info=True)
            return []

    # ── helpers ────────────────────────────────────────────────────────────────
    @staticmethod
    def _goal_dict(g) -> dict:
        if hasattr(g, "to_dict"):
            return g.to_dict()
        return dict(g)

    @staticmethod
    def _confidence(pkg: ContextPackage) -> float:
        """Coverage-weighted confidence: how much relevant material did we find,
        and how strong were the memory matches?"""
        coverage = min(1.0, (len(pkg.memories) + len(pkg.goals)) / 6.0)
        scores = [m["score"] for m in pkg.memories
                  if isinstance(m, dict) and m.get("score") is not None]
        strength = (sum(scores) / len(scores)) if scores else (0.4 if pkg.memories else 0.0)
        return round(0.5 * coverage + 0.5 * max(0.0, min(1.0, strength)), 3)

    # ── diagnostics ────────────────────────────────────────────────────────────
    def metrics(self) -> dict:
        return {"builds": self._builds}

    def health(self) -> dict:
        return {
            "status": "ok",
            "builds": self._builds,
            "memory": self._memory is not None,
            "goals": self._goals is not None,
            "attention": self._attention is not None,
            "world": self._world is not None,
        }
