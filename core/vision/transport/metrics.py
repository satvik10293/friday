"""
core/vision/transport/metrics.py — FRIDAY 6.1 (M14)
Transport-wide metrics, aggregated across all cameras. Thread-safe counters +
throughput, published to Mission Control. Frame pixel data is never recorded here.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass, field


@dataclass
class TransportMetrics:
    cameras_registered: int = 0
    cameras_removed: int = 0
    frames_received: int = 0
    frames_dropped: int = 0
    frames_corrupt: int = 0
    decode_failures: int = 0
    reconnects: int = 0
    bytes_total: int = 0
    _recent_frames: deque = field(default_factory=lambda: deque(maxlen=300))   # ts
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def frame_received(self, nbytes: int = 0) -> None:
        with self._lock:
            self.frames_received += 1
            self.bytes_total += int(nbytes)
            self._recent_frames.append(time.time())

    def frame_dropped(self) -> None:
        with self._lock:
            self.frames_dropped += 1

    def frame_corrupt(self) -> None:
        with self._lock:
            self.frames_corrupt += 1

    def decode_failure(self) -> None:
        with self._lock:
            self.decode_failures += 1

    def camera_registered(self) -> None:
        with self._lock:
            self.cameras_registered += 1

    def camera_removed(self) -> None:
        with self._lock:
            self.cameras_removed += 1

    def reconnect(self) -> None:
        with self._lock:
            self.reconnects += 1

    def total_fps(self, now: float = None) -> float:
        now = now if now is not None else time.time()
        with self._lock:
            return self._fps_locked(now)

    def _fps_locked(self, now: float) -> float:
        """Frames in the last second. Caller MUST hold self._lock (the lock is not
        reentrant, so snapshot() computes fps via this helper instead of re-locking)."""
        return float(sum(1 for t in self._recent_frames if now - t <= 1.0))

    def snapshot(self) -> dict:
        now = time.time()
        with self._lock:
            received = self.frames_received
            return {
                "cameras_registered": self.cameras_registered,
                "cameras_removed": self.cameras_removed,
                "frames_received": received,
                "frames_dropped": self.frames_dropped,
                "frames_corrupt": self.frames_corrupt,
                "decode_failures": self.decode_failures,
                "reconnects": self.reconnects,
                "bytes_total": self.bytes_total,
                "drop_rate": round(self.frames_dropped / received, 4) if received else 0.0,
                "total_fps": self._fps_locked(now),
            }
