"""
core/services/learning_service.py — FRIDAY V3 (M16)
LearningService — a PLACEHOLDER for the M17+ learning subsystem. It records experience
(spatial corrections, tracking outcomes, relationship confirmations) into a bounded
buffer so future learning can train on it, but performs no training yet. Stable API now
so callers don't change when real learning lands.
"""

from __future__ import annotations

import time
from collections import deque


class LearningService:
    name = "learning"

    def __init__(self, *, buffer: int = 2000) -> None:
        self._buffer: deque = deque(maxlen=buffer)

    def record(self, kind: str, data: dict) -> None:
        self._buffer.append({"kind": kind, "data": data, "ts": time.time()})

    def samples(self, *, kind: str = "", limit: int = 100) -> list:
        items = [s for s in self._buffer if not kind or s["kind"] == kind]
        return items[-limit:][::-1]

    def health(self) -> dict:
        return {"status": "placeholder", "buffered": len(self._buffer)}
