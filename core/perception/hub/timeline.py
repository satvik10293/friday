"""
core/perception/hub/timeline.py — FRIDAY V3 (M17)
The timeline engine — a chronological record of unified observations that future
milestones (prediction, planning, episodic memory) query with temporal operators:
before / after / during / recently / current / historical. Bounded in-memory ring buffer
(configurable capacity) so long sessions stay memory-light; thread-safe.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from typing import Optional

from .config import TimelineConfig


class Timeline:
    def __init__(self, config: Optional[TimelineConfig] = None) -> None:
        self.config = config or TimelineConfig()
        self._buf: deque = deque(maxlen=self.config.capacity)
        self._lock = threading.Lock()
        self._added = 0

    def add(self, unified) -> None:
        with self._lock:
            self._buf.append(unified)
            self._added += 1

    # ── temporal queries ─────────────────────────────────────────────────────────
    def current(self):
        with self._lock:
            return self._buf[-1] if self._buf else None

    def recently(self, *, seconds: Optional[float] = None, limit: int = 20) -> list:
        window = seconds if seconds is not None else self.config.recent_window_s
        cutoff = time.time() - window
        with self._lock:
            items = [u for u in self._buf if u.timestamp >= cutoff]
        return items[-limit:][::-1]

    def before(self, ts: float, *, limit: int = 50) -> list:
        with self._lock:
            items = [u for u in self._buf if u.timestamp < ts]
        return items[-limit:][::-1]

    def after(self, ts: float, *, limit: int = 50) -> list:
        with self._lock:
            items = [u for u in self._buf if u.timestamp > ts]
        return items[:limit]

    def during(self, start: float, end: float, *, limit: int = 200) -> list:
        with self._lock:
            return [u for u in self._buf if start <= u.timestamp <= end][:limit]

    def historical(self, *, limit: int = 100) -> list:
        with self._lock:
            return list(self._buf)[-limit:][::-1]

    def by_category(self, category: str, *, limit: int = 50) -> list:
        with self._lock:
            items = [u for u in self._buf if u.event_category == category]
        return items[-limit:][::-1]

    # ── observability ────────────────────────────────────────────────────────────
    def __len__(self) -> int:
        return len(self._buf)

    def metrics(self) -> dict:
        return {"added": self._added, "size": len(self._buf), "capacity": self.config.capacity}

    def health(self) -> dict:
        return {"status": "ok", "size": len(self._buf)}
