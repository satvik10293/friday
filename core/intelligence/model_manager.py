"""
core/intelligence/model_manager.py — FRIDAY 4.0 (M12)
Manages the lifecycle of loaded models: bootstrap the local team, load/unload
plugins on demand, account for memory, and restart unhealthy models. Composes the
loader, registry, and health monitor.
"""

from __future__ import annotations

import logging
from typing import Optional

from .base import Model, ModelStatus
from .health_monitor import HealthMonitor
from .model_loader import ModelLoader
from .registry import IntelligenceRegistry

log = logging.getLogger("friday.intelligence.model_manager")


class ModelManager:
    def __init__(self, registry: IntelligenceRegistry, *,
                 health: Optional[HealthMonitor] = None) -> None:
        self._registry = registry
        self._loader = ModelLoader(registry)
        self._health = health if health is not None else HealthMonitor()

    @property
    def registry(self) -> IntelligenceRegistry:
        return self._registry

    @property
    def health_monitor(self) -> HealthMonitor:
        return self._health

    def bootstrap(self, *, discover_optional: bool = True) -> list[str]:
        """Load the always-available team (and optional heavier models if present)."""
        loaded = self._loader.load_builtins()
        if discover_optional:
            loaded += self._loader.discover_optional()
        return loaded

    def load_plugin(self, model: Model) -> str:
        return self._loader.load_plugin(model)

    def unload(self, name: str) -> bool:
        return self._loader.unload(name)

    def loaded_models(self) -> list[Model]:
        return [m for m in self._registry.all()
                if m.info.status == ModelStatus.LOADED.value]

    def memory_usage_mb(self) -> float:
        return round(sum(m.info.ram_mb for m in self.loaded_models()), 2)

    def restart(self, name: str) -> bool:
        """Unload + reload a model in place (used when health declares it unhealthy)."""
        model = self._registry.get(name)
        if model is None:
            return False
        try:
            model.unload()
            model.load()
            model.info.health = "ok"
            model.info.status = ModelStatus.LOADED.value
            self._health.reset(name)
            log.info("restarted model %s", name)
            return True
        except Exception as e:  # noqa: BLE001
            model.info.health = "failed"
            log.warning("restart of %s failed: %s", name, e)
            return False

    def restart_unhealthy(self) -> list[str]:
        """Restart every model the health monitor flagged unhealthy (Part 12)."""
        restarted = []
        for name in self._health.unhealthy_models():
            if self.restart(name):
                restarted.append(name)
        return restarted

    def status(self) -> dict:
        return {"loaded": [m.info.name for m in self.loaded_models()],
                "total_registered": len(self._registry.all()),
                "memory_mb": self.memory_usage_mb(),
                "unhealthy": self._health.unhealthy_models()}
