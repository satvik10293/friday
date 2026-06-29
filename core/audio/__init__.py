"""
core/audio/ — FRIDAY 4.0 (M12.1) Intelligent Listening & Audio Processing.

An event-driven auditory perception pipeline: a continuously running, modular,
interruptible listening system that turns sound into events and spoken commands
into Intelligence-OS (M12) requests — fully local, never blocking, privacy-aware.

Side-effect-free to import (no microphone opens, no models load at import).
"""

from __future__ import annotations

from .listener.events import AudioEvent, AudioEventBus, Event
from .listener.pipeline import ListeningPipeline, ListeningState
from .listener.service import ListeningService, get_listening_service
# M15 — Auditory Cognition (environmental sound understanding, additive to M12.1)
from .cognition.service import AuditoryCognition, get_auditory_cognition
from .cognition.config import AudioCognitionConfig

__all__ = ["ListeningService", "get_listening_service", "ListeningPipeline",
           "ListeningState", "AudioEvent", "AudioEventBus", "Event",
           "AuditoryCognition", "get_auditory_cognition", "AudioCognitionConfig"]
