"""
M51 — the private overlay: you see her, screen shares don't.

A transparent always-on-top corner panel shows FRIDAY's state + last heard +
last answer, and on Windows is excluded from screen capture
(SetWindowDisplayAffinity / WDA_EXCLUDEFROMCAPTURE). The GUI itself is verified
live (it needs a display); here we pin the thread-safe feed, the guards, the
constants, and the bridge wiring — all without opening a window.
"""

from __future__ import annotations

from core.io import overlay as ov
from core.io.overlay import Overlay


def test_capture_exclusion_constant_is_the_documented_value():
    # WDA_EXCLUDEFROMCAPTURE must be exactly 0x11 (Win10 2004+); a wrong value
    # would silently fail to hide the overlay from screen shares
    assert ov._WDA_EXCLUDEFROMCAPTURE == 0x00000011
    assert ov._WS_EX_TRANSPARENT == 0x00000020        # click-through


def test_post_is_thread_safe_and_bounded():
    o = Overlay()
    for i in range(200):                              # more than the queue cap
        o.set_state("thinking")
        o.answer(f"answer {i}")
    assert o._q.qsize() <= 64                         # bounded, drops when full


def test_feed_helpers_enqueue_the_right_events():
    o = Overlay()
    o.set_state("listening")
    o.heard("what time is it")
    o.answer("It's noon.")
    o.notice("online")
    kinds = []
    while not o._q.empty():
        kinds.append(o._q.get_nowait())
    assert [e["kind"] for e in kinds] == ["state", "heard", "answer", "notice"]
    assert kinds[1]["text"] == "what time is it"
    assert kinds[0]["state"] == "listening"


def test_long_text_is_truncated_before_display():
    o = Overlay()
    o.answer("x" * 1000)
    o.heard("y" * 1000)
    ans = o._q.get_nowait(); heard = o._q.get_nowait()
    assert len(ans["text"]) <= 400 and len(heard["text"]) <= 160


def test_start_degrades_without_tkinter(monkeypatch):
    monkeypatch.setattr(ov, "available", lambda: False)
    o = Overlay()
    assert o.start() is False                         # no display → no-op
    assert o.status()["started"] is False


def test_status_shape():
    s = Overlay(corner="bottom-left").status()
    assert s["corner"] == "bottom-left"
    assert s["excluded_from_capture"] is False        # not applied until shown


# ── bridge wiring: her answers reach the overlay ──────────────────────────────

class _FakeOverlay:
    def __init__(self):
        self.heard_calls, self.answers, self.states = [], [], []
    def heard(self, t): self.heard_calls.append(t)
    def answer(self, t): self.answers.append(t)
    def set_state(self, s): self.states.append(s)


def test_bridge_pushes_heard_and_answer_to_overlay():
    from core.launcher.conversation import ConversationBridge, _SpeechOutput
    from tests.test_teacher import _LocalIOS, _Log
    ovl = _FakeOverlay()
    bridge = ConversationBridge(
        _LocalIOS(confidence=0.9), decision_log=_Log(), overlay=ovl,
        speech=_SpeechOutput(synthesizer=lambda t: None), speak_answers=True)
    bridge.think("what is the capital of France")
    assert ovl.heard_calls == ["what is the capital of France"]
    assert "thinking" in ovl.states
    assert ovl.answers                                # her answer was shown
    assert "speaking" in ovl.states


def test_bridge_without_overlay_is_unaffected():
    from core.launcher.conversation import ConversationBridge, _SpeechOutput
    from tests.test_teacher import _LocalIOS, _Log
    bridge = ConversationBridge(
        _LocalIOS(confidence=0.9), decision_log=_Log(), overlay=None,
        speech=_SpeechOutput(synthesizer=lambda t: None), speak_answers=False)
    r = bridge.think("hello there friend")            # no crash without an overlay
    assert r is not None
