"""
core/brains/ — FRIDAY V3 (M17 revision) Cognitive Brains.

FRIDAY is a society of specialized Cognitive Brains. Each owns local reasoning, local
state, local memory, and situation reporting, and follows one standard lifecycle
(observe → analyze → update_local_memory → reason → generate_situation_report →
publish → wait). Brains emit only structured `SituationReport`s on the Situation Report
Bus; the Cognitive Coordinator consumes them; the Executive Brain never sees raw data.

Brains reach peers and subsystems only through services — no brain imports another's
internals. Side-effect-free to import: constructing a brain opens nothing.
"""

from __future__ import annotations

from typing import Optional

from .audio.brain import AudioBrain
from .automation.brain import AutomationBrain
from .base import (CognitiveBrain, LocalMemory, SituationReport, SituationReportBus)
from .emotion.brain import EmotionBrain
from .executive.brain import ExecutiveBrain
from .learning.brain import LearningBrain
from .memory.brain import MemoryBrain
from .runtime.brain import RuntimeBrain
from .spatial.brain import SpatialBrain
from .vision.brain import VisionBrain

__all__ = [
    "CognitiveBrain", "SituationReport", "SituationReportBus", "LocalMemory",
    "VisionBrain", "AudioBrain", "SpatialBrain", "MemoryBrain", "LearningBrain",
    "EmotionBrain", "AutomationBrain", "RuntimeBrain", "ExecutiveBrain", "build_brains",
]

# the sensor + support brains that follow the standard lifecycle (Executive + Memory are
# managed separately by the Coordinator / society wiring).
_LIFECYCLE_BRAINS = (VisionBrain, AudioBrain, SpatialBrain, LearningBrain, EmotionBrain,
                     AutomationBrain, RuntimeBrain)


def build_brains(*, services=None, report_bus: Optional[SituationReportBus] = None,
                 config: Optional[dict] = None) -> dict:
    """Construct the standard brain society over a service container + report bus.
    Returns {brain_name: brain}. Each brain is independent and individually testable."""
    bus = report_bus or SituationReportBus()
    cfg = dict(config or {})
    brains: dict = {}
    for klass in _LIFECYCLE_BRAINS:
        brain = klass(services=services, config=cfg.get(klass.name, {}), report_bus=bus)
        brains[brain.name] = brain
    memory = MemoryBrain(services=services, config=cfg.get("memory_brain", {}), report_bus=bus)
    brains[memory.name] = memory
    if services is not None and hasattr(services, "register"):
        try:
            services.register("memory_brain", memory)    # the sanctioned memory gateway
        except Exception:  # noqa: BLE001
            pass
    return brains
