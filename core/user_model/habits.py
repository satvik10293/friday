"""
core/user_model/habits.py — FRIDAY 4.0 (M9)
Habit detection. FRIDAY notices *when* the user tends to do certain kinds of
activity (study, coding, research, project work) and assigns a confidence to each
recurring pattern — e.g. "codes in the evening (0.82)".

No surveillance: a habit is only ever recorded from an activity the user has
explicitly reported (via `record_activity`). FRIDAY never watches the screen or
the clock on its own here — it only counts what it was told.
"""

from __future__ import annotations

import time
from typing import Optional

from .models import Habit, now
from .store import UserModelEvent, UserModelStore

# Coarse parts of day — deliberately low-resolution (privacy: no precise tracking).
_BUCKETS = (("night", 0, 5), ("morning", 5, 12), ("afternoon", 12, 17),
            ("evening", 17, 22), ("night", 22, 24))


def bucket_for(hour: int) -> str:
    for name, lo, hi in _BUCKETS:
        if lo <= hour < hi:
            return name
    return "night"


class HabitTracker:
    def __init__(self, store: UserModelStore, emit=None, *,
                 discovery_threshold: float = 0.6) -> None:
        self._store = store
        self._emit = emit
        self._threshold = discovery_threshold

    def record_activity(self, kind: str, *, at: Optional[float] = None,
                        bucket: Optional[str] = None) -> Habit:
        """Record that the user did `kind` of activity (optionally at time `at`).
        Confidence grows with repetition and saturates."""
        if bucket is None:
            hour = time.localtime(at if at is not None else time.time()).tm_hour
            bucket = bucket_for(hour)
        key = f"{kind}@{bucket}"
        habit = self._store.get_habit(key) or Habit(key=key, kind=kind, bucket=bucket)
        habit.count += 1
        # diminishing-returns confidence: 1 - 1/(1+count), normalised by a soft cap
        habit.confidence = min(1.0, habit.count / (habit.count + 3))
        habit.updated_at = now()

        was_below = habit.count <= 1 or (habit.confidence - 1.0 / (habit.count + 2)) < self._threshold
        self._store.save_habit(habit)
        self._store.record_metric("user.activity.recorded")

        if habit.confidence >= self._threshold and was_below:
            self._store.add_event(UserModelEvent.HABIT_DISCOVERED.value,
                                  {"key": key, "confidence": round(habit.confidence, 3)})
            if self._emit:
                self._emit(UserModelEvent.HABIT_DISCOVERED,
                           {"key": key, "confidence": habit.confidence})
        return habit

    def get(self, kind: str, bucket: str) -> Optional[Habit]:
        return self._store.get_habit(f"{kind}@{bucket}")

    def list(self, kind: Optional[str] = None) -> list[Habit]:
        return self._store.list_habits(kind=kind)

    def discovered(self) -> list[Habit]:
        """Habits FRIDAY is confident enough to act on."""
        return [h for h in self._store.list_habits() if h.confidence >= self._threshold]

    def typical_time(self, kind: str) -> Optional[str]:
        """The bucket the user most often does `kind` in (or None)."""
        habits = self._store.list_habits(kind=kind)
        if not habits:
            return None
        return max(habits, key=lambda h: h.count).bucket
