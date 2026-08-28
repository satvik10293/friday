"""
core/cognition_core/self_model.py — FRIDAY 6.0 (M13)
The Self Model: FRIDAY's live model of herself, aggregated additively from existing
subsystems (goals, executive state, sensors, agent society, compute/resources,
intelligence health). It reads through injected providers and degrades gracefully —
a missing or failing provider yields an empty field, never an error.
"""

from __future__ import annotations

import logging

from .models import SelfModelSnapshot

log = logging.getLogger("friday.cognition.self_model")

# Static, honest limitations of the current build (extended dynamically below).
_BASE_LIMITATIONS = ["cpu-only", "local-first models", "single-process runtime"]


def _safe(fn, default):
    try:
        return fn()
    except Exception:  # noqa: BLE001 — a provider failure must not break the self model
        return default


class SelfModel:
    def __init__(self, *, goal_service=None, sensor_registry=None, society=None,
                 resource_monitor=None, cognitive_state=None, intelligence=None) -> None:
        self._goals = goal_service
        self._sensors = sensor_registry
        self._society = society
        self._resources = resource_monitor
        self._cognitive_state = cognitive_state
        self._intelligence = intelligence

    def snapshot(self) -> SelfModelSnapshot:
        snap = SelfModelSnapshot()
        snap.active_goals = self._active_goals()
        snap.current_task, snap.current_plan = self._current_work()
        snap.sensors = self._active_sensors()
        snap.active_agents = self._active_agents()
        snap.compute = self._compute()
        snap.workload = {"active_goals": len(snap.active_goals),
                         "active_agents": snap.active_agents}
        snap.limitations = self._limitations(snap.compute)
        snap.confidence = self._confidence(snap.compute)
        return snap

    # ── providers (each guarded) ────────────────────────────────────────────────
    def _active_goals(self) -> list:
        if self._goals is None:
            return []
        def go():
            from core.goals import GoalStatus
            return [g.title for g in self._goals.list_goals(status=GoalStatus.ACTIVE)]
        return _safe(go, [])

    def _current_work(self) -> tuple:
        if self._cognitive_state is None:
            return "", None
        def go():
            st = self._cognitive_state() if callable(self._cognitive_state) else self._cognitive_state
            d = st.to_dict() if hasattr(st, "to_dict") else dict(st or {})
            return d.get("current_task", ""), d.get("active_plan")
        return _safe(go, ("", None))

    def _active_sensors(self) -> list:
        if self._sensors is None:
            return []
        return _safe(lambda: [s for s in self._sensors.list()], [])

    def _active_agents(self) -> int:
        if self._society is None:
            return 0
        return _safe(lambda: len(self._society.coordinator.active_workers()), 0)

    def _compute(self) -> dict:
        if self._resources is None:
            return {"available": False}
        return _safe(lambda: self._resources.system(), {"available": False})

    def _confidence(self, compute: dict) -> float:
        if compute.get("available") and compute.get("ram_percent", 0) > 92:
            return 0.6
        return 0.9

    def _limitations(self, compute: dict) -> list:
        lims = list(_BASE_LIMITATIONS)
        gpu = compute.get("gpu") if isinstance(compute, dict) else None
        if isinstance(gpu, dict) and not gpu.get("present"):
            lims.append("no-gpu")
        return lims
