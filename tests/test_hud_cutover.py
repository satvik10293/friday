"""
tests/test_hud_cutover.py — M32.6 base perfection.

The HUD, proactive watcher, PDF module and desktop app no longer import the
legacy 3.0 brain: they answer through the Intelligence OS — the same cognition
stack the voice path uses — and every HUD turn writes a DecisionLog row.
"""

from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]

_LEGACY = ("core.brain.friday_brain", "core.brain.friday_neural")
_CUTOVER_FILES = [
    ROOT / "core" / "io" / "friday_face.py",
    ROOT / "core" / "io" / "friday_proactive.py",
    ROOT / "core" / "knowledge" / "friday_pdf.py",
    ROOT / "friday_app.py",
]


@pytest.mark.parametrize("path", _CUTOVER_FILES, ids=lambda p: p.name)
def test_no_legacy_brain_imports(path):
    source = path.read_text(encoding="utf-8")
    for module in _LEGACY:
        assert module not in source, f"{path.name} still references {module}"


class _FakeIOS:
    def __init__(self):
        self.calls = []

    def think(self, prompt, **kw):
        self.calls.append(prompt)
        return SimpleNamespace(answer="ios answer", task="chat", strategy="direct",
                               models_used=["local:team"], confidence=0.9,
                               trace_id="t-1", ok=True)

    def status(self):
        return {"models": {}}


class _LogSpy:
    def __init__(self):
        self.rows = []

    def log(self, **kw):
        self.rows.append(kw)


@pytest.fixture
def hud(monkeypatch):
    import core.io.friday_face as face
    import core.intelligence.service as service
    import core.observability.decision_log as dlog

    ios = _FakeIOS()
    spy = _LogSpy()
    monkeypatch.setattr(service, "get_intelligence_os", lambda **kw: ios)
    monkeypatch.setattr(dlog, "get_decision_log", lambda: spy)
    monkeypatch.setattr(face, "_brain", None)
    return face, ios, spy


def test_hud_turn_routes_through_intelligence_os(hud):
    face, ios, spy = hud
    brain = face._get_brain()
    answer = brain.respond("hello there")
    assert answer == "ios answer"
    assert ios.calls == ["hello there"]


def test_hud_turn_writes_decision_log_row(hud):
    face, ios, spy = hud
    face._get_brain().respond("what's the weather")
    assert len(spy.rows) == 1
    row = spy.rows[0]
    assert row["source"] == "hud"
    assert row["route"] == ["direct"]
    assert row["models_used"] == ["local:team"]
    assert row["was_autonomous"] is False


def test_think_text_returns_plain_answer(monkeypatch):
    import core.intelligence.service as service

    monkeypatch.setattr(service, "get_intelligence_os", lambda **kw: _FakeIOS())
    assert service.think_text("summarize this") == "ios answer"
