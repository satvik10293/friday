"""
core/perception/hub/reasoning.py — FRIDAY V3 (M17)
First-level cognitive reasoning over unified observations. Each rule is a small, pure,
independently-testable function `(unified, context) -> Optional[conclusion]`; the reasoner
runs them all and returns the conclusions that fired. Rules are modular and extensible —
register a new one (or inject a learned/LLM reasoner via the PluginService) without
touching the engine. This is *understanding*, not planning: it labels the situation; the
Executive decides what to do.

Built-in rules cover the milestone's examples:
  doorbell @ front door         → someone may have arrived
  laptop + keyboard + typing    → user is working
  phone + room + no user        → phone left behind
  bottle + running water + kitchen + morning → preparing breakfast
"""

from __future__ import annotations

from typing import Callable, Optional

_WORK_OBJECTS = {"laptop", "keyboard", "monitor", "mouse"}
_KITCHEN_OBJECTS = {"bottle", "cup", "mug", "kettle", "food", "pan", "plate"}
_ARRIVAL_SOUNDS = {"doorbell", "door_knock", "phone_ringing"}


def _conclusion(situation: str, confidence: float, because: str, category: str) -> dict:
    return {"situation": situation, "confidence": round(min(1.0, confidence), 4),
            "because": because, "category": category}


# ── built-in rules ──────────────────────────────────────────────────────────────────
def rule_arrival(u, ctx) -> Optional[dict]:
    sounds = set(u.audio_context.get("sounds", []))
    hit = sounds & _ARRIVAL_SOUNDS
    if not hit:
        return None
    where = u.location or "the door"
    door = "front door" if ("door" in where.lower() or "entrance" in where.lower()) else where
    return _conclusion(f"Someone may have arrived at the {door}.",
                       0.6 + 0.4 * u.confidence, f"heard {','.join(sorted(hit))}", "alert")


def rule_working(u, ctx) -> Optional[dict]:
    objs = set(o.lower() for o in u.related_objects)
    typing = "keyboard_typing" in u.audio_context.get("sounds", []) or \
        u.spatial_context.get("user_state") == "working"
    if objs & _WORK_OBJECTS and typing:
        return _conclusion("The user is working.", 0.7 + 0.3 * u.confidence,
                           "work objects present and typing/working activity", "user_state")
    return None


def rule_left_behind(u, ctx) -> Optional[dict]:
    objs = set(o.lower() for o in u.related_objects)
    no_one_here = not u.related_people and u.spatial_context.get("user_state") not in (
        "working", "at_desk", "present", "walking", "entering_room")
    user_elsewhere = ctx.get("room") and ctx.get("room") != u.location
    if "phone" in objs and no_one_here and user_elsewhere:
        return _conclusion(f"The phone may have been left behind in the {u.location}.",
                           0.55 + 0.3 * u.confidence, "phone present with no user in the room",
                           "alert")
    return None


def rule_breakfast(u, ctx) -> Optional[dict]:
    objs = set(o.lower() for o in u.related_objects)
    water = "running_water" in u.audio_context.get("sounds", [])
    kitchen = (u.location or "").lower() == "kitchen"
    if objs & _KITCHEN_OBJECTS and water and kitchen:
        morning = "morning" in (ctx.get("situation", "").lower())
        return _conclusion("The user is preparing breakfast.",
                           (0.7 if morning else 0.6) + 0.3 * u.confidence,
                           "kitchen items + running water in the kitchen", "user_state")
    return None


_DEFAULT_RULES: list = [rule_arrival, rule_working, rule_left_behind, rule_breakfast]


class CognitiveReasoner:
    def __init__(self, rules: Optional[list] = None) -> None:
        self._rules: list = list(rules if rules is not None else _DEFAULT_RULES)
        self._fired = 0

    def register_rule(self, rule: Callable) -> None:
        """Add a rule `(unified, context) -> Optional[conclusion]`. Extensibility seam."""
        self._rules.append(rule)

    def reason(self, unified, context: dict) -> list:
        conclusions = []
        for rule in self._rules:
            try:
                c = rule(unified, context or {})
            except Exception:  # noqa: BLE001 — a bad rule never breaks reasoning
                c = None
            if c:
                conclusions.append(c)
        conclusions.sort(key=lambda c: c["confidence"], reverse=True)
        self._fired += len(conclusions)
        return conclusions

    def metrics(self) -> dict:
        return {"rules": len(self._rules), "conclusions_fired": self._fired}
