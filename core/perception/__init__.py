"""
core/perception — FRIDAY 4.0 (M6) Perception layer.

Turns raw sensor readings into meaning: deduplicate, merge, score significance,
promote important facts into the M5 World Model, and let Attention focus on what
changed. 100% local — no cloud, no external AI. Import is side-effect free.

    from core.perception import PerceptionManager, PerceptionStore, WorldFeed
    pm = PerceptionManager(store=PerceptionStore(), world_feed=WorldFeed(world))
    pm.ingest(observation)
"""

from .models import (
    Observation, ObservationBatch, ObservationConfidence, ObservationSource,
    ObservationType, new_observation,
)
from .events import PerceptionEvent
from .store import PerceptionStore
from .world_feed import WorldFeed
from .fusion import FusionRule, SensorFusion, noisy_or
from .health import HealthStatus, PerceptionHealth, aggregate, derive_status
from .manager import PerceptionManager
from .brain import PerceptiveBrain, get_perceptive_brain
from .cognition import PerceptiveCognitiveLoop, PERCEPTION_PHASES

__all__ = [
    "Observation", "ObservationBatch", "ObservationConfidence", "ObservationSource",
    "ObservationType", "new_observation",
    "PerceptionEvent",
    "PerceptionStore",
    "WorldFeed",
    "FusionRule", "SensorFusion", "noisy_or",
    "HealthStatus", "PerceptionHealth", "aggregate", "derive_status",
    "PerceptionManager",
    "PerceptiveBrain", "get_perceptive_brain",
    "PerceptiveCognitiveLoop", "PERCEPTION_PHASES",
]
