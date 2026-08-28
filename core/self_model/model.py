"""
core/self_model/model.py — FRIDAY 5.x (M23, Internal Mind)
The Self Model: FRIDAY's live understanding of herself — loaded models,
resources, latency, confidence, capabilities and current limitations. It is
an AGGREGATOR over data that already exists (Intelligence OS, DecisionLog,
runtime health, psutil); it computes nothing speculative and never raises.

Answers, truthfully: "What am I doing?", "What can I do?",
"What can't I currently do?"

Directives 8 (roadmap Phase D) and 13 of docs/FRIDAY_5X_COGNITIVE_EVOLUTION.md.
"""

from __future__ import annotations

import logging

log = logging.getLogger("friday.self_model")

_RAM_CONCERN_PCT = 85.0


class SelfModel:
    def __init__(self, *, ios=None, decision_log=None, runtime=None,
                 conversation=None, goals=None, thoughts=None) -> None:
        self._ios = ios
        self._decision_log = decision_log
        self._runtime = runtime
        self._conversation = conversation
        self._goals = goals
        self._thoughts = thoughts

    # ── raw sections (each guarded; absence is data, not an error) ───────────────
    def _models(self) -> dict:
        try:
            loaded = self._ios.models.loaded_models()
            return {"loaded": [m.info.name for m in loaded],
                    "ram_mb": self._ios.models.memory_usage_mb()}
        except Exception:  # noqa: BLE001
            return {"loaded": [], "ram_mb": 0.0}

    def _resources(self) -> dict:
        try:
            import psutil
            vm = psutil.virtual_memory()
            return {"cpu_pct": psutil.cpu_percent(interval=None),
                    "ram_pct": vm.percent,
                    "ram_available_mb": round(vm.available / 1e6, 1)}
        except Exception:  # noqa: BLE001
            return {}

    def _performance(self) -> dict:
        try:
            stats = self._decision_log.stats()
            perf = {"turns": stats.get("total", 0),
                    "avg_confidence": stats.get("avg_confidence")}
            if hasattr(self._decision_log, "independence"):
                perf["independence_pct"] = \
                    self._decision_log.independence().get("independence_pct")
            return perf
        except Exception:  # noqa: BLE001
            return {}

    def _capabilities(self) -> list[str]:
        caps: set[str] = set()
        try:
            for m in self._ios.registry.all():
                caps |= set(m.info.capabilities or ())
        except Exception:  # noqa: BLE001
            pass
        return sorted(caps)

    def _limitations(self) -> list[str]:
        limits: list[str] = []
        resources = self._resources()
        if resources.get("ram_pct", 0.0) > _RAM_CONCERN_PCT:
            limits.append(f"memory pressure ({resources['ram_pct']:.0f}% RAM used)")
        try:
            import importlib.util
            for group, mods in (("vision", ("cv2",)), ("voice", ("sounddevice",)),
                                ("transcription", ("faster_whisper",)),
                                ("deep language models", ("transformers",))):
                if any(importlib.util.find_spec(m) is None for m in mods):
                    limits.append(f"no {group} backend installed")
        except Exception:  # noqa: BLE001
            pass
        limits.append("cannot call external services — fully local by rule")
        return limits

    def _current_activity(self) -> dict:
        activity: dict = {}
        try:
            activity["conversation"] = self._conversation.status()
        except Exception:  # noqa: BLE001
            pass
        try:
            from core.cognition.background import _active_goals
            activity["goals_active"] = len(_active_goals(self._goals))
        except Exception:  # noqa: BLE001
            pass
        try:
            activity["recent_thoughts"] = [t.text for t in self._thoughts.recent(3)]
        except Exception:  # noqa: BLE001
            pass
        return activity

    # ── the aggregate view ────────────────────────────────────────────────────────
    def snapshot(self) -> dict:
        return {"models": self._models(), "resources": self._resources(),
                "performance": self._performance(),
                "capabilities": self._capabilities(),
                "limitations": self._limitations(),
                "activity": self._current_activity()}

    # ── first-person answers ─────────────────────────────────────────────────────
    def what_am_i_doing(self) -> str:
        activity = self._current_activity()
        parts = []
        conv = activity.get("conversation") or {}
        if conv.get("turns"):
            parts.append(f"I've handled {conv['turns']} voice turns this session")
        if activity.get("goals_active"):
            parts.append(f"I'm tracking {activity['goals_active']} active goals")
        if activity.get("recent_thoughts"):
            parts.append(f"I'm currently thinking about: {activity['recent_thoughts'][0]}")
        return ". ".join(parts) + "." if parts else \
            "I'm listening and keeping my models warm."

    def what_can_i_do(self) -> str:
        caps = self._capabilities()
        models = self._models()
        head = f"I reason locally with {len(models['loaded'])} models"
        return f"{head}, covering: {', '.join(caps)}." if caps else head + "."

    def what_cant_i_do(self) -> str:
        limits = self._limitations()
        return "Right now: " + "; ".join(limits) + "."

    def health(self) -> dict:
        resources = self._resources()
        status = "ok"
        if resources.get("ram_pct", 0.0) > _RAM_CONCERN_PCT:
            status = "strained"
        return {"status": status, **resources}
