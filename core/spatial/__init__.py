"""
core/spatial/ — FRIDAY V3 (M16) Spatial Cognition.

Transforms FRIDAY from "I see objects" into "I understand the environment": object
permanence, location, relationships, movement, room structure, user position, and change.
It maintains a persistent Scene Graph (relationships, not pixels), tracks persistent
object identity, infers spatial relationships, models rooms, localizes the user, remembers
meaningful spatial events, and answers spatial queries.

Everything flows through the M16 service layer (dependency injection) — the spatial
engine never imports another subsystem's internals; it consumes source-agnostic
`SpatialObservation`s and communicates via services + the Runtime event bus.

Side-effect-free to import: no DB opens, no camera, no threads until constructed/started.
"""

from __future__ import annotations

from .config import SpatialConfig
from .engine import SpatialEngine
from .events import SpatialEvent
from .interfaces import SpatialObservation
from .scene_graph import SceneGraph, SceneNode
from .service import SpatialService, attach_to_container, get_spatial_service

__all__ = [
    "SpatialService", "get_spatial_service", "attach_to_container",
    "SpatialEngine", "SpatialConfig", "SpatialObservation", "SpatialEvent",
    "SceneGraph", "SceneNode",
]
