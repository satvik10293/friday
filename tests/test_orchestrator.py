"""
tests/test_orchestrator.py — FRIDAY 4.0 M5
Orchestrator: decide (execute/wait/blocked split), synthetic step execution,
real skill execution through the M3 SkillExecutor, full plan execution honoring
dependencies, and failure handling.
"""

import pytest

from core.executive import ExecutivePlanner, Orchestrator, PlanStepStatus
from core.skills import SkillRegistry
from core.skills.permissions import Permission, RiskLevel
from core.skills.skill import Skill


class EchoSkill(Skill):
    name = "test.echo"
    description = "echo args back"
    permission = Permission.SAFE
    risk_level = RiskLevel.LOW

    def run(self, context, **kwargs):
        return {"echo": kwargs}


class BoomSkill(Skill):
    name = "test.boom"
    description = "always raises"
    permission = Permission.SAFE
    risk_level = RiskLevel.LOW

    def run(self, context, **kwargs):
        raise RuntimeError("boom")


# ── decide ───────────────────────────────────────────────────────────────────
def test_decide_splits_ready_and_waiting():
    plan = ExecutivePlanner().build_plan("x", steps=[
        {"step_id": "a", "action": "a"},
        {"step_id": "b", "action": "b", "depends_on": ["a"]},
    ])
    d = Orchestrator().decide(plan)
    assert d["execute"] == ["a"] and d["wait"] == ["b"] and d["blocked"] == []


def test_decide_reports_blocked():
    plan = ExecutivePlanner().build_plan("x", steps=[
        {"step_id": "a", "action": "a"},
        {"step_id": "b", "action": "b", "depends_on": ["a"]},
    ])
    plan.step("a").status = PlanStepStatus.FAILED
    assert Orchestrator().decide(plan)["blocked"] == ["b"]


# ── synthetic execution (no skill) ───────────────────────────────────────────
def test_execute_step_synthetic_completes():
    plan = ExecutivePlanner().build_plan("think", steps=[{"step_id": "a", "action": "ponder"}])
    step = Orchestrator().execute_step(plan.step("a"))
    assert step.status == PlanStepStatus.DONE and step.result["synthetic"] is True


def test_execute_plan_runs_all_synthetic_steps():
    plan = ExecutivePlanner().build_plan("x")        # 3-step scaffold
    result = Orchestrator().execute_plan(plan)
    assert result.success and len(result.completed) == 3


def test_execute_plan_blocks_dependents_on_failure():
    plan = ExecutivePlanner().build_plan("x", steps=[
        {"step_id": "a", "action": "a"},
        {"step_id": "b", "action": "b", "depends_on": ["a"]},
    ])
    # force step a to fail by giving it a failing skill
    plan.step("a").skill = "test.boom"
    reg = SkillRegistry(); reg.register(BoomSkill())
    from core.skills import SkillExecutor
    ex = SkillExecutor(registry=reg)
    result = Orchestrator(skill_executor=ex).execute_plan(plan)
    assert "a" in result.failed
    assert "b" in result.skipped and not result.success


# ── real skill execution through SkillExecutor ───────────────────────────────
def test_execute_step_routes_through_executor(make_executor):
    reg = SkillRegistry(); reg.register(EchoSkill())
    ex, _ = make_executor(registry=reg)
    orch = Orchestrator(skill_executor=ex)
    plan = ExecutivePlanner().build_plan("p", steps=[
        {"step_id": "a", "action": "echo", "skill": "test.echo", "args": {"v": 1}},
    ])
    step = orch.execute_step(plan.step("a"))
    assert step.status == PlanStepStatus.DONE
    assert step.result["success"] is True
    assert step.result["data"] == {"echo": {"v": 1}}


def test_execute_plan_tracks_metrics(make_executor):
    reg = SkillRegistry(); reg.register(EchoSkill())
    ex, _ = make_executor(registry=reg)
    orch = Orchestrator(skill_executor=ex)
    plan = ExecutivePlanner().build_plan("p", steps=[
        {"step_id": "a", "action": "echo", "skill": "test.echo"},
    ])
    orch.execute_plan(plan)
    assert orch.metrics()["steps_executed"] == 1
    assert orch.health()["executor"] is True
