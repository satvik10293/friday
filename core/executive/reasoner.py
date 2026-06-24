"""
core/executive/reasoner.py — FRIDAY 4.0 (M5)
The Reasoner: analyze a ContextPackage (or raw goals/memories) and produce a
ReasoningResult — priorities, contradictions, missing information, and a
confidence with an explicit rationale.

The engine is heuristic and deterministic (no LLM yet) and decomposed into four
independently testable capabilities: memory, goal, dependency, and conflict
reasoning. An LLM reasoner can later replace any single method behind the same
interface.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

log = logging.getLogger("friday.executive.reasoner")

# Tokens that signal a negation/contradiction when one memory has them and a
# near-identical memory does not.
_NEGATIONS = ("not", "no longer", "isn't", "is not", "never", "stopped", "cancelled")


@dataclass
class ReasoningResult:
    priorities: list = field(default_factory=list)       # ranked focus dicts
    contradictions: list = field(default_factory=list)   # list[dict(a, b, why)]
    missing_info: list = field(default_factory=list)     # list[str]
    confidence: float = 0.0
    rationale: str = ""
    recommended_focus: Optional[dict] = None
    considered: int = 0

    def to_dict(self) -> dict:
        return dict(self.__dict__)


class Reasoner:
    def __init__(self) -> None:
        self._cycles = 0

    # ── top-level ──────────────────────────────────────────────────────────────
    def analyze(self, context, goals: Optional[list] = None) -> ReasoningResult:
        """`context` is a ContextPackage (preferred) or a plain dict. `goals` may
        be passed explicitly (Goal objects) for richer dependency reasoning."""
        memories = _attr(context, "memories", [])
        ctx_goals = _attr(context, "goals", [])
        focus_items = _attr(context, "focus_items", [])

        contradictions = self.reason_memory(memories)
        priorities = self.reason_goals(focus_items or ctx_goals)
        dep_missing = self.reason_dependencies(goals or [])
        conflicts = self.reason_conflicts(goals or [])

        missing = list(dep_missing)
        if not memories:
            missing.append("no relevant memories found")
        if not ctx_goals and not goals:
            missing.append("no active goals to reason about")

        considered = len(memories) + len(ctx_goals) + len(goals or [])
        recommended = priorities[0] if priorities else None
        confidence = self._confidence(context, contradictions, missing, considered)

        rationale = self._rationale(priorities, contradictions, missing, conflicts)
        self._cycles += 1
        return ReasoningResult(
            priorities=priorities, contradictions=contradictions + conflicts,
            missing_info=missing, confidence=confidence, rationale=rationale,
            recommended_focus=recommended, considered=considered,
        )

    # ── capabilities (each independently testable) ─────────────────────────────
    def reason_memory(self, memories: list[dict]) -> list[dict]:
        """Detect contradictory memories: two memories on the same topic where one
        negates the other."""
        out: list[dict] = []
        for i in range(len(memories)):
            for j in range(i + 1, len(memories)):
                a, b = memories[i], memories[j]
                if self._same_topic(a, b) and self._contradicts(a, b):
                    out.append({
                        "a": str(a.get("content", ""))[:120],
                        "b": str(b.get("content", ""))[:120],
                        "why": "same topic, opposing polarity",
                    })
        return out

    def reason_goals(self, items: list) -> list[dict]:
        """Rank goals/focus items by salience. Accepts attention-score dicts or
        goal dicts; returns a normalized priority list."""
        norm = []
        for it in items:
            if not isinstance(it, dict):
                continue
            score = it.get("score")
            if score is None:
                # goal dict: derive a rough score from priority (1=highest)
                score = max(0.0, (10 - it.get("priority", 5)) / 9.0)
            norm.append({
                "target_id": it.get("target_id") or it.get("goal_id", ""),
                "label": it.get("label") or it.get("title", ""),
                "score": round(float(score), 4),
            })
        return sorted(norm, key=lambda d: d["score"], reverse=True)

    def reason_dependencies(self, goals: list) -> list[str]:
        """Identify goals whose dependencies are unmet (a class of missing info)."""
        by_id = {getattr(g, "goal_id", None): g for g in goals}
        missing: list[str] = []
        for g in goals:
            for dep_id in getattr(g, "dependencies", []) or []:
                dep = by_id.get(dep_id)
                from core.goals import GoalStatus
                if dep is None:
                    missing.append(f"goal '{getattr(g, 'title', '')}' depends on unknown {dep_id}")
                elif dep.status != GoalStatus.COMPLETED:
                    missing.append(
                        f"goal '{getattr(g, 'title', '')}' waits on '{dep.title}' ({dep.status.value})")
        return missing

    def reason_conflicts(self, goals: list) -> list[dict]:
        """Detect competing goals: two ACTIVE goals with the same title or sharing
        a parent both active simultaneously."""
        from core.goals import GoalStatus
        active = [g for g in goals if getattr(g, "status", None) == GoalStatus.ACTIVE]
        out: list[dict] = []
        seen_titles: dict[str, str] = {}
        for g in active:
            title = getattr(g, "title", "")
            if title in seen_titles:
                out.append({"a": seen_titles[title], "b": g.goal_id,
                            "why": f"two active goals named '{title}'"})
            seen_titles[title] = g.goal_id
        return out

    # ── diagnostics ────────────────────────────────────────────────────────────
    def metrics(self) -> dict:
        return {"reasoning_cycles": self._cycles}

    def health(self) -> dict:
        return {"status": "ok", "reasoning_cycles": self._cycles}

    # ── internals ──────────────────────────────────────────────────────────────
    @staticmethod
    def _same_topic(a: dict, b: dict) -> bool:
        ta, tb = (a.get("topic") or "").lower(), (b.get("topic") or "").lower()
        if ta and ta == tb:
            return True
        # fallback: significant word overlap in content
        wa = set(str(a.get("content", "")).lower().split())
        wb = set(str(b.get("content", "")).lower().split())
        wa.discard(""); wb.discard("")
        if not wa or not wb:
            return False
        overlap = len(wa & wb) / min(len(wa), len(wb))
        return overlap >= 0.5

    @staticmethod
    def _contradicts(a: dict, b: dict) -> bool:
        ca, cb = str(a.get("content", "")).lower(), str(b.get("content", "")).lower()
        neg_a = any(n in ca for n in _NEGATIONS)
        neg_b = any(n in cb for n in _NEGATIONS)
        return neg_a != neg_b   # exactly one is negated → opposing polarity

    @staticmethod
    def _confidence(context, contradictions: list, missing: list, considered: int) -> float:
        base = _attr(context, "confidence", 0.0) or 0.0
        if considered and base == 0.0:
            base = min(1.0, considered / 8.0)
        penalty = 0.12 * len(contradictions) + 0.08 * len(missing)
        return round(max(0.0, min(1.0, base - penalty)), 3)

    @staticmethod
    def _rationale(priorities, contradictions, missing, conflicts) -> str:
        parts = []
        if priorities:
            parts.append(f"top focus: {priorities[0]['label'] or priorities[0]['target_id']}")
        if contradictions:
            parts.append(f"{len(contradictions)} contradiction(s)")
        if conflicts:
            parts.append(f"{len(conflicts)} goal conflict(s)")
        if missing:
            parts.append(f"{len(missing)} gap(s)")
        return "; ".join(parts) if parts else "nothing salient to reason about"


def _attr(obj, name, default):
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)
