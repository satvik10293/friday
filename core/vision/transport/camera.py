"""
core/vision/transport/camera.py — FRIDAY 6.1 (M14)
Camera identity + lifecycle types. Every camera has a permanent opaque id
(CAMERA_0001) and is referenced ONLY by that id — never by IP, socket, or browser
session. CameraInfo is the public record the Camera Manager exposes.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum


class CameraKind(str, Enum):
    BROWSER = "browser"            # Android/iPhone/laptop browser camera (SocketIO)
    USB_WEBCAM = "usb_webcam"
    LAPTOP_WEBCAM = "laptop_webcam"
    NETWORK = "network"
    RTSP = "rtsp"
    ESP32 = "esp32"
    ROBOT = "robot"
    DRONE = "drone"
    WEARABLE = "wearable"
    ARRAY = "array"               # offline / test source
    UNKNOWN = "unknown"


class CameraStatus(str, Enum):
    REGISTERED = "registered"     # known, not yet streaming
    CONNECTED = "connected"       # socket/handle established
    STREAMING = "streaming"       # frames flowing
    DEGRADED = "degraded"         # frames late / dropping
    DISCONNECTED = "disconnected"  # no frames past timeout
    REMOVED = "removed"


@dataclass
class CameraInfo:
    camera_id: str
    kind: str = CameraKind.UNKNOWN.value
    label: str = ""
    key: str = ""                 # stable registration key (client token / source uri)
    status: str = CameraStatus.REGISTERED.value
    registered_at: float = field(default_factory=time.time)
    last_frame_at: float = 0.0
    reconnects: int = 0
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return dict(self.__dict__)
