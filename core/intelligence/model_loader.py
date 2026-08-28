"""
core/intelligence/model_loader.py — FRIDAY 4.0 (M12)
Hot model loading (Parts 2 & 3). Discovers available model plugins and registers
them into the IntelligenceRegistry without a restart. The built-in local team is
always available; optional heavier/cloud plugins load only if their dependencies
exist (local-first: nothing external is required, and cloud plugins are opt-in).
"""

from __future__ import annotations

import importlib.util
import logging

from .base import Model
from .builtin_models import builtin_models
from .registry import IntelligenceRegistry

log = logging.getLogger("friday.intelligence.loader")


class ModelLoader:
    def __init__(self, registry: IntelligenceRegistry) -> None:
        self._registry = registry

    def load_builtins(self) -> list[str]:
        """Register the always-available local team. Idempotent."""
        loaded = []
        for model in builtin_models():
            model.load()
            self._registry.register(model)
            loaded.append(model.info.name)
        return loaded

    def load_plugin(self, model: Model) -> str:
        """Hot-register a user/3rd-party model plugin."""
        model.load()
        self._registry.register(model)
        return model.info.name

    def discover_optional(self) -> list[str]:
        """Load optional heavier local models when their deps are present (never
        required). Cloud plugins are NOT auto-loaded — they are opt-in (local-first)."""
        loaded = []
        if importlib.util.find_spec("transformers") is not None:
            try:
                from .plugins.flan_t5 import FlanT5Model
                self.load_plugin(FlanT5Model())
                loaded.append("flan-t5")
            except Exception as e:  # noqa: BLE001
                log.debug("flan-t5 plugin unavailable: %s", e)
        return loaded

    def unload(self, name: str) -> bool:
        return self._registry.unregister(name)
