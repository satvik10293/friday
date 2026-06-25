"""M10 — Mission Control cockpit (panels, state, authenticated server)."""

import pytest

from core.mission_control import MissionControl
from core.security.auth import AuthStore, Authenticator


@pytest.fixture
def mc(tmp_path, goal_service, knowledge_service):
    auth = Authenticator(store=AuthStore(path=tmp_path / "auth.db"))
    knowledge_service.teach("Python", "a programming language")
    g = goal_service.create_goal("Ship M10", priority=1)
    goal_service.activate_goal(g.goal_id)
    return MissionControl(goal_service=goal_service, knowledge_service=knowledge_service,
                          authenticator=auth)


# ── panels / state ────────────────────────────────────────────────────────────────
def test_state_has_seven_panels(mc):
    st = mc.state()
    assert st["operational"] is True
    expected = {"cognitive_state", "goal_network", "knowledge_space", "agent_team",
                "resource_monitor", "security_center", "event_stream"}
    assert expected <= set(st["panels"].keys())


def test_goal_network_3d(mc):
    p = mc.panel("goal_network")
    assert p["status"] == "ok" and p["render"] == "3d"
    assert p["nodes"] and p["active"] >= 1


def test_knowledge_space_galaxy(mc):
    p = mc.panel("knowledge_space")
    assert p["status"] == "ok" and p["galaxy"] is True
    assert p["nodes"]


def test_agent_team_future_ready(mc):
    p = mc.panel("agent_team")
    assert p["status"] == "ready" and p["future"] == "M11"
    assert p["render"] == "3d"


def test_resource_monitor(mc):
    p = mc.panel("resource_monitor")
    assert "system" in p and "databases" in p and "models" in p


def test_security_center(mc):
    mc.authenticator.tokens.create("admin", ["admin"])
    p = mc.panel("security_center")
    assert p["status"] == "ok" and p["tokens"] >= 1


def test_event_stream(mc):
    mc.events.push("test.event", {"x": 1}, level="info")
    mc.events.push("danger", level="critical")
    p = mc.panel("event_stream")
    assert p["events"] and p["alerts"]


def test_cognitive_state_absent_without_brain(mc):
    p = mc.panel("cognitive_state")
    assert p["status"] in ("absent", "ok")


def test_health(mc):
    h = mc.health()
    assert h["operational"] is True and h["status"] in ("ok", "degraded")


# ── authenticated server ──────────────────────────────────────────────────────────
def test_server_serves_hud(mc):
    pytest.importorskip("flask")
    app = mc.server().build_app()
    client = app.test_client()
    r = client.get("/")
    assert r.status_code == 200
    body = r.get_data(as_text=True)
    assert "MISSION CONTROL" in body
    # security headers applied
    assert r.headers.get("X-Frame-Options") == "DENY"
    assert "Content-Security-Policy" in r.headers


def test_server_state_open_read(mc):
    pytest.importorskip("flask")
    client = mc.server().build_app().test_client()
    r = client.get("/api/state")
    assert r.status_code == 200
    assert "panels" in r.get_json()


def test_server_write_requires_auth(mc):
    pytest.importorskip("flask")
    client = mc.server().build_app().test_client()
    # no token → 401
    r = client.post("/api/event", json={"kind": "x"}, headers={"Origin": "http://127.0.0.1:5050"})
    assert r.status_code == 401


def test_server_write_with_admin_token(mc):
    pytest.importorskip("flask")
    tok = mc.authenticator.tokens.create("admin", ["admin"])
    client = mc.server().build_app().test_client()
    r = client.post("/api/event", json={"kind": "deploy"},
                    headers={"Origin": "http://127.0.0.1:5050", "X-API-Token": tok.secret})
    assert r.status_code == 200
    assert r.get_json()["pushed"]["kind"] == "deploy"


def test_server_foreign_origin_blocked(mc):
    pytest.importorskip("flask")
    tok = mc.authenticator.tokens.create("admin", ["admin"])
    client = mc.server().build_app().test_client()
    r = client.post("/api/event", json={"kind": "x"},
                    headers={"Origin": "http://evil.example.com", "X-API-Token": tok.secret})
    assert r.status_code == 401


def test_import_side_effect_free():
    import importlib
    importlib.import_module("core.mission_control")
    importlib.import_module("core.mission_control.ui")
