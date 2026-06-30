"""
core/services/ — FRIDAY V3 (M16) Service Layer.

The communication backbone introduced in M16: beginning here, subsystems talk ONLY
through stable service interfaces obtained from a `ServiceContainer` (dependency
injection) — never by importing another subsystem's internals. Each service is a thin,
graceful adapter over an existing subsystem (or a placeholder for future ones), so the
whole system is mockable, testable, and ready for remote services later.

Side-effect-free to import: constructing the container wires nothing until a service is
resolved, and every wrapper degrades gracefully when its backend is absent.
"""

from __future__ import annotations

from .attention_service import AttentionService
from .audio_service import AudioService
from .configuration_service import ConfigurationService
from .container import ServiceContainer, build_default_container
from .emotion_service import EmotionService
from .executive_service import ExecutiveService
from .interfaces import ServiceName
from .learning_service import LearningService
from .memory_service import MemoryService
from .plugin_service import PluginService
from .runtime_service import RuntimeService
from .vision_service import VisionService
from .world_model_service import WorldModelService

__all__ = [
    "ServiceContainer", "build_default_container", "ServiceName",
    "RuntimeService", "WorldModelService", "MemoryService", "AttentionService",
    "VisionService", "AudioService", "ExecutiveService", "ConfigurationService",
    "PluginService", "LearningService", "EmotionService",
]
