"""Tests for the permission model and role clearance."""

import pytest

from core.skills import Permission, RiskLevel, requires_approval
from core.security import Role, get_role


def test_permission_ordering():
    assert Permission.SAFE < Permission.USER_APPROVAL < Permission.ADMIN_ONLY < Permission.SYSTEM


def test_risk_ordering():
    assert RiskLevel.LOW < RiskLevel.MEDIUM < RiskLevel.HIGH < RiskLevel.CRITICAL


def test_requires_approval():
    assert requires_approval(Permission.SAFE) is False
    assert requires_approval(Permission.USER_APPROVAL) is True
    assert requires_approval(Permission.ADMIN_ONLY) is True
    assert requires_approval(Permission.SYSTEM) is True


@pytest.mark.parametrize("role,perm,allowed", [
    (Role.GUEST, Permission.SAFE, True),
    (Role.GUEST, Permission.USER_APPROVAL, False),
    (Role.USER, Permission.SAFE, True),
    (Role.USER, Permission.USER_APPROVAL, True),
    (Role.USER, Permission.ADMIN_ONLY, False),
    (Role.ADMIN, Permission.ADMIN_ONLY, True),
    (Role.ADMIN, Permission.SYSTEM, False),
    (Role.SYSTEM, Permission.SYSTEM, True),
])
def test_role_clearance(role, perm, allowed):
    assert role.allows(perm) is allowed


def test_get_role():
    assert get_role("admin") is Role.ADMIN
    assert get_role("system") is Role.SYSTEM
    with pytest.raises(ValueError):
        get_role("emperor")
