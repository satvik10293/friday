"""
core/skills/permissions.py — FRIDAY 4.0
Permission levels and risk levels. Both are ordered IntEnums so role clearance
is a simple threshold comparison and risk can gate sandboxing.

Permission levels (the central enforcement axis):
  SAFE           read memory, search knowledge, health checks       (no approval)
  USER_APPROVAL  send messages, write files, store memories         (user must approve)
  ADMIN_ONLY     execute shell, manage services                     (admin role + approval)
  SYSTEM         modify core runtime, alter security policies        (system role + approval)
"""

from __future__ import annotations

from enum import IntEnum


class Permission(IntEnum):
    SAFE = 0
    USER_APPROVAL = 1
    ADMIN_ONLY = 2
    SYSTEM = 3


class RiskLevel(IntEnum):
    LOW = 0
    MEDIUM = 1
    HIGH = 2
    CRITICAL = 3


def requires_approval(permission: Permission) -> bool:
    """SAFE runs freely; everything above needs an approval decision."""
    return int(permission) >= int(Permission.USER_APPROVAL)
