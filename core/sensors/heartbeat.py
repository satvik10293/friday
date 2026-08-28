"""
core/sensors/heartbeat.py — FRIDAY 4.0 (M6)
Sensor heartbeats: track liveness so the manager can tell a healthy-but-quiet
sensor from a stalled one. A heartbeat is updated on every poll; a sensor is
"stale" if it hasn't beaten within a grace multiple of its interval.
"""

from __future__ import annotations

import time
from dataclasses import dataclass


@dataclass
class Heartbeat:
    sensor: str
    interval_s: float = 5.0
    last_beat: float = 0.0
    beats: int = 0
    misses: int = 0
    healthy: bool = True

    def beat(self, ok: bool = True, now: float | None = None) -> None:
        self.last_beat = now if now is not None else time.time()
        self.beats += 1
        self.healthy = ok
        if not ok:
            self.misses += 1

    def is_stale(self, now: float | None = None, grace: float = 3.0) -> bool:
        now = now if now is not None else time.time()
        if self.last_beat == 0.0:
            return False                       # never polled yet ≠ stale
        return (now - self.last_beat) > (self.interval_s * grace)

    def to_dict(self) -> dict:
        return dict(self.__dict__)


class HeartbeatMonitor:
    """Tracks one Heartbeat per sensor."""

    def __init__(self) -> None:
        self._beats: dict[str, Heartbeat] = {}

    def register(self, sensor: str, interval_s: float = 5.0) -> Heartbeat:
        hb = Heartbeat(sensor=sensor, interval_s=interval_s)
        self._beats[sensor] = hb
        return hb

    def beat(self, sensor: str, ok: bool = True, now: float | None = None) -> None:
        hb = self._beats.get(sensor)
        if hb is None:
            hb = self.register(sensor)
        hb.beat(ok, now)

    def get(self, sensor: str) -> Heartbeat | None:
        return self._beats.get(sensor)

    def stale(self, now: float | None = None) -> list[str]:
        return [name for name, hb in self._beats.items() if hb.is_stale(now)]

    def snapshot(self) -> dict:
        return {name: hb.to_dict() for name, hb in self._beats.items()}
