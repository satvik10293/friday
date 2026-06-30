"""
core/brains/vision/brain.py — FRIDAY V3 (M17 revision)
The Vision Brain. Wraps the M14 vision subsystem (via VisionService) and turns raw
detections into a structured situation report — "I see 3 objects: a laptop, a keyboard,
and a person." Raw frames and detections never leave this brain; it owns local caches
(objects, faces, tracking, confidence history) and reports only processed knowledge.
"""

from __future__ import annotations

from typing import Optional

from ..base import CognitiveBrain, SituationReport


class VisionBrain(CognitiveBrain):
    name = "vision_brain"

    def __init__(self, *, services=None, config=None, report_bus=None) -> None:
        super().__init__(services=services, config=config, report_bus=report_bus)
        for c in ("object_cache", "face_cache", "tracking_cache", "confidence_history"):
            self.local.cache(c, capacity=256)
        self._vision = self._service("vision")

    def observe(self):
        return self._vision.detect() if self._vision is not None else []

    def analyze(self, detections):
        objects, people, confs = [], [], []
        for d in detections or []:
            label = d.get("label") or d.get("object_class") or "object"
            confs.append(float(d.get("confidence", 0.0)))
            if d.get("object_class") == "person" or label == "person":
                people.append("person")
            else:
                objects.append(label)
        return {"objects": objects, "people": people, "confidences": confs,
                "count": len(detections or [])}

    def update_local_memory(self, analysis) -> None:
        for o in analysis["objects"]:
            self.local.push("object_cache", o)
        if analysis["confidences"]:
            self.local.push("confidence_history",
                            round(sum(analysis["confidences"]) / len(analysis["confidences"]), 3))
        if analysis["people"]:
            self.local.push("tracking_cache", "person")

    def reason(self, analysis):
        return analysis

    def generate_situation_report(self, insight) -> Optional[SituationReport]:
        if insight["count"] == 0:
            return None
        labels = sorted(set(insight["objects"]))
        people = len(insight["people"])
        conf = (sum(insight["confidences"]) / len(insight["confidences"])
                if insight["confidences"] else 0.6)
        parts = []
        if labels:
            parts.append(f"{len(labels)} object(s): {', '.join(labels[:6])}")
        if people:
            parts.append(f"{people} person(s)")
        return self._report("I see " + " and ".join(parts) + ".",
                            confidence=round(conf, 3), priority=0.6 if people else 0.4,
                            category="vision",
                            evidence=[{"objects": labels, "people": people}],
                            data={"objects": labels, "people": people})
