"""
core/perception/brain.py — FRIDAY 4.0 (M6)
PerceptiveBrain: an additive subclass of the M5 ExecutiveBrain that gives FRIDAY
environmental awareness. It can poll sensors, summarize the current environment,
and reason about *reality* (the world model + recent observations) rather than only
memory.

Delivered as a subclass (not an edit to executive.py) to honor M6's hard rule:
"No M1–M5 files may be modified." PerceptiveBrain is a drop-in superset of
ExecutiveBrain that exposes observe / analyze_environment / current_environment /
important_changes.
"""

from __future__ import annotations

import logging
import threading
from typing import Optional

from core.executive import ExecutiveBrain

log = logging.getLogger("friday.perception.brain")


class PerceptiveBrain(ExecutiveBrain):
    def __init__(self, *, perception_manager=None, sensor_manager=None, **kwargs) -> None:
        super().__init__(**kwargs)
        self._perception = perception_manager
        self._sensors = sensor_manager

    # ── perception API ─────────────────────────────────────────────────────────
    def observe(self) -> list[dict]:
        """Poll all sensors once and ingest their observations through perception
        (which dedupes, scores, and promotes to the world model). Returns the
        per-observation ingest results."""
        if self._sensors is not None:
            return self._sensors.poll_once()
        return []

    def current_environment(self) -> dict:
        """A snapshot of reality as FRIDAY currently models it: world entities
        grouped by kind."""
        if self._world is None:
            return {}
        env: dict[str, list] = {}
        for e in self._world.all_entities():
            env.setdefault(e.kind, []).append({"name": e.name, "state": e.state,
                                               "confidence": e.confidence})
        return env

    def important_changes(self, limit: int = 5) -> list[dict]:
        """The most salient recent observations (attention-ranked), falling back to
        promoted observations."""
        if self._perception is None:
            return []
        focus = self._perception.focus(limit)
        if focus:
            return [f.to_dict() for f in focus]
        return self._perception.promoted(limit)

    def analyze_environment(self) -> dict:
        """Reason about the current environment: combine world state + salient
        observations + active goals into a reasoning result. This is the brain
        thinking about reality, not just stored memory."""
        from core.context import ContextPackage
        changes = self.important_changes()
        goals = self._all_goals()
        pkg = ContextPackage(
            query="current environment", focus_items=changes,
            goals=[g.to_dict() for g in goals],
            world=(self._world.counts() if self._world is not None else {}),
            confidence=0.6,
        )
        reasoning = self.reasoner.analyze(pkg, goals=goals)
        with self._lock:
            self._metrics["reasoning_cycles"] += 1
        self._observe("executive.analyze_environment", reasoning.rationale,
                      reasoning.confidence)
        return {
            "environment": self.current_environment(),
            "important_changes": changes,
            "reasoning": reasoning.to_dict(),
            "summary": reasoning.rationale,
        }

    # ── health ─────────────────────────────────────────────────────────────────
    def health(self) -> dict:
        h = super().health()
        if self._perception is not None:
            h["perception"] = self._perception.health(
                self._sensors.health() if self._sensors is not None else None)
        if self._sensors is not None:
            h["sensors"] = self._sensors.health()
        return h

    def attach(self, runtime, sensor_interval: float = 5.0) -> None:
        super().attach(runtime)
        if self._perception is not None:
            runtime.register_health("perception", lambda: self._perception.health(
                self._sensors.health() if self._sensors is not None else None))
        if self._sensors is not None:
            self._sensors.attach(runtime, every=sensor_interval)


# ── singleton ───────────────────────────────────────────────────────────────────
_pbrain: Optional[PerceptiveBrain] = None
_pbrain_lock = threading.Lock()


def get_perceptive_brain() -> PerceptiveBrain:
    global _pbrain
    with _pbrain_lock:
        if _pbrain is None:
            _pbrain = PerceptiveBrain()
    return _pbrain
