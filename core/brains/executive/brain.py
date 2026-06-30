"""
core/brains/executive/brain.py — FRIDAY V3 (M18 foundation)
The Executive Brain — the CEO of FRIDAY. It receives ONLY Unified Situation Reports from
the Cognitive Coordinator and makes decisions: prioritization, focus, delegation, and
(via the M5 executive service) planning. It NEVER processes raw data — camera frames,
audio samples, object detections, database queries, or scene graphs are refused. It owns
only Working Memory; every other memory request goes through the Memory Brain.

This is the M18 foundation: the consumption surface + working memory + decision/focus +
delegation hooks are in place; richer planning/scheduling builds on top.
"""

from __future__ import annotations

import logging
import threading
from collections import deque
from typing import Optional

log = logging.getLogger("friday.brains.executive")

# keys that indicate raw sensor data — the Executive must never receive these
_RAW_KEYS = {"frame", "frames", "image", "audio_samples", "pcm", "detections",
             "scene_graph", "sql", "query", "embedding"}


class WorkingMemory:
    """The Executive's only memory — a small, bounded, volatile focus buffer."""

    def __init__(self, capacity: int = 32) -> None:
        self._buf: deque = deque(maxlen=capacity)
        self._focus: Optional[dict] = None
        self._lock = threading.Lock()

    def add(self, situation: dict) -> None:
        with self._lock:
            self._buf.append(situation)

    def set_focus(self, situation: Optional[dict]) -> None:
        with self._lock:
            self._focus = situation

    def focus(self) -> Optional[dict]:
        with self._lock:
            return dict(self._focus) if self._focus else None

    def recent(self, limit: int = 10) -> list:
        with self._lock:
            return list(self._buf)[-limit:][::-1]

    def snapshot(self) -> dict:
        with self._lock:
            return {"size": len(self._buf), "focus": self._focus}


class ExecutiveBrain:
    name = "executive_brain"

    def __init__(self, *, services=None, config: Optional[dict] = None, planner=None) -> None:
        self.services = services
        self.config = dict(config or {})
        self.working_memory = WorkingMemory(capacity=int(self.config.get("working_capacity", 32)))
        self._planner = planner                          # optional M5 executive (think/decide)
        self._memory_brain = _svc(services, "memory_brain")
        self._lock = threading.Lock()
        self._received = 0
        self._decisions = 0
        self._refused = 0

    # ── receive unified situations (the ONLY input) ──────────────────────────────
    def receive(self, unified_situation: dict) -> dict:
        """Accept one Unified Situation Report from the Coordinator. Refuses raw data."""
        if not isinstance(unified_situation, dict):
            self._refused += 1
            return {"accepted": False, "reason": "not a situation report"}
        if _RAW_KEYS & set(unified_situation.keys()):
            self._refused += 1
            log.debug("executive refused raw data: %s", set(unified_situation) & _RAW_KEYS)
            return {"accepted": False, "reason": "raw data refused — situations only"}

        self.working_memory.add(unified_situation)
        self._received += 1
        priority = float(unified_situation.get("priority",
                         unified_situation.get("importance", 0.5)))
        current = self.working_memory.focus()
        if current is None or priority >= float(current.get("priority", current.get("importance", 0.0))):
            self.working_memory.set_focus(unified_situation)
        emergency = unified_situation.get("category") == "emergency" or priority >= 0.9
        return {"accepted": True, "priority": priority, "emergency": emergency,
                "focus": self.working_memory.focus() is unified_situation}

    # ── decisions (CEO) ──────────────────────────────────────────────────────────
    def decide(self, objective: Optional[str] = None) -> dict:
        """Make a decision. With an objective + an M5 planner, delegate planning; else
        act on the current focus. Returns a decision (never executes raw work itself)."""
        self._decisions += 1
        if objective and self._planner is not None:
            try:
                plan = self._planner.decide(objective)
                return {"objective": objective, "plan": _plan_to_dict(plan), "source": "planner"}
            except Exception:  # noqa: BLE001
                log.debug("planner.decide failed", exc_info=True)
        focus = self.working_memory.focus()
        if focus is None:
            return {"decision": "idle", "reason": "no active situation"}
        action = focus.get("recommended_action") or _default_action(focus)
        return {"decision": action, "about": focus.get("summary", focus.get("situation", "")),
                "priority": focus.get("priority", focus.get("importance", 0.5)),
                "delegate_to": _delegate_for(focus)}

    def plan(self, objective: str) -> dict:
        return self.decide(objective)

    # ── memory access (ONLY via the Memory Brain) ────────────────────────────────
    def request_memory(self, query: str, *, limit: int = 5) -> list:
        if self._memory_brain is None:
            return []
        try:
            return self._memory_brain.recall(query, limit=limit)
        except Exception:  # noqa: BLE001
            return []

    # ── observability ────────────────────────────────────────────────────────────
    def status(self) -> dict:
        return {"focus": self.working_memory.focus(), "received": self._received,
                "decisions": self._decisions, "refused_raw": self._refused}

    def metrics(self) -> dict:
        return {"brain": self.name, "received": self._received, "decisions": self._decisions,
                "refused_raw": self._refused}

    def health(self) -> dict:
        return {"status": "ok", "brain": self.name,
                "working_memory": self.working_memory.snapshot()["size"],
                "refused_raw": self._refused}

    def service(self) -> "ExecutiveBrain":
        return self


def _svc(services, name):
    if services is None:
        return None
    getter = getattr(services, "try_get", None)
    return getter(name) if callable(getter) else None


def _default_action(focus: dict) -> str:
    cat = focus.get("category", "")
    return {"emergency": "alert_user", "alert": "notify_user",
            "user_state": "continue_monitoring"}.get(cat, "observe")


def _delegate_for(focus: dict) -> str:
    return {"emergency": "automation_brain", "alert": "automation_brain"}.get(
        focus.get("category", ""), "")


def _plan_to_dict(plan) -> dict:
    if hasattr(plan, "to_dict"):
        try:
            return plan.to_dict()
        except Exception:  # noqa: BLE001
            pass
    return {"plan": str(plan)}
