"""
core/goals/generator.py — FRIDAY 5.x (M28, Phase D completion)
GoalGenerator: FRIDAY proposes her own goals. One bounded, deduplicated pass —
run from background cognition, never from a request path — turns what she
already knows into candidate goals:

    failed goals without a follow-up  →  a remediation goal from the lesson
    curiosity hypotheses ("'X' keeps coming up")  →  a learning goal for X
    repeated high-confidence concerns  →  an investigation goal

Every candidate is created through `GoalService.propose_goal()` and is
human-gated exactly like codex proposals: it sits PENDING with
`metadata.proposal_status == "proposed"`, invisible to the scheduler until
Satvik approves it (rejections are archived and never re-proposed).
"""

from __future__ import annotations

import logging
import re
from typing import Optional

from .models import GoalStatus
from .reflection import _lesson_for

log = logging.getLogger("friday.goals.generator")

_MAX_OPEN_PROPOSALS = 3
_MIN_CONCERN_CONFIDENCE = 0.7


def _norm(title: str) -> str:
    return re.sub(r"\s+", " ", (title or "").strip().lower())


class GoalGenerator:
    """Duck-typed over GoalService (propose_goal / list_goals / list_proposals)
    and the ThoughtStream (recent). Stateless between passes — dedup is derived
    from the store itself, so it survives restarts."""

    def __init__(self, goals, thoughts=None, *,
                 max_open_proposals: int = _MAX_OPEN_PROPOSALS) -> None:
        self.goals = goals
        self.thoughts = thoughts
        self.max_open_proposals = max_open_proposals
        self.proposed = 0
        self.skipped = 0

    # ── the one bounded pass ──────────────────────────────────────────────────
    def propose(self) -> dict:
        """Generate at most one proposal per source per pass; respect the open
        cap; never raise (a generation fault is data, not a crash)."""
        report: dict = {"proposed": [], "open": 0}
        try:
            known = self._known_titles()
            open_proposals = self._open_proposals()
            report["open"] = len(open_proposals)
            budget = self.max_open_proposals - len(open_proposals)
            for source, candidate in ((s, c) for s, c in (
                    ("failure", self._from_failures(known)),
                    ("curiosity", self._from_curiosity(known)),
                    ("concern", self._from_concerns(known))) if c):
                if budget <= 0:
                    self.skipped += 1
                    break
                title, description, evidence = candidate
                goal = self.goals.propose_goal(
                    title, description=description, source=source,
                    evidence=evidence)
                known.add(_norm(title))
                report["proposed"].append(goal.title)
                self.proposed += 1
                budget -= 1
        except Exception as e:  # noqa: BLE001
            log.debug("goal generation failed", exc_info=True)
            report["error"] = str(e)
        report["open"] += len(report["proposed"])
        return report

    # ── sources (each returns at most one candidate) ──────────────────────────
    def _from_failures(self, known: set) -> Optional[tuple]:
        """The most recent FAILED goal whose lesson has no follow-up yet."""
        failed = self.goals.list_goals(GoalStatus.FAILED)
        for goal in sorted(failed, key=lambda g: g.updated_at, reverse=True):
            if goal.metadata.get("proposed_by") == "friday":
                continue                     # don't chain proposals off proposals
            reason = goal.metadata.get("failure_reason", "") or "unknown failure"
            title = f"Address: {_lesson_for(reason)}"
            if _norm(title) in known:
                continue
            evidence = f"goal '{goal.title}' failed: {reason}"
            return title, f"Follow up on the failed goal '{goal.title}'.", evidence
        return None

    def _from_curiosity(self, known: set) -> Optional[tuple]:
        """A curiosity hypothesis from background cognition becomes a learning
        goal ('X' keeps coming up — worth learning more about it)."""
        for thought in self._recent("hypothesis"):
            m = re.search(r"'([^']+)'", thought.text)
            topic = m.group(1).strip() if m else ""
            if not topic:
                continue
            title = f"Learn more about {topic}"
            if _norm(title) in known:
                continue
            return title, f"Curiosity: {thought.text}", thought.text
        return None

    def _from_concerns(self, known: set) -> Optional[tuple]:
        """A high-confidence internal concern becomes an investigation goal."""
        for thought in self._recent("concern"):
            if thought.confidence < _MIN_CONCERN_CONFIDENCE:
                continue
            summary = thought.text.split("—")[0].split(";")[0].strip().rstrip(".")
            if not summary:
                continue
            title = f"Investigate: {summary}"
            if _norm(title) in known:
                continue
            return title, f"Recurring internal concern: {thought.text}", thought.text
        return None

    # ── dedup ─────────────────────────────────────────────────────────────────
    def _known_titles(self) -> set:
        """Every goal title ever stored — including archived (rejected)
        proposals — so nothing is proposed twice."""
        return {_norm(g.title) for g in self.goals.list_goals()}

    def _open_proposals(self) -> list:
        return self.goals.list_proposals()

    def _recent(self, kind: str) -> list:
        if self.thoughts is None:
            return []
        try:
            return self.thoughts.recent(10, kind=kind)
        except Exception:  # noqa: BLE001
            return []

    def status(self) -> dict:
        return {"proposed": self.proposed, "skipped": self.skipped,
                "max_open": self.max_open_proposals}
