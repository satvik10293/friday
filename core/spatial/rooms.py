"""
core/spatial/rooms.py — FRIDAY V3 (M16)
Room awareness. Rooms are NEVER hardcoded: they are learned/registered at runtime and
mapped from cameras (or an injected classifier plugin). A camera is associated with a
room via configuration or `set_camera_room`, and new rooms appear simply by being named.
Supports future expansion (a learned room classifier satisfies the `RoomClassifier`
protocol and can be injected via the PluginService) without changing this module.
"""

from __future__ import annotations

import re
import threading
from typing import Optional

from .config import RoomConfig


def _norm(name: str) -> str:
    return re.sub(r"\s+", " ", (name or "").strip()) or "unknown"


class RoomModel:
    def __init__(self, config: Optional[RoomConfig] = None, *, classifier=None) -> None:
        self.config = config or RoomConfig()
        self._classifier = classifier                  # optional RoomClassifier plugin
        self._camera_rooms: dict[str, str] = {_norm_cam(k): _norm(v)
                                              for k, v in (self.config.camera_rooms or {}).items()}
        self._known: set = set(self._camera_rooms.values())
        self._lock = threading.Lock()

    # ── configuration / extensibility ────────────────────────────────────────────
    def set_camera_room(self, camera_id: str, room: str) -> None:
        room = _norm(room)
        with self._lock:
            self._camera_rooms[_norm_cam(camera_id)] = room
            self._known.add(room)

    def register_room(self, room: str) -> str:
        room = _norm(room)
        with self._lock:
            self._known.add(room)
        return room

    def set_classifier(self, classifier) -> None:
        self._classifier = classifier

    # ── resolution ───────────────────────────────────────────────────────────────
    def room_for(self, *, camera_id: str = "", observation=None) -> str:
        """Resolve the room for an observation. Precedence: explicit observation.room →
        injected classifier → camera→room map → default."""
        if observation is not None and getattr(observation, "room", None):
            return self._remember(_norm(observation.room))
        if self._classifier is not None:
            try:
                room = self._classifier.room_for(camera_id=camera_id, observation=observation)
                if room:
                    return self._remember(_norm(room))
            except Exception:  # noqa: BLE001
                pass
        with self._lock:
            mapped = self._camera_rooms.get(_norm_cam(camera_id))
        return mapped or _norm(self.config.default_room)

    def _remember(self, room: str) -> str:
        with self._lock:
            self._known.add(room)
        return room

    def known_rooms(self) -> list:
        with self._lock:
            return sorted(self._known)

    def health(self) -> dict:
        return {"status": "ok", "known_rooms": len(self.known_rooms()),
                "mapped_cameras": len(self._camera_rooms)}


def _norm_cam(camera_id: str) -> str:
    return str(camera_id or "").strip()
