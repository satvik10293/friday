"""
core/vision/transport/health.py — FRIDAY 6.1 (M14)
Per-camera health. Computes FPS, latency, bandwidth, dropped frames, queue depth,
connection quality, and a 0–100 health score from rolling windows, and decides
status transitions (streaming → degraded → disconnected) used for failure recovery.
Mission Control consumes these.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from enum import Enum
from typing import Optional

from .camera import CameraStatus


class ConnectionQuality(str, Enum):
    EXCELLENT = "excellent"
    GOOD = "good"
    FAIR = "fair"
    POOR = "poor"
    LOST = "lost"


class CameraHealth:
    def __init__(self, camera_id: str, *, target_fps: float = 10.0,
                 degrade_after_s: float = 2.0, disconnect_after_s: float = 6.0,
                 window: int = 60) -> None:
        self.camera_id = camera_id
        self.target_fps = target_fps
        self._degrade_after = degrade_after_s
        self._disconnect_after = disconnect_after_s
        self._frame_ts: deque = deque(maxlen=window)
        self._latencies: deque = deque(maxlen=window)
        self._bytes: deque = deque(maxlen=window)       # (ts, nbytes)
        self.last_frame_at = 0.0
        self.dropped = 0
        self.queue_depth = 0
        self._lock = threading.Lock()

    def on_frame(self, *, latency_ms: float, nbytes: int, ts: Optional[float] = None) -> None:
        ts = ts if ts is not None else time.time()
        with self._lock:
            self._frame_ts.append(ts)
            self._latencies.append(float(latency_ms))
            self._bytes.append((ts, int(nbytes)))
            self.last_frame_at = ts

    def on_drop(self) -> None:
        with self._lock:
            self.dropped += 1

    def set_queue_depth(self, depth: int) -> None:
        self.queue_depth = depth

    # ── derived metrics ─────────────────────────────────────────────────────────
    def fps(self, now: Optional[float] = None) -> float:
        now = now if now is not None else time.time()
        with self._lock:
            recent = [t for t in self._frame_ts if now - t <= 1.0]
        return float(len(recent))

    def avg_latency_ms(self) -> float:
        with self._lock:
            return round(sum(self._latencies) / len(self._latencies), 3) if self._latencies else 0.0

    def bandwidth_bps(self, now: Optional[float] = None) -> float:
        now = now if now is not None else time.time()
        with self._lock:
            recent = [(t, b) for (t, b) in self._bytes if now - t <= 1.0]
        return float(sum(b for _t, b in recent))

    def silence_s(self, now: Optional[float] = None) -> float:
        now = now if now is not None else time.time()
        return (now - self.last_frame_at) if self.last_frame_at else float("inf")

    def status(self, now: Optional[float] = None) -> str:
        s = self.silence_s(now)
        if s == float("inf"):
            return CameraStatus.CONNECTED.value
        if s >= self._disconnect_after:
            return CameraStatus.DISCONNECTED.value
        if s >= self._degrade_after:
            return CameraStatus.DEGRADED.value
        return CameraStatus.STREAMING.value

    def quality(self, now: Optional[float] = None) -> str:
        s = self.silence_s(now)
        if s >= self._disconnect_after:
            return ConnectionQuality.LOST.value
        fps_ratio = self.fps(now) / self.target_fps if self.target_fps else 1.0
        lat = self.avg_latency_ms()
        if fps_ratio >= 0.9 and lat < 150:
            return ConnectionQuality.EXCELLENT.value
        if fps_ratio >= 0.6 and lat < 350:
            return ConnectionQuality.GOOD.value
        if fps_ratio >= 0.3:
            return ConnectionQuality.FAIR.value
        return ConnectionQuality.POOR.value

    def score(self, now: Optional[float] = None) -> int:
        """0–100 composite: frame rate, latency, drops, recency."""
        now = now if now is not None else time.time()
        if self.silence_s(now) >= self._disconnect_after:
            return 0
        fps_ratio = min(1.0, self.fps(now) / self.target_fps) if self.target_fps else 1.0
        lat = self.avg_latency_ms()
        lat_score = max(0.0, 1.0 - lat / 500.0)
        total = self.dropped + len(self._frame_ts)
        drop_score = 1.0 - (self.dropped / total) if total else 1.0
        return int(round(100 * (0.45 * fps_ratio + 0.30 * lat_score + 0.25 * drop_score)))

    def snapshot(self, now: Optional[float] = None) -> dict:
        now = now if now is not None else time.time()
        return {
            "camera_id": self.camera_id,
            "fps": self.fps(now),
            "avg_latency_ms": self.avg_latency_ms(),
            "bandwidth_bps": self.bandwidth_bps(now),
            "dropped": self.dropped,
            "queue_depth": self.queue_depth,
            "silence_s": round(self.silence_s(now), 3) if self.last_frame_at else None,
            "status": self.status(now),
            "quality": self.quality(now),
            "health_score": self.score(now),
        }
