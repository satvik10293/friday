"""Tests for the RC1 diagnostics screen (core/launcher/diagnostics.py)."""

from __future__ import annotations

import os

from core.launcher.diagnostics import Diagnostics, from_launcher


class _FakeBrain:
    def __init__(self, status="online"):
        self._status = status

    def health(self):
        return {"status": self._status}


class _FakePlugin:
    def kinds(self):
        return ["action", "visual"]


class _FakeKernel:
    def try_get(self, name):
        return _FakePlugin() if name == "plugin" else None

    def health(self):
        return {"status": "ok"}


def test_report_shape_empty():
    d = Diagnostics()
    r = d.report()
    for key in ("version", "runtime_status", "system", "brains", "plugins",
                "provider", "event_bus"):
        assert key in r


def test_version_includes_build_tag():
    d = Diagnostics()
    v = d.version()
    # release_tag() should surface as build (e.g. 0.20.0-rc1)
    assert v.get("version")
    assert "rc" in v.get("build", "") or v.get("build") == v.get("version")


def test_brains_status_collected():
    comps = {"brains": {"memory_brain": _FakeBrain(), "vision_brain": _FakeBrain("degraded")}}
    d = Diagnostics(components=comps)
    b = d.brains()
    assert b["memory_brain"] == "online"
    assert b["vision_brain"] == "degraded"


def test_brain_health_error_is_caught():
    class Bad:
        def health(self):
            raise RuntimeError("boom")

    d = Diagnostics(components={"brains": {"x": Bad()}})
    assert d.brains()["x"] == "error"          # never raises


def test_plugins_reported():
    d = Diagnostics(components={"kernel": _FakeKernel()})
    p = d.plugins()
    assert p["available"] is True
    assert p["count"] == 2
    assert "action" in p["kinds"]


def test_plugins_absent():
    d = Diagnostics()
    assert d.plugins() == {"available": False, "kinds": [], "count": 0}


def test_active_provider_prefers_present_key(monkeypatch):
    for env in ("GROQ_API_KEY", "GEMINI_API_KEY", "OPENAI_API_KEY"):
        monkeypatch.delenv(env, raising=False)
    monkeypatch.setenv("GROQ_API_KEY", "x")
    assert Diagnostics.active_provider()["provider"] == "groq"


def test_active_provider_local_only(monkeypatch):
    for env in ("GROQ_API_KEY", "GEMINI_API_KEY", "OPENAI_API_KEY"):
        monkeypatch.delenv(env, raising=False)
    prov = Diagnostics.active_provider()
    assert prov["provider"] == "local-only"
    assert prov["configured"] is False


def test_provider_never_exposes_key_value(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "super-secret-value")
    prov = Diagnostics.active_provider()
    assert "super-secret-value" not in str(prov)


def test_event_bus_not_started():
    assert Diagnostics().event_bus()["status"] == "not started"


def test_render_is_string():
    out = Diagnostics(components={"kernel": _FakeKernel(),
                                  "brains": {"memory_brain": _FakeBrain()}}).render()
    assert "FRIDAY Diagnostics" in out
    assert "memory_brain" in out


def test_from_launcher_uses_components():
    class L:
        components = {"brains": {"memory_brain": _FakeBrain()}}

    d = from_launcher(L())
    assert "memory_brain" in d.brains()
