"""
core/sensors/manager.py — FRIDAY 4.0 (M6)
The Sensor Manager: coordinates all registered sensors. It polls them, collects
their Observations, optionally fuses corroborating readings, feeds the Perception
Manager, records sensor health/metrics, and (when attached) schedules periodic
polling on the M1 Runtime.

It is the bridge from raw sensing → perception → world model.
"""

from __future__ import annotations

import logging
from typing import Optional

from .heartbeat import HeartbeatMonitor
from .registry import SensorRegistry

log = logging.getLogger("friday.sensors.manager")


class SensorManager:
    def __init__(self, registry: Optional[SensorRegistry] = None, perception_manager=None,
                 fusion=None, store=None, runtime=None,
                 heartbeat: Optional[HeartbeatMonitor] = None) -> None:
        self._registry = registry if registry is not None else SensorRegistry()
        self._perception = perception_manager
        self._fusion = fusion
        self._store = store if store is not None else getattr(perception_manager, "_store", None)
        self._runtime = runtime
        self._heartbeat = heartbeat if heartbeat is not None else HeartbeatMonitor()
        self._polls = 0

    # ── registration ───────────────────────────────────────────────────────────
    def register(self, sensor):
        self._registry.register(sensor)
        sensor.start()
        self._heartbeat.register(sensor.name, sensor.interval_s)
        return sensor

    def unregister(self, name: str) -> None:
        s = self._registry.get(name)
        if s is not None:
            s.stop()
        self._registry.unregister(name)

    def sensors(self) -> list:
        return self._registry.list()

    # ── polling ────────────────────────────────────────────────────────────────
    def collect(self) -> list:
        """Poll every sensor once and return the raw observations (no ingest).
        Records per-sensor health/metrics + heartbeats."""
        observations: list = []
        for sensor in self._registry.list():
            errs_before = sensor.metrics()["errors"]
            batch = sensor.poll()
            ok = sensor.metrics()["errors"] == errs_before
            self._heartbeat.beat(sensor.name, ok=ok)
            observations.extend(list(batch))
            if self._store is not None:
                m = sensor.metrics()
                self._store.record_sensor_health(sensor.name, ok,
                                                 sensor.health().get("last_error") or "")
                self._store.record_sensor_metrics(sensor.name, m["polls"],
                                                  m["observations"], m["errors"])
        return observations

    def poll_once(self) -> list[dict]:
        """Full pass: collect → fuse → ingest into perception. Returns ingest
        results (one dict per observation). Safe to schedule on the Runtime."""
        observations = self.collect()
        if self._fusion is not None:
            observations = self._fusion.fuse_and_merge(observations)
        results: list[dict] = []
        if self._perception is not None:
            results = self._perception.ingest_batch(observations)
        self._polls += 1
        return results

    # ── lifecycle ──────────────────────────────────────────────────────────────
    def start_all(self) -> None:
        for s in self._registry.list():
            s.start()

    def stop_all(self) -> None:
        for s in self._registry.list():
            s.stop()

    def attach(self, runtime, every: float = 5.0) -> None:
        self._runtime = runtime
        runtime.register_health("sensors", self.health)
        runtime.schedule("sensors.poll", self.poll_once, every=every)

    # ── diagnostics ────────────────────────────────────────────────────────────
    def health(self) -> dict:
        reg = self._registry.health()
        stale = self._heartbeat.stale()
        return {"status": "ok" if not stale else "degraded", "polls": self._polls,
                "count": reg["count"], "sensors": reg["sensors"],
                "stale": stale, "heartbeats": self._heartbeat.snapshot()}

    def metrics(self) -> dict:
        return {"polls": self._polls, "sensors": len(self._registry)}
