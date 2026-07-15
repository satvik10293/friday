"""
M48 — the proper app: system-tray presence replaces the cinematic HUD.

FRIDAY is voice-first; her surface is a tray icon (state colour, mute, quit,
notifications), not a Flask+WebView2 browser HUD. The tray is optional — a
machine without pystray/Pillow degrades to console-resident, never a boot
failure. `ui.mode` (tray|hud|none) picks the surface.
"""

from __future__ import annotations

import pytest

from core.io import tray


# ── tray logic (no display needed) ────────────────────────────────────────────

def test_icon_renders_for_every_state():
    for state, color in tray._COLORS.items():
        img = tray._make_icon(color)
        assert img.size == (64, 64) and img.mode == "RGBA"


class _Listening:
    def __init__(self):
        self.private = None

    def set_privacy(self, v):
        self.private = v


def test_mute_toggles_mic_privacy():
    listening = _Listening()
    app = tray.TrayApp(listening=listening)
    app._toggle_mute()
    assert app._muted is True and listening.private is True
    app._toggle_mute()
    assert app._muted is False and listening.private is False


def test_quit_calls_back_and_never_raises():
    called = []
    app = tray.TrayApp(on_quit=lambda: called.append(True))
    app._quit()                                  # no icon running — must not raise
    assert called == [True]


def test_notify_is_best_effort_and_never_raises(monkeypatch):
    # even with every backend missing, notify() returns False, not an exception
    import sys
    monkeypatch.setitem(sys.modules, "plyer", None)
    monkeypatch.setitem(sys.modules, "win10toast", None)
    assert tray.notify("t", "m") in (True, False)


def test_set_state_before_start_is_harmless():
    tray.TrayApp().set_state("thinking")         # no icon yet → no-op, no crash


# ── launcher surface selection (ui.mode) ──────────────────────────────────────

def _launcher(mode, *, headless=False):
    from core.launcher.launcher import Launcher
    lz = Launcher.__new__(Launcher)              # skip heavy __init__
    lz.headless = headless
    lz.config = {"ui": {"mode": mode}}
    lz.components = {}
    lz._tray = None
    return lz


def test_headless_has_no_surface():
    assert _launcher("tray", headless=True).start_ui() == "none"


def test_mode_none_starts_nothing():
    assert _launcher("none").start_ui() == "none"


def test_mode_tray_starts_the_tray(monkeypatch):
    lz = _launcher("tray")
    monkeypatch.setattr(lz, "_start_tray", lambda: True)
    monkeypatch.setattr(lz, "_start_hud", lambda: pytest.fail("HUD started in tray mode"))
    assert lz.start_ui() == "tray"


def test_tray_unavailable_falls_back_to_hud(monkeypatch):
    lz = _launcher("tray")
    monkeypatch.setattr(lz, "_start_tray", lambda: False)   # no pystray
    monkeypatch.setattr(lz, "_start_hud", lambda: True)
    assert lz.start_ui() == "hud"


def test_mode_hud_starts_the_hud(monkeypatch):
    lz = _launcher("hud")
    monkeypatch.setattr(lz, "_start_hud", lambda: True)
    monkeypatch.setattr(lz, "_start_tray", lambda: pytest.fail("tray started in hud mode"))
    assert lz.start_ui() == "hud"
