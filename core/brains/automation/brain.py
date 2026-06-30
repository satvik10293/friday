"""
core/brains/automation/brain.py — FRIDAY V3 (M17 revision)
The Automation Brain (foundation). It holds automation rules (trigger → action) and,
each cycle, evaluates them against the current situation, reporting any that would fire.
It does NOT execute actions itself — it reports recommendations to the Coordinator/
Executive, which own decisions. Rules are data, registered at runtime (extensible).
"""

from __future__ import annotations

from typing import Callable, Optional

from ..base import CognitiveBrain, SituationReport


class AutomationBrain(CognitiveBrain):
    name = "automation_brain"

    def __init__(self, *, services=None, config=None, report_bus=None) -> None:
        super().__init__(services=services, config=config, report_bus=report_bus)
        self.local.cache("fired", capacity=128)
        self._rules: list = []                           # list[(name, predicate, action)]
        self._context: dict = {}

    def add_rule(self, name: str, predicate: Callable[[dict], bool], action: str) -> None:
        """Register a trigger → action rule. `predicate(context) -> bool`."""
        self._rules.append((name, predicate, action))

    def set_context(self, context: dict) -> None:
        """The Coordinator feeds the current unified context here (not raw data)."""
        self._context = dict(context or {})

    def reason(self, analysis):
        fired = []
        for name, predicate, action in self._rules:
            try:
                if predicate(self._context):
                    fired.append({"rule": name, "action": action})
            except Exception:  # noqa: BLE001 — a bad rule never breaks the brain
                continue
        for f in fired:
            self.local.push("fired", f)
        return fired

    def generate_situation_report(self, insight) -> Optional[SituationReport]:
        if not insight:
            return None
        actions = ", ".join(f["action"] for f in insight)
        return self._report(f"Automation: {len(insight)} rule(s) ready — {actions}.",
                            confidence=0.7, priority=0.5, category="automation",
                            recommended_action=insight[0]["action"], data={"fired": insight})

    def health(self) -> dict:
        return {"status": "placeholder", "brain": self.name, "rules": len(self._rules)}
