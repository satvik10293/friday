"""
core/security/roles.py — FRIDAY 4.0
Roles and their permission clearance. Role checks happen in the executor BEFORE
any skill runs. Clearance is a threshold over the ordered Permission enum.
"""

from __future__ import annotations

from enum import Enum

from core.skills.permissions import Permission


class Role(str, Enum):
    GUEST = "guest"
    USER = "user"
    ADMIN = "admin"
    SYSTEM = "system"

    def allows(self, permission: Permission) -> bool:
        return int(permission) <= int(_CLEARANCE[self])


_CLEARANCE: dict[Role, Permission] = {
    Role.GUEST: Permission.SAFE,
    Role.USER: Permission.USER_APPROVAL,
    Role.ADMIN: Permission.ADMIN_ONLY,
    Role.SYSTEM: Permission.SYSTEM,
}


def get_role(name: str) -> Role:
    return Role(name)
