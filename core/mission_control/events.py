"""
core/mission_control/events.py — FRIDAY 4.0 (M10)
The real-time event stream. A bounded in-memory ring buffer of everything that
happens in FRIDAY, rendered as the cockpit's live timeline. Mission Control pushes
events here (and can subscribe to the M1 runtime bus to capture them automatically).
"""

from __future__ import annotations

import threading
import time
from collections import deque
from typing import Optional


class EventStream:
    def __init__(self, capacity: int = 500) -> None:
        self._buf: deque = deque(maxlen=capacity)
        self._seq = 0
        self._lock = threading.Lock()

    def push(self, kind: str, data: Optional[dict] = None, *,
             source: str = "", level: str = "info") -> dict:
        with self._lock:
            self._seq += 1
            ev = {"seq": self._seq, "ts": time.time(), "kind": str(kind),
                  "source": source, "level": level, "data": data or {}}
            self._buf.append(ev)
            return ev

    def recent(self, limit: int = 100, *, level: Optional[str] = None) -> list[dict]:
        with self._lock:
            items = list(self._buf)
        if level:
            items = [e for e in items if e["level"] == level]
        return items[-limit:][::-1]      # newest first

    def alerts(self, limit: int = 50) -> list[dict]:
        with self._lock:
            items = list(self._buf)
        return [e for e in items if e["level"] in ("warning", "critical")][-limit:][::-1]

    def attach_runtime(self, runtime, events) -> None:
        """Subscribe to runtime events so they flow into the stream automatically.
        `events` is an iterable of str-enum event keys to capture."""
        for ev in events:
            try:
                async def _handler(payload, _ev=ev):
                    self.push(str(getattr(_ev, "value", _ev)),
                              data=getattr(payload, "data", {}) if payload else {},
                              source="runtime")
                runtime.on(ev, _handler)
            except Exception:
                pass

    def __len__(self) -> int:
        return len(self._buf)
