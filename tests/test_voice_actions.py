"""
M47 — her body: action-shaped voice commands run governed skills.

"take a screenshot", "what's my IP", "system status", "set volume to 40" route
through the SkillExecutor (which enforces policy → clearance → approval →
sandbox → audit). VOICE POLICY: only SAFE-permission skills run hands-free;
anything needing approval or admin (shell.run, power.*, input.*) is never
voice-triggerable. A skill answer never enters the cloud conversation window.
"""

from __future__ import annotations

from core.launcher.conversation import ConversationBridge, _SpeechOutput
from core.skills.permissions import Permission
from core.skills.results import FailureResult, SuccessResult
from tests.test_cloud_reasoner import _FakeReasoner
from tests.test_teacher import _LocalIOS, _Log


class _FakeSkill:
    def __init__(self, permission=Permission.SAFE):
        self.permission = permission


class _FakeRegistry:
    def __init__(self, skills):
        self._skills = skills

    def get(self, name):
        return self._skills[name]


class _FakeExecutor:
    """Records executions; returns canned Results — no real system actions."""

    def __init__(self, skills=None, results=None):
        self._registry = _FakeRegistry(skills or {})
        self._results = results or {}
        self.calls = []

    def execute(self, name, args=None):
        self.calls.append((name, dict(args or {})))
        return self._results.get(name, SuccessResult(data="ok"))


_SAFE = {
    "system.screenshot": _FakeSkill(), "net.ip": _FakeSkill(),
    "net.check_internet": _FakeSkill(), "system.summary": _FakeSkill(),
    "audio.set_volume": _FakeSkill(), "audio.mute": _FakeSkill(),
}


def _bridge(executor, ios=None, reasoner=None):
    return ConversationBridge(
        ios if ios is not None else _LocalIOS(confidence=0.9),
        decision_log=_Log(), skills=executor, reasoner=reasoner,
        speech=_SpeechOutput(synthesizer=lambda t: None), speak_answers=False)


def test_safe_action_executes_and_speaks_result():
    ex = _FakeExecutor(_SAFE, {"net.ip": SuccessResult(data="10.0.0.5")})
    ios, reasoner = _LocalIOS(confidence=0.9), _FakeReasoner()
    bridge = _bridge(ex, ios=ios, reasoner=reasoner)
    r = bridge.think("what is my ip address")
    assert r.strategy == "skill:net.ip"
    assert "10.0.0.5" in r.answer
    assert ex.calls == [("net.ip", {})]
    assert ios.thinks == 0 and reasoner.asked == []   # never touched reasoning
    assert bridge.status()["skill_turns"] == 1


def test_volume_command_extracts_the_level():
    ex = _FakeExecutor(_SAFE)
    bridge = _bridge(ex)
    bridge.think("set the volume to 40")
    assert ex.calls == [("audio.set_volume", {"level": 40})]


def test_check_internet_renders_boolean():
    ex = _FakeExecutor(_SAFE, {"net.check_internet": SuccessResult(data=False)})
    bridge = _bridge(ex)
    r = bridge.think("am i online")
    assert "offline" in r.answer.lower()


def test_approval_tier_skill_is_refused_from_voice():
    # a route that resolves to a non-SAFE skill must NOT execute — refused
    skills = {"system.screenshot": _FakeSkill(permission=Permission.USER_APPROVAL)}
    ex = _FakeExecutor(skills)
    bridge = _bridge(ex)
    r = bridge.think("take a screenshot")
    assert r.strategy == "skill:system.screenshot:refused"
    assert "approval" in r.answer.lower()
    assert ex.calls == [], "a non-SAFE skill was executed from voice"


def test_dangerous_commands_never_execute_without_confirmation():
    # shell/power/keystroke commands NEVER reach the executor unbidden. Admin-
    # tier (shell/power) is flatly refused; keystroke (type/press) is
    # USER_APPROVAL and only ARMS a two-step confirm — nothing runs until the
    # owner says 'confirm'. Either way: zero execution, no reasoning essay.
    ex = _FakeExecutor(_SAFE)
    ios = _LocalIOS(confidence=0.9)
    bridge = _bridge(ex, ios=ios)
    admin_refused = 0
    for cmd in ("run shell rm -rf /", "restart the computer", "type my password",
                "press enter", "shut down"):
        r = bridge.think(cmd)
        if "administrator" in (r.answer or "").lower():
            admin_refused += 1
    assert ex.calls == [], f"a dangerous command reached the executor: {ex.calls}"
    assert admin_refused == 3               # shell + restart + shutdown refused
    assert ios.thinks == 0                  # gate handled all five, never reasoned


def test_failed_action_reports_gracefully():
    ex = _FakeExecutor(_SAFE, {"system.summary": FailureResult("sensor busy")})
    bridge = _bridge(ex)
    r = bridge.think("system status")
    assert "couldn't" in r.answer.lower() and "sensor busy" in r.answer


def test_skill_answer_stays_out_of_the_cloud_window():
    ex = _FakeExecutor(_SAFE, {"net.ip": SuccessResult(data="10.0.0.5")})
    reasoner = _FakeReasoner()
    bridge = _bridge(ex, reasoner=reasoner)
    bridge.think("what is my ip address")
    bridge.think("what is the capital of France?")     # cloud turn
    turns = " ".join(t.get("text", "")
                     for t in reasoner.contexts[-1]["recent_turns"])
    assert "10.0.0.5" not in turns and "ip address" not in turns


def test_no_executor_means_no_action_route():
    ios = _LocalIOS(confidence=0.9)
    bridge = ConversationBridge(
        ios, decision_log=_Log(), skills=None,
        speech=_SpeechOutput(synthesizer=lambda t: None), speak_answers=False)
    bridge.think("what is my ip address")
    assert ios.thinks == 1                             # fell through, no crash


def test_every_route_targets_a_real_SAFE_skill():
    """Lock the voice policy at the TABLE level (security review): every route
    must resolve to a real registered skill whose permission is SAFE — a future
    route pointed at an approval/admin skill fails here, not just at runtime."""
    from core.skills import SkillRegistry
    from core.skills.builtin import register_builtins
    registry = SkillRegistry()
    register_builtins(registry)
    for _pattern, name, _args, _render in ConversationBridge._skill_routes():
        skill = registry.get(name)                     # raises if the name is bogus
        assert skill.permission == Permission.SAFE, \
            f"voice route '{name}' targets a non-SAFE skill ({skill.permission.name})"


def test_volume_level_is_clamped_to_0_100():
    ex = _FakeExecutor(_SAFE)
    bridge = _bridge(ex)
    bridge.think("set the volume to 500")
    assert ex.calls == [("audio.set_volume", {"level": 100})]
