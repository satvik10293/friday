"""
Phase A cutover — exit-criteria tests (docs/FRIDAY_5X_ROADMAP.md).

One boot path: the launcher wires the full cognitive stack (intelligence stage
included); a voice turn flows through the ConversationBridge producing exactly
one DecisionLog row and a spoken answer; the friday_spine shim imports no 3.0
brain modules.
"""

from __future__ import annotations

import sys

from core.launcher.conversation import ConversationBridge, _SpeechOutput
from core.launcher.startup import STARTUP_STAGES, StartupSequence


# ── boot path ─────────────────────────────────────────────────────────────────

def test_intelligence_stage_is_part_of_the_boot():
    assert "intelligence" in STARTUP_STAGES
    assert STARTUP_STAGES.index("intelligence") < STARTUP_STAGES.index("voice")


def test_headless_boot_reaches_ready_with_intelligence_online():
    report = StartupSequence(headless=True, start_runtime=False).run()
    assert report.ready
    by_stage = {s.stage: s for s in report.stages}
    assert by_stage["intelligence"].status == "ok"
    assert report.components.get("intelligence") is not None


# ── conversation bridge ───────────────────────────────────────────────────────

class _FakeResponse:
    task = "general"
    strategy = "direct"
    ok = True
    answer = "the answer"
    confidence = 0.8
    models_used = ["fake-model"]
    trace_id = "t-1"


class _FakeIOS:
    def __init__(self):
        self.calls = []

    def think(self, prompt, context=None, **kw):
        self.calls.append((prompt, context))
        return _FakeResponse()


class _FakeLog:
    def __init__(self):
        self.rows = []

    def log(self, **row):
        self.rows.append(row)
        return len(self.rows)


def _bridge():
    spoken = []
    bridge = ConversationBridge(
        _FakeIOS(), decision_log=_FakeLog(),
        speech=_SpeechOutput(synthesizer=spoken.append))
    return bridge, spoken


def test_voice_turn_produces_one_decision_log_row():
    bridge, _ = _bridge()
    # substantive turn — exercises the reasoning path (greetings now short-
    # circuit to the small-talk fast-path and never reach the IOS mock)
    bridge.think("tell me about the roman empire", context={"source": "voice"})
    rows = bridge._decision_log.rows
    assert len(rows) == 1
    row = rows[0]
    assert row["source"] == "voice"
    assert row["was_autonomous"] is False
    assert row["models_used"] == ["fake-model"]
    assert row["confidence"] == 0.8
    assert row["turn_id"] == 1


def test_voice_turn_speaks_the_answer():
    bridge, spoken = _bridge()
    # a substantive turn (not a greeting — greetings are now answered directly
    # by the small-talk fast-path, which never reaches the reasoning/speak mock)
    bridge.think("tell me about the roman empire")
    import time
    for _ in range(50):
        if spoken:
            break
        time.sleep(0.02)
    assert spoken == ["the answer"]
    assert bridge.status()["turns"] == 1


def test_decision_log_failure_never_breaks_a_turn():
    class BrokenLog:
        def log(self, **row):
            raise RuntimeError("db locked")

    bridge = ConversationBridge(
        _FakeIOS(), decision_log=BrokenLog(),
        speech=_SpeechOutput(synthesizer=lambda t: None))
    response = bridge.think("hello")
    assert response.ok


def test_announcements_route_through_the_bridge():
    bridge, spoken = _bridge()
    assert bridge.announce("I'm ready.")
    import time
    for _ in range(50):
        if spoken:
            break
        time.sleep(0.02)
    assert spoken == ["I'm ready."]


# ── quarantine ────────────────────────────────────────────────────────────────

def test_spine_shim_imports_no_30_brain_modules():
    forbidden = {"core.brain.friday_brain", "core.brain.friday_neural",
                 "legacy.friday_spine_v3"}
    # Evict the shim AND the forbidden modules first: other tests may import
    # the 3.0 brain legitimately (e.g. to test its repairs). What this guard
    # proves is that importing the spine shim does not RE-import them.
    for mod in list(sys.modules):
        if mod.startswith("friday_spine") or mod.startswith("legacy") \
                or mod in forbidden:
            del sys.modules[mod]
    import friday_spine  # noqa: F401
    assert not (set(sys.modules) & forbidden), \
        "importing friday_spine pulled in a 3.0 brain module"


def test_spine_shim_delegates_to_the_launcher(monkeypatch):
    import friday_spine
    called = {}

    def fake_main(argv):
        called["argv"] = argv
        return 0

    import core.launcher
    monkeypatch.setattr(core.launcher, "main", fake_main)
    assert friday_spine.main([]) == 0
    assert called["argv"] == []
