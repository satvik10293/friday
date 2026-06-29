"""
core/audio/cognition/ — FRIDAY V3 (M15) Auditory Cognition.

Extends FRIDAY's hearing beyond speech into understanding of the whole auditory
environment: environmental sound detection (an open, plugin-based catalog), context
reasoning into the World Model (no bypass), auditory memory, audio attention
priorities, plus wake-word control and speech de-duplication for the speech path.

Built additively on the M12.1 listening pipeline — that pipeline is not modified.
Side-effect-free to import: no microphone opens, no model loads at import.
"""

from __future__ import annotations

from .attention import AudioAttention
from .config import AudioCognitionConfig
from .context import AudioContextReasoner, ContextRule
from .dedup import SpeechDeduplicator
from .engine import AudioEventEngine
from .events import (AudioCognitionEvent, AuditoryEvent, SoundCatalog, SoundCategory,
                     SoundType, default_catalog)
from .memory import AuditoryMemory
from .service import AuditoryCognition, get_auditory_cognition
from .wake import WakeWordController

__all__ = [
    "AuditoryCognition", "get_auditory_cognition", "AudioCognitionConfig",
    "AudioEventEngine", "AudioContextReasoner", "ContextRule", "AuditoryMemory",
    "AudioAttention", "WakeWordController", "SpeechDeduplicator",
    "AuditoryEvent", "SoundType", "SoundCategory", "SoundCatalog", "default_catalog",
    "AudioCognitionEvent",
]
