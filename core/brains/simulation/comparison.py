"""
core/brains/simulation/comparison.py — FRIDAY V3 (M19)
Plan comparison + ranking. Given the evaluated candidate plans, sort them best-first by
composite score and produce a concise comparison the Executive can act on (the winner,
why it wins, and the margin over the runner-up). Pure ranking — no side effects.
"""

from __future__ import annotations


class PlanComparison:
    @staticmethod
    def rank(evaluations: list) -> list:
        """Return evaluations sorted best-first (higher composite score wins; ties broken
        by lower risk, then higher confidence)."""
        return sorted(evaluations, key=lambda e: (e.score, -e.risk_level, e.confidence),
                      reverse=True)

    @staticmethod
    def summarize(ranked: list) -> dict:
        if not ranked:
            return {"best": None, "summary": "no viable plans", "margin": 0.0}
        best = ranked[0]
        runner = ranked[1] if len(ranked) > 1 else None
        margin = round(best.score - runner.score, 4) if runner is not None else best.score
        summary = (f"Best plan: '{best.scenario.name}' "
                   f"(success {int(best.expected_success * 100)}%, risk {best.risk_level:.2f}, "
                   f"score {best.score:.3f})")
        if runner is not None:
            summary += f", ahead of '{runner.scenario.name}' by {margin:.3f}"
        return {"best": best.scenario.name, "margin": margin, "summary": summary,
                "order": [e.scenario.name for e in ranked]}
