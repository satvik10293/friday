"""
core/cognition/thoughts.py — FRIDAY 5.x (M23, Internal Mind)
The Internal Thought Stream: FRIDAY's private, transient reasoning surface.
It never produces user responses — it holds observations, hypotheses,
concerns, predictions, reminders and planning notes in a bounded ring buffer.
Thoughts expire automatically; they are NOT permanent memories (only what the
Executive verifies is worth keeping ever reaches the Memory Service).

Directive 2 of docs/FRIDAY_5X_COGNITIVE_EVOLUTION.md.
"""

from __future__ import annotations

import itertools
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Optional

THOUGHT_KINDS = ("observation", "hypothesis", "concern", "prediction",
                 "reminder", "planning")

_DEFAULT_TTL_S = 15 * 60          # a quarter hour, then the thought fades
_ids = itertools.count(1)


@dataclass
class Thought:
    kind: str
    text: str
    source: str = "friday"
    confidence: float = 0.5
    ttl_s: float = _DEFAULT_TTL_S
    ts: float = field(default_factory=time.time)
    id: int = field(default_factory=lambda: next(_ids))

    def expired(self, now: Optional[float] = None) -> bool:
        return ((now or time.time()) - self.ts) > self.ttl_s

    def to_dict(self) -> dict:
        return {"id": self.id, "kind": self.kind, "text": self.text,
                "source": self.source, "confidence": round(self.confidence, 3),
                "ts": self.ts, "ttl_s": self.ttl_s}


class ThoughtStream:
    """Thread-safe bounded ring buffer of expiring thoughts."""

    def __init__(self, capacity: int = 200) -> None:
        self._buf: deque[Thought] = deque(maxlen=capacity)
        self._lock = threading.Lock()
        self.generated = 0

    def think(self, kind: str, text: str, *, source: str = "friday",
              confidence: float = 0.5, ttl_s: float = _DEFAULT_TTL_S) -> Thought:
        if kind not in THOUGHT_KINDS:
            kind = "observation"
        text = (text or "").strip()
        thought = Thought(kind=kind, text=text, source=source,
                          confidence=max(0.0, min(1.0, confidence)), ttl_s=ttl_s)
        if text:
            with self._lock:
                self._buf.append(thought)
                self.generated += 1
        return thought

    def _sweep(self) -> None:
        now = time.time()
        with self._lock:
            live = [t for t in self._buf if not t.expired(now)]
            self._buf.clear()
            self._buf.extend(live)

    def recent(self, limit: int = 20, *, kind: Optional[str] = None) -> list[Thought]:
        self._sweep()
        with self._lock:
            items = list(self._buf)
        if kind:
            items = [t for t in items if t.kind == kind]
        return items[-limit:][::-1]

    def snapshot(self) -> dict:
        """Mission Control / Self Model view of the stream."""
        thoughts = self.recent(20)
        return {"title": "Internal Thoughts", "generated": self.generated,
                "live": len(thoughts),
                "thoughts": [t.to_dict() for t in thoughts]}

    def __len__(self) -> int:
        self._sweep()
        with self._lock:
            return len(self._buf)
