"""Built-in skill: search FRIDAY's memory (SAFE, read-only)."""

from __future__ import annotations

from core.skills.permissions import Permission, RiskLevel
from core.skills.skill import Skill


class MemorySearchSkill(Skill):
    name = "memory.search"
    description = "Search FRIDAY's memory for entries relevant to a query."
    version = "1.0.0"
    permission = Permission.SAFE
    risk_level = RiskLevel.LOW
    tags = ("memory", "read")
    input_schema = {
        "query": {"required": True, "type": str},
        "k": {"required": False, "type": int},
    }

    def run(self, context, *, query, k=8):
        ms = context.memory_service
        if ms is None:
            return {"results": [], "count": 0, "note": "no memory service in context"}
        hits = ms.recall(query, k=k)
        return {
            "count": len(hits),
            "results": [
                {"id": h["id"], "content": h["content"][:200], "score": h.get("score")}
                for h in hits
            ],
        }
