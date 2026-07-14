"""
core/brains/spatial/brain.py — FRIDAY V3 (M17 revision)
The Spatial Brain. Wraps the M16 spatial subsystem (via SpatialService) and reports the
spatial situation — "The user is working at the desk in the office; 4 objects tracked."
Its local memory mirrors the spatial subsystem's structure (scene graph summary, room
cache, motion history, object locations); raw scene graphs never leave the brain.
"""

from __future__ import annotations

from typing import Optional

from ..base import CognitiveBrain, SituationReport


class SpatialBrain(CognitiveBrain):
    name = "spatial_brain"

    def __init__(self, *, services=None, config=None, report_bus=None) -> None:
        super().__init__(services=services, config=config, report_bus=report_bus)
        for c in ("room_cache", "motion_history", "object_locations"):
            self.local.cache(c, capacity=128)
        self._spatial = self._service("spatial")

    def observe(self):
        spatial = self._resolve("_spatial", "spatial")
        return spatial.snapshot() if spatial is not None else {}

    def analyze(self, snapshot):
        scene = (snapshot or {}).get("scene", {})
        user = (snapshot or {}).get("user", {})
        objects = scene.get("objects", [])
        rooms = [r.get("label") for r in scene.get("rooms", [])]
        return {"object_count": len(objects), "rooms": rooms,
                "user_state": user.get("last_state", "unknown"),
                "user_room": user.get("room", "unknown"),
                "objects": [o.get("label") for o in objects][:10]}

    def update_local_memory(self, analysis) -> None:
        for r in analysis["rooms"]:
            self.local.push("room_cache", r)
        self.local.set("user_room", analysis["user_room"])
        for o in analysis["objects"]:
            self.local.push("object_locations", o)

    def generate_situation_report(self, insight) -> Optional[SituationReport]:
        if insight["object_count"] == 0 and insight["user_state"] == "unknown":
            return None
        state = insight["user_state"]
        room = insight["user_room"]
        summary = (f"The user is {state.replace('_', ' ')} in the {room}; "
                   f"{insight['object_count']} object(s) tracked.")
        return self._report(summary, confidence=0.8,
                            priority=0.6 if state in ("entering_room", "leaving_room") else 0.4,
                            category="spatial",
                            evidence=[{"objects": insight["objects"], "room": room}],
                            data={"user_state": state, "room": room,
                                  "objects": insight["objects"]})
