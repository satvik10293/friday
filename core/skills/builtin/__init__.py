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
from .system_actions import (
    ALL_ACTION_SPECS,
    SystemActionSkill,
    build_action_skills,
    register_action_skills,
)
from .home_actions import HOME_SKILLS, register_home_skills
from .browser_actions import BROWSER_SKILLS, register_browser_skills

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
    # M34: the full FridayAction catalog as governed, tiered skills.
    register_action_skills(registry)
    # home control through Home Assistant (lights / fans / TV / plugs / phone)
    register_home_skills(registry)
    # driving a real Chrome (open / read / screenshot; click & type are governed)
    register_browser_skills(registry)
    return registry


__all__ = [
    "MemorySearchSkill", "MemoryStoreSkill", "HealthCheckSkill", "SystemStatusSkill",
    "SystemActionSkill", "ALL_ACTION_SPECS", "build_action_skills",
    "register_action_skills", "ALL_BUILTIN", "register_builtins",
]
