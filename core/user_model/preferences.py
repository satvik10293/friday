"""
core/user_model/preferences.py — FRIDAY 4.0 (M9)
Preference engine. FRIDAY learns preferences automatically from repeated signals:
each observation nudges a preference's score toward 1.0 (confirmed) or 0.0
(rejected). Categories: UI, coding, learning, communication, general.

Example: the user repeatedly asks for detailed explanations → the
`learning.detail` preference score rises and stays high.

Only learns from signals the user actually produces — no inference about anything
the user hasn't expressed.
"""

from __future__ import annotations

from typing import Optional

from .models import Preference, PreferenceCategory, now
from .store import UserModelEvent, UserModelStore


def _clamp(x: float) -> float:
    return max(0.0, min(1.0, x))


class PreferenceEngine:
    def __init__(self, store: UserModelStore, emit=None, *, rate: float = 0.15) -> None:
        self._store = store
        self._emit = emit
        self._rate = rate

    def observe(self, key: str, *, positive: bool = True,
                category: str = PreferenceCategory.GENERAL.value,
                value: str = "", strength: float = 1.0) -> Preference:
        """Record one preference signal. Positive signals raise the score, negative
        lower it; repeated signals converge the score and grow evidence."""
        pref = self._store.get_preference(key)
        if pref is None:
            pref = Preference(key=key, category=category, value=value, score=0.5)
        delta = self._rate * strength * (1.0 if positive else -1.0)
        pref.score = _clamp(pref.score + delta)
        pref.evidence_count += 1
        if value:
            pref.value = value
        if category:
            pref.category = category
        pref.updated_at = now()
        self._store.save_preference(pref)
        self._store.add_event(UserModelEvent.PREFERENCE_CHANGED.value,
                              {"key": key, "score": round(pref.score, 3)})
        self._store.record_metric("user.preference.changed")
        if self._emit:
            self._emit(UserModelEvent.PREFERENCE_CHANGED,
                       {"key": key, "score": pref.score})
        return pref

    def set(self, key: str, value: str, *, score: float = 0.9,
            category: str = PreferenceCategory.GENERAL.value) -> Preference:
        """Explicit user-stated preference (trusted, high score)."""
        pref = self._store.get_preference(key) or Preference(key=key)
        pref.value = value
        pref.category = category
        pref.score = _clamp(score)
        pref.evidence_count += 1
        pref.updated_at = now()
        self._store.save_preference(pref)
        if self._emit:
            self._emit(UserModelEvent.PREFERENCE_CHANGED, {"key": key, "score": pref.score})
        return pref

    def get(self, key: str) -> Optional[Preference]:
        return self._store.get_preference(key)

    def score(self, key: str, default: float = 0.5) -> float:
        pref = self._store.get_preference(key)
        return pref.score if pref is not None else default

    def list(self, category: Optional[str] = None) -> list[Preference]:
        return self._store.list_preferences(category=category)

    def strong(self, threshold: float = 0.65) -> list[Preference]:
        """Confidently-held preferences (used to personalise behaviour)."""
        return [p for p in self._store.list_preferences() if p.score >= threshold]
