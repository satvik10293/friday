"""
core/intelligence/optimizer.py — FRIDAY 4.0 (M12)
The optimizer (Parts 15 & 17). Continuously looks for bottlenecks and proposes
improvements — memory, CPU/GPU, context size, scheduling, caching, model loading.
It may auto-tune its OWN intelligence-internal resources (cache size, unloading idle
models); anything that would touch production is returned as a **recommendation
requiring approval** — FRIDAY never modifies production automatically.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Recommendation:
    area: str                  # memory|cpu|context|scheduling|caching|model_loading|architecture
    message: str
    severity: str = "info"     # info|warn|critical
    requires_approval: bool = True
    auto_applicable: bool = False

    def to_dict(self) -> dict:
        return dict(self.__dict__)


class Optimizer:
    def __init__(self, *, cache=None, model_manager=None, health=None,
                 retrieval_metrics=None) -> None:
        self._cache = cache
        self._models = model_manager
        self._health = health
        self._metrics = retrieval_metrics

    # ── analysis ────────────────────────────────────────────────────────────────
    def analyze(self) -> list[Recommendation]:
        recs: list[Recommendation] = []

        if self._cache is not None:
            stats = self._cache.stats()
            if stats["hit_rate"] < 0.2 and stats["misses"] > 50:
                recs.append(Recommendation("caching",
                    "low cache hit rate — increase cache key reuse or capacity", "warn",
                    requires_approval=False, auto_applicable=True))
            if stats["size"] >= stats["capacity"]:
                recs.append(Recommendation("caching",
                    "cache full — consider raising capacity", "info",
                    requires_approval=False, auto_applicable=True))

        if self._models is not None:
            status = self._models.status()
            if status.get("unhealthy"):
                recs.append(Recommendation("model_loading",
                    f"unhealthy models: {status['unhealthy']} — restart recommended",
                    "critical", requires_approval=False, auto_applicable=True))
            if status.get("memory_mb", 0) > 4000:
                recs.append(Recommendation("memory",
                    "loaded model memory high — unload idle models", "warn"))

        if self._health is not None:
            sysinfo = self._health.system()
            if sysinfo.get("available") and sysinfo.get("ram_percent", 0) > 90:
                recs.append(Recommendation("memory",
                    "system RAM pressure — reduce context budget / unload models", "critical"))
            if sysinfo.get("available") and sysinfo.get("cpu_percent", 0) > 90:
                recs.append(Recommendation("cpu",
                    "CPU saturated — lower reasoning parallelism", "warn"))

        if not recs:
            recs.append(Recommendation("architecture", "no bottlenecks detected", "info",
                                       requires_approval=False))
        return recs

    # ── safe auto-tuning (intelligence-internal only) ───────────────────────────
    def apply_safe(self) -> list[str]:
        """Apply only the recommendations that touch intelligence-internal resources
        (cache, model restarts) — never production data."""
        applied = []
        if self._cache is not None:
            stats = self._cache.stats()
            if stats["size"] >= stats["capacity"]:
                self._cache.resize(stats["capacity"] * 2)
                applied.append(f"cache capacity → {self._cache.capacity}")
        if self._models is not None and self._models.status().get("unhealthy"):
            restarted = self._models.restart_unhealthy()
            if restarted:
                applied.append(f"restarted unhealthy models: {restarted}")
        return applied

    # ── self-improvement (Part 17) — recommend, never auto-modify production ─────
    def self_improvement(self) -> dict:
        recs = self.analyze()
        production_changes = [r.to_dict() for r in recs if r.requires_approval]
        auto = self.apply_safe()
        return {
            "bottlenecks": [r.to_dict() for r in recs if r.severity in ("warn", "critical")],
            "auto_applied": auto,
            "pending_approval": production_changes,
            "note": "production changes require explicit approval",
        }
