"""
core/skills/exceptions.py — FRIDAY 4.0
Skill/security exception hierarchy. All recoverable failures are SkillError
subclasses so the executor can turn them into structured FailureResults and
route them to the audit + security logs.
"""

from __future__ import annotations


class SkillError(Exception):
    """Base for all skill/security failures the executor handles gracefully."""


class SkillNotFound(SkillError):
    """Requested skill name is not registered."""


class DuplicateSkill(SkillError):
    """A skill with this name is already registered."""


class ValidationError(SkillError):
    """Skill input failed validation."""


class PermissionDenied(SkillError):
    """The caller's role lacks clearance for this skill's permission level."""


class ApprovalRejected(SkillError):
    """An approval request was rejected."""


class ApprovalTimeout(SkillError):
    """An approval request timed out."""


class PolicyViolation(SkillError):
    """A security policy denied execution."""


class SandboxTimeout(SkillError):
    """Skill execution exceeded its sandbox time budget."""


class SkillExecutionError(SkillError):
    """Generic execution failure raised by a skill's run()."""
