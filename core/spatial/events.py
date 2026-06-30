"""
core/spatial/events.py — FRIDAY V3 (M16)
The Spatial Cognition event vocabulary. Published on the Runtime event bus (via the
RuntimeService) so subsystems react to spatial happenings without tight coupling.
str-valued so they are first-class bus keys, consistent with the vision/audio events.
"""

from __future__ import annotations

from enum import Enum


class SpatialEvent(str, Enum):
    OBJECT_DETECTED = "spatial.object.detected"
    OBJECT_TRACKED = "spatial.object.tracked"
    OBJECT_MOVED = "spatial.object.moved"
    OBJECT_LOST = "spatial.object.lost"
    OBJECT_RETURNED = "spatial.object.returned"
    OBJECT_REMOVED = "spatial.object.removed"
    SCENE_UPDATED = "spatial.scene.updated"
    RELATIONSHIP_CHANGED = "spatial.relationship.changed"
    ROOM_CHANGED = "spatial.room.changed"
    USER_MOVED = "spatial.user.moved"
    USER_LOCATED = "spatial.user.located"
    SCENE_LOADED = "spatial.scene.loaded"
    SCENE_SAVED = "spatial.scene.saved"
