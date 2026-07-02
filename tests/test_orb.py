"""
tests/test_orb.py -- FRIDAY V3 (M20 revision) Orb UI.

Headless tests (no window, no display, no audio device). They exercise the data model,
config, and the Orb Controller's Runtime-Event-Bus behaviour through fakes.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from core.infra.friday_signal import Event, Signal
from core.io.orb import events as E
from core.io.orb.config import OrbConfig
from core.io.orb.controller import OrbController
from core.io.orb.state import (OrbSettings, SettingsStore, coerce_amplitude,
                               coerce_state)


# -- fakes -------------------------------------------------------------------------
class FakeBus:
    def __init__(self):
        self.subs = {}
        self.emitted = []

    def on(self, signal, handler):
        self.subs.setdefault(signal, []).append(handler)

    def off(self, signal, handler):
        self.subs.get(signal, []).remove(handler)

    def emit(self, signal, data=None, source="?"):
        self.emitted.append((signal, data, source))

    def dispatch(self, signal, data=None):
        ev = Event(signal=signal, data=data)
        for h in list(self.subs.get(signal, [])):
            asyncio.run(h(ev))

    def signals(self):
        return [s for s, _, _ in self.emitted]

    def payload(self, signal):
        return [d for s, d, _ in self.emitted if s == signal]


class FakeView:
    def __init__(self):
        self.calls = []

    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)

        def rec(*args):
            self.calls.append((name, list(args)))
        return rec

    def called(self, name):
        return [args for n, args in self.calls if n == name]


def _controller(tmp_path, **kw):
    store = SettingsStore(tmp_path / "orb_state.json")
    bus = FakeBus()
    view = FakeView()
    c = OrbController(bus=bus, view=view, settings_store=store,
                      config=kw.get("config", OrbConfig()))
    c.start()
    return c, bus, view, store


# -- state model -----------------------------------------------------------------
def test_settings_roundtrip(tmp_path):
    store = SettingsStore(tmp_path / "s.json")
    s = OrbSettings(x=11, y=22, width=300, height=310, opacity=0.5, mode="text",
                    always_on_top=False)
    assert store.save(s)
    loaded = store.load()
    assert (loaded.x, loaded.y, loaded.width, loaded.height) == (11, 22, 300, 310)
    assert loaded.mode == "text" and loaded.opacity == 0.5 and loaded.always_on_top is False


def test_settings_sanitized_clamps():
    s = OrbSettings(opacity=9.0, width=10, height=5, mode="bogus").sanitized()
    assert s.opacity == 1.0 and s.width == 120 and s.height == 120 and s.mode == "voice"


def test_coerce_state_and_amplitude():
    assert coerce_state("hearing") == "listening"
    assert coerce_state("speaking") == "speaking"
    assert coerce_state("nonsense") == "idle"
    assert coerce_amplitude(2.0) == 1.0
    assert coerce_amplitude(-1) == 0.0
    assert coerce_amplitude("x") == 0.0
    assert coerce_amplitude(0.5) == 0.5


# -- config ------------------------------------------------------------------------
def test_config_defaults():
    c = OrbConfig()
    assert c.primary_interface == "orb"
    assert c.voice_mode_default is True
    assert c.animation_quality == "high"


def test_config_from_friday_config(tmp_path):
    p = tmp_path / "friday_config.json"
    p.write_text(json.dumps({"ui": {"animation_quality": "low",
                                    "primary_interface": "dashboard",
                                    "voice_mode_default": False}}), encoding="utf-8")
    c = OrbConfig.load(p)
    assert c.animation_quality == "low"
    assert c.primary_interface == "dashboard"
    assert c.voice_mode_default is False


def test_config_sanitize_bad_values():
    c = OrbConfig(animation_quality="ultra", primary_interface="weird").sanitized()
    assert c.animation_quality == "high" and c.primary_interface == "orb"


# -- controller: reflected FRIDAY signals -------------------------------------------
def test_speak_start_sets_speaking_and_shows_text(tmp_path):
    c, bus, view, _ = _controller(tmp_path)
    bus.dispatch(Signal.SPEAK_START, "hello satvik")
    assert c.state == "speaking"
    assert ["speaking"] in view.called("set_state")
    assert ["hello satvik"] in view.called("show_speech")


def test_speak_done_hides_and_idle(tmp_path):
    c, bus, view, _ = _controller(tmp_path)
    bus.dispatch(Signal.SPEAK_START, "hi")
    bus.dispatch(Signal.SPEAK_DONE, None)
    assert c.state == "idle"
    assert view.called("hide_speech")


def test_thinking_and_listening(tmp_path):
    c, bus, view, _ = _controller(tmp_path)
    bus.dispatch(Signal.THINKING_START, None)
    assert c.state == "thinking"
    bus.dispatch(Signal.WAKE_WORD, None)
    assert c.state == "listening"


def test_thinking_done_does_not_override_speaking(tmp_path):
    c, bus, _, _ = _controller(tmp_path)
    bus.dispatch(Signal.SPEAK_START, "speaking now")
    bus.dispatch(Signal.THINKING_DONE, None)
    assert c.state == "speaking"


def test_mood_updates_emotion(tmp_path):
    c, bus, view, _ = _controller(tmp_path)
    bus.dispatch(Signal.MOOD_UPDATED, {"mood": "curious"})
    assert c.emotion in ("curious", "focused")
    assert view.called("set_emotion")


def test_amplitude_reflected(tmp_path):
    c, bus, view, _ = _controller(tmp_path)
    bus.dispatch(Signal.ORB_AMPLITUDE, 0.7)
    assert c.amplitude == 0.7
    assert [0.7] in view.called("set_amplitude")


def test_notify_maps_to_glow(tmp_path):
    c, bus, view, _ = _controller(tmp_path)
    bus.dispatch(Signal.ORB_NOTIFY, {"kind": "error"})
    assert ["error", "#f87171"] in view.called("notify")


def test_speech_show_hide_signals(tmp_path):
    c, bus, view, _ = _controller(tmp_path)
    bus.dispatch(Signal.ORB_SPEECH_SHOW, "streaming text")
    assert c.state == "speaking" and ["streaming text"] in view.called("show_speech")
    bus.dispatch(Signal.ORB_SPEECH_HIDE, None)
    assert c.state == "idle" and view.called("hide_speech")


# -- controller: user interactions (orb -> FRIDAY) ----------------------------------
def test_wake_emits_signal(tmp_path):
    c, bus, _, _ = _controller(tmp_path)
    c.wake()
    assert Signal.ORB_WAKE in bus.signals()


def test_toggle_dashboard(tmp_path):
    c, bus, view, _ = _controller(tmp_path)
    c.toggle_dashboard()
    assert c.dashboard_open is True and view.called("open_dashboard")
    c.toggle_dashboard()
    assert c.dashboard_open is False and view.called("close_dashboard")
    assert bus.signals().count(Signal.ORB_DASHBOARD_TOGGLE) == 2


def test_command_emits(tmp_path):
    c, bus, _, _ = _controller(tmp_path)
    c.command("restart")
    assert Signal.ORB_COMMAND in bus.signals()
    assert {"action": "restart"} in bus.payload(Signal.ORB_COMMAND)
    assert c.state == "idle"


def test_set_mode_persists_and_emits(tmp_path):
    c, bus, view, store = _controller(tmp_path)
    assert c.set_mode("text") is True
    assert c.mode == "text"
    assert "text" in bus.payload(Signal.ORB_MODE)
    assert ["text"] in view.called("set_mode")
    assert store.load().mode == "text"          # persisted across restarts
    assert c.set_mode("bogus") is False


def test_external_mode_signal_reflected(tmp_path):
    c, bus, view, _ = _controller(tmp_path)
    bus.dispatch(Signal.ORB_MODE, "text")
    assert c.mode == "text" and ["text"] in view.called("set_mode")


def test_voice_commands(tmp_path):
    c, _, _, _ = _controller(tmp_path)
    assert c.handle_voice_command("FRIDAY, switch to text mode.") is True
    assert c.mode == "text"
    assert c.handle_voice_command("FRIDAY, switch to voice mode.") is True
    assert c.mode == "voice"
    assert c.handle_voice_command("FRIDAY, disable voice.") is True
    assert c.mode == "text"
    assert c.handle_voice_command("FRIDAY, enable voice.") is True
    assert c.mode == "voice"
    assert c.handle_voice_command("FRIDAY, open dashboard.") is True
    assert c.dashboard_open is True
    assert c.handle_voice_command("FRIDAY, close dashboard.") is True
    assert c.dashboard_open is False
    assert c.handle_voice_command("what is the weather") is False


def test_move_resize_persist(tmp_path):
    c, _, _, store = _controller(tmp_path)
    c.on_move(100, 200)
    c.on_resize(400, 410)
    s = store.load()
    assert (s.x, s.y, s.width, s.height) == (100, 200, 400, 410)


def test_snapshot_shape(tmp_path):
    c, _, _, _ = _controller(tmp_path)
    snap = c.snapshot()
    for k in ("state", "mode", "emotion", "dashboard_open", "always_on_top", "config"):
        assert k in snap
    assert isinstance(snap["config"], dict)


# -- architectural invariant: no AI logic in the controller --------------------------
def test_controller_imports_no_cognition():
    src = Path(OrbController.__module__.replace(".", "/") + ".py")
    src = Path(__file__).resolve().parents[1] / "core" / "io" / "orb" / "controller.py"
    text = src.read_text(encoding="utf-8")
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("import ") or s.startswith("from "):
            for banned in ("brain", "executive", "memory", "neural"):
                assert banned not in s, f"controller must not import {banned}: {s}"


# -- import guards (no window / no display opened) ----------------------------------
def test_window_and_bridge_import():
    import importlib
    importlib.import_module("core.io.orb.window")
    importlib.import_module("core.io.orb.speech_bridge")


def test_speech_bridge_synthetic_envelope(tmp_path):
    from core.io.orb.speech_bridge import SpeechBridge
    bus = FakeBus()
    br = SpeechBridge(bus)
    br.emit_speech("hello", audio_path=None, block=True)   # no audio -> synthetic
    sigs = bus.signals()
    assert Signal.ORB_SPEECH_SHOW in sigs
    assert Signal.ORB_AMPLITUDE in sigs
    assert Signal.ORB_SPEECH_HIDE in sigs
