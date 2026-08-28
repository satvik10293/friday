"""
core/intelligence/registry.py — FRIDAY 4.0 (M12)
The runtime model registry (Part 2). Every model that loads registers here with its
full metadata; the router queries it to pick models by capability. Supports hot
registration/unregistration (Part 2 "hot loading") and persists a snapshot so the
roster survives restarts. Distinct from the M10 `core.infra.model_registry`, which
catalogues the on-disk model *configs*; this one tracks *live* inference models.
"""

from __future__ import annotations

import logging
import threading
from typing import Optional

from .base import Model, ModelStatus
from .store import IntelligenceStore

log = logging.getLogger("friday.intelligence.registry")


class IntelligenceRegistry:
    def __init__(self, store: Optional[IntelligenceStore] = None) -> None:
        self._store = store
        self._models: dict[str, Model] = {}
        self._lock = threading.RLock()

    # ── registration (hot) ──────────────────────────────────────────────────────
    def register(self, model: Model) -> None:
        with self._lock:
            self._models[model.info.name] = model
            model.info.status = model.info.status or ModelStatus.REGISTERED.value
            if self._store is not None:
                self._store.save_model(model.info.name, model.info.to_dict())
        log.info("registered model %s (caps=%s)", model.info.name, sorted(model.info.capabilities))

    def unregister(self, name: str) -> bool:
        with self._lock:
            model = self._models.pop(name, None)
            if model is not None:
                try:
                    model.unload()
                except Exception:  # noqa: BLE001
                    pass
                return True
            return False

    # ── lookup ──────────────────────────────────────────────────────────────────
    def get(self, name: str) -> Optional[Model]:
        return self._models.get(name)

    def all(self) -> list[Model]:
        return list(self._models.values())

    def names(self) -> list[str]:
        return list(self._models.keys())

    def by_capability(self, task: str) -> list[Model]:
        """Healthy models that support `task`, best first (accuracy·reliability)."""
        out = [m for m in self._models.values()
               if m.info.supports(task) and m.info.health != "failed"]
        out.sort(key=lambda m: (m.info.avg_accuracy * m.info.reliability), reverse=True)
        return out

    def best_for(self, task: str) -> Optional[Model]:
        cands = self.by_capability(task)
        return cands[0] if cands else None

    def infos(self) -> list[dict]:
        return [m.info.to_dict() for m in self._models.values()]

    def update_stats(self, name: str, *, latency_ms: Optional[float] = None,
                     success: Optional[bool] = None, accuracy: Optional[float] = None) -> None:
        """Fold an execution outcome into a model's live stats (EWMA)."""
        m = self._models.get(name)
        if m is None:
            return
        info = m.info
        if latency_ms is not None:
            info.avg_speed_ms = (0.7 * info.avg_speed_ms + 0.3 * latency_ms
                                 if info.avg_speed_ms else latency_ms)
        if success is not None:
            info.reliability = 0.9 * info.reliability + 0.1 * (1.0 if success else 0.0)
        if accuracy is not None:
            info.avg_accuracy = (0.8 * info.avg_accuracy + 0.2 * accuracy
                                 if info.avg_accuracy else accuracy)
        if self._store is not None:
            self._store.save_model(name, info.to_dict())

    def health(self) -> dict:
        return {"status": "ok", "models": len(self._models),
                "by_capability": {t: len(self.by_capability(t))
                                  for t in {c for m in self._models.values()
                                            for c in m.info.capabilities}}}
