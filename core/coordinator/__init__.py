"""
core/coordinator/ — FRIDAY V3 (M17 revision) Cognitive Coordinator.

The successor to the Perception Hub, operating on Situation Reports instead of raw
observations. It receives reports from every Cognitive Brain, merges related ones,
resolves conflicts, removes duplicates, maintains the active context, builds Unified
Situations, and publishes only processed knowledge to the Executive Brain — the only
gateway into Executive Intelligence.

`CoordinatorService` wires the whole society (report bus + brains + executive +
coordinator). Reuses the M17 hub's ConfidenceEngine + Timeline. Side-effect-free import.
"""

from __future__ import annotations

from .config import CoordinatorConfig
from .coordinator import CognitiveCoordinator
from .events import CoordinatorEvent
from .service import CoordinatorService, get_coordinator_service
from .unified_situation import UnifiedSituation

__all__ = ["CoordinatorService", "get_coordinator_service", "CognitiveCoordinator",
           "CoordinatorConfig", "CoordinatorEvent", "UnifiedSituation"]
