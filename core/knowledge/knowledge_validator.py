"""
core/knowledge/knowledge_validator.py — FRIDAY 4.0 (M7)
Knowledge quality gate. Before a new piece of knowledge is stored, the validator
checks it against what FRIDAY already knows and returns a ValidationReport with a
recommendation: store (new), update (refine an existing entry), or reject.

Checks:
  • duplicate    — near-identical title/content already exists
  • contradiction — an active entry on the same subject asserts the opposite
  • outdated     — an older, lower-confidence entry the newcomer supersedes
  • low_confidence — the candidate itself is too weak to trust

Purely local and deterministic; no cloud, no ML beyond the shared embedder.
"""

from __future__ import annotations

import re
from typing import Optional

from .knowledge_models import KnowledgeEntry, ValidationReport

_NEG = re.compile(r"\b(not|never|no|cannot|can't|don't|doesn't|isn't|won't|"
                  r"avoid|incorrect|false|wrong|deprecated)\b")
_WORD = re.compile(r"[a-z0-9]+")


def _tokens(text: str) -> set[str]:
    return set(_WORD.findall((text or "").lower()))


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


class KnowledgeValidator:
    def __init__(self, store, *, dup_threshold: float = 0.85,
                 subject_threshold: float = 0.5,
                 low_confidence: float = 0.25) -> None:
        self._store = store
        self._dup = dup_threshold
        self._subject = subject_threshold
        self._low = low_confidence

    def validate(self, candidate: KnowledgeEntry,
                 peers: Optional[list[KnowledgeEntry]] = None) -> ValidationReport:
        report = ValidationReport()
        if candidate.confidence < self._low:
            report.low_confidence = True
            report.notes.append("candidate confidence below trust threshold")

        if peers is None:
            peers = self._store.list(category=candidate.category, status="active", limit=500)

        cand_title = _tokens(candidate.title)
        cand_body = _tokens(candidate.content)
        cand_neg = bool(_NEG.search(candidate.content or ""))

        for peer in peers:
            if peer.id == candidate.id:
                continue
            title_sim = _jaccard(cand_title, _tokens(peer.title))
            body_sim = _jaccard(cand_body, _tokens(peer.content))

            # duplicate: same thing said again
            if title_sim >= self._dup or body_sim >= self._dup:
                report.duplicates.append(peer.id)
                continue

            # same subject → check for contradiction / supersession
            if title_sim >= self._subject:
                peer_neg = bool(_NEG.search(peer.content or ""))
                if peer_neg != cand_neg and body_sim < self._dup:
                    report.contradictions.append({
                        "id": peer.id, "title": peer.title,
                        "reason": "opposite polarity on same subject",
                    })
                if (peer.confidence < candidate.confidence
                        and peer.updated_at <= candidate.updated_at):
                    report.outdated.append(peer.id)

        report.ok = not (report.duplicates or report.contradictions or report.low_confidence)
        report.recommendation = self._recommend(report)
        return report

    def _recommend(self, report: ValidationReport) -> str:
        if report.low_confidence and not report.outdated:
            return "reject"
        if report.duplicates or report.outdated:
            return "update"
        return "store"
