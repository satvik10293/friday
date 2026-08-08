"""
tests/test_home_assistant.py — FRIDAY's home bridge (Home Assistant).

Covers the client's name->entity resolution and high-level actions (mocked, no
HTTP) and the governed home skills, including the honest not-configured path.
"""

from __future__ import annotations

from core.home.hass import HomeAssistant


_STATES = [
    {"entity_id": "fan.living_room", "state": "off",
     "attributes": {"friendly_name": "Living Room Fan"}},
    {"entity_id": "light.kitchen", "state": "on",
     "attributes": {"friendly_name": "Kitchen Light"}},
    {"entity_id": "media_player.tv", "state": "idle",
     "attributes": {"friendly_name": "Living Room TV"}},
    {"entity_id": "sensor.temperature", "state": "21",
     "attributes": {"friendly_name": "Temperature"}},
]


def _client_with_states():
    ha = HomeAssistant("http://x:8123", "tok")
    ha.states = lambda: list(_STATES)          # type: ignore[assignment]
    return ha


# ── config / connectivity ─────────────────────────────────────────────────────

def test_available_requires_url_and_token():
    assert HomeAssistant("", "").available() is False
    assert HomeAssistant("http://x", "").available() is False
    assert HomeAssistant("http://x", "tok").available() is True


def test_from_config_reads_env_token(monkeypatch):
    monkeypatch.setenv("HASS_TOKEN", "envtok")
    ha = HomeAssistant.from_config({"home_assistant": {"url": "http://h:8123"}})
    assert ha.url == "http://h:8123"
    assert ha.available() is True


# ── name resolution ───────────────────────────────────────────────────────────

def test_find_entity_resolves_friendly_names():
    ha = _client_with_states()
    assert ha.find_entity("living room fan") == "fan.living_room"
    assert ha.find_entity("kitchen light") == "light.kitchen"
    assert ha.find_entity("tv") == "media_player.tv"


def test_find_entity_returns_none_for_unknown():
    assert _client_with_states().find_entity("dishwasher") is None


def test_controllable_lists_only_switchable_domains():
    c = _client_with_states().controllable()
    assert "Living Room Fan" in c and "Kitchen Light" in c and "Living Room TV" in c
    assert "Temperature" not in c          # a sensor isn't controllable


def test_set_by_name_calls_turn_on():
    ha = _client_with_states()
    calls = []
    ha.call_service = lambda dom, svc, entity_id=None, data=None: (
        calls.append((dom, svc, entity_id)) or True)          # type: ignore
    ok, eid = ha.set_by_name("living room fan", on=True)
    assert ok is True and eid == "fan.living_room"
    assert calls == [("homeassistant", "turn_on", "fan.living_room")]


# ── governed skills ───────────────────────────────────────────────────────────

class _FakeHA:
    def __init__(self, available=True):
        self._available = available

    def available(self):
        return self._available

    def set_by_name(self, name, *, on):
        return (True, "switch." + name.replace(" ", "_")) if name != "ghost" \
            else (False, None)

    def find_entity(self, name):
        return "fan.x" if name != "ghost" else None

    def toggle(self, eid):
        return True

    def controllable(self):
        return ["Living Room Fan", "Kitchen Light"]

    def notify_phone(self, message, *, target="notify"):
        return True


def test_turn_on_skill_switches_a_device():
    from core.skills.builtin import home_actions as H
    H.set_client(_FakeHA())
    r = H.HomeTurnOnSkill().run(None, device="living room fan")
    assert r["ok"] is True and r["device"] == "living room fan"


def test_turn_on_skill_reports_unknown_device():
    from core.skills.builtin import home_actions as H
    H.set_client(_FakeHA())
    r = H.HomeTurnOnSkill().run(None, device="ghost")
    assert r["ok"] is False and r["reason"] == "not_found"


def test_skills_are_honest_when_not_configured():
    from core.skills.builtin import home_actions as H
    H.set_client(_FakeHA(available=False))
    r = H.HomeTurnOnSkill().run(None, device="fan")
    assert r["ok"] is False and r["reason"] == "not_configured"


def test_phone_notify_skill():
    from core.skills.builtin import home_actions as H
    H.set_client(_FakeHA())
    r = H.PhoneNotifySkill().run(None, message="here's your phone")
    assert r["ok"] is True


def test_home_skills_are_safe_and_registered():
    from core.skills.builtin.home_actions import HOME_SKILLS
    from core.skills.permissions import Permission
    names = {s.name for s in HOME_SKILLS}
    assert {"home.turn_on", "home.turn_off", "home.toggle", "home.list",
            "phone.notify"} <= names
    assert all(s.permission == Permission.SAFE for s in HOME_SKILLS)
