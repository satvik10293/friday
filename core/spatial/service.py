"""
core/spatial/service.py — FRIDAY V3 (M16)
SpatialService — the public face of Spatial Cognition and the only way other subsystems
reach it (it satisfies `core.services.interfaces.SpatialServiceProtocol`). It owns the
`SpatialEngine`, is constructed via dependency injection (a `ServiceContainer` or
individual subsystems), registers itself into the container as the `spatial` service, and
optionally runs an autonomous poll loop that pulls observations from the VisionService.

All cross-subsystem communication is mediated by services; nothing here imports another
subsystem's internals. Side-effect-free to import; no DB opens, no threads start, until
constructed/started.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from pathlib import Path
from typing import Optional

from .config import SpatialConfig
from .engine import SpatialEngine

log = logging.getLogger("friday.spatial.service")

_MANIFEST_PATH = Path(__file__).resolve().parent / "architecture.json"


class SpatialService:
    name = "spatial"

    def __init__(self, config: Optional[SpatialConfig] = None, *, container=None,
                 runtime=None, world_model=None, memory=None, attention=None, vision=None,
                 audio=None, executive=None, emotion=None, config_dict: Optional[dict] = None,
                 engine: Optional[SpatialEngine] = None) -> None:
        self.config = config or SpatialConfig.from_dict(config_dict or {})
        # obtain or build a service container (dependency injection) -----------------
        if container is None:
            from core.services import build_default_container
            container = build_default_container(
                runtime=runtime, world_model=world_model, memory=memory, attention=attention,
                vision=vision, audio=audio, executive=executive, emotion=emotion,
                config=config_dict or {})
        self.container = container
        self.engine = engine or SpatialEngine(self.config, services=container)
        # register self into the container so others resolve us as the "spatial" service
        try:
            container.register("spatial", self)
        except Exception:  # noqa: BLE001
            log.debug("could not register spatial service", exc_info=True)

        self._stop = threading.Event()
        self._worker: Optional[threading.Thread] = None
        self._poll_interval = max(0.1, 1.0 / max(0.1, self.config.camera_timeout))

    # ── SpatialServiceProtocol ───────────────────────────────────────────────────
    def update_scene(self, observations: list, *, camera_id: str = "",
                     room: Optional[str] = None) -> dict:
        return self.engine.update_scene(observations, camera_id=camera_id, room=room)

    def query(self, intent: str, **params) -> dict:
        return self.engine.queries.query(intent, **params)

    def snapshot(self) -> dict:
        return {"session": self.engine.session, "scene": self.engine.scene.snapshot(),
                "tracks": self.engine.tracker.tracks(),
                "rooms": self.engine.rooms.known_rooms(),
                "user": self.engine.localizer.health()}

    # ── convenience ──────────────────────────────────────────────────────────────
    def poll(self, *, camera_id: str = "") -> dict:
        return self.engine.poll(camera_id=camera_id)

    def save(self) -> int:
        return self.engine.save()

    def load(self) -> int:
        return self.engine.load()

    def set_camera_room(self, camera_id: str, room: str) -> None:
        self.engine.rooms.set_camera_room(camera_id, room)

    # ── autonomous poll loop (optional) ──────────────────────────────────────────
    def start(self) -> "SpatialService":
        if self._worker is not None and self._worker.is_alive():
            return self
        self._stop.clear()
        self._worker = threading.Thread(target=self._loop, daemon=True, name="friday-spatial")
        self._worker.start()
        return self

    def _loop(self) -> None:  # pragma: no cover - timing/thread loop
        while not self._stop.is_set():
            try:
                self.engine.poll()
            except Exception:  # noqa: BLE001
                log.debug("spatial poll failed", exc_info=True)
            time.sleep(self._poll_interval)

    def stop(self) -> None:
        self._stop.set()
        if self._worker is not None:
            self._worker.join(timeout=2.0)

    def close(self) -> None:
        self.stop()
        self.engine.close()

    # ── observability ────────────────────────────────────────────────────────────
    def dashboard(self) -> dict:
        return {"title": "Spatial Cognition", "milestone": "M16",
                "metrics": self.engine.metrics(), "snapshot": self.snapshot(),
                "services": self.container.health() if self.container else {}}

    def metrics(self) -> dict:
        return self.engine.metrics()

    def health(self) -> dict:
        return self.engine.health()

    def manifest(self) -> dict:
        try:
            return json.loads(_MANIFEST_PATH.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def attach(self, runtime) -> None:
        try:
            runtime.register_health("spatial", self.health)
        except Exception:  # noqa: BLE001
            log.debug("attach failed", exc_info=True)


def attach_to_container(container, *, config: Optional[SpatialConfig] = None,
                        config_dict: Optional[dict] = None) -> SpatialService:
    """Build a SpatialService over an existing ServiceContainer and register it. The
    sanctioned way to add spatial cognition to a running system."""
    return SpatialService(config or SpatialConfig.from_dict(config_dict or {}),
                          container=container)


_instance: Optional[SpatialService] = None
_lock = threading.Lock()


def get_spatial_service(**kw) -> SpatialService:
    global _instance
    with _lock:
        if _instance is None:
            _instance = SpatialService(**kw)
    return _instance
