"""
core/skills/builtin/home_actions.py — controlling the physical home.

Governed skills that drive the house through Home Assistant (core/home/hass.py):
turn devices on/off, toggle them, notify the phone, and list what's controllable.
They run through the SAME SkillExecutor pipeline as every other action (policy ->
role -> approval -> audit + DecisionLog). All are SAFE + reversible (on/off), so
they're voice-runnable; nothing here can do anything a light switch can't undo.

If Home Assistant isn't configured yet (no URL/token), each skill returns
{"ok": False, "reason": "not_configured"} instead of failing — FRIDAY then tells
the owner how to connect it.
"""

from __future__ import annotations

import json
import logging
import pathlib
from typing import Any, Optional

from core.skills.permissions import Permission, RiskLevel
from core.skills.skill import Skill

log = logging.getLogger("friday.skills.home")

_CLIENT = None


def _client():
    """Lazy Home Assistant client, built from friday_config.json + the env token."""
    global _CLIENT
    if _CLIENT is None:
        cfg: dict = {}
        try:
            root = pathlib.Path(__file__).resolve().parents[3]
            p = root / "friday_config.json"
            if p.exists():
                cfg = json.loads(p.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            cfg = {}
        try:
            from core.infra.friday_secrets import load_env
            load_env()                      # so HASS_TOKEN is present in os.environ
        except Exception:  # noqa: BLE001
            pass
        from core.home.hass import HomeAssistant
        _CLIENT = HomeAssistant.from_config(cfg)
    return _CLIENT


def set_client(client) -> None:
    """Inject a client (tests / DI)."""
    global _CLIENT
    _CLIENT = client


class _HomeSkill(Skill):
    permission = Permission.SAFE
    risk_level = RiskLevel.MEDIUM
    tags = ("home", "act")

    def _switch(self, device: str, on: bool) -> dict:
        ha = _client()
        if not ha.available():
            return {"ok": False, "reason": "not_configured", "device": device}
        ok, eid = ha.set_by_name(device, on=on)
        if eid is None:
            return {"ok": False, "reason": "not_found", "device": device}
        return {"ok": ok, "entity_id": eid, "device": device,
                "reason": "" if ok else "call_failed"}


class HomeTurnOnSkill(_HomeSkill):
    name = "home.turn_on"
    description = "Turn a home device on (light, fan, TV, plug) via Home Assistant."
    input_schema = {"device": {"required": True, "type": str}}

    def run(self, context: Any, **kwargs) -> dict:
        return self._switch(str(kwargs.get("device", "")), True)


class HomeTurnOffSkill(_HomeSkill):
    name = "home.turn_off"
    description = "Turn a home device off via Home Assistant."
    input_schema = {"device": {"required": True, "type": str}}

    def run(self, context: Any, **kwargs) -> dict:
        return self._switch(str(kwargs.get("device", "")), False)


class HomeToggleSkill(_HomeSkill):
    name = "home.toggle"
    description = "Toggle a home device via Home Assistant."
    input_schema = {"device": {"required": True, "type": str}}

    def run(self, context: Any, **kwargs) -> dict:
        ha = _client()
        device = str(kwargs.get("device", ""))
        if not ha.available():
            return {"ok": False, "reason": "not_configured", "device": device}
        eid = ha.find_entity(device)
        if not eid:
            return {"ok": False, "reason": "not_found", "device": device}
        return {"ok": ha.toggle(eid), "entity_id": eid, "device": device}


class HomeListSkill(_HomeSkill):
    name = "home.list"
    description = "List the home devices FRIDAY can control via Home Assistant."
    risk_level = RiskLevel.LOW
    tags = ("home", "read")

    def run(self, context: Any, **kwargs) -> dict:
        ha = _client()
        if not ha.available():
            return {"ok": False, "reason": "not_configured", "devices": []}
        return {"ok": True, "devices": ha.controllable()}


class PhoneNotifySkill(_HomeSkill):
    name = "phone.notify"
    description = "Send a notification to the phone via the Home Assistant app."
    input_schema = {"message": {"required": True, "type": str},
                    "target": {"type": str}}

    def run(self, context: Any, **kwargs) -> dict:
        ha = _client()
        if not ha.available():
            return {"ok": False, "reason": "not_configured"}
        target = str(kwargs.get("target") or "notify")
        ok = ha.notify_phone(str(kwargs.get("message", "")), target=target)
        return {"ok": ok, "target": target}


HOME_SKILLS = [HomeTurnOnSkill, HomeTurnOffSkill, HomeToggleSkill,
               HomeListSkill, PhoneNotifySkill]


def register_home_skills(registry) -> None:
    for cls in HOME_SKILLS:
        if not registry.has(cls.name):
            registry.register(cls())
