"""
core/security/policies.py — FRIDAY 4.0
The Policy Engine. Dynamically-evaluated rules that can DENY a skill outright or
force it to REQUIRE_APPROVAL, independent of (and in addition to) role clearance.

Policies are plain callables (skill, context, args) -> Optional[PolicyResult],
returning None when they have no opinion. The engine aggregates: any DENY wins;
else any REQUIRE_APPROVAL wins; else ALLOW. Policies key off skill tags so new
skills opt into restrictions declaratively.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Optional


class PolicyEffect(Enum):
    ALLOW = "allow"
    DENY = "deny"
    REQUIRE_APPROVAL = "require_approval"


@dataclass
class PolicyResult:
    effect: PolicyEffect
    reason: str = ""
    policy: str = ""


Policy = Callable[[Any, Any, dict], Optional[PolicyResult]]


# ── built-in policies (declarative, tag-driven) ──────────────────────────────────
def deny_shell_execution(skill, context, args) -> Optional[PolicyResult]:
    if "shell" in getattr(skill, "tags", ()):
        return PolicyResult(PolicyEffect.DENY, "shell execution denied by policy",
                            "deny_shell_execution")
    return None


def deny_network_access(skill, context, args) -> Optional[PolicyResult]:
    if "network" in getattr(skill, "tags", ()):
        return PolicyResult(PolicyEffect.DENY, "network access denied by policy",
                            "deny_network_access")
    return None


def require_approval_for_messaging(skill, context, args) -> Optional[PolicyResult]:
    if "messaging" in getattr(skill, "tags", ()):
        return PolicyResult(PolicyEffect.REQUIRE_APPROVAL,
                            "messaging requires approval", "require_approval_for_messaging")
    return None


def limit_file_modification(skill, context, args) -> Optional[PolicyResult]:
    if "file_write" in getattr(skill, "tags", ()):
        return PolicyResult(PolicyEffect.REQUIRE_APPROVAL,
                            "file modification requires approval", "limit_file_modification")
    return None


def default_policies() -> list[Policy]:
    return [
        deny_shell_execution,
        deny_network_access,
        require_approval_for_messaging,
        limit_file_modification,
    ]


class PolicyEngine:
    def __init__(self, policies: Optional[list[Policy]] = None) -> None:
        self._policies: list[Policy] = list(policies or [])

    def add(self, policy: Policy) -> None:
        self._policies.append(policy)

    def remove(self, name: str) -> None:
        self._policies = [p for p in self._policies if getattr(p, "__name__", "") != name]

    def names(self) -> list[str]:
        return [getattr(p, "__name__", repr(p)) for p in self._policies]

    def evaluate(self, skill, context, args: dict) -> PolicyResult:
        approval: Optional[PolicyResult] = None
        for policy in self._policies:
            res = policy(skill, context, args)
            if res is None:
                continue
            if res.effect is PolicyEffect.DENY:
                return res
            if res.effect is PolicyEffect.REQUIRE_APPROVAL and approval is None:
                approval = res
        return approval or PolicyResult(PolicyEffect.ALLOW)
