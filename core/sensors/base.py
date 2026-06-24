"""
core/sensors/base.py — FRIDAY 4.0 (M6)
The abstract Sensor. A sensor is the only thing that produces Observations: it
polls some slice of reality (system, time, processes, files, …) and returns
Observation objects. Sensors are local-only by contract — no network/cloud calls.

Subclasses set metadata (name/version/type/interval) and implement `observe()`.
`poll()` wraps `observe()` with error isolation and metrics so one flaky sensor
never breaks the manager.
"""

from __future__ import annotations

import logging
import time
from abc import ABC, abstractmethod
from typing import Optional

from core.perception.models import (
    Observation, ObservationBatch, ObservationSource, ObservationType, new_observation,
)

log = logging.getLogger("friday.sensors.base")


class Sensor(ABC):
    name: str = ""
    version: str = "1.0.0"
    type: ObservationType = ObservationType.CUSTOM
    interval_s: float = 5.0

    def __init__(self) -> None:
        self._started = False
        self._polls = 0
        self._errors = 0
        self._observations = 0
        self._last_error: Optional[str] = None
        self._last_poll: Optional[float] = None

    # ── lifecycle ──────────────────────────────────────────────────────────────
    def start(self) -> None:
        self._started = True

    def stop(self) -> None:
        self._started = False

    @property
    def started(self) -> bool:
        return self._started

    # ── observation ────────────────────────────────────────────────────────────
    @abstractmethod
    def observe(self) -> list[Observation]:
        """Produce zero or more Observations about the current state of the world.
        Must not raise for ordinary 'nothing to report' — return []."""
        raise NotImplementedError

    def poll(self) -> ObservationBatch:
        """Error-isolated wrapper around observe(); updates metrics + heartbeat."""
        self._polls += 1
        self._last_poll = time.time()
        batch = ObservationBatch(sensor=self.name)
        try:
            for obs in self.observe() or []:
                batch.add(obs)
            self._observations += len(batch)
        except Exception as e:                     # one bad poll never kills the manager
            self._errors += 1
            self._last_error = str(e)
            log.debug("sensor '%s' poll failed: %s", self.name, e, exc_info=True)
        return batch

    # ── metadata / diagnostics ─────────────────────────────────────────────────
    def capabilities(self) -> dict:
        return {"name": self.name, "version": self.version, "type": self.type.value,
                "interval_s": self.interval_s}

    def health(self) -> dict:
        healthy = self._last_error is None or self._errors < max(1, self._polls)
        return {"name": self.name, "healthy": healthy, "started": self._started,
                "polls": self._polls, "observations": self._observations,
                "errors": self._errors, "last_error": self._last_error,
                "last_poll": self._last_poll}

    def metrics(self) -> dict:
        return {"polls": self._polls, "observations": self._observations,
                "errors": self._errors}

    # ── helper ─────────────────────────────────────────────────────────────────
    def _obs(self, payload: dict, *, confidence: float = 0.8,
             type: Optional[ObservationType] = None,
             metadata: Optional[dict] = None) -> Observation:
        return new_observation(
            type or self.type,
            ObservationSource(name=self.name, kind="sensor", version=self.version),
            payload=payload, confidence=confidence, metadata=metadata or {},
        )

    def __repr__(self) -> str:
        return f"<Sensor {self.name} v{self.version} {self.type.value}>"
