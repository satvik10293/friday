"""
core/context — FRIDAY 4.0 (M5) Context Engine.

Assembles the best reasoning context for a query by combining relevant memories
(M2), active goals (M4), reflections, attention focus (M5), and world state (M5)
into a single inspectable ContextPackage. Import is side-effect free.

    from core.context import ContextBuilder
    builder = ContextBuilder(memory_service=mem, goal_service=goals,
                             attention=att, world_model=world)
    ctx = builder.build("what should I work on?")
"""

from .context_package import ContextPackage
from .context_builder import ContextBuilder

__all__ = ["ContextPackage", "ContextBuilder"]
