"""
core/vision/integration/events.py — FRIDAY 6.1 (M14)
Cognitive-stage vision events (distinct from the transport events in
core/vision/transport/events.py). These are published when vision perception turns
into cognition-relevant happenings: an object appears/disappears, motion starts/stops,
or the scene changes. str-valued so they are first-class runtime-bus keys.
"""

from __future__ import annotations

from enum import Enum


class VisionCognitionEvent(str, Enum):
    OBSERVATION = "vision.observation"
    OBJECT_APPEARED = "vision.object.appeared"
    OBJECT_DISAPPEARED = "vision.object.disappeared"
    OBJECT_PROMOTED = "vision.object.promoted"
    MOTION_STARTED = "vision.motion.started"
    MOTION_STOPPED = "vision.motion.stopped"
    SCENE_CHANGED = "vision.scene.changed"
    ENTITY_LINKED = "vision.entity.linked"
