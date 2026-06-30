"""
core/spatial/localization.py — FRIDAY V3 (M16)
User localization — estimate where the user is and what they are doing, from visual
presence (person detections) and auditory cues (keyboard/mouse/speech). It produces a
compact user-state estimate the engine writes to the World Model and publishes as
USER_LOCATED / USER_MOVED.

States: AT_DESK · WORKING · SITTING · STANDING · WALKING · ENTERING_ROOM ·
LEAVING_ROOM · IDLE · UNAVAILABLE · PRESENT. Heuristic and explainable; a learned
estimator can replace it (it only needs the `UserStateEstimator` protocol). Holds a
little temporal state to detect entering/leaving/idle transitions.
"""

from __future__ import annotations

import time
from typing import Optional

from .config import LocalizationConfig

_WALK_EPS = 0.08            # normalized centre delta that counts as walking
_WORK_AUDIO = {"keyboard_typing", "mouse_clicking"}
_PRESENT_AUDIO = {"laughter", "crying"}


class UserState:
    AT_DESK = "at_desk"
    WORKING = "working"
    SITTING = "sitting"
    STANDING = "standing"
    WALKING = "walking"
    ENTERING_ROOM = "entering_room"
    LEAVING_ROOM = "leaving_room"
    IDLE = "idle"
    UNAVAILABLE = "unavailable"
    PRESENT = "present"


class UserLocalizer:
    def __init__(self, config: Optional[LocalizationConfig] = None) -> None:
        self.config = config or LocalizationConfig()
        self._was_present = False
        self._last_present_at = 0.0
        self._last_activity_at = 0.0
        self._last_center: Optional[tuple] = None
        self._last_room = "unknown"
        self._last_state = UserState.UNAVAILABLE

    def estimate(self, *, observations: list, audio_events: list,
                 now: Optional[float] = None) -> dict:
        if not self.config.enabled:
            return {"state": UserState.PRESENT, "present": True, "room": self._last_room,
                    "changed": False, "moved": False, "confidence": 0.0, "ts": now or time.time()}
        now = now if now is not None else time.time()
        persons = [o for o in observations if o.object_class in ("person", "user")]
        work_audio = any(e.get("sound") in _WORK_AUDIO for e in audio_events)
        present_audio = any(e.get("sound") in _PRESENT_AUDIO for e in audio_events) or work_audio

        if persons:
            result = self._present(persons, observations, work_audio, now)
        elif present_audio:                              # heard but not seen → working at desk
            result = {"state": UserState.WORKING if work_audio else UserState.PRESENT,
                      "present": True, "room": self._last_room, "moved": False,
                      "confidence": 0.5, "ts": now}
            self._last_present_at = now
            self._last_activity_at = now
            self._was_present = True
        else:
            result = self._absent(now)

        result["changed"] = result["state"] != self._last_state or result.get("moved", False)
        self._last_state = result["state"]
        self._last_room = result["room"]
        return result

    # ── present ──────────────────────────────────────────────────────────────────
    def _present(self, persons: list, observations: list, work_audio: bool, now: float) -> dict:
        person = persons[0]
        center = person.center
        room = person.room or self._last_room
        moved = self._last_center is not None and _dist(self._last_center, center) > _WALK_EPS
        entering = not self._was_present
        room_changed = room != self._last_room and self._last_room != "unknown"

        near_desk = self._near_desk(center, observations)
        if entering:
            state = UserState.ENTERING_ROOM
        elif moved:
            state = UserState.WALKING
        elif work_audio and near_desk:
            state = UserState.WORKING
        elif near_desk:
            state = UserState.AT_DESK
        else:
            state = UserState.PRESENT

        self._was_present = True
        self._last_present_at = now
        if state in (UserState.WORKING, UserState.WALKING, UserState.AT_DESK):
            self._last_activity_at = now
        self._last_center = center
        return {"state": state, "present": True, "room": room,
                "location": "desk" if near_desk else "room",
                "moved": moved or room_changed, "confidence": float(person.confidence), "ts": now}

    def _near_desk(self, center: tuple, observations: list) -> bool:
        desk = set(self.config.desk_objects)
        for o in observations:
            if o.object_class in desk and _dist(center, o.center) < 0.3:
                return True
        return False

    # ── absent ───────────────────────────────────────────────────────────────────
    def _absent(self, now: float) -> dict:
        leaving = self._was_present
        self._was_present = False
        self._last_center = None
        silence = now - self._last_present_at if self._last_present_at else float("inf")
        if leaving:
            state = UserState.LEAVING_ROOM
        elif silence >= self.config.away_after_s:
            state = UserState.UNAVAILABLE
        elif silence >= self.config.idle_after_s:
            state = UserState.IDLE
        else:
            state = UserState.IDLE
        return {"state": state, "present": False, "room": self._last_room, "moved": leaving,
                "confidence": 0.6, "ts": now}

    def health(self) -> dict:
        return {"status": "ok", "last_state": self._last_state, "room": self._last_room,
                "present": self._was_present}


def _dist(a: tuple, b: tuple) -> float:
    return ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5
