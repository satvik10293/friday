"""
core/cognition/background.py — FRIDAY 5.x (M23, Internal Mind)
Background cognition: FRIDAY keeps thinking when nobody is speaking. A single
bounded `tick()` — scheduled on the Runtime, never a `while True` — performs:

    memory consolidation · unfinished-goal review · self-reflection ·
    curiosity generation

How much runs each tick is budgeted from live resources (the Executive's
cognitive-budget rule: an overloaded machine thinks less in the background).
Background cognition NEVER blocks a response — everything here is off the
request path, and every pass is observable via `status()` and the thought
stream.

Directives 1 and 12 of docs/FRIDAY_5X_COGNITIVE_EVOLUTION.md.
"""

from __future__ import annotations

import logging
import time

log = logging.getLogger("friday.cognition.background")

_BUSY_CPU_PCT = 75.0          # above this the tick only does the cheapest work


def _active_goals(goals) -> list:
    """Duck-typed: GoalService (list_goals) or anything exposing active()."""
    if hasattr(goals, "active"):
        return list(goals.active())
    from core.goals.models import GoalStatus
    return list(goals.list_goals(GoalStatus.ACTIVE))


class BackgroundCognition:
    def __init__(self, *, thoughts, memory=None, goals=None, self_model=None,
                 generator=None, notifier=None, interval_s: float = 300.0) -> None:
        self.thoughts = thoughts
        self.memory = memory
        self.goals = goals
        self.self_model = self_model
        self.generator = generator          # GoalGenerator (M28)
        self.notifier = notifier            # ProactiveNotifier (M49) — optional
        self.interval_s = interval_s
        self.ticks = 0
        self.last_report: dict = {}

    # ── budgeting ─────────────────────────────────────────────────────────────────
    def _budget(self) -> str:
        """full | light — decided from live CPU load (cognitive budget)."""
        try:
            import psutil
            if psutil.cpu_percent(interval=None) > _BUSY_CPU_PCT:
                return "light"
        except Exception:  # noqa: BLE001
            pass
        return "full"

    # ── the one bounded pass ──────────────────────────────────────────────────────
    def tick(self) -> dict:
        t0 = time.perf_counter()
        budget = self._budget()
        report: dict = {"budget": budget}

        report["reflection"] = self._reflect()
        report["goals"] = self._review_goals()
        if budget == "full":
            report["consolidation"] = self._consolidate()
            report["curiosity"] = self._wonder()
            report["proposals"] = self._propose()

        # proactive presence (M49): after thinking, surface the single most
        # salient new thought/proposal to the owner (rate-limited, never nags)
        if self.notifier is not None:
            surfaced = self.notifier.check()
            if surfaced:
                report["notified"] = surfaced

        self.ticks += 1
        report["ms"] = round((time.perf_counter() - t0) * 1000.0, 1)
        self.last_report = report
        log.debug("background cognition tick: %s", report)
        return report

    # ── passes (each guarded; a failure is data) ──────────────────────────────────
    def _consolidate(self) -> dict:
        if self.memory is None:
            return {"status": "no-memory"}
        try:
            return {"status": "ok", **(self.memory.consolidate() or {})}
        except Exception as e:  # noqa: BLE001
            return {"status": "failed", "error": str(e)}

    def _review_goals(self) -> dict:
        if self.goals is None:
            return {"status": "no-goals"}
        try:
            active = _active_goals(self.goals)
            for goal in active[:3]:
                title = getattr(goal, "title", None) or str(goal)
                self.thoughts.think("reminder", f"Unfinished goal: {title}",
                                    source="background")
            return {"status": "ok", "active": len(active)}
        except Exception as e:  # noqa: BLE001
            return {"status": "failed", "error": str(e)}

    def _reflect(self) -> dict:
        if self.self_model is None:
            return {"status": "no-self-model"}
        try:
            snap = self.self_model.snapshot()
            resources = snap.get("resources", {})
            if resources.get("ram_pct", 0.0) > 85.0:
                self.thoughts.think(
                    "concern", f"Memory pressure at {resources['ram_pct']:.0f}% — "
                    "I should avoid loading more models.", source="background",
                    confidence=0.8)
            perf = snap.get("performance", {})
            if perf.get("avg_confidence") is not None and perf["avg_confidence"] < 0.5:
                self.thoughts.think(
                    "concern", "My recent answers have been low-confidence; "
                    "deeper local reasoning is being used often.",
                    source="background", confidence=0.7)
            return {"status": "ok"}
        except Exception as e:  # noqa: BLE001
            return {"status": "failed", "error": str(e)}

    def _propose(self) -> dict:
        """Autonomous goal generation (M28): turn lessons, curiosity and
        concerns into human-gated goal proposals."""
        if self.generator is None:
            return {"status": "no-generator"}
        try:
            report = self.generator.propose()
            for title in report.get("proposed", []):
                self.thoughts.think("planning", f"I proposed a goal for myself: "
                                    f"{title} (awaiting Satvik's approval).",
                                    source="background", confidence=0.6)
            return {"status": "ok", **report}
        except Exception as e:  # noqa: BLE001
            return {"status": "failed", "error": str(e)}

    def _wonder(self) -> dict:
        """Curiosity: surface a recent memory topic worth revisiting."""
        if self.memory is None:
            return {"status": "no-memory"}
        try:
            hits = self.memory.recall("recent topics Satvik cares about", k=3)
            topic = next((h.get("topic") for h in hits if h.get("topic")), None)
            if topic:
                self.thoughts.think(
                    "hypothesis", f"'{topic}' keeps coming up — worth learning "
                    "more about it.", source="background", confidence=0.4)
            return {"status": "ok", "topic": topic}
        except Exception as e:  # noqa: BLE001
            return {"status": "failed", "error": str(e)}

    # ── lifecycle ─────────────────────────────────────────────────────────────────
    def attach(self, runtime) -> None:
        """Schedule the periodic tick on the runtime (jittered so idle work
        never synchronizes with anything else)."""
        runtime.schedule("background_cognition", self.tick, every=self.interval_s,
                         jitter=self.interval_s * 0.1)
        try:
            runtime.register_health("background_cognition", self.status)
        except Exception:  # noqa: BLE001
            log.debug("health registration failed", exc_info=True)

    def status(self) -> dict:
        return {"status": "ok", "ticks": self.ticks,
                "interval_s": self.interval_s, "last": self.last_report}
