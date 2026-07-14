"""
core/brains/goals/brain.py — FRIDAY V3 (M46)
The Goal Brain. Wraps the M28 goal service and reports the goal situation —
"2 proposals await approval: tidy the vault; index new PDFs." It reports on
CHANGE only (a new/removed proposal, active-count movement) and recommends
review when proposals are waiting; approval itself stays human-gated.
"""

from __future__ import annotations

from typing import Optional

from ..base import CognitiveBrain, SituationReport


class GoalBrain(CognitiveBrain):
    name = "goal_brain"

    def __init__(self, *, services=None, config=None, report_bus=None) -> None:
        super().__init__(services=services, config=config, report_bus=report_bus)
        self.local.cache("proposal_history", capacity=128)
        self._goals = self._service("goals")

    def observe(self):
        goals = self._resolve("_goals", "goals")
        if goals is None:
            return {}
        try:
            return goals.status() or {}
        except Exception:  # noqa: BLE001 — a status fault must not blind the brain
            return {}

    def analyze(self, status):
        status = status or {}
        counts = status.get("counts") or {}
        return {"proposals": sorted(str(t) for t in (status.get("proposals") or [])),
                "active": int(counts.get("active", 0) or 0),
                "pending": int(counts.get("pending", 0) or 0)}

    def update_local_memory(self, analysis) -> None:
        for title in analysis["proposals"]:
            self.local.push("proposal_history", title)

    def generate_situation_report(self, insight) -> Optional[SituationReport]:
        state = {"proposals": insight["proposals"], "active": insight["active"]}
        previous = self.local.get("last_goal_state")
        self.local.set("last_goal_state", state)
        if state == previous:
            return None                              # nothing moved → no report
        if not insight["proposals"] and previous is None and insight["active"] == 0:
            return None                              # empty first look, nothing to say
        if insight["proposals"]:
            titles = "; ".join(insight["proposals"][:3])
            n = len(insight["proposals"])
            return self._report(
                f"{n} proposal(s) await approval: {titles}.",
                confidence=0.9, priority=0.55, category="goals",
                recommended_action="review_proposals",
                data={"proposals": insight["proposals"], "active": insight["active"]})
        return self._report(
            f"Goals: {insight['active']} active, no proposals waiting.",
            confidence=0.9, priority=0.25, category="goals",
            data={"proposals": [], "active": insight["active"]})
