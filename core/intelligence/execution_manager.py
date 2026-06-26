"""
core/intelligence/execution_manager.py — FRIDAY 4.0 (M12)
Runs a single model inference with production guarantees: result caching (Part 14),
health recording (Part 12), live stat updates, and automatic retry on a backup
model (Part 3). It is the uniform executor the reasoning engine calls for every
model, so retry/health/cache apply everywhere.
"""

from __future__ import annotations

import logging
from typing import Optional

from .base import InferenceRequest, InferenceResult, Model
from .cache import IntelligenceCache, cache_key
from .health_monitor import HealthMonitor
from .registry import IntelligenceRegistry

log = logging.getLogger("friday.intelligence.execution")


class ExecutionManager:
    def __init__(self, registry: IntelligenceRegistry, *,
                 health: Optional[HealthMonitor] = None,
                 cache: Optional[IntelligenceCache] = None,
                 retries: int = 1) -> None:
        self._registry = registry
        self._health = health if health is not None else HealthMonitor()
        self._cache = cache if cache is not None else IntelligenceCache()
        self._retries = retries

    @property
    def cache(self) -> IntelligenceCache:
        return self._cache

    @property
    def health(self) -> HealthMonitor:
        return self._health

    # ── single model (the reasoning engine's executor) ──────────────────────────
    def run(self, model: Model, request: InferenceRequest) -> InferenceResult:
        key = cache_key("infer", model.info.name, request.task, request.prompt,
                        sorted(request.context.keys()))
        cached = self._cache.get(key)
        if cached is not None:
            return cached
        result = model.infer(request)
        self._health.record(model.info.name, success=result.ok, latency_ms=result.latency_ms)
        self._registry.update_stats(model.info.name, latency_ms=result.latency_ms,
                                    success=result.ok,
                                    accuracy=result.confidence if result.ok else 0.0)
        if result.ok:
            self._cache.put(key, result)
        return result

    # ── task-level with backup fallback (Part 3) ────────────────────────────────
    def execute(self, request: InferenceRequest) -> InferenceResult:
        """Pick the best healthy model for the task and run it; on failure, retry on
        the next-best (backup) model automatically."""
        candidates = [m for m in self._registry.by_capability(request.task)
                      if self._health.is_healthy(m.info.name)]
        if not candidates:
            candidates = self._registry.by_capability(request.task)
        if not candidates:
            return InferenceResult(model="<none>", ok=False,
                                   error=f"no model for task {request.task}")
        attempts = candidates[: self._retries + 1]
        last: Optional[InferenceResult] = None
        for model in attempts:
            last = self.run(model, request)
            if last.ok:
                return last
            log.debug("model %s failed; trying backup", model.info.name)
        return last or InferenceResult(model="<none>", ok=False, error="all attempts failed")
