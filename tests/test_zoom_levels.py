"""M11 — Zoom levels, LOD budgets, spatial partitioning, scalability design."""

from core.cognitive_space.models import SpaceNode, ZoomLevel
from core.cognitive_space.zoom import (LEVEL_BUDGETS, apply_budget, budget_for,
                                       partition, place)


def test_six_zoom_levels():
    assert [z.value for z in ZoomLevel] == [1, 2, 3, 4, 5, 6]
    assert ZoomLevel.UNIVERSE.value == 1 and ZoomLevel.THOUGHT_CHAIN.value == 6


def test_every_level_has_budget():
    for z in ZoomLevel:
        assert LEVEL_BUDGETS[z.value] > 0


def test_universe_budget_smallest():
    # the universe summarises (fewest nodes); deeper levels reveal more detail
    assert budget_for(ZoomLevel.UNIVERSE.value) < budget_for(ZoomLevel.TASK.value)


def test_apply_budget_trims():
    nodes = [SpaceNode(f"n{i}", "knowledge", str(i)) for i in range(5000)]
    trimmed = apply_budget(nodes, ZoomLevel.UNIVERSE.value)
    assert len(trimmed) == budget_for(ZoomLevel.UNIVERSE.value)


def test_place_is_deterministic():
    a = place(3, 100)
    b = place(3, 100)
    assert a == b                              # stable layout
    assert len(a) == 3


def test_place_spreads_nodes():
    positions = [place(i, 50) for i in range(50)]
    assert len(set(positions)) > 40            # not all stacked


def test_partition_buckets_nodes():
    nodes = []
    for i in range(200):
        n = SpaceNode(f"n{i}", "knowledge", str(i))
        n.position = place(i, 200)
        nodes.append(n)
    grid = partition(nodes, cells=8)
    assert len(grid) > 1                        # spread across multiple cells
    assert sum(len(v) for v in grid.values()) == 200   # every node placed once


def test_partition_accepts_dicts():
    grid = partition([{"id": "a", "position": (0, 0, 0)},
                      {"id": "b", "position": (90, 90, 90)}], cells=8)
    assert sum(len(v) for v in grid.values()) == 2


def test_scales_toward_100k_without_redesign():
    # 100k nodes partition into a bounded grid; per-level budget caps what renders
    nodes = []
    for i in range(100_000):
        n = SpaceNode(f"n{i}", "knowledge", "")
        n.position = place(i % 1000, 1000)
        nodes.append(n)
    grid = partition(nodes, cells=8)
    assert sum(len(v) for v in grid.values()) == 100_000
    assert len(apply_budget(nodes, ZoomLevel.TASK.value)) == budget_for(ZoomLevel.TASK.value)
