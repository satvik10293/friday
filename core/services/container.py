"""
core/services/container.py — FRIDAY V3 (M16)
The dependency-injection container. Services are registered by name and resolved on
demand; nothing reaches across subsystems except through a service obtained here. This
is the seam that makes the system mockable (inject fakes), testable (no global state),
and future-proof (swap a local wrapper for a remote proxy without touching callers).

There is NO module-level singleton: a `ServiceContainer` is constructed and passed in
(dependency injection). `build_default_container()` is an optional convenience that wires
the concrete wrappers over whatever subsystems you hand it — each one is optional and
degrades gracefully, so spatial cognition runs with a fully mocked container in tests.
"""

from __future__ import annotations

import logging
import threading
from typing import Any, Callable, Optional

from .interfaces import ServiceName

log = logging.getLogger("friday.services")


class ServiceContainer:
    """A small, thread-safe service registry supporting eager instances and lazy
    factories. Resolution order: cached instance → factory (memoized) → KeyError."""

    def __init__(self) -> None:
        self._instances: dict[str, Any] = {}
        self._factories: dict[str, Callable[["ServiceContainer"], Any]] = {}
        self._lock = threading.RLock()

    # ── registration ─────────────────────────────────────────────────────────────
    def register(self, name: str, service: Any) -> Any:
        """Register a concrete service instance under `name`."""
        with self._lock:
            self._instances[name] = service
        return service

    def register_factory(self, name: str, factory: Callable[["ServiceContainer"], Any]) -> None:
        """Register a lazy factory; built (once) on first `get`."""
        with self._lock:
            self._factories[name] = factory

    # ── resolution ───────────────────────────────────────────────────────────────
    def get(self, name: str) -> Any:
        with self._lock:
            if name in self._instances:
                return self._instances[name]
            factory = self._factories.get(name)
            if factory is None:
                raise KeyError(f"service not registered: {name!r}")
            instance = factory(self)
            self._instances[name] = instance
            return instance

    def try_get(self, name: str) -> Optional[Any]:
        """Resolve a service or return None if unregistered/unavailable (graceful)."""
        try:
            return self.get(name)
        except Exception:  # noqa: BLE001
            return None

    def has(self, name: str) -> bool:
        with self._lock:
            return name in self._instances or name in self._factories

    def replace(self, name: str, instance: Any) -> bool:
        """Swap a LIVE service instance (M59 self-heal reload): after a failed
        module is safely rebuilt, consumers that resolve through the container
        get the fresh instance — no app restart. Only replaces a name the
        container already knows; a reload must never *introduce* services."""
        with self._lock:
            if name not in self._instances and name not in self._factories:
                return False
            self._instances[name] = instance
        return True

    def names(self) -> list[str]:
        with self._lock:
            return sorted(set(self._instances) | set(self._factories))

    # ── observability ────────────────────────────────────────────────────────────
    def health(self) -> dict:
        out: dict[str, Any] = {}
        for name in self.names():
            svc = self.try_get(name)
            if svc is None:
                out[name] = {"status": "absent"}
                continue
            try:
                out[name] = svc.health() if hasattr(svc, "health") else {"status": "ok"}
            except Exception as e:  # noqa: BLE001
                out[name] = {"status": "error", "error": str(e)}
        ok = all(v.get("status") in ("ok", "absent", "placeholder") for v in out.values())
        return {"status": "ok" if ok else "degraded", "services": out}

    def close(self) -> None:
        with self._lock:
            services = list(self._instances.values())
            self._instances.clear()
        for svc in services:
            close = getattr(svc, "close", None)
            if callable(close):
                try:
                    close()
                except Exception:  # noqa: BLE001
                    log.debug("service close failed", exc_info=True)


def build_default_container(*, runtime=None, world_model=None, memory=None,
                            attention=None, vision=None, audio=None, executive=None,
                            config: Optional[dict] = None, emotion=None) -> ServiceContainer:
    """Wire the concrete service wrappers over the supplied subsystems. Every argument
    is optional; a missing subsystem yields a graceful, absent-degrading wrapper. The
    spatial service is registered lazily (built from the rest) by the caller, or via
    `core.spatial.attach_to_container`."""
    from .runtime_service import RuntimeService
    from .world_model_service import WorldModelService
    from .memory_service import MemoryService
    from .attention_service import AttentionService
    from .vision_service import VisionService
    from .audio_service import AudioService
    from .executive_service import ExecutiveService
    from .configuration_service import ConfigurationService
    from .plugin_service import PluginService
    from .learning_service import LearningService
    from .emotion_service import EmotionService

    c = ServiceContainer()
    c.register(ServiceName.RUNTIME, RuntimeService(runtime))
    c.register(ServiceName.WORLD_MODEL, WorldModelService(world_model))
    c.register(ServiceName.MEMORY, MemoryService(memory))
    c.register(ServiceName.ATTENTION, AttentionService(attention))
    c.register(ServiceName.VISION, VisionService(vision))
    c.register(ServiceName.AUDIO, AudioService(audio))
    c.register(ServiceName.EXECUTIVE, ExecutiveService(executive))
    c.register(ServiceName.CONFIGURATION, ConfigurationService(config or {}))
    c.register(ServiceName.PLUGIN, PluginService())
    c.register(ServiceName.LEARNING, LearningService())
    c.register(ServiceName.EMOTION, EmotionService(emotion))
    return c
