"""
core/io/orb/ -- FRIDAY V3 (M20 revision) Orb UI.

The primary FRIDAY interface: a floating, frameless, always-on-top orb that runs in its own
native window (never a browser tab). It is driven ONLY through the Runtime Event Bus by the
Orb Controller and contains no AI logic -- cognition publishes signals, the orb visualises
them; user interactions travel back as inbound signals.

Side-effect free to import: the window/webview and TTS backends are imported lazily.
"""

from __future__ import annotations

from . import events, state
from .config import OrbConfig
from .controller import OrbController
from .speech_bridge import SpeechBridge
from .state import Emotion, InteractionMode, OrbSettings, OrbState, SettingsStore
from .window import Api, OrbView, OrbWindow

__all__ = [
    "OrbController", "OrbView", "OrbWindow", "Api", "SpeechBridge",
    "OrbConfig", "OrbSettings", "SettingsStore",
    "OrbState", "Emotion", "InteractionMode",
    "events", "state",
]
