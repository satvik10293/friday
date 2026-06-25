"""M10 — Graceful degradation: Mission Control survives subsystem failure."""

import pytest

from core.mission_control import MissionControl, safe_call
from core.mission_control.resilience import Degraded, is_degraded
from core.security.auth import AuthStore, Authenticator


class Exploding:
    """A subsystem whose every access raises — the worst case."""
    def __getattr__(self, name):
        def _boom(*a, **k):
            raise RuntimeError(f"{name} exploded")
        return _boom


# ── safe_call primitive ───────────────────────────────────────────────────────────
def test_safe_call_returns_value():
    assert safe_call("x", lambda: 42) == 42


def test_safe_call_degrades_on_error():
    out = safe_call("memory", lambda: (_ for _ in ()).throw(RuntimeError("down")))
    assert is_degraded(out)
    assert isinstance(out, Degraded) and out.system == "memory"


def test_safe_call_custom_default():
    assert safe_call("x", lambda: 1 / 0, default={"status": "degraded"})["status"] == "degraded"


# ── cockpit survives failures ─────────────────────────────────────────────────────
def _mc(tmp_path, **kw):
    auth = Authenticator(store=AuthStore(path=tmp_path / "auth.db"))
    return MissionControl(authenticator=auth, **kw)


def test_state_with_no_subsystems(tmp_path):
    mc = _mc(tmp_path)
    st = mc.state()
    assert st["operational"] is True
    assert len(st["panels"]) == 7          # all panels still present (absent/ok)


def test_state_with_exploding_knowledge(tmp_path, goal_service):
    mc = _mc(tmp_path, knowledge_service=Exploding(), goal_service=goal_service)
    st = mc.state()
    assert st["operational"] is True
    assert "knowledge_space" in st["degraded"]
    # the healthy goal panel still works
    assert st["panels"]["goal_network"]["status"] == "ok"


def test_state_with_everything_broken(tmp_path):
    mc = _mc(tmp_path, executive=Exploding(), goal_service=Exploding(),
             knowledge_service=Exploding(), user_model=Exploding(),
             agent_runtime=Exploding())
    st = mc.state()
    # individual systems degrade; the whole system does not collapse
    assert st["operational"] is True
    assert len(st["degraded"]) >= 3


def test_panel_failure_isolated(tmp_path):
    mc = _mc(tmp_path, knowledge_service=Exploding())
    p = mc.panel("knowledge_space")
    assert is_degraded(p)


def test_health_reports_degraded(tmp_path):
    mc = _mc(tmp_path, knowledge_service=Exploding())
    h = mc.health()
    assert h["operational"] is True


def test_resource_monitor_degrades_gracefully(tmp_path):
    # resource monitor must not raise even if psutil is missing
    mc = _mc(tmp_path)
    p = mc.panel("resource_monitor")
    assert "system" in p           # present whether or not psutil exists
