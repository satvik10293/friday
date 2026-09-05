"""
core/skills/builtin/system_actions.py — M34 Executive Supremacy.
Every FridayAction capability as a governed Skill: 37 thin wrappers that
DELEGATE to core/io/friday_action.FridayAction (the single implementation —
refactor, not rewrite) and execute only through the SkillExecutor pipeline
(policy → role → approval → sandbox → audit + DecisionLog).

Risk tiers (plan/MASTER_PLAN.md, M34):
  Tier 1  read-only          → Permission.SAFE,          RiskLevel.LOW
  Tier 2  reversible         → Permission.SAFE,          RiskLevel.MEDIUM
  Tier 3  consequential      → Permission.USER_APPROVAL, RiskLevel.HIGH
  Tier 3+ machine-altering   → Permission.ADMIN_ONLY,    RiskLevel.HIGH/CRITICAL

`shell.run` carries the "shell" tag on purpose: the default PolicyEngine
DENIES shell execution outright. The skill existing does not make it usable —
enabling it is an explicit owner act (replace the policy, ideally with a
command allowlist). m29 posture: spoken input is an attack surface.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Optional

from core.skills.permissions import Permission, RiskLevel
from core.skills.skill import Skill

_action = None
_action_lock = threading.Lock()


def _get_action():
    """Lazy singleton — FridayAction probes hardware capabilities on init."""
    global _action
    with _action_lock:
        if _action is None:
            from core.io.friday_action import FridayAction
            _action = FridayAction()
    return _action


@dataclass(frozen=True)
class ActionSpec:
    skill_name: str
    method: str
    description: str
    permission: Permission
    risk: RiskLevel
    tags: tuple
    schema: dict = field(default_factory=dict)
    timeout: Optional[float] = None       # None → executor default (15s)


_T1 = (Permission.SAFE, RiskLevel.LOW)
_T2 = (Permission.SAFE, RiskLevel.MEDIUM)
_T3 = (Permission.USER_APPROVAL, RiskLevel.HIGH)

_SPECS: list[ActionSpec] = [
    # ── Tier 1 — read-only, auto-approved ────────────────────────────────────
    ActionSpec("system.screenshot", "screenshot", "Capture the screen to a file.",
               *_T1, ("system", "read"), {"path": {"type": str}}),
    ActionSpec("clipboard.get", "get_clipboard", "Read the clipboard text.",
               *_T1, ("system", "read")),
    ActionSpec("display.get_brightness", "get_brightness", "Read screen brightness.",
               *_T1, ("display", "read")),
    ActionSpec("system.summary", "get_system_summary", "CPU / RAM / disk / battery summary.",
               *_T1, ("system", "read")),
    ActionSpec("net.wifi_status", "get_wifi_status", "Current Wi-Fi connection details.",
               *_T1, ("net", "read")),
    ActionSpec("net.check_internet", "check_internet", "Is the internet reachable?",
               *_T1, ("net", "read")),
    ActionSpec("net.ip", "get_ip", "Local IP address.",
               *_T1, ("net", "read")),
    ActionSpec("files.search", "search_files", "Search files by name/extension.",
               *_T1, ("files", "read"),
               {"query": {"required": True, "type": str},
                "folder": {"type": str}, "extension": {"type": str}}),
    ActionSpec("files.recent", "get_recent_files", "Most recently modified files.",
               *_T1, ("files", "read"), {"count": {"type": int}}),
    ActionSpec("files.open", "open_file", "Open a file or folder with its default program.",
               *_T2, ("files", "act"), {"path": {"required": True, "type": str}}),
    ActionSpec("files.find_open", "find_and_open", "Find a file by name and open it.",
               *_T2, ("files", "act"),
               {"query": {"required": True, "type": str},
                "folder": {"type": str}, "extension": {"type": str}}),
    ActionSpec("screen.locate", "locate_text",
               "Find where visible text sits on screen (coordinates, read-only).",
               *_T1, ("screen", "read"), {"query": {"required": True, "type": str}}),
    ActionSpec("screen.locate_image", "locate_image",
               "Find where an icon/reference image sits on screen (read-only).",
               *_T1, ("screen", "read"),
               {"template_path": {"required": True, "type": str},
                "threshold": {"type": float}}),
    ActionSpec("screen.teach_icon", "teach_icon",
               "Remember the icon under the cursor by name (point-and-teach).",
               *_T2, ("screen", "act"),
               {"name": {"required": True, "type": str}, "size": {"type": int}}),
    ActionSpec("vision.describe", "describe_image",
               "Look at an image file and describe what's in it (read-only).",
               *_T1, ("vision", "read"), {"path": {"required": True, "type": str}}),
    ActionSpec("system.capabilities", "capabilities", "Which action capabilities are available.",
               *_T1, ("system", "read")),
    ActionSpec("system.battery_alert", "start_battery_alert",
               "Start the background low-battery monitor.",
               *_T1, ("system", "monitor"), {"threshold": {"type": int}}),

    # ── Tier 2 — reversible, policy-evaluated, no human gate ─────────────────
    ActionSpec("app.open", "open_app", "Open an application by name.",
               *_T2, ("app", "act"), {"name": {"required": True, "type": str}}),
    ActionSpec("window.focus", "focus_window", "Focus a window by title.",
               *_T2, ("window", "act"), {"title": {"required": True, "type": str}}),
    ActionSpec("window.minimize", "minimize_window", "Minimize a window (active if untitled).",
               *_T2, ("window", "act"), {"title": {"type": str}}),
    ActionSpec("window.maximize", "maximize_window", "Maximize a window (active if untitled).",
               *_T2, ("window", "act"), {"title": {"type": str}}),
    ActionSpec("audio.set_volume", "set_volume", "Set system volume (0–100).",
               *_T2, ("audio", "act"), {"level": {"required": True, "type": int}}),
    ActionSpec("audio.mute", "mute", "Mute system audio.", *_T2, ("audio", "act")),
    ActionSpec("audio.unmute", "unmute", "Unmute system audio.", *_T2, ("audio", "act")),
    ActionSpec("media.play_pause", "media_play_pause", "Toggle media play/pause.",
               *_T2, ("media", "act")),
    ActionSpec("media.play_music", "play_music",
               "Actually start music playing (launches Spotify and plays).",
               *_T2, ("media", "act"), {"query": {"type": str}}),
    ActionSpec("media.next", "media_next", "Next media track.", *_T2, ("media", "act")),
    ActionSpec("media.prev", "media_prev", "Previous media track.", *_T2, ("media", "act")),
    ActionSpec("display.brightness_up", "brightness_up", "Raise screen brightness.",
               *_T2, ("display", "act"), {"step": {"type": int}}),
    ActionSpec("display.brightness_down", "brightness_down", "Lower screen brightness.",
               *_T2, ("display", "act"), {"step": {"type": int}}),
    ActionSpec("display.set_brightness", "set_brightness", "Set screen brightness (0–100).",
               *_T2, ("display", "act"), {"level": {"required": True, "type": int}}),
    ActionSpec("web.open_url", "open_url", "Open a URL in the default browser.",
               *_T2, ("web", "act"), {"url": {"required": True, "type": str}}),
    ActionSpec("clipboard.copy", "copy_to_clipboard", "Copy text to the clipboard.",
               *_T2, ("system", "act"), {"text": {"required": True, "type": str}}),
    ActionSpec("input.move_mouse", "move_mouse", "Move the mouse cursor.",
               *_T2, ("input", "act"),
               {"x": {"required": True, "type": int}, "y": {"required": True, "type": int},
                "duration": {"type": (int, float)}}),
    ActionSpec("input.scroll", "scroll", "Scroll the active window.",
               *_T2, ("input", "act"), {"clicks": {"type": int}, "direction": {"type": str}}),

    # ── Tier 3 — consequential, human approval required ──────────────────────
    ActionSpec("app.close", "close_app", "Close an application by name.",
               *_T3, ("app", "act"), {"name": {"required": True, "type": str}}),
    ActionSpec("input.type_text", "type_text", "Type text as keyboard input.",
               *_T3, ("input", "act"),
               {"text": {"required": True, "type": str}, "interval": {"type": (int, float)}}),
    ActionSpec("input.press_key", "press_key", "Press a keyboard key.",
               *_T3, ("input", "act"), {"key": {"required": True, "type": str}}),
    ActionSpec("input.click", "click", "Click the mouse.",
               *_T3, ("input", "act"),
               {"x": {"type": int}, "y": {"type": int}, "button": {"type": str}}),
    # screen-clicks do OCR/template matching (slow on a CPU, and the first call
    # loads the OCR model), so give them a roomy sandbox budget — the downscaled
    # OCR keeps typical calls quick; this only covers the one-time model load.
    ActionSpec("screen.click_text", "click_text",
               "Find a visible text label on screen and click it.",
               *_T3, ("input", "act"),
               {"query": {"required": True, "type": str}, "button": {"type": str}},
               timeout=45.0),
    ActionSpec("screen.click_image", "click_image",
               "Find an icon/reference image on screen and click it.",
               *_T3, ("input", "act"),
               {"template_path": {"required": True, "type": str},
                "button": {"type": str}, "threshold": {"type": float}},
               timeout=45.0),
    ActionSpec("screen.click_icon", "click_icon",
               "Find a previously-taught icon by name and click it.",
               *_T3, ("input", "act"),
               {"name": {"required": True, "type": str},
                "button": {"type": str}, "threshold": {"type": float}},
               timeout=45.0),

    # ── Tier 3+ — machine-altering, admin role + approval ─────────────────────
    ActionSpec("shell.run", "run_shell",
               "Run a shell command. DENIED by default policy — enabling is an "
               "explicit owner act.",
               Permission.ADMIN_ONLY, RiskLevel.CRITICAL, ("shell", "act"),
               {"command": {"required": True, "type": str}, "timeout": {"type": int}}),
    ActionSpec("system.startup_add", "add_to_startup", "Register a program to run at startup.",
               Permission.ADMIN_ONLY, RiskLevel.HIGH, ("system", "startup", "act"),
               {"name": {"required": True, "type": str},
                "exe_path": {"required": True, "type": str}}),
    ActionSpec("system.startup_remove", "remove_from_startup", "Remove a startup entry.",
               Permission.ADMIN_ONLY, RiskLevel.HIGH, ("system", "startup", "act"),
               {"name": {"required": True, "type": str}}),
    ActionSpec("power.sleep", "sleep_pc", "Put the PC to sleep.",
               Permission.ADMIN_ONLY, RiskLevel.HIGH, ("power", "act")),
    ActionSpec("power.restart", "restart_pc", "Restart the PC.",
               Permission.ADMIN_ONLY, RiskLevel.CRITICAL, ("power", "act"),
               {"delay": {"type": int}}),
]


class SystemActionSkill(Skill):
    """One governed wrapper around a single FridayAction method."""

    def __init__(self, spec: ActionSpec) -> None:
        self._spec = spec
        self.name = spec.skill_name
        self.description = spec.description
        self.permission = spec.permission
        self.risk_level = spec.risk
        self.tags = spec.tags
        self.input_schema = dict(spec.schema)
        self.timeout = spec.timeout        # per-skill sandbox budget (None = default)

    def run(self, context, **kwargs):
        from core.skills.exceptions import SkillExecutionError
        method = getattr(_get_action(), self._spec.method)
        try:
            return method(**kwargs)
        except (OSError, ValueError) as e:
            # an EXPECTED action failure (app not installed, no such window,
            # device absent) — a clean failure, not a bug. Surfacing it as a
            # SkillError lets the executor return an honest FailureResult and
            # log it quietly, instead of an alarming "skill crashed" traceback.
            raise SkillExecutionError(str(e)) from e

    def health(self) -> dict:
        caps = _get_action().capabilities()
        return {"name": self.name, "ok": True, "capabilities": caps}


def build_action_skills() -> list[SystemActionSkill]:
    return [SystemActionSkill(spec) for spec in _SPECS]


def register_action_skills(registry) -> None:
    """Register all 37 action skills (idempotent per registry)."""
    for skill in build_action_skills():
        if not registry.has(skill.name):
            registry.register(skill)


ALL_ACTION_SPECS = tuple(_SPECS)
