"""
core/skills — FRIDAY 4.0 skill layer.

The only approved execution path for actions. Everything FRIDAY does is a Skill,
resolved from the registry and run through the Executor (which enforces
validation, policy, role clearance, approvals, sandboxing, audit, and decision
logging). Import is side-effect free.

    from core.skills import get_registry, SkillExecutor, SkillContext
    from core.skills.builtin import register_builtins
    reg = get_registry(); register_builtins(reg)
    ex = SkillExecutor(registry=reg)
    result = ex.execute("memory.search", {"query": "friday"}, SkillContext(...))
"""

from .exceptions import (
    SkillError, SkillNotFound, DuplicateSkill, ValidationError, PermissionDenied,
    ApprovalRejected, ApprovalTimeout, PolicyViolation, SandboxTimeout, SkillExecutionError,
)
from .permissions import Permission, RiskLevel, requires_approval
from .results import Result, SuccessResult, FailureResult
from .context import SkillContext
from .manifests import SkillManifest, build_manifest
from .skill import Skill
from .registry import SkillRegistry, get_registry
from .audit import AuditLog
from .executor import SkillExecutor

__all__ = [
    # exceptions
    "SkillError", "SkillNotFound", "DuplicateSkill", "ValidationError",
    "PermissionDenied", "ApprovalRejected", "ApprovalTimeout", "PolicyViolation",
    "SandboxTimeout", "SkillExecutionError",
    # core types
    "Permission", "RiskLevel", "requires_approval",
    "Result", "SuccessResult", "FailureResult",
    "SkillContext", "SkillManifest", "build_manifest",
    "Skill", "SkillRegistry", "get_registry",
    "AuditLog", "SkillExecutor",
]
