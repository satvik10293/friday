"""
core/brains/automation/brain.py — FRIDAY (PC Automation agent)

The Automation Brain is FRIDAY's PC-automation agent: the society member that
OWNS the laptop itself — opening apps, playing music, volume/brightness,
windows, files, and system state. It is her "hands" for everything local.

It never touches the machine directly. Its hands are the governed action layer
(the M47 SkillExecutor, service "skills"), so every action it takes still runs
the full M3 security pipeline (policy -> clearance -> approval -> sandbox ->
audit). AUTONOMY POLICY: this agent runs `Permission.SAFE` skills ONLY — the
same posture as the voice + autonomous-goal gates. An above-SAFE task is
refused here (needs the owner's approval), never silently executed.

Two jobs:

  1. ACT — `act(skill, **args)` and the typed helpers (open_app, play_music,
     set_volume, screenshot, ...) run a PC task through the governed layer and
     return an HONEST result (never a canned "done" when nothing happened).

  2. WATCH — each society cycle it reads a cheap, read-only system snapshot and
     evaluates its automation rules (trigger -> action), reporting only on
     CHANGE: a rule that just became ready, or a fresh PC concern (battery low,
     disk nearly full). Reports flow to the Coordinator/Executive on the bus;
     it decides. This agent advises and acts, it does not command the society.
"""

from __future__ import annotations

from typing import Callable, Optional

from ..base import CognitiveBrain, SituationReport


class AutomationBrain(CognitiveBrain):
    name = "automation_brain"

    def __init__(self, *, services=None, config=None, report_bus=None) -> None:
        super().__init__(services=services, config=config, report_bus=report_bus)
        self.local.cache("fired", capacity=128)
        self.local.cache("done", capacity=128)          # a log of actions taken
        self._skills = None                              # the governed executor (lazy)
        self._rules: list = []                           # list[(name, predicate, action)]
        self._context: dict = {}
        self._battery_floor = int((config or {}).get("battery_floor", 15))
        self._disk_floor_gb = float((config or {}).get("disk_floor_gb", 5))

    # ── ACT: PC tasks through the governed, SAFE-only action layer ────────────────
    def act(self, skill_name: str, **args) -> dict:
        """Run one PC-control skill through the governed executor, SAFE-only.
        Returns {ok, skill, message} on success or {ok: False, skill, error}
        (with needs_approval=True when the skill is above SAFE). Never raises."""
        ex = self._resolve("_skills", "skills")
        if ex is None:
            return {"ok": False, "skill": skill_name,
                    "error": "the action layer isn't online yet"}
        try:
            from core.skills.permissions import Permission
            skill = ex.registry.get(skill_name)
        except Exception:  # noqa: BLE001 — unknown skill is a clean failure
            return {"ok": False, "skill": skill_name,
                    "error": f"I don't have an action called '{skill_name}'."}
        if skill.permission != Permission.SAFE:
            # narrow, never widen: an above-SAFE task waits for the owner
            return {"ok": False, "skill": skill_name, "needs_approval": True,
                    "error": "that needs your approval."}
        try:
            result = ex.execute(skill_name, args)
        except Exception as e:  # noqa: BLE001 — an action fault never breaks the brain
            return {"ok": False, "skill": skill_name, "error": str(e)}
        if getattr(result, "success", False):
            self.local.push("done", {"skill": skill_name, "args": args})
            return {"ok": True, "skill": skill_name, "message": result.data}
        return {"ok": False, "skill": skill_name,
                "error": getattr(result, "error", "it failed")}

    # typed conveniences — the vocabulary of the PC-automation domain
    def open_app(self, name: str) -> dict:
        return self.act("app.open", name=name)

    def play_music(self, query: Optional[str] = None) -> dict:
        return self.act("media.play_music", **({"query": query} if query else {}))

    def set_volume(self, level: int) -> dict:
        return self.act("audio.set_volume", level=int(level))

    def screenshot(self) -> dict:
        return self.act("system.screenshot")

    def system_summary(self) -> dict:
        return self.act("system.summary")

    # ── rules (trigger -> action), registered at runtime — data, not code ─────────
    def add_rule(self, name: str, predicate: Callable[[dict], bool], action: str) -> None:
        self._rules.append((name, predicate, action))

    def set_context(self, context: dict) -> None:
        """The Coordinator feeds the current unified context here (not raw data)."""
        self._context = dict(context or {})

    # ── WATCH: one read-only cognitive cycle ──────────────────────────────────────
    def observe(self):
        ex = self._resolve("_skills", "skills")
        # capabilities: probe once through the governed layer, then cache — so
        # health() can answer without executing anything on demand (the M46
        # addressable route is read-only and must not run skills from a guest
        # transcript).
        if ex is not None and self.local.get("caps") is None:
            probe = self.act("system.capabilities")
            if probe.get("ok") and isinstance(probe.get("message"), dict):
                self.local.set("caps", probe["message"])
        ctx = dict(self._context)
        ctx.update(self._system_snapshot())
        return ctx

    @staticmethod
    def _system_snapshot() -> dict:
        """Cheap, side-effect-free read of the state rules + concerns care about."""
        try:
            import psutil
            bat = psutil.sensors_battery()
            snap = {"battery": (round(bat.percent) if bat else None),
                    "plugged": (bool(bat.power_plugged) if bat else None)}
            for root in ("C:\\", "/"):
                try:
                    snap["disk_free_gb"] = round(psutil.disk_usage(root).free / 1e9, 1)
                    break
                except Exception:  # noqa: BLE001
                    continue
            return snap
        except Exception:  # noqa: BLE001 — snapshot is best-effort
            return {}

    def reason(self, analysis):
        ctx = analysis or {}
        fired = []
        for name, predicate, action in self._rules:
            try:
                if predicate(ctx):
                    fired.append({"rule": name, "action": action})
            except Exception:  # noqa: BLE001 — a bad rule never breaks the brain
                continue
        for f in fired:
            self.local.push("fired", f)

        concerns = []
        bat, plugged = ctx.get("battery"), ctx.get("plugged")
        if isinstance(bat, (int, float)) and bat <= self._battery_floor and plugged is False:
            concerns.append({"kind": "battery_low", "detail": f"battery at {bat}%",
                             "action": "remind you to plug in the charger"})
        dfree = ctx.get("disk_free_gb")
        if isinstance(dfree, (int, float)) and dfree < self._disk_floor_gb:
            concerns.append({"kind": "disk_low", "detail": f"only {dfree}GB free on disk",
                             "action": "help you free up disk space"})
        return {"fired": fired, "concerns": concerns}

    def generate_situation_report(self, insight) -> Optional[SituationReport]:
        insight = insight or {}
        fired = insight.get("fired") or []
        concerns = insight.get("concerns") or []
        concern_keys = sorted(c["kind"] for c in concerns)
        previous = self.local.get("last_concerns")
        self.local.set("last_concerns", concern_keys)

        if fired:
            actions = ", ".join(f["action"] for f in fired)
            return self._report(
                f"Automation: {len(fired)} rule(s) ready — {actions}.",
                confidence=0.7, priority=0.5, category="automation",
                recommended_action=fired[0]["action"],
                data={"fired": fired, "concerns": concerns})
        # a concern reports only when it FIRST appears — never every cycle (no nag)
        if concerns and concern_keys != (previous or []):
            c = concerns[0]
            return self._report(
                f"Heads-up: {c['detail']}.",
                confidence=0.8, priority=0.6, category="automation",
                recommended_action=c["action"], data={"concerns": concerns})
        return None

    # ── observability ────────────────────────────────────────────────────────────
    def capabilities(self) -> dict:
        """What her hands can do on this machine (cached from the last cycle)."""
        return dict(self.local.get("caps") or {})

    def health(self) -> dict:
        # honest health: report the real state of her hands, never a placeholder.
        # Read-only — reads cached capabilities, executes nothing.
        ex = getattr(self, "_skills", None) or self._service("skills")
        return {"status": "ok" if self._last_tick_ok else "degraded",
                "brain": self.name,
                "hands": "online" if ex is not None else "offline",
                "capabilities": self.capabilities(),
                "rules": len(self._rules),
                "actions_done": len(self.local.items("done")),
                "errors": self._errors,
                "last_report": self._last_report.summary if self._last_report else None}
