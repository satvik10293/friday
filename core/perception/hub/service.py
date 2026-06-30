"""
core/perception/hub/service.py — FRIDAY V3 (M17)
PerceptionService — the public face of the Perception Hub and the only way other
subsystems reach it (it satisfies `core.services.interfaces.PerceptionServiceProtocol`).
It owns the `PerceptionHub`, is constructed via dependency injection (a `ServiceContainer`
or individual subsystems), registers itself into the container as the `perception`
service, and optionally runs an autonomous perceive loop.

All cross-subsystem communication is mediated by services; nothing here imports another
subsystem's internals. Side-effect-free to import.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from pathlib import Path
from typing import Optional

from .config import PerceptionHubConfig
from .hub import PerceptionHub

log = logging.getLogger("friday.perception.service")

_MANIFEST_PATH = Path(__file__).resolve().parent / "architecture.json"


class PerceptionService:
    name = "perception"

    def __init__(self, config: Optional[PerceptionHubConfig] = None, *, container=None,
                 runtime=None, world_model=None, memory=None, vision=None, audio=None,
                 spatial=None, executive=None, attention=None, config_dict: Optional[dict] = None,
                 hub: Optional[PerceptionHub] = None) -> None:
        self.config = config or PerceptionHubConfig.from_dict(config_dict or {})
        if container is None:
            from core.services import build_default_container
            container = build_default_container(
                runtime=runtime, world_model=world_model, memory=memory, vision=vision,
                audio=audio, executive=executive, attention=attention, config=config_dict or {})
            if spatial is not None:
                container.register("spatial", spatial)
        self.container = container
        self.hub = hub or PerceptionHub(self.config, services=container)
        try:
            container.register("perception", self)
        except Exception:  # noqa: BLE001
            log.debug("could not register perception service", exc_info=True)

        self._stop = threading.Event()
        self._worker: Optional[threading.Thread] = None
        self._interval = 1.0

    # ── PerceptionServiceProtocol ────────────────────────────────────────────────
    def ingest(self, observations: list, *, session_id: str = "") -> dict:
        return self.hub.ingest(observations, session_id=session_id)

    def perceive(self) -> dict:
        return self.hub.perceive()

    def situation(self) -> dict:
        return self.hub.situation()

    def context(self) -> dict:
        return self.hub.context.snapshot()

    def timeline(self, *, scope: str = "recent", **params) -> list:
        tl = self.hub.timeline
        dispatch = {
            "recent": lambda: tl.recently(seconds=params.get("seconds"),
                                          limit=params.get("limit", 20)),
            "current": lambda: [tl.current()] if tl.current() is not None else [],
            "before": lambda: tl.before(params.get("ts", time.time()), limit=params.get("limit", 50)),
            "after": lambda: tl.after(params.get("ts", 0.0), limit=params.get("limit", 50)),
            "during": lambda: tl.during(params.get("start", 0.0), params.get("end", time.time()),
                                        limit=params.get("limit", 200)),
            "historical": lambda: tl.historical(limit=params.get("limit", 100)),
        }
        fn = dispatch.get(scope, dispatch["recent"])
        return [u.to_dict() for u in fn()]

    # ── autonomous perceive loop (optional) ──────────────────────────────────────
    def start(self, *, interval: float = 1.0) -> "PerceptionService":
        self._interval = max(0.1, interval)
        if self._worker is not None and self._worker.is_alive():
            return self
        self._stop.clear()
        self._worker = threading.Thread(target=self._loop, daemon=True, name="friday-perception")
        self._worker.start()
        return self

    def _loop(self) -> None:  # pragma: no cover - timing/thread loop
        while not self._stop.is_set():
            try:
                self.hub.perceive()
            except Exception:  # noqa: BLE001
                log.debug("perceive loop failed", exc_info=True)
            time.sleep(self._interval)

    def stop(self) -> None:
        self._stop.set()
        if self._worker is not None:
            self._worker.join(timeout=2.0)

    def close(self) -> None:
        self.stop()

    # ── observability ────────────────────────────────────────────────────────────
    def dashboard(self) -> dict:
        return {"title": "Perception Hub", "milestone": "M17",
                "situation": self.situation(), "context": self.context(),
                "metrics": self.hub.metrics()}

    def metrics(self) -> dict:
        return self.hub.metrics()

    def health(self) -> dict:
        return self.hub.health()

    def manifest(self) -> dict:
        try:
            return json.loads(_MANIFEST_PATH.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def attach(self, runtime) -> None:
        try:
            runtime.register_health("perception", self.health)
        except Exception:  # noqa: BLE001
            log.debug("attach failed", exc_info=True)


def attach_to_container(container, *, config: Optional[PerceptionHubConfig] = None,
                        config_dict: Optional[dict] = None) -> PerceptionService:
    """Build a PerceptionService over an existing ServiceContainer and register it."""
    return PerceptionService(config or PerceptionHubConfig.from_dict(config_dict or {}),
                             container=container)


_instance: Optional[PerceptionService] = None
_lock = threading.Lock()


def get_perception_service(**kw) -> PerceptionService:
    global _instance
    with _lock:
        if _instance is None:
            _instance = PerceptionService(**kw)
    return _instance
