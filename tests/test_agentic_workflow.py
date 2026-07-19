"""
The agentic workflow (M59): the audited missing wire between ACTIVE goals and
actual work — and nothing more.

Pins the audit-driven contract:
· ACTIVE goals are consumed (next_actions → decide → plan → execute)
· SAFE-only autonomy: an above-SAFE skill NEVER reaches the executor (whose
  approval path blocks); the goal pauses (BLOCKED, awaiting approval)
· results feed BACK into goal state (complete/fail/block) so a goal is never
  re-executed forever — the flaw that kept the raw CognitiveLoop unwired
· reflection (learn-back) runs on completion AND failure
· the boot stage schedules goals.tick + agentic.cycle on the runtime
"""

from __future__ import annotations

from types import SimpleNamespace

from core.executive.agentic import (AgenticWorkflow, SafeAutonomyGate,
                                    build_agentic_workflow)
from core.skills.permissions import Permission
from core.skills.results import Result


# ── stubs ─────────────────────────────────────────────────────────────────────

class _Goal:
    def __init__(self, gid, title, skill=None, args=None):
        self.goal_id = gid
        self.title = title
        self.description = title
        self.status = SimpleNamespace(value="active")
        self.dependencies = []
        self.metadata = ({"skill": skill, "args": args or {}} if skill else {})

    def to_dict(self):
        return {"goal_id": self.goal_id, "title": self.title}


class _Goals:
    """Minimal GoalService double with real feedback recording."""

    def __init__(self, goals):
        self._goals = {g.goal_id: g for g in goals}
        self.completed, self.failed, self.blocked, self.reflected = [], [], [], []

    def next_actions(self, limit=5):
        active = [g for g in self._goals.values()
                  if g.goal_id not in self.completed
                  and g.goal_id not in self.failed
                  and g.goal_id not in self.blocked]
        return [g.to_dict() for g in active[:limit]]

    def get_goal(self, gid):
        return self._goals.get(gid)

    def list_goals(self, status=None):
        return list(self._goals.values())

    def complete_goal(self, gid, note=""):
        self.completed.append(gid)

    def fail_goal(self, gid, reason=""):
        self.failed.append(gid)

    def block_goal(self, gid, reason=""):
        self.blocked.append((gid, reason))

    def reflect(self, gid):
        self.reflected.append(gid)


class _Skill:
    def __init__(self, permission, risk=0):
        self.permission = permission
        self.risk_level = SimpleNamespace(name="LOW", value=risk)

    def __lt__(self, other):  # pragma: no cover - risk compare unused here
        return False


class _Registry:
    def __init__(self, skills):
        self._skills = skills

    def get(self, name):
        return self._skills[name]


class _Executor:
    """Records calls; blocking approval path must NEVER be reached for
    above-SAFE skills in autonomous mode."""

    def __init__(self, skills):
        self.registry = _Registry(skills)
        self.calls = []

    def execute(self, name, args=None, context=None):
        self.calls.append(name)
        return Result(success=True, data="done")


# ── the SAFE-only gate ────────────────────────────────────────────────────────

def test_gate_runs_safe_skills_through_the_executor():
    ex = _Executor({"net.ip": _Skill(Permission.SAFE)})
    gate = SafeAutonomyGate(ex)
    r = gate.execute("net.ip")
    assert r.success and ex.calls == ["net.ip"]


def test_gate_refuses_above_safe_without_touching_the_executor():
    ex = _Executor({"shell.run": _Skill(Permission.ADMIN_ONLY)})
    gate = SafeAutonomyGate(ex)
    r = gate.execute("shell.run")
    assert not r.success and r.error == "needs_approval"
    assert ex.calls == []                      # the blocking path never reached
    assert r.metadata["permission"] == "ADMIN_ONLY"


# ── the workflow: goals actually get worked ───────────────────────────────────

def _workflow(goals, executor=None):
    return AgenticWorkflow(goals, executor, goals_per_cycle=5)


def test_thinking_goal_completes_and_reflects():
    goals = _Goals([_Goal("g1", "review the notebook coverage")])
    wf = _workflow(goals)                       # no skills at all → synthetic
    summary = wf.cycle()
    assert summary["completed"] == ["g1"]
    assert goals.completed == ["g1"]
    assert goals.reflected == ["g1"]            # learn-back ran


def test_safe_skill_goal_executes_the_skill_and_completes():
    ex = _Executor({"system.screenshot": _Skill(Permission.SAFE)})
    goals = _Goals([_Goal("g1", "capture the screen",
                          skill="system.screenshot")])
    wf = _workflow(goals, ex)
    wf.cycle()
    assert ex.calls == ["system.screenshot"]    # real skill, real pipeline
    assert goals.completed == ["g1"]


def test_above_safe_goal_pauses_awaiting_approval():
    ex = _Executor({"input.type": _Skill(Permission.USER_APPROVAL)})
    goals = _Goals([_Goal("g1", "type the report", skill="input.type")])
    wf = _workflow(goals, ex)
    summary = wf.cycle()
    assert summary["paused"] == ["g1"]
    assert ex.calls == []                       # never reached the executor
    gid, reason = goals.blocked[0]
    assert gid == "g1" and "approval" in reason and "input.type" in reason
    assert goals.completed == []                # not falsely completed


def test_worked_goals_are_not_reworked_next_cycle():
    goals = _Goals([_Goal("g1", "a thinking goal")])
    wf = _workflow(goals)
    wf.cycle()
    second = wf.cycle()
    assert second["worked"] == []               # feedback prevented re-execution


def test_cycle_is_bounded_and_never_raises():
    goals = _Goals([_Goal(f"g{i}", f"goal {i}") for i in range(10)])
    wf = AgenticWorkflow(goals, None, goals_per_cycle=2)
    summary = wf.cycle()
    assert len(summary["worked"]) == 2          # bounded per cycle

    class _Broken:
        def next_actions(self, limit=5):
            raise RuntimeError("store down")
    wf2 = AgenticWorkflow(_Broken(), None)
    assert isinstance(wf2.cycle(), dict)        # contained, no raise


def test_status_reports_the_loop_honestly():
    goals = _Goals([_Goal("g1", "one goal")])
    wf = _workflow(goals)
    wf.cycle()
    s = wf.status()
    assert s["cycles"] == 1 and s["completed"] == 1
    assert s["policy"] == "safe_only"


def test_factory_is_none_without_goals():
    assert build_agentic_workflow(goals=None) is None


# ── boot wiring: the stage schedules both loops ───────────────────────────────

def test_boot_schedules_goal_tick_and_agentic_cycle():
    from core.launcher.startup import StartupSequence

    class _FakeRuntime:
        def __init__(self):
            self.jobs = []
            self.health = {}

        def schedule(self, name, fn, every, **kw):
            self.jobs.append(name)

        def register_health(self, name, provider):
            self.health[name] = provider

        def emit(self, *a, **kw):
            pass

    seq = StartupSequence(headless=True, start_runtime=True)
    rt = _FakeRuntime()
    seq.components["runtime"] = rt
    seq.components["kernel"] = None
    seq.components["intelligence"] = None
    from core.goals.service import get_goal_service
    seq.components["goals"] = get_goal_service()
    seq._stage_mind()
    assert "agentic.cycle" in rt.jobs           # the workflow is scheduled
    assert "goals.tick" in rt.jobs              # goal activation is scheduled
