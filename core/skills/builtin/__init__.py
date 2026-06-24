"""
core/skills/builtin — reference Skill implementations.

These are the canonical examples every future capability (vision, OCR, web search,
automation, planning, ...) should mirror: typed metadata, permissions, validated
inputs, and execution only through the Skill Executor.
"""

from .health_check import HealthCheckSkill
from .memory_search import MemorySearchSkill
from .memory_store import MemoryStoreSkill
from .system_status import SystemStatusSkill

ALL_BUILTIN = [
    MemorySearchSkill,
    MemoryStoreSkill,
    HealthCheckSkill,
    SystemStatusSkill,
]


def register_builtins(registry) -> object:
    """Register all built-in skills into a registry (idempotent per registry)."""
    for cls in ALL_BUILTIN:
        if not registry.has(cls.name):
            registry.register(cls())
    return registry


__all__ = [
    "MemorySearchSkill", "MemoryStoreSkill", "HealthCheckSkill", "SystemStatusSkill",
    "ALL_BUILTIN", "register_builtins",
]
