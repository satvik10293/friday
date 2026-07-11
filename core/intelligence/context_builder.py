"""
core/intelligence/context_builder.py — FRIDAY 4.0 (M12)
Builds the inference context (Part 4). Before every reasoning run it gathers
relevant memories, knowledge, goals, projects, preferences, agent reports, and
simulation results, then compresses to a token budget so context is never larger
than necessary.

Crucially, the output is a **plain dict of primitives** — no service or store
references cross into it. That is the security boundary (Part 18): models reason
over data, never over live FRIDAY objects.
"""

from __future__ import annotations

import re
from typing import Optional

from core.mission_control.resilience import safe_call


def _approx_tokens(text: str) -> int:
    return max(1, len(text) // 4)


# a short prompt that leans on a pronoun or "what about…" is a follow-up: its
# retrieval anchor lives in the PREVIOUS turn, not in the prompt itself
_FOLLOWUP_RE = re.compile(
    r"\b(he|she|it|they|him|her|them|that|this|those|these)\b"
    r"|^\s*(what|how|and)\s+about\b|^\s*(and|so|then)\b", re.IGNORECASE)


def _retrieval_query(prompt: str, seed: Optional[dict]) -> str:
    turns = (seed or {}).get("recent_turns") or []
    if not turns or len(prompt.split()) > 8 or not _FOLLOWUP_RE.search(prompt):
        return prompt
    last_user = next((t.get("text", "") for t in reversed(turns)
                      if t.get("role") == "user"), "")
    return f"{last_user} {prompt}".strip() if last_user else prompt


class ContextBuilder:
    def __init__(self, *, memory_service=None, knowledge_service=None, goal_service=None,
                 user_model=None, society=None, simulation_service=None,
                 token_budget: int = 1500) -> None:
        self.memory = memory_service
        self.knowledge = knowledge_service
        self.goals = goal_service
        self.user_model = user_model
        self.society = society
        self.simulations = simulation_service
        self.token_budget = token_budget

    def build(self, prompt: str, *, k: int = 5, seed: Optional[dict] = None) -> dict:
        # `seed` is the caller's incoming context (e.g. recent_turns from the
        # conversation bridge): a follow-up like "what about in miles?" anchors
        # retrieval to the previous user turn instead of three bare pronouns
        query = _retrieval_query(prompt, seed)
        ctx: dict = {"query": query}
        ctx["memories"] = safe_call("ctx.mem",
            lambda: [self._mem(m) for m in self.memory.recall(query, k=k)],
            default=[]) if self.memory else []
        ctx["knowledge"] = safe_call("ctx.know",
            lambda: [{"title": e.title, "content": e.content[:300], "confidence": e.confidence}
                     for e in self.knowledge.search_knowledge(query, k=k)],
            default=[]) if self.knowledge else []
        ctx["goals"] = safe_call("ctx.goals",
            lambda: [{"title": g.title, "status": self._status(g)}
                     for g in self.goals.list_goals()[:k]],
            default=[]) if self.goals else []
        ctx["projects"] = safe_call("ctx.proj",
            lambda: [{"name": p.name, "status": p.status}
                     for p in self.user_model.projects.active()],
            default=[]) if self.user_model else []
        ctx["preferences"] = safe_call("ctx.prefs",
            lambda: {p.key: p.value for p in self.user_model.preferences.strong()},
            default={}) if self.user_model else {}
        ctx["agent_reports"] = safe_call("ctx.agents",
            lambda: {"active_workers": len(self.society.coordinator.active_workers()),
                     "leaders": len(self.society.leaders)},
            default={}) if self.society else {}
        ctx["simulation_results"] = safe_call("ctx.sims",
            lambda: [{"name": s.get("name"), "type": s.get("sim_type")}
                     for s in self.simulations.list(limit=3)],
            default=[]) if self.simulations else []
        return self.compress(ctx)

    # ── compression ─────────────────────────────────────────────────────────────
    def compress(self, ctx: dict) -> dict:
        """Trim the heaviest list fields until the estimated token count fits the
        budget. Keeps the highest-signal items (already ranked by the services)."""
        order = ["simulation_results", "agent_reports", "projects", "goals",
                 "memories", "knowledge"]   # trimmed from the front (least critical first)
        while self._tokens(ctx) > self.token_budget:
            trimmed = False
            for field in order:
                val = ctx.get(field)
                if isinstance(val, list) and len(val) > 1:
                    ctx[field] = val[:-1]
                    trimmed = True
                    break
            if not trimmed:
                break
        ctx["_tokens"] = self._tokens(ctx)
        return ctx

    @staticmethod
    def _tokens(ctx: dict) -> int:
        total = 0
        for v in ctx.values():
            total += _approx_tokens(str(v))
        return total

    @staticmethod
    def _mem(m: dict) -> dict:
        # id → provenance (DecisionLog memory_used); private → never leaves the
        # local store (cloud consults must filter on it)
        return {"id": m.get("id"), "content": str(m.get("content", ""))[:300],
                "score": m.get("score"),
                "private": bool((m.get("metadata") or {}).get("private"))}

    @staticmethod
    def _status(g) -> str:
        return g.status.value if hasattr(g.status, "value") else str(g.status)
