"""
core/vision/transport/live_view.py — the live recognition view (M64)

A tiny thread-safe holder for the most recent ANNOTATED camera frame (JPEG with
detection boxes drawn) plus the objects in it. The vision "eyes" loop writes to
it after each processed frame; the dashboard routes read from it. This is the
seam that lets a browser watch FRIDAY recognise things in real time without the
producer (processing thread) and consumer (Flask route) knowing about each other.
"""

from __future__ import annotations

import threading
import time


class LiveView:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._jpeg = b""
        self._objects: list = []
        self._ts = 0.0
        self._frames = 0
        self._events: list = []          # proactive alerts (newest last)

    def update(self, jpeg: bytes, objects: list) -> None:
        with self._lock:
            self._jpeg = jpeg or b""
            self._objects = list(objects or [])
            self._ts = time.time()
            self._frames += 1

    def add_event(self, text: str, kind: str = "info") -> None:
        """Record a notable thing she noticed (a new object, someone appearing)."""
        with self._lock:
            self._events.append({"ts": time.time(), "text": str(text), "kind": kind})
            self._events = self._events[-40:]

    def frame(self) -> bytes:
        with self._lock:
            return self._jpeg

    def state(self) -> dict:
        with self._lock:
            return {"objects": list(self._objects), "ts": self._ts,
                    "frames": self._frames, "has_frame": bool(self._jpeg),
                    "events": list(reversed(self._events[-8:]))}


_live: LiveView | None = None
_lock = threading.Lock()


def get_live_view() -> LiveView:
    global _live
    with _lock:
        if _live is None:
            _live = LiveView()
    return _live
