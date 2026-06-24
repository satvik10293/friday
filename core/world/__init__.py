"""
core/world — FRIDAY 4.0 (M5) World Model.

A persistent internal model of reality: typed entities (user/project/runtime/
system) with mutable state and weighted relationships, plus snapshots and diffs
for change detection. Import is side-effect free.

    from core.world import WorldModel
    wm = WorldModel()
    wm.observe("project", "Friday", state={"phase": "M5"})
    before = wm.snapshot()
    wm.observe("project", "Friday", state={"phase": "M6"})
    wm.compare(before)        # -> {"added": [], "removed": [], "changed": {...}}
"""

from .entities import WorldEntity, WorldRelationship, new_entity
from .snapshots import WorldSnapshot, diff_snapshots, new_snapshot
from .world_model import WorldModel

__all__ = [
    "WorldEntity", "WorldRelationship", "new_entity",
    "WorldSnapshot", "diff_snapshots", "new_snapshot",
    "WorldModel",
]
