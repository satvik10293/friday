"""
core/vision/transport/adapters/ — FRIDAY 6.1 (M14)
Camera adapters. Adding support for a new camera type requires implementing only an
adapter (no transport redesign). Pull adapters (webcam, RTSP, array) capture frames
when polled; push adapters (browser/SocketIO, ESP32-HTTP, …) buffer externally
submitted payloads and decode them off the socket thread.
"""

from __future__ import annotations

from .array_adapter import ArrayAdapter
from .base import CameraAdapter, PushAdapter
from .browser_adapter import BrowserAdapter
from .webcam_adapter import RtspAdapter, WebcamAdapter

__all__ = ["CameraAdapter", "PushAdapter", "ArrayAdapter", "BrowserAdapter",
           "WebcamAdapter", "RtspAdapter"]
