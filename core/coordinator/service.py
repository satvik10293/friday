"""
core/coordinator/service.py — FRIDAY V3 (M17 revision)
The Cognitive System facade. It wires the whole society together over the M16 service
container: the Situation Report Bus, the Cognitive Brains (built via `build_brains`), the
Executive Brain, and the Cognitive Coordinator. One `cycle()` ticks every brain (each
publishes a Situation Report) and then coordinates them into Unified Situations published
to the Executive.

This is the single public seam other code uses; everything underneath communicates only
through services + the report bus. Side-effect-free to import.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from pathlib import Path
from typing import Optional

from core.brains import SituationReportBus, build_brains
from core.brains.executive.brain import ExecutiveBrain

from .config import CoordinatorConfig
from .coordinator import CognitiveCoordinator

log = logging.getLogger("friday.coordinator.service")

_MANIFEST_PATH = Path(__file__).resolve().parent / "architecture.json"


class CoordinatorService:
    name = "coordinator"

    def __init__(self, config: Optional[CoordinatorConfig] = None, *, container=None,
                 runtime=None, vision=None, audio=None, spatial=None, memory=None,
                 executive_planner=None, config_dict: Optional[dict] = None) -> None:
        self.config = config or CoordinatorConfig.from_dict(config_dict or {})
        if container is None:
            from core.services import build_default_container
            container = build_default_container(runtime=runtime, vision=vision, audio=audio,
                                                memory=memory, config=config_dict or {})
            if spatial is not None:
                container.register("spatial", spatial)
        self.container = container

        self.bus = SituationReportBus()
        self.executive = ExecutiveBrain(services=container, planner=executive_planner)
        _register(container, "executive_brain", self.executive)
        # build the brain society (registers memory_brain into the container)
        self.brains = build_brains(services=container, report_bus=self.bus,
                                   config=(config_dict or {}).get("brains", {}))
        self.coordinator = CognitiveCoordinator(self.config, services=container,
                                                report_bus=self.bus, executive=self.executive)
        _register(container, "coordinator", self)

        self._stop = threading.Event()
        self._worker: Optional[threading.Thread] = None
        self._interval = 1.0

    # ── one full society cycle ───────────────────────────────────────────────────
    def cycle(self) -> dict:
        """Tick every brain (each may publish a Situation Report), then coordinate them
        into Unified Situations for the Executive. Returns the cycle summary."""
        reported = 0
        for brain in self.brains.values():
            if brain.tick() is not None:
                reported += 1
        situations = self.coordinator.coordinate()
        return {"reports": reported, "situations": situations,
                "executive_focus": self.executive.working_memory.focus()}

    # ── direct report intake (push / tests) ──────────────────────────────────────
    def submit_report(self, report) -> None:
        self.bus.publish(report)

    def coordinate(self) -> list:
        return self.coordinator.coordinate()

    # ── queries ──────────────────────────────────────────────────────────────────
    def situation(self) -> dict:
        return {"current": self.coordinator.current(), "context": self.coordinator.context(),
                "executive": self.executive.status()}

    def context(self) -> dict:
        return self.coordinator.context()

    def reports(self, *, limit: int = 30) -> list:
        return self.bus.recent(limit)

    def brain(self, name: str):
        return self.brains.get(name)

    # ── autonomous loop (optional) ───────────────────────────────────────────────
    def start(self, *, interval: float = 1.0) -> "CoordinatorService":
        self._interval = max(0.1, interval)
        if self._worker is not None and self._worker.is_alive():
            return self
        self._stop.clear()
        self._worker = threading.Thread(target=self._loop, daemon=True, name="friday-coordinator")
        self._worker.start()
        return self

    def _loop(self) -> None:  # pragma: no cover - timing/thread loop
        while not self._stop.is_set():
            try:
                self.cycle()
            except Exception:  # noqa: BLE001
                log.debug("cognitive cycle failed", exc_info=True)
            time.sleep(self._interval)

    def stop(self) -> None:
        self._stop.set()
        if self._worker is not None:
            self._worker.join(timeout=2.0)

    def close(self) -> None:
        self.stop()

    # ── observability ────────────────────────────────────────────────────────────
    def dashboard(self) -> dict:
        return {"title": "Cognitive Coordinator", "milestone": "M17-rev",
                "coordinator": self.coordinator.metrics(),
                "executive": self.executive.metrics(),
                "brains": {n: b.metrics() for n, b in self.brains.items()},
                "report_bus": self.bus.stats()}

    def metrics(self) -> dict:
        return {"coordinator": self.coordinator.metrics(),
                "brains": {n: b.metrics() for n, b in self.brains.items()}}

    def health(self) -> dict:
        brain_health = {n: b.health() for n, b in self.brains.items()}
        degraded = [n for n, h in brain_health.items() if h.get("status") not in ("ok", "placeholder")]
        return {"status": "ok" if not degraded else "degraded",
                "coordinator": self.coordinator.health(),
                "executive": self.executive.health(), "brains": brain_health,
                "degraded": degraded}

    def manifest(self) -> dict:
        try:
            return json.loads(_MANIFEST_PATH.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def attach(self, runtime) -> None:
        try:
            runtime.register_health("coordinator", self.health)
        except Exception:  # noqa: BLE001
            log.debug("attach failed", exc_info=True)


def _register(container, name: str, obj) -> None:
    try:
        container.register(name, obj)
    except Exception:  # noqa: BLE001
        log.debug("register %s failed", name, exc_info=True)


_instance: Optional[CoordinatorService] = None
_lock = threading.Lock()


def get_coordinator_service(**kw) -> CoordinatorService:
    global _instance
    with _lock:
        if _instance is None:
            _instance = CoordinatorService(**kw)
    return _instance
