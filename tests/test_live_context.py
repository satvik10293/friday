"""
M25 — Live context: every turn reasons over the user's live state (projects,
strong preferences, active goals) injected through the Intelligence OS context
builder; the goal service and user model come online at boot and feed the
internal mind (goal review, self model).
"""

from __future__ import annotations

from core.intelligence.context_builder import ContextBuilder
from core.launcher.startup import StartupSequence


class _Pref:
    def __init__(self, key, value):
        self.key, self.value = key, value


class _Project:
    def __init__(self, name):
        self.name, self.status = name, "active"


class _UserModel:
    class preferences:
        @staticmethod
        def strong():
            return [_Pref("language", "python")]

    class projects:
        @staticmethod
        def active():
            return [_Project("FRIDAY 5.x")]


class _Goal:
    title = "finish the milestone"
    status = "active"


class _Goals:
    def list_goals(self, status=None):
        return [_Goal()]


def test_context_builder_injects_user_and_goal_state_into_every_turn():
    ctx = ContextBuilder(user_model=_UserModel(), goal_service=_Goals()).build("hello")
    assert ctx["preferences"] == {"language": "python"}
    assert ctx["projects"] == [{"name": "FRIDAY 5.x", "status": "active"}]
    assert ctx["goals"] and ctx["goals"][0]["title"] == "finish the milestone"


def test_boot_brings_goals_and_user_model_online():
    report = StartupSequence(headless=True, start_runtime=False).run()
    assert report.components.get("goals") is not None
    assert report.components.get("user_model") is not None
    ios = report.components.get("intelligence")
    assert ios is not None
    # the singleton IOS may predate this boot's wiring (test-order dependent);
    # what must hold is that a context build works and carries the live keys
    ctx = ios.context_builder.build("what am I working on?")
    for key in ("memories", "goals", "projects", "preferences"):
        assert key in ctx
