"""
tests/test_exec_planner.py — FRIDAY 4.0 M5
Executive Planner: objective scaffolding, explicit-step plans, goal-derived plans,
dependency-aware readiness, recursive expansion, and PlanResult.

(Named test_exec_planner to avoid colliding with M4's tests/test_planner.py, which
covers the distinct goals.Planner — both are preserved.)
"""

import pytest

from core.executive import (
    ExecutivePlanner, Plan, PlanResult, PlanStep, PlanStepStatus,
)
from core.goals import new_goal, GoalStatus


def test_build_plan_scaffold():
    plan = ExecutivePlanner().build_plan("clean the vault")
    assert len(plan.steps) == 3
    # linear: each step depends on the previous
    assert plan.steps[0].depends_on == []
    assert plan.steps[1].depends_on == [plan.steps[0].step_id]


def test_build_plan_with_explicit_steps():
    specs = [
        {"step_id": "s1", "action": "fetch", "skill": "memory.search"},
        {"step_id": "s2", "action": "store", "depends_on": ["s1"]},
    ]
    plan = ExecutivePlanner().build_plan("pipeline", steps=specs)
    assert plan.step("s2").depends_on == ["s1"]
    assert plan.step("s1").skill == "memory.search"


def test_ready_steps_respects_dependencies():
    plan = ExecutivePlanner().build_plan("x", steps=[
        {"step_id": "a", "action": "a"},
        {"step_id": "b", "action": "b", "depends_on": ["a"]},
    ])
    ready = plan.ready_steps()
    assert [s.step_id for s in ready] == ["a"]
    plan.step("a").status = PlanStepStatus.DONE
    assert [s.step_id for s in plan.ready_steps()] == ["b"]


def test_from_goals_maps_dependencies():
    g0 = new_goal("Research", priority=1)
    g1 = new_goal("Build", priority=2, dependencies=[g0.goal_id])
    plan = ExecutivePlanner().from_goals([g0, g1], objective="build app")
    assert plan.step(g0.goal_id).action == "Research"
    assert plan.step(g1.goal_id).depends_on == [g0.goal_id]
    assert plan.step(g0.goal_id).goal_id == g0.goal_id


def test_from_goals_carries_terminal_status():
    g = new_goal("Done thing")
    g.status = GoalStatus.COMPLETED
    plan = ExecutivePlanner().from_goals([g])
    assert plan.step(g.goal_id).status == PlanStepStatus.DONE


def test_blocked_steps_detected():
    plan = ExecutivePlanner().build_plan("x", steps=[
        {"step_id": "a", "action": "a"},
        {"step_id": "b", "action": "b", "depends_on": ["a"]},
    ])
    plan.step("a").status = PlanStepStatus.FAILED
    assert [s.step_id for s in plan.blocked_steps()] == ["b"]


def test_is_complete():
    plan = ExecutivePlanner().build_plan("x", steps=[{"step_id": "a", "action": "a"}])
    assert not plan.is_complete()
    plan.step("a").status = PlanStepStatus.DONE
    assert plan.is_complete()


def test_expand_step_creates_subplan():
    planner = ExecutivePlanner()
    plan = planner.build_plan("big", steps=[{"step_id": "a", "action": "do a"}])
    sub = planner.expand_step(plan, "a", [{"action": "a.1"}, {"action": "a.2"}])
    assert sub.parent_plan == plan.plan_id
    assert plan.step("a").sub_plan == sub.plan_id
    assert len(sub.steps) == 2


def test_plan_dict_and_result():
    plan = ExecutivePlanner().build_plan("x")
    d = plan.to_dict()
    assert d["objective"] == "x" and len(d["steps"]) == 3
    res = PlanResult(plan_id=plan.plan_id, success=True, steps_total=3)
    assert res.to_dict()["success"] is True
