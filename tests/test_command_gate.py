"""
Understanding vs ACTION (M59.1): clear commands trigger actions, not essays.

The pipeline separation pinned here:
· a clear device command that maps to a SAFE skill EXECUTES it (governed)
· an above-SAFE command gets the M47 approval refusal — one sentence
· a device command with no matching action gets an honest decline — one
  sentence, and the CLOUD IS NEVER CONSULTED for a command
· questions and speech-acts (explain/tell/summarize) keep the full
  understanding path untouched
"""

from __future__ import annotations

from types import SimpleNamespace

from core.launcher.conversation import ConversationBridge, _SpeechOutput
from core.skills.permissions import Permission
from core.skills.results import Result


class _Skill:
    def __init__(self, permission=Permission.SAFE):
        self.permission = permission


class _Registry:
    def __init__(self, skills):
        self._skills = skills

    def get(self, name):
        return self._skills[name]


class _Skills:
    """SkillExecutor double: records executions."""

    def __init__(self, skills):
        self._registry = _Registry(skills)
        self.executed = []

    def execute(self, name, args=None, context=None):
        self.executed.append((name, dict(args or {})))
        return Result(success=True, data="ok")


class _CloudSpy:
    def __init__(self):
        self.called = 0

    def available(self):
        return True

    def reason(self, q, *, context=None):
        self.called += 1
        return SimpleNamespace(ok=True, answer="a long explanation …",
                               model="x", latency_ms=1.0)

    def status(self):
        return {}


class _IOS:
    def __init__(self):
        self.calls = 0

    def think(self, prompt, context=None, **kw):
        self.calls += 1
        return SimpleNamespace(task="general", strategy="ios", ok=True,
                               confidence=0.7, answer="ios answer",
                               models_used=[], structured={}, trace_id="t",
                               context_used={})


def _bridge(skills=None, cloud=None):
    return ConversationBridge(
        _IOS(), decision_log=_Log(), skills=skills, reasoner=cloud,
        speech=_SpeechOutput(synthesizer=lambda t: None))


class _Log:
    def __init__(self):
        self.rows = []

    def log(self, **row):
        self.rows.append(row)
        return len(self.rows)


# ── clear commands ACT ────────────────────────────────────────────────────────

def test_open_app_command_executes_the_skill_not_the_cloud():
    skills = _Skills({"app.open": _Skill()})
    cloud = _CloudSpy()
    bridge = _bridge(skills, cloud)
    resp = bridge.think("open notepad")
    assert skills.executed == [("app.open", {"name": "notepad"})]
    assert cloud.called == 0                       # acted, didn't explain
    assert "opening" in resp.answer.lower()


def test_open_url_routes_to_the_browser_skill():
    skills = _Skills({"web.open_url": _Skill(), "app.open": _Skill()})
    bridge = _bridge(skills, _CloudSpy())
    bridge.think("open youtube.com")
    assert skills.executed[0][0] == "web.open_url"
    assert skills.executed[0][1]["url"] == "https://youtube.com"


def test_clipboard_and_brightness_commands_act():
    skills = _Skills({"clipboard.get": _Skill(), "display.set_brightness": _Skill()})
    bridge = _bridge(skills, _CloudSpy())
    bridge.think("what's on my clipboard")
    bridge.think("set the brightness to 70")
    assert ("clipboard.get", {}) in skills.executed
    assert ("display.set_brightness", {"level": 70}) in skills.executed


# ── above-SAFE commands refuse for approval, in one sentence ──────────────────

def test_close_app_refuses_for_approval_never_reaching_the_cloud():
    skills = _Skills({"app.close": _Skill(Permission.USER_APPROVAL)})
    cloud = _CloudSpy()
    bridge = _bridge(skills, cloud)
    resp = bridge.think("close chrome")
    assert skills.executed == []                   # never executed
    assert cloud.called == 0                       # never explained
    assert "approval" in resp.answer.lower()


def test_type_and_restart_commands_refuse_for_approval():
    bridge = _bridge(_Skills({}), _CloudSpy())
    assert "approval" in bridge.think("type hello world").answer.lower()
    assert "approval" in bridge.think("restart the computer").answer.lower()


# ── unknown device commands decline honestly (no essay) ───────────────────────

def test_unknown_device_command_declines_in_one_sentence():
    cloud = _CloudSpy()
    bridge = _bridge(_Skills({}), cloud)
    resp = bridge.think("eject the usb drive")
    assert cloud.called == 0                       # a command never hits cloud
    assert "don't have an action" in resp.answer
    assert "command:unavailable" in bridge._decision_log.rows[-1]["route"]


# ── understanding stays understanding ─────────────────────────────────────────

def test_questions_still_take_the_reasoning_path():
    cloud = _CloudSpy()
    bridge = _bridge(_Skills({}), cloud)
    resp = bridge.think("how do I open notepad on windows?")
    assert cloud.called == 1                       # a question MAY be explained
    assert resp.answer == "a long explanation …"


def test_speech_act_verbs_are_not_gated():
    cloud = _CloudSpy()
    bridge = _bridge(_Skills({}), cloud)
    bridge.think("explain how volcanoes form")
    bridge.think("tell me about the roman empire")
    assert cloud.called == 2                       # understanding untouched
