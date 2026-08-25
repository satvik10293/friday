"""
core/awareness/situation.py — FRIDAY 5.x (M64)
"What's going on right now" and "why did you do that".

She pulls a coherent picture from whatever subsystems are live — perception
(vision/audio/space), the World Model (people, devices, the current project),
active goals, and the decision log — and narrates it like a person catching you
up. Nothing here perceives on its own; it reads what the rest of her already
knows and makes it legible. Every source is optional and guarded.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Optional

log = logging.getLogger("friday.awareness")


# How a route key becomes plain English in "why did you do that".
_ROUTE_PHRASES = {
    "notebook": "from my own distilled notes",
    "local_reasoner": "with my own on-device reasoning",
    "native": "by working it out in my own mind",
    "exact": "by computing it exactly myself",
    "reasoning": "by reasoning it through step by step",
    "cloud": "by consulting a cloud model",
    "council": "by polling several cloud models and synthesising",
    "project": "by reading your project's code",
    "screen": "by reading what's on your screen",
    "memory": "from what I remember",
    "skill": "by running an action",
}


def _route_to_phrase(route: list) -> str:
    for key in (route or []):
        base = str(key).split(":", 1)[0]
        if base in _ROUTE_PHRASES:
            return _ROUTE_PHRASES[base]
    if route:
        return f"via {route[0]}"
    return "from what I already knew"


def _part_of_day(t: Optional[float] = None) -> str:
    h = time.localtime(t).tm_hour
    if h < 5:
        return "late night"
    if h < 12:
        return "morning"
    if h < 17:
        return "afternoon"
    if h < 21:
        return "evening"
    return "night"


@dataclass
class Situation:
    part_of_day: str = ""
    room: str = ""
    activity: str = ""
    people: list = field(default_factory=list)
    objects: list = field(default_factory=list)
    perceiving: list = field(default_factory=list)     # which senses are live
    project: str = ""
    devices: list = field(default_factory=list)
    goals: list = field(default_factory=list)           # active goal titles
    recent_actions: list = field(default_factory=list)  # [(intent, route_phrase)]
    notes: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return dict(self.__dict__)

    def narrate(self) -> str:
        """A warm, spoken-style 'here's what's going on' — only the parts that
        are actually true right now."""
        bits = []

        # what she perceives
        if self.perceiving:
            senses = " and ".join(self.perceiving)
            head = f"Right now I'm watching through {senses}"
            if self.room:
                head += f", and we're in the {self.room}"
            bits.append(head + ".")
        elif self.room or self.activity:
            bits.append(f"It looks like {self.activity or 'things are quiet'}"
                        + (f" in the {self.room}" if self.room else "") + ".")
        else:
            bits.append(f"It's {self.part_of_day}. My eyes and ears are off right "
                        "now, so I'm going on what I know rather than what I can see.")

        if self.people:
            who = ", ".join(self.people[:4])
            bits.append(f"I can see {who}.")
        if self.objects:
            bits.append("Around us: " + ", ".join(self.objects[:6]) + ".")

        # what she's grounded in
        if self.project:
            bits.append(f"We're working in the {self.project} project.")
        if self.devices:
            bits.append("Connected devices: " + ", ".join(self.devices[:5]) + ".")

        # what she's working on
        if self.goals:
            g = "; ".join(self.goals[:3])
            bits.append(f"On my own I'm working on: {g}.")

        # what she just did
        if self.recent_actions:
            intent, phrase = self.recent_actions[0]
            label = intent or "your last question"
            bits.append(f"The last thing I handled was {label}, {phrase}.")

        if not bits:
            bits.append("Honestly, it's quiet — nothing notable is happening, and "
                        "I'm idle and ready.")
        return " ".join(bits)


def gather(*, world_model=None, perception=None, goals=None, decision_log=None,
           project=None, self_model=None, vision=None) -> Situation:
    """Assemble the current situation from whatever is available. Never raises."""
    s = Situation(part_of_day=_part_of_day())

    # ── perception hub: room / activity / people / objects ──────────────────────
    try:
        if perception is None:
            from core.perception.hub.service import get_perception_service
            perception = get_perception_service()
        snap = perception.situation() if perception is not None else {}
        if isinstance(snap, dict):
            s.room = snap.get("room", "") or ""
            s.activity = snap.get("activity", "") or ""
            s.people = [str(p) for p in (snap.get("people") or [])][:8]
            s.objects = [str(o) for o in (snap.get("objects") or [])][:12]
    except Exception:  # noqa: BLE001
        log.debug("perception snapshot failed", exc_info=True)

    # which senses are actually live (best-effort health probes)
    try:
        if vision is not None and getattr(vision, "health", None):
            h = vision.health()
            if isinstance(h, dict) and h.get("cameras"):
                s.perceiving.append("the camera")
    except Exception:  # noqa: BLE001
        log.debug("vision health probe failed", exc_info=True)

    # ── World Model: the project + connected devices ────────────────────────────
    try:
        if world_model is None:
            from core.world.world_model import WorldModel
            world_model = WorldModel()
        if project:
            s.project = project
        else:
            projects = world_model.entities_by_kind("project")
            if projects:
                s.project = projects[0].name
        devs = world_model.entities_by_kind("device")
        s.devices = [d.name for d in devs][:8]
        if not s.people:
            ppl = world_model.entities_by_kind("person")
            s.people = [p.name for p in ppl][:8]
    except Exception:  # noqa: BLE001
        log.debug("world-model read failed", exc_info=True)

    # ── active goals ────────────────────────────────────────────────────────────
    try:
        if goals is not None:
            active = None
            for meth in ("active", "list_active", "active_goals", "list"):
                fn = getattr(goals, meth, None)
                if callable(fn):
                    active = fn()
                    break
            for g in (active or [])[:5]:
                title = g.get("title") if isinstance(g, dict) else getattr(g, "title", None)
                if title:
                    s.goals.append(str(title))
    except Exception:  # noqa: BLE001
        log.debug("goals read failed", exc_info=True)

    # ── the last few things she did ─────────────────────────────────────────────
    try:
        if decision_log is None:
            from core.observability.decision_log import get_decision_log
            decision_log = get_decision_log()
        for d in decision_log.recent(limit=3):
            s.recent_actions.append(
                (d.get("intent") or "", _route_to_phrase(d.get("route") or [])))
    except Exception:  # noqa: BLE001
        log.debug("decision log read failed", exc_info=True)

    return s


def describe_situation(**kw) -> str:
    """The high-level call: gather + narrate. Never raises."""
    try:
        return gather(**kw).narrate()
    except Exception:  # noqa: BLE001
        log.debug("describe_situation failed", exc_info=True)
        return "I can't get a clear read on the situation right now."


def explain_last_decision(decision_log=None) -> str:
    """'Why did you do that?' — read the last decision and say, plainly, how she
    arrived at it and how confident she was. Never raises."""
    try:
        if decision_log is None:
            from core.observability.decision_log import get_decision_log
            decision_log = get_decision_log()
        recent = decision_log.recent(limit=1)
        if not recent:
            return ("I haven't actually done anything yet this session, so there's "
                    "nothing to explain.")
        d = recent[0]
        phrase = _route_to_phrase(d.get("route") or [])
        intent = d.get("intent")
        conf = d.get("confidence")
        skills = d.get("skills_invoked") or []
        models = d.get("models_used") or []

        parts = []
        lead = f"I handled {intent}" if intent else "I answered that"
        parts.append(f"{lead} {phrase}")
        if skills:
            parts.append(f"I ran: {', '.join(str(x) for x in skills[:3])}")
        if models:
            parts.append(f"the model behind it was {', '.join(str(m) for m in models[:2])}")
        if isinstance(conf, (int, float)) and conf:
            if conf >= 0.75:
                parts.append("and I was confident in it")
            elif conf >= 0.5:
                parts.append("and I was reasonably sure")
            else:
                parts.append("though I wasn't fully certain")
        rationale = (d.get("rationale") or "").strip()
        out = ". ".join(p.rstrip(".") for p in parts) + "."
        if rationale and "Intelligence OS" not in rationale:
            out += f" ({rationale})"
        return out
    except Exception:  # noqa: BLE001
        log.debug("explain_last_decision failed", exc_info=True)
        return "I can't reconstruct my reasoning for that one right now."
