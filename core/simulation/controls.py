"""
core/simulation/controls.py — FRIDAY 4.0 (M11)
Interactive playback over a simulation's recorded steps (Part 6): pause, resume,
fast-forward, replay, restart, and step navigation. Operates on the snapshots the
engine recorded, so scrubbing is instant (no recomputation).
"""

from __future__ import annotations

from .models import SimStatus, Simulation


class SimulationControls:
    def __init__(self, simulation: Simulation) -> None:
        self._sim = simulation
        self._pos = 0
        self._paused = False

    @property
    def position(self) -> int:
        return self._pos

    @property
    def total(self) -> int:
        return len(self._sim.steps)

    def pause(self) -> None:
        self._paused = True
        self._sim.status = SimStatus.PAUSED.value

    def resume(self) -> None:
        self._paused = False
        self._sim.status = SimStatus.RUNNING.value

    @property
    def paused(self) -> bool:
        return self._paused

    def fast_forward(self, n: int = 1) -> int:
        self._pos = min(self.total - 1, self._pos + n) if self.total else 0
        return self._pos

    def rewind(self, n: int = 1) -> int:
        self._pos = max(0, self._pos - n)
        return self._pos

    def goto(self, index: int) -> int:
        self._pos = max(0, min(self.total - 1, index)) if self.total else 0
        return self._pos

    def replay(self) -> int:
        self._pos = 0
        return self._pos

    restart = replay

    def current(self):
        if not self._sim.steps:
            return None
        return self._sim.steps[self._pos]

    def state(self) -> dict:
        cur = self.current()
        return {"position": self._pos, "total": self.total, "paused": self._paused,
                "metrics": cur.metrics if cur else {}}
