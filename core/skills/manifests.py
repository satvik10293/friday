"""
core/skills/manifests.py — FRIDAY 4.0
Skill manifests: the discoverable, serializable description of a skill (for the
registry, Mission Control, and future plugin/hot-loading).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .skill import Skill


@dataclass
class SkillManifest:
    name: str
    description: str
    version: str
    permission: str       # Permission.name
    risk_level: str       # RiskLevel.name
    tags: tuple = ()
    input_schema: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "version": self.version,
            "permission": self.permission,
            "risk_level": self.risk_level,
            "tags": list(self.tags),
            "input_schema": {
                k: {**v, "type": getattr(v.get("type"), "__name__", str(v.get("type")))}
                if isinstance(v, dict) else v
                for k, v in self.input_schema.items()
            },
        }


def build_manifest(skill: "Skill") -> SkillManifest:
    return SkillManifest(
        name=skill.name,
        description=skill.description,
        version=skill.version,
        permission=skill.permission.name,
        risk_level=skill.risk_level.name,
        tags=tuple(skill.tags),
        input_schema=dict(skill.input_schema),
    )
