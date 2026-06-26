"""
core/cognitive_space/ — FRIDAY 4.0 (M11) Interactive Cognitive Space.

The navigable 3D universe of FRIDAY's mind, integrated with Mission Control. Six
zoom levels — Universe → Domain → Team → Agent → Task → Thought Chain — let the
user inspect any layer; a global search focuses the camera on anything (knowledge,
goals, projects, agents, tasks, models, simulations, events).

Visual language: knowledge = stars, goals = attractors, agents = living entities,
tasks = energy streams, decisions = convergence events, simulations = separate
universes. Designed for LOD + spatial partitioning so the data layer scales toward
100k nodes without redesign.

Side-effect-free to import.
"""

from __future__ import annotations

from .models import (SpaceEdge, SpaceNode, VISUAL_LANGUAGE, VisualKind, ZoomLevel)
from .search import GlobalSearch
from .service import CognitiveSpace, get_cognitive_space
from .zoom import LEVEL_BUDGETS, partition, place

__all__ = ["CognitiveSpace", "get_cognitive_space", "GlobalSearch", "ZoomLevel",
           "SpaceNode", "SpaceEdge", "VisualKind", "VISUAL_LANGUAGE",
           "LEVEL_BUDGETS", "partition", "place"]
