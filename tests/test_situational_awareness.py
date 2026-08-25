"""
Situational awareness + self-explanation (M64).

Pins the honest behaviour: she narrates a picture from whatever subsystems are
live (never inventing senses she doesn't have), she explains her last decision
in plain words from the real decision log, and both degrade gracefully to a
truthful "nothing to report" instead of crashing when nothing is wired.
"""

from __future__ import annotations

from core.awareness.situation import (
    gather, describe_situation, explain_last_decision, Situation,
)


class _WM:
    """Minimal World Model stand-in."""
    def __init__(self, projects=(), devices=(), people=()):
        self._p = projects
        self._d = devices
        self._pe = people

    def entities_by_kind(self, kind):
        class _E:
            def __init__(self, name): self.name = name
        src = {"project": self._p, "device": self._d, "person": self._pe}.get(kind, [])
        return [_E(n) for n in src]


class _Log:
    def __init__(self, rows): self._rows = rows
    def recent(self, limit=50): return self._rows[:limit]


class _Goals:
    def active(self):
        return [{"title": "learn the trading data pipeline"},
                {"title": "index the new project"}]


def test_gather_builds_a_true_picture():
    wm = _WM(projects=["PythonProject1"], devices=["living room TV"])
    log = _Log([{"intent": "question", "route": ["local_reasoner"], "confidence": 0.8}])
    s = gather(world_model=wm, goals=_Goals(), decision_log=log, perception=None)
    assert isinstance(s, Situation)
    assert s.project == "PythonProject1"
    assert "living room TV" in s.devices
    assert any("trading data" in g for g in s.goals)
    text = s.narrate()
    assert "PythonProject1" in text
    # she must NOT claim to see when perception is empty
    assert "watching through" not in text


def test_describe_situation_never_raises_with_nothing_wired():
    # no services at all — must return a truthful, non-empty line, not crash
    text = describe_situation(world_model=_WM(), goals=None,
                              decision_log=_Log([]), perception=None)
    assert isinstance(text, str) and text


def test_explain_last_decision_plain_words():
    log = _Log([{"intent": "a math question", "route": ["exact"],
                 "confidence": 0.9, "models_used": [], "skills_invoked": []}])
    out = explain_last_decision(log)
    assert "computing it exactly myself" in out
    assert "confident" in out


def test_explain_last_decision_cloud_route():
    log = _Log([{"intent": "general knowledge", "route": ["cloud:groq_primary"],
                 "confidence": 0.4, "models_used": ["llama-3.3-70b"]}])
    out = explain_last_decision(log)
    assert "cloud model" in out
    assert "wasn't fully certain" in out


def test_explain_last_decision_empty_is_honest():
    out = explain_last_decision(_Log([]))
    assert "nothing to explain" in out


def test_route_regexes_match():
    from core.launcher.conversation import ConversationBridge as CB
    for phrase in ("what's going on", "what's happening right now",
                   "give me a situation report", "catch me up",
                   "what's the situation"):
        assert CB._SITUATION_RE.search(phrase), phrase
    for phrase in ("why did you do that", "explain your reasoning",
                   "how did you arrive at that", "what made you choose that"):
        assert CB._WHY_RE.search(phrase), phrase
