"""
core/vision/transport/events.py — FRIDAY 6.1 (M14)
Vision transport event vocabulary. str-valued so they are first-class keys on the M1
runtime bus (the GoalEvent/PerceptionEvent pattern), without touching the frozen 3.0
Signal enum. Mission Control and downstream stages subscribe here.
"""

from __future__ import annotations

from enum import Enum


class VisionEvent(str, Enum):
    CAMERA_REGISTERED = "vision.camera.registered"
    CAMERA_CONNECTED = "vision.camera.connected"
    CAMERA_STREAMING = "vision.camera.streaming"
    CAMERA_DEGRADED = "vision.camera.degraded"
    CAMERA_RECOVERED = "vision.camera.recovered"
    CAMERA_DISCONNECTED = "vision.camera.disconnected"
    CAMERA_REMOVED = "vision.camera.removed"
    FRAME_RECEIVED = "vision.frame.received"
    FRAME_DROPPED = "vision.frame.dropped"
    FRAME_CORRUPT = "vision.frame.corrupt"
    TRANSPORT_WARNING = "vision.transport.warning"
    TRANSPORT_ERROR = "vision.transport.error"
