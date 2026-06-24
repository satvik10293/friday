"""
core/sensors/registry.py — FRIDAY 4.0 (M6)
Thread-safe sensor registry. Mirrors the M3 SkillRegistry discipline: duplicate-
guarded registration, lookup, listing, and aggregate health.
"""

from __future__ import annotations

import threading
from typing import Optional

from .base import Sensor


class SensorRegistry:
    def __init__(self) -> None:
        self._sensors: dict[str, Sensor] = {}
        self._lock = threading.RLock()

    def register(self, sensor: Sensor) -> Sensor:
        if not sensor.name:
            raise ValueError("sensor must have a name")
        with self._lock:
            if sensor.name in self._sensors:
                raise ValueError(f"sensor '{sensor.name}' already registered")
            self._sensors[sensor.name] = sensor
        return sensor

    def unregister(self, name: str) -> None:
        with self._lock:
            self._sensors.pop(name, None)

    def get(self, name: str) -> Optional[Sensor]:
        with self._lock:
            return self._sensors.get(name)

    def has(self, name: str) -> bool:
        with self._lock:
            return name in self._sensors

    def list(self) -> list[Sensor]:
        with self._lock:
            return list(self._sensors.values())

    def names(self) -> list[str]:
        with self._lock:
            return list(self._sensors)

    def __len__(self) -> int:
        with self._lock:
            return len(self._sensors)

    def health(self) -> dict:
        with self._lock:
            sensors = {name: s.health() for name, s in self._sensors.items()}
        return {"count": len(sensors), "sensors": sensors}
