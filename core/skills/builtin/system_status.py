"""Built-in skill: host system status (SAFE, read-only; psutil optional)."""

from __future__ import annotations

from core.skills.permissions import Permission, RiskLevel
from core.skills.skill import Skill


class SystemStatusSkill(Skill):
    name = "system.status"
    description = "Report host CPU / memory / disk status."
    version = "1.0.0"
    permission = Permission.SAFE
    risk_level = RiskLevel.LOW
    tags = ("system", "read")

    def run(self, context):
        try:
            import psutil
        except Exception as e:
            return {"available": False, "reason": f"psutil unavailable: {e}"}
        vm = psutil.virtual_memory()
        return {
            "available": True,
            "cpu_pct": psutil.cpu_percent(interval=0.1),
            "mem_pct": vm.percent,
            "mem_used_gb": round(vm.used / 1e9, 2),
        }
