"""
core/vision/transport/adapters/browser_adapter.py — FRIDAY 6.1 (M14)
The browser camera adapter — Android / iPhone / laptop browser cameras streaming over
Flask + SocketIO. It is a push adapter: the SocketIO handler calls `submit()` with the
base64 JPEG payload (fast), and the manager's worker thread decodes it. This is the
adapter that wraps the owner's existing receiver protocol.
"""

from __future__ import annotations

from ..camera import CameraKind
from .base import PushAdapter


class BrowserAdapter(PushAdapter):
    kind = CameraKind.BROWSER
