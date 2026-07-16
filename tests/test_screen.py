"""
M52 — screen sight: she reads the screen on-device, image stays local.

Capture + OCR use the OS's own engine (winocr on Windows, Apple Vision on
macOS) with a cross-platform RapidOCR fallback. The screenshot is never
returned or stored — only the extracted text. "read my screen" / "what's this
error" route to it; "take a screenshot" still goes to the action skill.
"""

from __future__ import annotations

from core.io import screen


def test_backend_order_is_os_native_first_then_fallback(monkeypatch):
    monkeypatch.setattr(screen.platform, "system", lambda: "Windows")
    assert [n for n, _ in screen._backends()] == ["winocr", "rapidocr"]
    monkeypatch.setattr(screen.platform, "system", lambda: "Darwin")
    assert [n for n, _ in screen._backends()] == ["ocrmac", "rapidocr"]
    monkeypatch.setattr(screen.platform, "system", lambda: "Linux")
    assert [n for n, _ in screen._backends()] == ["rapidocr"]   # universal fallback


def test_read_screen_returns_text_never_the_image(monkeypatch):
    class _Img:
        size = (100, 100)
    monkeypatch.setattr(screen, "_capture", lambda: _Img())
    monkeypatch.setattr(screen, "_backends", lambda: [("winocr", lambda im: "Error: KeyError line 42")])
    monkeypatch.setattr(screen, "_backend_available", lambda n: True)
    r = screen.read_screen()
    assert r["ok"] and r["backend"] == "winocr"
    assert r["text"] == "Error: KeyError line 42"
    assert "image" not in r and "img" not in r          # only text ever escapes


def test_read_screen_degrades_without_a_display(monkeypatch):
    monkeypatch.setattr(screen, "_capture", lambda: None)
    r = screen.read_screen()
    assert r["ok"] is False and r["backend"] is None


def test_read_screen_falls_through_to_the_next_backend(monkeypatch):
    class _Img:
        size = (10, 10)
    monkeypatch.setattr(screen, "_capture", lambda: _Img())
    monkeypatch.setattr(screen, "_backend_available", lambda n: True)
    monkeypatch.setattr(screen, "_backends",
                        lambda: [("winocr", lambda im: None),      # failed
                                 ("rapidocr", lambda im: "fallback text")])
    r = screen.read_screen()
    assert r["backend"] == "rapidocr" and r["text"] == "fallback text"


def test_clean_collapses_whitespace_and_blank_lines():
    assert screen._clean("  a  b \n\n  c \n") == "a b\nc"


# ── the voice route ────────────────────────────────────────────────────────────

def test_read_my_screen_routes_to_screen_sight(monkeypatch):
    from core.launcher.conversation import ConversationBridge, _SpeechOutput
    from tests.test_teacher import _LocalIOS, _Log
    monkeypatch.setattr(screen, "available", lambda: True)
    monkeypatch.setattr(screen, "read_screen",
                        lambda: {"ok": True, "text": "a terminal with a traceback",
                                 "backend": "winocr", "chars": 26})
    bridge = ConversationBridge(_LocalIOS(confidence=0.9), decision_log=_Log(),
                                speech=_SpeechOutput(synthesizer=lambda t: None),
                                speak_answers=False)
    r = bridge.think("read my screen")
    assert r.strategy == "screen"
    assert "traceback" in r.answer
    assert bridge.status()["screen_reads"] == 1


def test_screenshot_command_does_not_hit_screen_sight(monkeypatch):
    # "take a screenshot" is an ACTION skill, not a screen READ — \bscreen\b
    # must not match inside "screenshot"
    called = []
    monkeypatch.setattr(screen, "read_screen", lambda: called.append(True) or {})
    from core.launcher.conversation import ConversationBridge
    b = ConversationBridge.__new__(ConversationBridge)
    assert b._read_screen("take a screenshot") is None
    assert b._read_screen("what is the weather") is None
    assert called == []


def test_screen_read_reports_when_ocr_is_unavailable(monkeypatch):
    from core.launcher.conversation import ConversationBridge
    monkeypatch.setattr(screen, "available", lambda: False)
    b = ConversationBridge.__new__(ConversationBridge)
    key, answer = b._read_screen("read my screen")
    assert key == "screen" and "isn't installed" in answer
