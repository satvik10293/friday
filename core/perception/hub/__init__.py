"""
core/perception/hub/ — FRIDAY V3 (M17) Multimodal Intelligence & Perception Hub.

The unified cognitive gateway. Vision, audio, and spatial no longer each write memory
separately; every sensor publishes observations and the Hub fuses them into ONE unified
observation, reasons about it, maintains the active context + timeline, forwards
understanding to the World Model, and remembers only meaningful, non-duplicate events.

Built additively on M16's service layer — the Hub imports no subsystem's internals; it
consumes source-agnostic `ModalityObservation`s and communicates via services + the
Runtime event bus. Lives under `core/perception/hub/` so the M6 perception package
(`core/perception/*.py`) is untouched.

Side-effect-free to import: no sensors, no DB, no threads until constructed/started.
"""

from __future__ import annotations

from .config import PerceptionHubConfig
from .confidence import ConfidenceEngine
from .context import ContextEngine
from .events import HubEvent
from .fusion import MultimodalFusion
from .hub import PerceptionHub
from .observations import ModalityObservation, UnifiedObservation
from .reasoning import CognitiveReasoner
from .service import (PerceptionService, attach_to_container, get_perception_service)
from .timeline import Timeline

__all__ = [
    "PerceptionService", "get_perception_service", "attach_to_container",
    "PerceptionHub", "PerceptionHubConfig", "ModalityObservation", "UnifiedObservation",
    "MultimodalFusion", "ConfidenceEngine", "ContextEngine", "Timeline",
    "CognitiveReasoner", "HubEvent",
]
