"""
core/user_model/learning_profile.py — FRIDAY 4.0 (M9)
Tracks how the user learns best, from conversation observations:

    visual          — prefers diagrams / images / spatial explanation
    step_by_step    — prefers ordered, incremental instructions
    example_driven  — prefers concrete examples first
    deep_dive       — prefers thorough, first-principles depth

Each observation increments the matching style's score; the dominant style is the
one FRIDAY leans on when teaching.
"""

from __future__ import annotations

from typing import Optional

from .models import LearningStyleType
from .store import UserModelEvent, UserModelStore


class LearningProfile:
    def __init__(self, store: UserModelStore, emit=None) -> None:
        self._store = store
        self._emit = emit

    def observe(self, style: str, *, weight: float = 1.0) -> dict:
        """Record evidence that the user favours `style`."""
        style = LearningStyleType(style).value if not isinstance(style, str) \
            else style
        row = self._store.get_learning(style)
        score = (row["score"] if row else 0.0) + weight
        count = (row["count"] if row else 0) + 1
        self._store.save_learning(style, score, count)
        self._store.record_metric("user.learning.adapted")
        if self._emit:
            self._emit(UserModelEvent.LEARNING_ADAPTED, {"style": style, "score": score})
        return {"style": style, "score": score, "count": count}

    def observe_visual(self):        return self.observe(LearningStyleType.VISUAL.value)
    def observe_step_by_step(self):  return self.observe(LearningStyleType.STEP_BY_STEP.value)
    def observe_example(self):       return self.observe(LearningStyleType.EXAMPLE_DRIVEN.value)
    def observe_deep_dive(self):     return self.observe(LearningStyleType.DEEP_DIVE.value)

    def scores(self) -> dict:
        return {r["style"]: r["score"] for r in self._store.list_learning()}

    def dominant(self) -> Optional[str]:
        rows = self._store.list_learning()
        if not rows:
            return None
        top = rows[0]
        return top["style"] if top["score"] > 0 else None

    def profile(self) -> dict:
        rows = self._store.list_learning()
        total = sum(r["score"] for r in rows) or 1.0
        return {
            "dominant": self.dominant(),
            "distribution": {r["style"]: round(r["score"] / total, 3) for r in rows},
        }
