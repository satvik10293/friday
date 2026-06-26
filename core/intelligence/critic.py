"""
core/intelligence/critic.py — FRIDAY 4.0 (M12)
The critic engine (Part 6). Every important answer is reviewed for logic gaps,
possible hallucinations, internal conflicts, missing information, weak arguments,
and overconfidence — and the critic returns concrete improvement suggestions plus a
confidence adjustment. Deterministic and local.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

_HEDGE = re.compile(r"\b(maybe|perhaps|might|possibly|i think|probably|not sure|unclear)\b", re.I)
_NEG = re.compile(r"\b(not|never|no|cannot|isn't|won't|doesn't)\b", re.I)
_WORD = re.compile(r"[a-z0-9]+")


@dataclass
class CriticReport:
    ok: bool = True
    issues: list = field(default_factory=list)
    suggestions: list = field(default_factory=list)
    confidence_delta: float = 0.0      # added to the answer's confidence
    severity: str = "low"

    def to_dict(self) -> dict:
        return dict(self.__dict__)


class CriticEngine:
    def review(self, text: str, *, structured: Optional[dict] = None,
               context: Optional[dict] = None, confidence: float = 0.5) -> CriticReport:
        structured = structured or {}
        context = context or {}
        report = CriticReport()

        # 1) logic / emptiness
        if not text or len(text.strip()) < 8:
            report.issues.append("answer is empty or too short")
            report.suggestions.append("produce a substantive answer")
            report.confidence_delta -= 0.2

        # 2) missing information
        if not context.get("knowledge") and not context.get("memories"):
            report.issues.append("no supporting knowledge/memory in context")
            report.suggestions.append("retrieve supporting context before answering")
            report.confidence_delta -= 0.1

        # 3) possible hallucination — claims grounded in nothing
        if text and not structured.get("steps") and not structured.get("items") \
                and not context.get("knowledge"):
            report.suggestions.append("ground claims in retrieved evidence")

        # 4) internal conflict — both an assertion and its negation about the subject
        if _NEG.search(text) and re.search(r"\b(is|are|will|can)\b", text) and len(text) < 40:
            report.issues.append("possible internal contradiction")

        # 5) weak arguments / hedging
        hedges = len(_HEDGE.findall(text or ""))
        if hedges >= 2:
            report.issues.append("hedged / weak argument")
            report.suggestions.append("commit to a position or state the uncertainty explicitly")
            report.confidence_delta -= 0.05

        # 6) overconfidence relative to evidence
        if confidence > 0.8 and not context.get("knowledge"):
            report.issues.append("high confidence without supporting evidence")
            report.confidence_delta -= 0.1

        if not report.suggestions and not report.issues:
            report.suggestions.append("consider an alternative approach for robustness")

        report.severity = ("high" if report.confidence_delta <= -0.25 else
                           "medium" if report.confidence_delta <= -0.1 else "low")
        report.ok = report.confidence_delta > -0.2
        return report
