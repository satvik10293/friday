"""
core/skills/registry.py — FRIDAY 4.0
The central Skill registry. Single source of truth for what FRIDAY can do.
Thread-safe, duplicate-guarded, discoverable, and ready for future plugin loading.
"""

from __future__ import annotations

import logging
import threading
from typing import Optional

from .exceptions import DuplicateSkill, SkillNotFound
from .manifests import SkillManifest
from .permissions import Permission
from .skill import Skill

log = logging.getLogger("friday.skills.registry")


class SkillRegistry:
    def __init__(self) -> None:
        self._skills: dict[str, Skill] = {}
        self._lock = threading.Lock()

    def register(self, skill: Skill) -> Skill:
        if not skill.name:
            raise ValueError("skill has no name")
        with self._lock:
            if skill.name in self._skills:
                raise DuplicateSkill(f"skill '{skill.name}' already registered")
            self._skills[skill.name] = skill
        log.info("registered skill %s (%s)", skill.name, skill.permission.name)
        return skill

    def unregister(self, name: str) -> None:
        with self._lock:
            self._skills.pop(name, None)

    def get(self, name: str) -> Skill:
        with self._lock:
            skill = self._skills.get(name)
        if skill is None:
            raise SkillNotFound(f"no skill named '{name}'")
        return skill

    def has(self, name: str) -> bool:
        with self._lock:
            return name in self._skills

    def list_skills(self) -> list[SkillManifest]:
        with self._lock:
            return [s.manifest() for s in self._skills.values()]

    def find_by_permission(self, permission: Permission) -> list[Skill]:
        with self._lock:
            return [s for s in self._skills.values() if s.permission == permission]

    def names(self) -> list[str]:
        with self._lock:
            return list(self._skills.keys())

    def __len__(self) -> int:
        with self._lock:
            return len(self._skills)


# ── singleton ───────────────────────────────────────────────────────────────────
_registry: Optional[SkillRegistry] = None
_reg_lock = threading.Lock()


def get_registry() -> SkillRegistry:
    global _registry
    with _reg_lock:
        if _registry is None:
            _registry = SkillRegistry()
    return _registry
