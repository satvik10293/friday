"""
core/vision/transport/frame_queue.py — FRIDAY 6.1 (M14)
A thread-safe, bounded frame queue with an explicit overflow policy and back-pressure.
This generalises the receiver's `maxsize=1, drop-oldest` design into production
infrastructure: it never blocks the socket/decoder threads under load (default policy
drops the oldest frame, keeping the freshest), and it publishes the metrics
(enqueued / dropped / depth / latency) the health system needs.
"""

from __future__ import annotations

import threading
from collections import deque
from enum import Enum
from typing import Optional

from .frame import Frame


class OverflowPolicy(str, Enum):
    DROP_OLDEST = "drop_oldest"   # keep the freshest frame (default; real-time vision)
    DROP_NEWEST = "drop_newest"   # keep the backlog (when order matters more than latency)
    BLOCK = "block"               # apply back-pressure (bounded wait)


class FrameQueue:
    def __init__(self, maxsize: int = 2, *,
                 policy: OverflowPolicy = OverflowPolicy.DROP_OLDEST) -> None:
        self.maxsize = max(1, maxsize)
        self.policy = policy
        self._buf: deque = deque()
        self._lock = threading.Condition()
        self.enqueued = 0
        self.dropped = 0
        self.max_depth = 0
        self.last_latency_ms = 0.0

    def put(self, frame: Frame, *, timeout: float = 0.5) -> bool:
        """Enqueue a frame. Returns True if stored, False if dropped (the caller can
        emit a frame.dropped event). Never blocks except under the BLOCK policy."""
        with self._lock:
            if len(self._buf) >= self.maxsize:
                if self.policy is OverflowPolicy.DROP_OLDEST:
                    self._buf.popleft()
                    self.dropped += 1
                elif self.policy is OverflowPolicy.DROP_NEWEST:
                    self.dropped += 1
                    return False
                else:  # BLOCK — bounded back-pressure
                    if not self._lock.wait_for(lambda: len(self._buf) < self.maxsize, timeout):
                        self.dropped += 1
                        return False
            self._buf.append(frame)
            self.enqueued += 1
            self.last_latency_ms = frame.latency_ms
            self.max_depth = max(self.max_depth, len(self._buf))
            self._lock.notify()
            return True

    def get(self, *, timeout: Optional[float] = None) -> Optional[Frame]:
        with self._lock:
            if timeout is not None and not self._buf:
                self._lock.wait_for(lambda: bool(self._buf), timeout)
            if not self._buf:
                return None
            frame = self._buf.popleft()
            self._lock.notify()
            return frame

    def peek(self) -> Optional[Frame]:
        with self._lock:
            return self._buf[-1] if self._buf else None

    def clear(self) -> None:
        with self._lock:
            self._buf.clear()

    @property
    def depth(self) -> int:
        with self._lock:
            return len(self._buf)

    def stats(self) -> dict:
        with self._lock:
            return {"depth": len(self._buf), "maxsize": self.maxsize,
                    "enqueued": self.enqueued, "dropped": self.dropped,
                    "max_depth": self.max_depth, "policy": self.policy.value,
                    "drop_rate": round(self.dropped / self.enqueued, 4) if self.enqueued else 0.0}
