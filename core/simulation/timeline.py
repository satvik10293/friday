"""
core/simulation/timeline.py — FRIDAY 4.0 (M11)
The time dimension (Part 8): past / present / predicted-future over a simulation's
steps. The user can scrub through time and watch the run evolve. "Predicted future"
extends the present trend forward without re-running the engine.
"""

from __future__ import annotations

from .models import Simulation


class Timeline:
    def __init__(self, simulation: Simulation) -> None:
        self._sim = simulation
        self._present = max(0, len(simulation.steps) - 1)

    @property
    def present_index(self) -> int:
        return self._present

    def scrub(self, index: int) -> int:
        n = len(self._sim.steps)
        self._present = max(0, min(n - 1, index)) if n else 0
        return self._present

    def past(self) -> list:
        return [s.to_dict() for s in self._sim.steps[: self._present]]

    def present(self):
        if not self._sim.steps:
            return None
        return self._sim.steps[self._present].to_dict()

    def predicted_future(self, horizon: int = 3) -> list:
        """Linear-extrapolate the most-recent numeric metrics forward `horizon`
        steps. A cheap forecast for the timeline's 'future' band — clearly marked
        predicted, never persisted as real steps."""
        steps = self._sim.steps
        if len(steps) < 2:
            return []
        a, b = steps[-2].metrics, steps[-1].metrics
        keys = [k for k in b if isinstance(b.get(k), (int, float))
                and isinstance(a.get(k), (int, float))]
        out = []
        for h in range(1, horizon + 1):
            pred = {k: round(b[k] + (b[k] - a[k]) * h, 4) for k in keys}
            out.append({"index": len(steps) - 1 + h, "predicted": True, "metrics": pred})
        return out

    def view(self, horizon: int = 3) -> dict:
        return {"past": len(self.past()), "present": self.present(),
                "future": self.predicted_future(horizon)}
