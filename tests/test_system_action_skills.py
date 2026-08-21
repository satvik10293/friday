"""
tests/test_system_action_skills.py — M34 Executive Supremacy.

The FridayAction catalog is governed: 37 tiered skills that execute only
through the SkillExecutor pipeline. Pins: tier counts, free tier-1 execution,
human-gated tier-3, admin-gated tier-3+, shell denied by default policy,
validation, delegation to the real FridayAction, and one audit row per
execution (the "every side-effecting action appears in audit.db" criterion).
"""

import sqlite3

import pytest

import core.skills.builtin.system_actions as sa
from core.security.approvals import ApprovalManager
from core.security.roles import Role
from core.skills.builtin import ALL_ACTION_SPECS, register_builtins
from core.skills.context import SkillContext
from core.skills.executor import SkillExecutor
from core.skills.permissions import Permission
from core.skills.registry import SkillRegistry


class FakeAction:
    """Stands in for FridayAction so tests never touch the real machine."""

    def __init__(self):
        self.calls = []

    def __getattr__(self, name):
        def _method(**kwargs):
            self.calls.append((name, kwargs))
            return f"{name} ok"
        return _method


class SecuritySpy:
    def __init__(self):
        self.events = []

    def record(self, **kw):
        self.events.append(kw)


@pytest.fixture
def fake_action(monkeypatch):
    fake = FakeAction()
    monkeypatch.setattr(sa, "_action", fake)
    return fake


@pytest.fixture
def harness(tmp_path, fake_action):
    """Registry + executor with a scratch audit DB and controllable approvals."""
    from core.skills.audit import AuditLog

    registry = SkillRegistry()
    register_builtins(registry)
    audit_path = tmp_path / "audit.db"
    state = {"decide": True}

    executor = SkillExecutor(
        registry=registry,
        audit=AuditLog(audit_path),
        security_log=SecuritySpy(),
        approvals=ApprovalManager(auto_decider=lambda req: state["decide"]),
    )

    def audit_rows():
        conn = sqlite3.connect(audit_path)
        try:
            return conn.execute(
                "SELECT skill_name, success, approved FROM audit").fetchall()
        finally:
            conn.close()

    return executor, fake_action, state, audit_rows


# ── catalog shape ──────────────────────────────────────────────────────────────

def test_all_37_actions_registered():
    registry = SkillRegistry()
    register_builtins(registry)
    action_names = {s.skill_name for s in ALL_ACTION_SPECS}
    assert len(ALL_ACTION_SPECS) == 38          # + media.play_music (real playback)
    assert action_names <= set(registry.names())


def test_tier_distribution():
    by_permission = {}
    for spec in ALL_ACTION_SPECS:
        by_permission.setdefault(spec.permission, []).append(spec.skill_name)
    assert len(by_permission[Permission.SAFE]) == 29          # tiers 1 + 2
    assert len(by_permission[Permission.USER_APPROVAL]) == 4  # tier 3
    assert len(by_permission[Permission.ADMIN_ONLY]) == 5     # tier 3+


# ── execution through the pipeline ─────────────────────────────────────────────

def test_tier1_runs_without_approval(harness):
    executor, fake, _, _ = harness
    result = executor.execute("system.summary")
    assert result.success
    assert ("get_system_summary", {}) in fake.calls


def test_tier2_runs_and_delegates_args(harness):
    executor, fake, _, _ = harness
    result = executor.execute("audio.set_volume", {"level": 30})
    assert result.success
    assert ("set_volume", {"level": 30}) in fake.calls


def test_tier3_requires_approval_and_respects_rejection(harness):
    executor, fake, state, _ = harness

    state["decide"] = True
    assert executor.execute("input.type_text", {"text": "hi"}).success

    state["decide"] = False
    result = executor.execute("input.press_key", {"key": "enter"})
    assert not result.success
    assert result.error_type == "ApprovalRejected"
    assert all(name != "press_key" for name, _ in fake.calls), \
        "rejected skill still executed"


def test_admin_actions_denied_for_user_role(harness):
    executor, fake, _, _ = harness
    result = executor.execute("power.sleep")   # default role: USER
    assert not result.success
    assert result.error_type == "PermissionDenied"
    assert all(name != "sleep_pc" for name, _ in fake.calls)


def test_admin_actions_run_for_admin_with_approval(harness):
    executor, fake, _, _ = harness
    ctx = SkillContext.minimal()
    ctx.user_role = Role.ADMIN
    result = executor.execute("power.sleep", context=ctx)
    assert result.success
    assert ("sleep_pc", {}) in fake.calls


def test_shell_run_denied_by_default_policy_even_for_admin(harness):
    executor, fake, _, _ = harness
    ctx = SkillContext.minimal()
    ctx.user_role = Role.ADMIN
    result = executor.execute("shell.run", {"command": "echo hi"}, context=ctx)
    assert not result.success
    assert result.error_type == "PolicyViolation"
    assert all(name != "run_shell" for name, _ in fake.calls), \
        "policy-denied shell command still executed"


def test_validation_blocks_bad_args(harness):
    executor, fake, _, _ = harness
    result = executor.execute("files.search", {})   # query is required
    assert not result.success
    assert result.error_type == "ValidationError"
    assert fake.calls == []


# ── audit: every action leaves a record ────────────────────────────────────────

def test_every_execution_writes_one_audit_row(harness):
    executor, _, state, audit_rows = harness
    executor.execute("system.summary")                       # success
    executor.execute("audio.mute")                           # success
    state["decide"] = False
    executor.execute("input.click", {"x": 1, "y": 2})        # rejected
    executor.execute("power.restart")                        # permission denied

    rows = audit_rows()
    assert len(rows) == 4, "an execution escaped the audit log"
    outcomes = {name: success for name, success, _ in rows}
    assert outcomes["system.summary"] == 1
    assert outcomes["audio.mute"] == 1
    assert outcomes["input.click"] == 0
    assert outcomes["power.restart"] == 0


# ── simulation deliberation (M34: think before acting) ────────────────────────

def _make_step(skill, args=None, action=""):
    from core.executive.planner import PlanStep
    return PlanStep(step_id="s1", action=action or skill, skill=skill,
                    args=args or {})


def test_high_risk_step_is_deliberated_and_can_be_stopped(harness):
    from core.executive.orchestrator import Orchestrator

    executor, fake, _, _ = harness
    asked = []

    def deliberator(action, context=None, options=None):
        asked.append(context["skill"])
        return {"decision": "ask_user", "reason": "all plans exceed the risk threshold"}

    orch = Orchestrator(skill_executor=executor, deliberator=deliberator)
    step = orch.execute_step(_make_step("power.sleep"))

    assert asked == ["power.sleep"], "high-risk skill was not deliberated"
    assert step.status.value == "failed"
    assert step.result["deliberation"]["decision"] == "ask_user"
    assert all(name != "sleep_pc" for name, _ in fake.calls), \
        "simulation said ask_user but the action executed anyway"


def test_high_risk_step_executes_when_deliberation_approves(harness):
    from core.executive.orchestrator import Orchestrator
    from core.security.roles import Role

    executor, fake, _, _ = harness

    def deliberator(action, context=None, options=None):
        return {"decision": "execute", "chosen_plan": "direct", "risk_level": "high"}

    orch = Orchestrator(skill_executor=executor, deliberator=deliberator)
    ctx = SkillContext.minimal()
    ctx.user_role = Role.ADMIN
    step = orch.execute_step(_make_step("power.sleep"), context=ctx)

    assert step.status.value == "done"
    assert step.result["deliberation"]["decision"] == "execute"
    assert ("sleep_pc", {}) in fake.calls


def test_low_risk_steps_skip_deliberation(harness):
    from core.executive.orchestrator import Orchestrator

    executor, fake, _, _ = harness
    asked = []

    orch = Orchestrator(skill_executor=executor,
                        deliberator=lambda a, **k: asked.append(a))
    step = orch.execute_step(_make_step("system.summary"))

    assert step.status.value == "done"
    assert asked == [], "low-risk skill wasted a simulation pass"
    assert "deliberation" not in step.result


def test_failing_deliberator_never_blocks_execution(harness):
    from core.executive.orchestrator import Orchestrator
    from core.security.roles import Role

    executor, fake, _, _ = harness

    def broken(action, **kw):
        raise RuntimeError("simulation down")

    orch = Orchestrator(skill_executor=executor, deliberator=broken)
    ctx = SkillContext.minimal()
    ctx.user_role = Role.ADMIN
    step = orch.execute_step(_make_step("power.sleep"), context=ctx)

    assert step.status.value == "done", "advisory failure blocked execution"
    assert ("sleep_pc", {}) in fake.calls


# ── real delegation (no side effects: capability probe only) ───────────────────

def test_real_friday_action_capabilities_through_pipeline(tmp_path, monkeypatch):
    from core.skills.audit import AuditLog

    monkeypatch.setattr(sa, "_action", None)   # force the real FridayAction
    registry = SkillRegistry()
    register_builtins(registry)
    executor = SkillExecutor(registry=registry,
                             audit=AuditLog(tmp_path / "audit.db"),
                             security_log=SecuritySpy())
    result = executor.execute("system.capabilities")
    assert result.success
    assert isinstance(result.data, dict)
