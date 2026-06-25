"""
core/review/design_gate.py — FRIDAY 4.0 (M10)
The Design Challenge Gate. A milestone (or any non-trivial change) must answer the
eight design-challenge questions before implementation begins; a milestone whose
review is incomplete does not pass the gate.

This is the executable form of docs/ARCHITECTURE_REVIEW.md §9 — it turns a written
discipline into a checkable, observable artifact. Reviews can be persisted to JSON
so the gate decision is auditable.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional


class DesignQuestion(str, Enum):
    EXISTS = "why_does_this_exist"
    BREAKS_WITHOUT = "what_breaks_without_it"
    CRASH = "what_fails_if_it_crashes"
    SCALE = "what_at_100x_scale"
    SECURITY = "security_risks"
    PERFORMANCE = "performance_risks"
    REMOVE = "would_we_remove_in_six_months"
    SIMPLIFY = "can_this_be_simplified"


# The canonical ordering, with the human-readable prompt for each.
QUESTIONS: dict[str, str] = {
    DesignQuestion.EXISTS.value: "Why does this exist?",
    DesignQuestion.BREAKS_WITHOUT.value: "What breaks without it?",
    DesignQuestion.CRASH.value: "What fails if it crashes?",
    DesignQuestion.SCALE.value: "What happens at 100x scale?",
    DesignQuestion.SECURITY.value: "What are the security risks?",
    DesignQuestion.PERFORMANCE.value: "What are the performance risks?",
    DesignQuestion.REMOVE.value: "Would we remove this in six months?",
    DesignQuestion.SIMPLIFY.value: "Can this be simplified?",
}

_MIN_ANSWER_LEN = 12


@dataclass
class DesignReview:
    milestone: str
    answers: dict = field(default_factory=dict)     # question key -> answer text
    additive: bool = True
    created_at: float = field(default_factory=time.time)

    def answer(self, question, text: str) -> "DesignReview":
        key = question.value if isinstance(question, DesignQuestion) else str(question)
        if key not in QUESTIONS:
            raise KeyError(f"unknown design question: {key}")
        self.answers[key] = (text or "").strip()
        return self

    def to_dict(self) -> dict:
        return {"milestone": self.milestone, "answers": dict(self.answers),
                "additive": self.additive, "created_at": self.created_at}

    @staticmethod
    def from_dict(d: dict) -> "DesignReview":
        r = DesignReview(milestone=d.get("milestone", "?"),
                         additive=d.get("additive", True),
                         created_at=d.get("created_at", time.time()))
        r.answers = dict(d.get("answers", {}))
        return r


@dataclass
class DesignGateResult:
    milestone: str
    passed: bool
    missing: list = field(default_factory=list)      # unanswered question keys
    weak: list = field(default_factory=list)         # answered but too thin
    notes: str = ""

    def to_dict(self) -> dict:
        return dict(self.__dict__)


class DesignGate:
    """Evaluates DesignReviews. A review passes only when every question has a
    substantive answer (and the change is declared additive, per the M-series
    charter — set `require_additive=False` to relax)."""

    def __init__(self, *, require_additive: bool = True,
                 store_path: Optional[str | Path] = None) -> None:
        self._require_additive = require_additive
        self._store_path = Path(store_path) if store_path else None
        self._reviews: dict[str, DesignReview] = {}

    def evaluate(self, review: DesignReview) -> DesignGateResult:
        missing, weak = [], []
        for key in QUESTIONS:
            ans = review.answers.get(key, "").strip()
            if not ans:
                missing.append(key)
            elif len(ans) < _MIN_ANSWER_LEN:
                weak.append(key)
        passed = not missing and not weak
        notes = ""
        if self._require_additive and not review.additive:
            passed = False
            notes = "change is not declared additive (M-series charter)"
        return DesignGateResult(milestone=review.milestone, passed=passed,
                                missing=missing, weak=weak, notes=notes)

    def submit(self, review: DesignReview) -> DesignGateResult:
        """Evaluate and, if it passes, record the review (and persist if configured)."""
        result = self.evaluate(review)
        if result.passed:
            self._reviews[review.milestone] = review
            self._persist()
        return result

    def passes(self, milestone: str) -> bool:
        return milestone in self._reviews

    def get_review(self, milestone: str) -> Optional[DesignReview]:
        return self._reviews.get(milestone)

    def reviews(self) -> list[dict]:
        return [r.to_dict() for r in self._reviews.values()]

    # ── persistence ──────────────────────────────────────────────────────────────
    def _persist(self) -> None:
        if self._store_path is None:
            return
        try:
            self._store_path.parent.mkdir(parents=True, exist_ok=True)
            self._store_path.write_text(
                json.dumps({"reviews": self.reviews()}, indent=2), encoding="utf-8")
        except OSError:
            pass

    def load(self) -> int:
        if self._store_path is None or not self._store_path.exists():
            return 0
        try:
            data = json.loads(self._store_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return 0
        for d in data.get("reviews", []):
            r = DesignReview.from_dict(d)
            self._reviews[r.milestone] = r
        return len(self._reviews)

    def health(self) -> dict:
        return {"status": "ok", "reviews_passed": len(self._reviews),
                "questions": len(QUESTIONS), "require_additive": self._require_additive}


_gate: Optional[DesignGate] = None


def get_design_gate() -> DesignGate:
    global _gate
    if _gate is None:
        _gate = DesignGate()
    return _gate
