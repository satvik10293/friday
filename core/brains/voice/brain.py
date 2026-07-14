"""
core/brains/voice/brain.py — FRIDAY V3 (M46)
The Voice Brain. Wraps the conversation bridge (via the "conversation"
service) and reports the interaction situation — "Conversation: 5 turns
(4 cloud, 1 clarification, 0 echoes dropped)." It reports on CHANGE only
(new turns since the last cycle); a silent room stays silent here too.
"""

from __future__ import annotations

from typing import Optional

from ..base import CognitiveBrain, SituationReport


class VoiceBrain(CognitiveBrain):
    name = "voice_brain"

    def __init__(self, *, services=None, config=None, report_bus=None) -> None:
        super().__init__(services=services, config=config, report_bus=report_bus)
        self.local.cache("turn_history", capacity=128)
        self._conversation = self._service("conversation")

    def observe(self):
        conversation = self._resolve("_conversation", "conversation")
        if conversation is None:
            return {}
        try:
            return conversation.status() or {}
        except Exception:  # noqa: BLE001 — a status fault must not blind the brain
            return {}

    def analyze(self, status):
        status = status or {}
        return {"turns": int(status.get("turns", 0) or 0),
                "cloud": int(status.get("cloud_turns", 0) or 0),
                "clarifications": int(status.get("clarifications", 0) or 0),
                "echoes": int(status.get("echoes_dropped", 0) or 0)}

    def update_local_memory(self, analysis) -> None:
        self.local.push("turn_history", analysis["turns"])

    def generate_situation_report(self, insight) -> Optional[SituationReport]:
        previous = self.local.get("last_turns")
        self.local.set("last_turns", insight["turns"])
        if insight["turns"] == 0 or insight["turns"] == previous:
            return None                              # no new conversation → silence
        return self._report(
            f"Conversation: {insight['turns']} turn(s) "
            f"({insight['cloud']} cloud, {insight['clarifications']} clarification(s), "
            f"{insight['echoes']} echo(es) dropped).",
            confidence=0.9, priority=0.3, category="voice", data=dict(insight))
