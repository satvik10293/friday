"""
core/security — FRIDAY 4.0 security layer.

Roles, policies, approvals, sandboxing, validation, and the security event log.
Enforced centrally by the Skill Executor — no action bypasses it. Import is
side-effect free.
"""

from .roles import Role, get_role
from .policies import (
    PolicyEngine,
    PolicyEffect,
    PolicyResult,
    Policy,
    default_policies,
)
from .approvals import ApprovalManager, ApprovalRequest, ApprovalDecision
from .sandbox import Sandbox, ThreadSandbox, NullSandbox
from .validation import validate_args, sanitize_shell, is_safe_path
from .security_log import SecurityLog

__all__ = [
    "Role", "get_role",
    "PolicyEngine", "PolicyEffect", "PolicyResult", "Policy", "default_policies",
    "ApprovalManager", "ApprovalRequest", "ApprovalDecision",
    "Sandbox", "ThreadSandbox", "NullSandbox",
    "validate_args", "sanitize_shell", "is_safe_path",
    "SecurityLog",
]
