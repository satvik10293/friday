"""
tests/test_planner.py — FRIDAY 4.0 M4
Decomposition heuristics, goal-tree wiring, dependency resolution, custom
decomposer injection.
"""

import pytest

from core.goals import Planner, GoalTree, default_decompose, GoalStatus


def test_default_decompose_build_objective():
    specs = default_decompose("build a weather dashboard")
    assert len(specs) == 6
    titles = [s["title"] for s in specs]
    assert titles[0] == "Research APIs" and titles[-1] == "Deployment"
    # linear pipeline: each phase depends on the previous index
    assert specs[0]["depends_on"] == []
    assert specs[3]["depends_on"] == [2]


def test_default_decompose_generic_objective():
    specs = default_decompose("write a poem")
    assert len(specs) == 4
    assert [s["title"] for s in specs] == ["Research", "Plan", "Execute", "Review"]


def test_planner_builds_tree_with_resolved_deps():
    tree = Planner().plan("build a chat app", owner="satvik")
    assert isinstance(tree, GoalTree)
    assert tree.root.metadata["kind"] == "root"
    assert len(tree.children) == 6

    ids = {c.goal_id for c in tree.children}
    # every child points at the root as parent
    assert all(c.parent_goal == tree.root.goal_id for c in tree.children)
    # dependencies are real sibling goal_ids, not raw indices
    second = tree.children[1]
    assert second.dependencies == [tree.children[0].goal_id]
    assert all(dep in ids for c in tree.children for dep in c.dependencies)


def test_planner_first_child_has_no_dependencies():
    tree = Planner().plan("build a platform")
    assert tree.children[0].dependencies == []
    assert all(c.status == GoalStatus.PENDING for c in tree.all_goals())


def test_planner_accepts_custom_decomposer():
    def two_step(objective):
        return [
            {"title": "Step A", "depends_on": [], "priority": 1, "confidence": 0.9},
            {"title": "Step B", "depends_on": [0], "priority": 2, "confidence": 0.8},
        ]

    tree = Planner(decomposer=two_step).plan("anything")
    assert [c.title for c in tree.children] == ["Step A", "Step B"]
    assert tree.children[1].dependencies == [tree.children[0].goal_id]
    assert tree.children[0].confidence == 0.9


def test_goal_tree_all_goals_includes_root():
    tree = Planner().plan("build an app")
    everything = tree.all_goals()
    assert everything[0] is tree.root
    assert len(everything) == 7
