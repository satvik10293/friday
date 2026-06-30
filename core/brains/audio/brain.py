"""
core/brains/audio/brain.py — FRIDAY V3 (M17 revision)
The Audio Brain. Wraps the M15 auditory subsystem (via AudioService) and reports the
auditory situation — "I hear typing and running water." Owns local caches (wake state,
speaker, noise profiles, conversation); raw audio never leaves the brain.
"""

from __future__ import annotations

from typing import Optional

from ..base import CognitiveBrain, SituationReport

_EMERGENCY = {"glass_breaking", "alarm", "crying"}


class AudioBrain(CognitiveBrain):
    name = "audio_brain"

    def __init__(self, *, services=None, config=None, report_bus=None) -> None:
        super().__init__(services=services, config=config, report_bus=report_bus)
        for c in ("wake_state", "speaker_cache", "noise_profiles", "conversation_cache"):
            self.local.cache(c, capacity=128)
        self._audio = self._service("audio")

    def observe(self):
        return self._audio.recent_events(limit=10) if self._audio is not None else []

    def analyze(self, events):
        sounds, confs, emergency = [], [], False
        for e in events or []:
            sound = e.get("sound", "")
            if sound:
                sounds.append(sound)
                confs.append(float(e.get("confidence", 0.0)))
                if sound in _EMERGENCY:
                    emergency = True
        return {"sounds": sounds, "confidences": confs, "emergency": emergency}

    def update_local_memory(self, analysis) -> None:
        for s in analysis["sounds"]:
            self.local.push("noise_profiles", s)

    def generate_situation_report(self, insight) -> Optional[SituationReport]:
        if not insight["sounds"]:
            return None
        labels = sorted(set(insight["sounds"]))
        conf = (sum(insight["confidences"]) / len(insight["confidences"])
                if insight["confidences"] else 0.6)
        action = "investigate" if insight["emergency"] else None
        return self._report("I hear " + ", ".join(s.replace("_", " ") for s in labels) + ".",
                            confidence=round(conf, 3),
                            priority=1.0 if insight["emergency"] else 0.45,
                            category="emergency" if insight["emergency"] else "audio",
                            evidence=[{"sounds": labels}], recommended_action=action,
                            data={"sounds": labels, "emergency": insight["emergency"]})
