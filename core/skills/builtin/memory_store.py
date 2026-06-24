"""Built-in skill: store a memory (USER_APPROVAL — writes require approval)."""

from __future__ import annotations

from core.skills.exceptions import SkillExecutionError
from core.skills.permissions import Permission, RiskLevel
from core.skills.skill import Skill


class MemoryStoreSkill(Skill):
    name = "memory.store"
    description = "Persist a new memory into FRIDAY's long-term store."
    version = "1.0.0"
    permission = Permission.USER_APPROVAL
    risk_level = RiskLevel.MEDIUM
    tags = ("memory", "write")
    input_schema = {
        "content": {"required": True, "type": str},
        "role": {"required": False, "type": str},
        "topic": {"required": False, "type": str},
        "importance": {"required": False, "type": (int, float)},
    }

    def run(self, context, *, content, role="user", topic="", importance=0.5):
        ms = context.memory_service
        if ms is None:
            raise SkillExecutionError("memory.store requires a memory service in context")
        mem_id = ms.remember(role, content, topic=topic, importance=float(importance))
        return {"id": mem_id, "stored": True}
