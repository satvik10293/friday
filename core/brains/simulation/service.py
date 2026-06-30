"""
core/brains/simulation/service.py — FRIDAY V3 (M19)
SimulationService — the public face of the Simulation Brain (satisfies
`core.services.interfaces.SimulationServiceProtocol`). It owns the `SimulationBrain`, is
constructed via dependency injection (a ServiceContainer or individual subsystems), and
registers itself into the container as the `simulation` service so the Executive Brain can
request a simulation before deciding. Advisory only — it never executes actions.
Side-effect-free to import.
"""

from __future__ import annotations

import json
import logging
import threading
from pathlib import Path
from typing import Optional

from ..base import SituationReportBus
from .config import SimulationConfig
from .simulation import SimulationBrain

log = logging.getLogger("friday.brains.simulation.service")

_MANIFEST_PATH = Path(__file__).resolve().parent / "architecture.json"


class SimulationService:
    name = "simulation"

    def __init__(self, config: Optional[SimulationConfig] = None, *, container=None,
                 runtime=None, memory_brain=None, learning=None, report_bus=None,
                 config_dict: Optional[dict] = None, brain: Optional[SimulationBrain] = None) -> None:
        self.config = config or SimulationConfig.from_dict(config_dict or {})
        if container is None:
            from core.services import build_default_container
            container = build_default_container(runtime=runtime, learning=None,
                                                config=config_dict or {})
            if memory_brain is not None:
                container.register("memory_brain", memory_brain)
            if learning is not None:
                container.register("learning", learning)
        self.container = container
        self.bus = report_bus or SituationReportBus()
        self.brain = brain or SimulationBrain(services=container, config=self.config.to_dict(),
                                              report_bus=self.bus, sim_config=self.config)
        try:
            container.register("simulation", self)
        except Exception:  # noqa: BLE001
            log.debug("could not register simulation service", exc_info=True)

    # ── SimulationServiceProtocol ────────────────────────────────────────────────
    def simulate(self, action: str, *, context: Optional[dict] = None,
                 options: Optional[list] = None) -> dict:
        return self.brain.simulate(action, context=context, options=options)

    def forecast(self, action: str, *, context: Optional[dict] = None) -> dict:
        return self.brain.forecast(action, context=context)

    def record_outcome(self, simulation_id: str, actual: dict) -> dict:
        return self.brain.record_outcome(simulation_id, actual)

    # ── observability ────────────────────────────────────────────────────────────
    def dashboard(self) -> dict:
        return {"title": "Simulation Brain", "milestone": "M19",
                "metrics": self.brain.metrics(), "recent": self.brain.history.recent(10)}

    def metrics(self) -> dict:
        return self.brain.metrics()

    def health(self) -> dict:
        return self.brain.health()

    def manifest(self) -> dict:
        try:
            return json.loads(_MANIFEST_PATH.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def attach(self, runtime) -> None:
        try:
            runtime.register_health("simulation", self.health)
        except Exception:  # noqa: BLE001
            log.debug("attach failed", exc_info=True)


def attach_to_container(container, *, config: Optional[SimulationConfig] = None,
                        config_dict: Optional[dict] = None,
                        report_bus: Optional[SituationReportBus] = None) -> SimulationService:
    """Build a SimulationService over an existing ServiceContainer and register it."""
    return SimulationService(config or SimulationConfig.from_dict(config_dict or {}),
                             container=container, report_bus=report_bus)


_instance: Optional[SimulationService] = None
_lock = threading.Lock()


def get_simulation_service(**kw) -> SimulationService:
    global _instance
    with _lock:
        if _instance is None:
            _instance = SimulationService(**kw)
    return _instance
