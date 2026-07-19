"""
Human-in-the-loop: approve a paused autonomous goal by voice (M59.2).

Closes the debt the M59 audit named: an autonomous goal that needs an
above-SAFE step pauses (BLOCKED, "awaiting your approval") — but there was no
way to approve it. Now a two-step voice confirm (M29 style) grants that step
ONE execution and resumes the goal.

The security invariants pinned here (nothing weakened vs M47):
· without a grant, above-SAFE still refuses (never touches the executor)
· a grant is one-shot and skill-specific — it can't authorize a second run
  or a different skill
· the grant satisfies ONLY the human-approval step; the full M47 pipeline
  (policy → clearance → sandbox → audit) still runs, so an ADMIN_ONLY step the
  owner's role can't clear STILL fails even when granted
· only USER_APPROVAL-tier goals are voice-approvable; admin/system are refused
"""

from __future__ import annotations

from types import SimpleNamespace

from core.executive.agentic import AgenticWorkflow, SafeAutonomyGate
from core.skills.executor import SkillExecutor
from core.skills.permissions import Permission, RiskLevel
from core.skills.registry import SkillRegistry
from core.skills.results import Result
from core.skills.skill import Skill


# ── a controlled skill so the REAL executor runs with no side effects ─────────

class _TypeSkill(Skill):
    name = "test.type"
    description = "a harmless USER_APPROVAL skill for tests"
    permission = Permission.USER_APPROVAL
    risk_level = RiskLevel.MEDIUM
    category = ("test", "act")

    def __init__(self):
        self.ran = []

    def validate(self, args):
        pass

    def run(self, context, **kwargs):
        self.ran.append(kwargs)
        return {"typed": kwargs.get("text", "")}


class _AdminSkill(_TypeSkill):
    name = "test.admin"
    permission = Permission.ADMIN_ONLY
    risk_level = RiskLevel.HIGH


def _real_gate():
    reg = SkillRegistry()
    typ, adm = _TypeSkill(), _AdminSkill()
    reg.register(typ)
    reg.register(adm)
    ex = SkillExecutor(registry=reg, default_timeout=5.0)
    return SafeAutonomyGate(ex), typ, adm


# ── the gate: grants are one-shot, specific, and pipeline-preserving ──────────

def test_above_safe_refuses_without_a_grant():
    gate, typ, _ = _real_gate()
    r = gate.execute("test.type", {"text": "hi"})
    assert not r.success and r.error == "needs_approval"
    assert typ.ran == []                        # never reached the executor


def test_granted_step_runs_through_the_full_pipeline():
    gate, typ, _ = _real_gate()
    gate.grant_once("test.type", {"text": "hi"})
    r = gate.execute("test.type", {"text": "hi"})
    assert r.success and r.data == {"typed": "hi"}
    assert typ.ran == [{"text": "hi"}]          # the real skill actually ran


def test_grant_is_one_shot():
    gate, typ, _ = _real_gate()
    gate.grant_once("test.type", {"text": "hi"})
    assert gate.execute("test.type", {"text": "hi"}).success
    second = gate.execute("test.type", {"text": "hi"})
    assert not second.success and second.error == "needs_approval"
    assert len(typ.ran) == 1                     # exactly once


def test_grant_does_not_leak_to_a_different_skill():
    gate, typ, adm = _real_gate()
    gate.grant_once("test.type", {})
    r = gate.execute("test.admin", {})           # different skill
    assert not r.success and r.error == "needs_approval"
    assert adm.ran == []


def test_clearance_still_blocks_admin_even_when_granted():
    # THE security invariant: a grant satisfies human-approval only; the USER
    # role still can't clear ADMIN_ONLY, so the M47 pipeline refuses it
    gate, _, adm = _real_gate()
    gate.grant_once("test.admin", {})
    r = gate.execute("test.admin", {})
    assert not r.success                         # PermissionDenied from clearance
    assert adm.ran == []
    assert "needs_approval" not in (r.error or "")   # refused deeper than the gate


def test_the_auto_decider_is_restored_after_a_granted_run():
    gate, _, _ = _real_gate()
    appr = gate._executor._approvals
    before = appr._auto
    gate.grant_once("test.type", {})
    gate.execute("test.type", {})
    assert appr._auto is before                  # one-shot decider fully cleaned up


# ── the workflow: list / approve / reject paused goals ────────────────────────

class _Goal:
    def __init__(self, gid, title, skill, perm_name, args=None):
        self.goal_id = gid
        self.title = title
        self.status = SimpleNamespace(value="blocked")
        self.metadata = {"skill": skill, "args": args or {}}


class _Goals:
    def __init__(self, goals):
        self._g = {x.goal_id: x for x in goals}
        self.resumed = []
        self.ticks = 0
        self.failed = []

    def list_goals(self, status=None):
        return list(self._g.values())

    def get_goal(self, gid):
        return self._g.get(gid)

    def resume_goal(self, gid):
        self.resumed.append(gid)

    def tick(self):
        self.ticks += 1
        return {}

    def fail_goal(self, gid, reason=""):
        self.failed.append(gid)

    def reflect(self, gid):
        pass


def _workflow(goals):
    gate, _, _ = _real_gate()
    wf = AgenticWorkflow.__new__(AgenticWorkflow)   # skip ExecutiveBrain build
    wf.goals = goals
    wf.gate = gate
    import threading
    wf._lock = threading.Lock()
    wf.approved_resumes = 0
    wf.rejected = 0
    wf.failed = 0
    return wf


def test_list_paused_reports_above_safe_blocks_with_their_skill():
    goals = _Goals([
        _Goal("g1", "type the report", "test.type", "USER_APPROVAL"),
        _Goal("g2", "read something", "memory.search", "SAFE"),   # not an approval pause
    ])
    wf = _workflow(goals)
    paused = wf.list_paused()
    assert [p["goal_id"] for p in paused] == ["g1"]
    assert paused[0]["skill"] == "test.type"


def test_approve_paused_grants_and_resumes():
    goals = _Goals([_Goal("g1", "type the report", "test.type", "USER_APPROVAL",
                          args={"text": "hi"})])
    wf = _workflow(goals)
    out = wf.approve_paused("g1")
    assert out == {"skill": "test.type", "title": "type the report"}
    assert goals.resumed == ["g1"] and goals.ticks == 1     # resumed + activated
    assert wf.gate._grants.get("test.type") == {"text": "hi"}   # one-shot grant set


def test_approve_paused_refuses_admin_tier():
    goals = _Goals([_Goal("g1", "wipe disk", "test.admin", "ADMIN_ONLY")])
    wf = _workflow(goals)
    assert wf.approve_paused("g1") is None       # never voice-approvable
    assert goals.resumed == []


def test_reject_paused_fails_the_goal():
    goals = _Goals([_Goal("g1", "type the report", "test.type", "USER_APPROVAL")])
    wf = _workflow(goals)
    assert wf.reject_paused("g1") is True
    assert goals.failed == ["g1"]


# ── the voice flow: two-step confirm, M29 style ───────────────────────────────

from core.launcher.conversation import ConversationBridge, _SpeechOutput


class _FakeAgentic:
    def __init__(self, paused):
        self._paused = list(paused)
        self.approved = []
        self.rejected = []

    def list_paused(self):
        return list(self._paused)

    def approve_paused(self, gid):
        for p in self._paused:
            if p["goal_id"] == gid:
                self.approved.append(gid)
                return {"skill": p["skill"], "title": p["title"]}
        return None

    def reject_paused(self, gid):
        self.rejected.append(gid)
        return True


class _Log:
    def __init__(self):
        self.rows = []

    def log(self, **row):
        self.rows.append(row)
        return len(self.rows)


class _IOS:
    def think(self, prompt, context=None, **kw):
        return SimpleNamespace(task="general", strategy="ios", ok=True,
                               confidence=0.7, answer="essay", models_used=[],
                               structured={}, trace_id="t", context_used={})


def _bridge(agentic):
    return ConversationBridge(
        _IOS(), decision_log=_Log(), agentic=agentic,
        speech=_SpeechOutput(synthesizer=lambda t: None))


_PAUSED = [{"goal_id": "g1", "title": "type the report", "skill": "input.type_text",
            "permission": "USER_APPROVAL", "args": {"text": "hi"}}]


def test_voice_lists_paused_goals():
    bridge = _bridge(_FakeAgentic(_PAUSED))
    r = bridge.think("any goals waiting for approval?")
    assert "type the report" in r.answer and "input.type_text" in r.answer


def test_voice_approval_is_two_step_confirm():
    ag = _FakeAgentic(_PAUSED)
    bridge = _bridge(ag)
    r1 = bridge.think("approve the paused goal")
    assert "confirm" in r1.answer.lower() and ag.approved == []   # not yet
    r2 = bridge.think("confirm")
    assert ag.approved == ["g1"]                 # now authorized
    assert "input.type_text" in r2.answer


def test_a_stray_phrase_does_not_confirm_an_approval():
    ag = _FakeAgentic(_PAUSED)
    bridge = _bridge(ag)
    bridge.think("approve the paused goal")      # arms the confirm
    bridge.think("what's the weather")           # NOT a confirm
    assert ag.approved == []                     # single-shot pending was dropped
    bridge.think("confirm")                      # too late — nothing pending
    assert ag.approved == []


def test_voice_can_reject_a_paused_goal():
    ag = _FakeAgentic(_PAUSED)
    bridge = _bridge(ag)
    r = bridge.think("reject the paused goal")
    assert ag.rejected == ["g1"] and "type the report" in r.answer


def test_nothing_paused_is_reported_honestly():
    bridge = _bridge(_FakeAgentic([]))
    r = bridge.think("any goals waiting for approval?")
    assert "nothing" in r.answer.lower()
