"""Built-in skill: aggregate subsystem health (SAFE, read-only)."""

from __future__ import annotations

from core.skills.permissions import Permission, RiskLevel
from core.skills.skill import Skill


class HealthCheckSkill(Skill):
    name = "system.health"
    description = "Report health of the runtime and memory subsystems."
    version = "1.0.0"
    permission = Permission.SAFE
    risk_level = RiskLevel.LOW
    tags = ("system", "read")

    def run(self, context):
        out: dict = {"ok": True}
        if context.runtime is not None:
            try:
                out["runtime"] = context.runtime.health()
            except Exception as e:
                out["runtime"] = {"error": str(e)}
        if context.memory_service is not None:
            try:
                out["memory"] = context.memory_service.health()
            except Exception as e:
                out["memory"] = {"error": str(e)}
        return out
