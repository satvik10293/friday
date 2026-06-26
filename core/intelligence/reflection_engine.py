"""
core/intelligence/reflection_engine.py — FRIDAY 4.0 (M12)
The reflection engine (Part 9). After every completed task it reviews what happened
— success/failure, time spent, knowledge gained, mistakes — distils a lesson, and
stores it permanently through the secure knowledge API (never by touching the store
directly).
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Reflection:
    task: str
    success: bool
    duration_ms: float = 0.0
    models: list = field(default_factory=list)
    knowledge_gained: str = ""
    mistakes: list = field(default_factory=list)
    lesson: str = ""
    ts: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return dict(self.__dict__)


class ReflectionEngine:
    def __init__(self, knowledge_service=None) -> None:
        # only the secure service API — the engine cannot reach the store directly
        self._knowledge = knowledge_service

    def reflect(self, *, task: str, success: bool, duration_ms: float = 0.0,
                models: Optional[list] = None, outcome: str = "",
                mistakes: Optional[list] = None) -> Reflection:
        mistakes = mistakes or ([] if success else ["task did not succeed"])
        lesson = self._distil(task, success, outcome, mistakes)
        ref = Reflection(task=task, success=success, duration_ms=duration_ms,
                         models=list(models or []), knowledge_gained=outcome,
                         mistakes=mistakes, lesson=lesson)
        self._store(ref)
        return ref

    def _distil(self, task: str, success: bool, outcome: str, mistakes: list) -> str:
        if success:
            return f"For {task} tasks, the approach that produced '{outcome[:80]}' worked."
        return (f"For {task} tasks, avoid: {'; '.join(mistakes)[:120]}. "
                f"Retrieve more context next time.")

    def _store(self, ref: Reflection) -> None:
        """Persist the lesson as knowledge via the secure API (Part 18)."""
        if self._knowledge is None:
            return
        try:
            self._knowledge.promote_reflection({
                "goal_id": None, "lesson": ref.lesson,
                "summary": ref.knowledge_gained or ref.task})
        except Exception:  # noqa: BLE001 — reflection must never crash the task
            pass
