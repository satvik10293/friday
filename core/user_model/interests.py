"""
core/user_model/interests.py — FRIDAY 4.0 (M9)
Interest graph. Tracks the topics the user cares about (AI, coding, robotics,
biology, stocks, genetics, personal projects…), how strongly, how that strength
evolves over time, and how interests relate to one another.

The graph lets FRIDAY reason "the user likes genetics, and genetics relates to
biology, so biology knowledge is probably relevant too."
"""

from __future__ import annotations

from typing import Optional

from .models import Interest, InterestLink, now
from .store import UserModelEvent, UserModelStore


def _clamp(x: float) -> float:
    return max(0.0, min(1.0, x))


class InterestGraph:
    def __init__(self, store: UserModelStore, emit=None, *, rate: float = 0.1,
                 decay: float = 0.0) -> None:
        self._store = store
        self._emit = emit
        self._rate = rate
        self._decay = decay

    def express(self, name: str, *, strength: float = 1.0,
                category: str = "") -> Interest:
        """Record that the user expressed interest in `name`. Repeated mentions
        raise its weight; evolution is tracked via count + last_seen + events."""
        name = name.strip()
        interest = self._store.get_interest(name)
        if interest is None:
            interest = Interest(name=name, weight=0.5, category=category)
        before = interest.weight
        interest.weight = _clamp(interest.weight + self._rate * strength)
        interest.count += 1
        interest.last_seen = now()
        if category:
            interest.category = category
        self._store.save_interest(interest)
        self._store.add_event(UserModelEvent.INTEREST_GROWN.value,
                              {"name": name, "weight": round(interest.weight, 3),
                               "delta": round(interest.weight - before, 3)})
        self._store.record_metric("user.interest.grown")
        if self._emit:
            self._emit(UserModelEvent.INTEREST_GROWN,
                       {"name": name, "weight": interest.weight})
        return interest

    def link(self, a: str, b: str, weight: float = 1.0) -> None:
        """Relate two interests (symmetric)."""
        if a.strip() == b.strip():
            return
        self._store.add_interest_link(InterestLink(a.strip(), b.strip(), weight))

    def related(self, name: str) -> list[str]:
        name = name.strip()
        out = []
        for link in self._store.interest_links(name):
            other = link.b if link.a == name else link.a
            if other != name:
                out.append(other)
        return out

    def get(self, name: str) -> Optional[Interest]:
        return self._store.get_interest(name.strip())

    def weight(self, name: str, default: float = 0.0) -> float:
        interest = self._store.get_interest(name.strip())
        return interest.weight if interest is not None else default

    def list(self) -> list[Interest]:
        return self._store.list_interests()

    def top(self, n: int = 5) -> list[Interest]:
        return self._store.list_interests()[:n]

    def evolution(self, name: str, limit: int = 50) -> list[dict]:
        """The recorded growth events for one interest (its history over time)."""
        name = name.strip()
        return [e for e in self._store.events(UserModelEvent.INTEREST_GROWN.value, limit=500)
                if e["data"].get("name") == name][:limit]

    def relevance_boost(self, text: str) -> float:
        """How strongly a piece of text aligns with the user's interests — used to
        re-rank knowledge. Sum of weights of interests whose name appears in text."""
        t = (text or "").lower()
        boost = 0.0
        for interest in self._store.list_interests():
            if interest.name.lower() in t:
                boost += interest.weight
        return boost
