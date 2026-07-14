"""
core/brains/knowledge/brain.py — FRIDAY V3 (M46)
The Knowledge Brain. Wraps the M7 knowledge library (via the knowledge service)
and reports how FRIDAY's distilled world knowledge is growing — "Library holds
128 notes (+3)." It reports on CHANGE only; a static library stays silent.
"""

from __future__ import annotations

from typing import Optional

from ..base import CognitiveBrain, SituationReport


class KnowledgeBrain(CognitiveBrain):
    name = "knowledge_brain"

    def __init__(self, *, services=None, config=None, report_bus=None) -> None:
        super().__init__(services=services, config=config, report_bus=report_bus)
        self.local.cache("growth_history", capacity=128)
        self._knowledge = self._service("knowledge")

    def observe(self):
        knowledge = self._resolve("_knowledge", "knowledge")
        if knowledge is None:
            return {}
        try:
            return knowledge.stats() or {}
        except Exception:  # noqa: BLE001 — a stats fault must not blind the brain
            return {}

    def analyze(self, stats):
        stats = stats or {}
        # the store counts active vs archived; active is the usable library
        notes = int(stats.get("active", stats.get("total", 0)) or 0)
        return {"notes": notes, "raw": stats}

    def update_local_memory(self, analysis) -> None:
        self.local.push("growth_history", analysis["notes"])

    def generate_situation_report(self, insight) -> Optional[SituationReport]:
        notes = insight["notes"]
        previous = self.local.get("last_notes")
        self.local.set("last_notes", notes)
        if previous is None and notes == 0:
            return None                              # nothing known yet, nothing to say
        if previous is not None and notes == previous:
            return None                              # no growth → no report
        delta = notes - (previous or 0)
        grew = f" (+{delta})" if previous is not None and delta > 0 else \
            f" ({delta})" if previous is not None and delta < 0 else ""
        return self._report(f"Library holds {notes} note(s){grew}.",
                            confidence=0.9, priority=0.25, category="knowledge",
                            data={"notes": notes, "delta": delta if previous is not None else 0})
