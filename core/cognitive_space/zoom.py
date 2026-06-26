"""
core/cognitive_space/zoom.py — FRIDAY 4.0 (M11)
Level-of-detail (LOD) + spatial partitioning for the cognitive universe (Parts 10
& 12). Each zoom level has a node budget so a frame never ships more than it can
render at 60 FPS; `place` lays nodes out deterministically; `partition` buckets
them into a spatial grid for frustum culling. These let the data layer scale toward
100k nodes without redesign — deeper zoom shows more of less.
"""

from __future__ import annotations

import math
from typing import Iterable

from .models import ZoomLevel

# Per-level node budget: the universe summarises (few nodes); deeper levels reveal
# more detail of a *focused* subtree (so totals stay bounded).
LEVEL_BUDGETS: dict[int, int] = {
    ZoomLevel.UNIVERSE.value: 64,
    ZoomLevel.DOMAIN.value: 256,
    ZoomLevel.TEAM.value: 512,
    ZoomLevel.AGENT.value: 1024,
    ZoomLevel.TASK.value: 2048,
    ZoomLevel.THOUGHT_CHAIN.value: 256,
}


def budget_for(level: int) -> int:
    return LEVEL_BUDGETS.get(int(level), 256)


def place(index: int, count: int, radius: float = 100.0) -> tuple:
    """Deterministic 3D layout on a Fibonacci sphere — stable positions for
    camera-focus and partitioning."""
    if count <= 1:
        return (0.0, 0.0, 0.0)
    y = 1 - (index / (count - 1)) * 2          # 1 .. -1
    r = math.sqrt(max(0.0, 1 - y * y))
    theta = index * 2.399963229728653          # golden angle
    return (round(math.cos(theta) * r * radius, 3),
            round(y * radius, 3),
            round(math.sin(theta) * r * radius, 3))


def apply_budget(nodes: list, level: int) -> list:
    """Trim to the level's LOD budget (keep the first N — callers sort by salience
    before calling)."""
    return nodes[: budget_for(level)]


def partition(nodes: Iterable, cells: int = 8, extent: float = 100.0) -> dict:
    """Bucket nodes into a `cells`³ spatial grid → {(cx,cy,cz): [node_ids]} for
    culling/streaming. Accepts SpaceNode or dicts with a `position`."""
    grid: dict = {}
    step = (2 * extent) / max(1, cells)
    for n in nodes:
        pos = n.position if hasattr(n, "position") else n.get("position", (0, 0, 0))
        nid = n.id if hasattr(n, "id") else n.get("id")
        cx = min(cells - 1, max(0, int((pos[0] + extent) / step)))
        cy = min(cells - 1, max(0, int((pos[1] + extent) / step)))
        cz = min(cells - 1, max(0, int((pos[2] + extent) / step)))
        grid.setdefault((cx, cy, cz), []).append(nid)
    return grid
