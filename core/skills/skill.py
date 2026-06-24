"""
core/skills/skill.py — FRIDAY 4.0
The abstract Skill interface. Everything FRIDAY *does* is a Skill: metadata +
permissions + risk + a validated, auditable run(). Skills may be sync or async.

Subclasses set the class attributes (name/description/permission/...) and
implement run(). validate() does minimal, dependency-free schema checks; the
executor additionally applies security validation + policy.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Optional

from .exceptions import ValidationError
from .manifests import SkillManifest, build_manifest
from .permissions import Permission, RiskLevel


def _type_name(t) -> str:
    if isinstance(t, tuple):
        return "/".join(getattr(x, "__name__", str(x)) for x in t)
    return getattr(t, "__name__", str(t))


class Skill(ABC):
    # ── metadata (override in subclasses) ──────────────────────────────────────
    name: str = ""
    description: str = ""
    version: str = "1.0.0"
    permission: Permission = Permission.SAFE
    risk_level: RiskLevel = RiskLevel.LOW
    tags: tuple = ()
    timeout: Optional[float] = None
    # input_schema: {field: {"required": bool, "type": type|tuple}}
    input_schema: dict = {}

    # ── lifecycle ──────────────────────────────────────────────────────────────
    def validate(self, args: dict) -> None:
        """Minimal, dependency-free schema validation. Raises ValidationError."""
        for fieldname, spec in self.input_schema.items():
            if spec.get("required") and fieldname not in args:
                raise ValidationError(f"{self.name}: missing required arg '{fieldname}'")
            if fieldname in args and "type" in spec:
                if not isinstance(args[fieldname], spec["type"]):
                    raise ValidationError(
                        f"{self.name}: arg '{fieldname}' must be {_type_name(spec['type'])}"
                    )

    @abstractmethod
    def run(self, context: Any, **kwargs) -> Any:
        """Execute the skill. May be `def` or `async def`. Returns serializable data."""
        raise NotImplementedError

    def health(self) -> dict:
        """Liveness/readiness of this skill. Overridable."""
        return {"name": self.name, "ok": True}

    # ── discovery ──────────────────────────────────────────────────────────────
    def manifest(self) -> SkillManifest:
        return build_manifest(self)

    def __repr__(self) -> str:
        return f"<Skill {self.name} v{self.version} {self.permission.name}>"
