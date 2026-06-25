"""
core/mission_control/service.py — FRIDAY 4.0 (M10)
The Mission Control facade. Wires the aggregator, resource monitor, event stream,
authenticator, and server into one cockpit object, and exposes the cockpit state /
panels / health. Built so the whole thing keeps operating even when subsystems are
missing or failing (Part 7).
"""

from __future__ import annotations

import logging
from typing import Optional

from .aggregator import MissionControlAggregator
from .events import EventStream
from .resilience import safe_call
from .resources import ResourceMonitor

log = logging.getLogger("friday.mission_control.service")


class MissionControl:
    def __init__(self, *, executive=None, goal_service=None, knowledge_service=None,
                 user_model=None, agent_runtime=None, authenticator=None,
                 model_registry=None, runtime=None) -> None:
        self.events = EventStream()
        self.resources = ResourceMonitor(model_registry=model_registry)
        if authenticator is None:
            from core.security.auth import Authenticator
            authenticator = Authenticator()
        self.authenticator = authenticator
        self._agg = MissionControlAggregator(
            executive=executive, goal_service=goal_service,
            knowledge_service=knowledge_service, user_model=user_model,
            agent_runtime=agent_runtime, authenticator=authenticator,
            resources=self.resources, events=self.events)
        self._runtime = runtime

    # ── cockpit data ────────────────────────────────────────────────────────────
    def state(self) -> dict:
        return safe_call("state", self._agg.state,
                         default={"ok": True, "operational": True, "panels": {},
                                  "degraded": ["all"]})

    def panel(self, name: str) -> dict:
        fn = getattr(self._agg, name, None)
        if fn is None:
            return {"error": "unknown_panel", "panel": name}
        return safe_call(name, fn, default={"status": "degraded", "panel": name})

    def health(self) -> dict:
        return {"status": "ok", "operational": True,
                "aggregator": safe_call("agg_health", self._agg.health,
                                        default={"status": "degraded"}),
                "resources": self.resources.health(),
                "auth": self.authenticator.health(),
                "events": len(self.events)}

    # ── runtime wiring ──────────────────────────────────────────────────────────
    def attach(self, runtime, event_keys=None) -> None:
        """Register health + stream runtime events into the cockpit timeline."""
        self._runtime = runtime
        try:
            runtime.register_health("mission_control", self.health)
        except Exception:
            log.debug("attach: health registration failed", exc_info=True)
        if event_keys:
            self.events.attach_runtime(runtime, event_keys)

    def server(self, **kw):
        from .server import MissionControlServer
        return MissionControlServer(self, **kw)


_mc: Optional[MissionControl] = None


def get_mission_control(**kw) -> MissionControl:
    global _mc
    if _mc is None:
        _mc = MissionControl(**kw)
    return _mc
