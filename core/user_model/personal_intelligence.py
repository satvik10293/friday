"""
core/user_model/personal_intelligence.py — FRIDAY 4.0 (M9)
The Personal Intelligence Engine. Builds a coherent understanding of the user and
uses it to personalise — predicting useful context, re-ranking knowledge by the
user's interests/projects, and adapting tone.

Explainability is a first-class requirement: every personalization decision comes
with `Evidence`, so FRIDAY can answer "Why did you recommend this?" with the
actual signals (interest weights, active projects, preferences) that drove it.

Connects to M8 Knowledge (interest-boosted retrieval) and M4 Goals (relevance)
purely by composition through the injected services — no M4/M8 file is modified.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from .models import Evidence


@dataclass
class Recommendation:
    item: dict
    score: float
    evidence: list = field(default_factory=list)     # list[Evidence]

    def to_dict(self) -> dict:
        return {"item": self.item, "score": round(self.score, 4),
                "evidence": [e.to_dict() for e in self.evidence]}


class PersonalIntelligence:
    def __init__(self, service) -> None:
        self._s = service

    # ── understanding ───────────────────────────────────────────────────────────
    def build_understanding(self) -> dict:
        """A compact, explainable snapshot of who FRIDAY thinks the user is."""
        profile = self._s.profile.get()
        return {
            "user": profile.display_name(),
            "top_interests": [{"name": i.name, "weight": round(i.weight, 3)}
                              for i in self._s.interests.top(5)],
            "active_projects": [{"id": p.id, "name": p.name}
                                for p in self._s.projects.active()],
            "strong_preferences": [{"key": p.key, "score": round(p.score, 3)}
                                   for p in self._s.preferences.strong()],
            "communication_style": self._s.communication.adapt_hint(),
            "learning_style": self._s.learning.dominant(),
            "habits": [{"key": h.key, "confidence": round(h.confidence, 3)}
                       for h in self._s.habits.discovered()],
        }

    # ── personalised knowledge retrieval ────────────────────────────────────────
    def suggest_knowledge(self, query: str, *, k: int = 5,
                          allow_external: bool = False) -> list[Recommendation]:
        """Search knowledge (M8) and re-rank by the user's interests + active
        projects. Each result carries the evidence behind its boost."""
        ks = self._s.knowledge_service
        if ks is None:
            return []
        entries = ks.search_knowledge(query, k=max(k * 2, k))
        active_terms = {p.name.lower() for p in self._s.projects.active()}

        recs: list[Recommendation] = []
        for e in entries:
            d = e.to_dict()
            base = float(d.get("confidence", 0.5))
            evidence = [Evidence("knowledge", f"base confidence {base:.2f}", base)]
            text = f"{d.get('title','')} {d.get('content','')}"

            interest_boost = self._s.interests.relevance_boost(text)
            if interest_boost > 0:
                evidence.append(Evidence(
                    "interest", f"matches your interests (+{interest_boost:.2f})",
                    interest_boost))
            # category-as-interest (e.g. interested in "Python", entry category Python)
            cat = str(d.get("category", "")).lower()
            cat_w = self._s.interests.weight(d.get("category", "")) if cat else 0.0
            if cat_w > 0:
                evidence.append(Evidence(
                    "interest", f"category '{d.get('category')}' is an interest (+{cat_w:.2f})",
                    cat_w))

            project_boost = 0.0
            for term in active_terms:
                if term and term in text.lower():
                    project_boost += 0.3
                    evidence.append(Evidence(
                        "project", f"relevant to active project '{term}'", 0.3))

            score = base + interest_boost + cat_w + project_boost
            recs.append(Recommendation(item=d, score=score, evidence=evidence))

        recs.sort(key=lambda r: r.score, reverse=True)
        return recs[:k]

    def knowledge_priority(self, text: str) -> float:
        """How strongly a piece of text aligns with the user (interest weight sum).
        The 'attention boost' M9 specifies for personalised retrieval."""
        return self._s.interests.relevance_boost(text)

    # ── goal relevance (M4 integration) ─────────────────────────────────────────
    def goal_relevance(self, goal) -> float:
        """Personalised priority score for a goal: blends its own priority with
        how well it aligns with the user's interests and active projects."""
        title = getattr(goal, "title", "") or (goal.get("title", "") if isinstance(goal, dict) else "")
        priority = getattr(goal, "priority", None)
        if priority is None and isinstance(goal, dict):
            priority = goal.get("priority", 3)
        priority = priority or 3
        base = (6 - min(5, max(1, priority))) / 5.0      # priority 1→1.0 … 5→0.2
        boost = self._s.interests.relevance_boost(title)
        return base + boost

    def prioritize_goals(self, goals: list) -> list[dict]:
        """Rank goals by personalised relevance, with evidence."""
        scored = []
        for g in goals:
            title = getattr(g, "title", None) or (g.get("title") if isinstance(g, dict) else "")
            score = self.goal_relevance(g)
            scored.append({"goal": g.to_dict() if hasattr(g, "to_dict") else g,
                           "title": title, "relevance": round(score, 4)})
        scored.sort(key=lambda x: x["relevance"], reverse=True)
        return scored

    # ── tone personalisation ────────────────────────────────────────────────────
    def personalize_response(self, text: str) -> dict:
        """Return the text alongside the style hints FRIDAY should apply."""
        return {"text": text, "style": self._s.communication.adapt_hint(),
                "learning_style": self._s.learning.dominant()}

    # ── explainability ──────────────────────────────────────────────────────────
    def explain(self, query: str, *, k: int = 5) -> dict:
        """Answer "why did you recommend this?" — the top suggestion with its
        full evidence trail."""
        recs = self.suggest_knowledge(query, k=k)
        if not recs:
            return {"query": query, "recommendation": None,
                    "reason": "no personal signals or knowledge matched"}
        top = recs[0]
        return {
            "query": query,
            "recommendation": top.item.get("title"),
            "score": round(top.score, 4),
            "evidence": [e.to_dict() for e in top.evidence],
            "reason": "; ".join(e.detail for e in top.evidence),
        }
