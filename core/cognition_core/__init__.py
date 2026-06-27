"""
core/cognition_core/ — FRIDAY 6.0 (M13) Persistent Entity & Belief Foundation.

The substrate of the Cognitive Operating System: permanent, name-independent entity
identity (opaque stable ids), first-class *evolving* beliefs (evidence + confidence +
provenance), and a live self model — integrated additively with the M5 World Model and
M6 perception. Persistence is abstracted behind repository interfaces; cognition never
couples to SQLite. Prediction, scientific reasoning, and research are deliberately NOT
here — they depend on this foundation and come in later milestones.

Side-effect-free to import.
"""

from __future__ import annotations

from .belief_system import BeliefSystem
from .entity_registry import PersistentEntityRegistry
from .entity_resolver import EntityResolver
from .events import CognitionEvent
from .interfaces import BeliefRepository, EntityRepository
from .models import (Belief, BeliefStatus, Entity, Evidence, ResolveMethod,
                     ResolveResult, SelfModelSnapshot)
from .repositories import (InMemoryBeliefRepository, InMemoryEntityRepository,
                           SqliteBeliefRepository, SqliteEntityRepository)
from .self_model import SelfModel
from .service import CognitionCore, get_cognition_core
from .world_integration import EntityLinker, ResolvingWorldFeed

__all__ = [
    "CognitionCore", "get_cognition_core", "EntityResolver",
    "PersistentEntityRegistry", "BeliefSystem", "SelfModel", "CognitionEvent",
    "EntityRepository", "BeliefRepository", "SqliteEntityRepository",
    "SqliteBeliefRepository", "InMemoryEntityRepository", "InMemoryBeliefRepository",
    "Entity", "Belief", "Evidence", "BeliefStatus", "ResolveMethod", "ResolveResult",
    "SelfModelSnapshot", "ResolvingWorldFeed", "EntityLinker",
]
