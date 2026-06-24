"""Tests for the Audit Log and Security Log persistence + executor integration."""

import pytest

from core.skills import SkillContext
from core.skills.audit import AuditLog
from core.skills.builtin import MemorySearchSkill
from core.security import Role
from core.security.security_log import SecurityLog


def test_audit_record_and_query(tmp_path):
    a = AuditLog(tmp_path / "a.db")
    try:
        a.record(trace_id="t1", skill_name="memory.search", caller="user", role="user",
                 permission="SAFE", approved=True, duration_ms=1.2, success=True,
                 error=None, result_summary="keys:count,results")
        rows = a.by_trace("t1")
        assert len(rows) == 1
        assert rows[0]["success"] is True
        assert rows[0]["approved"] is True
        assert a.stats() == {"total": 1, "success": 1, "failure": 0}
    finally:
        a.close()


def test_audit_persists_across_reopen(tmp_path):
    p = tmp_path / "a.db"
    a = AuditLog(p)
    a.record(trace_id="t", skill_name="x", caller="c", role="user", permission="SAFE",
             approved=True, duration_ms=1.0, success=True)
    a.close()
    a2 = AuditLog(p)
    try:
        assert a2.stats()["total"] == 1
    finally:
        a2.close()


def test_security_log_record_and_filter(tmp_path):
    s = SecurityLog(tmp_path / "s.db")
    try:
        s.record(event_type="permission_violation", severity="high", trace_id="t",
                 skill_name="memory.store", caller="guest", role="guest", detail="denied")
        s.record(event_type="failed_approval", severity="medium", skill_name="msg.send")
        assert s.stats()["total"] == 2
        assert s.stats()["by_type"]["permission_violation"] == 1
        assert len(s.by_type("permission_violation")) == 1
    finally:
        s.close()


def test_executor_writes_audit_row(make_executor):
    ex, reg = make_executor()
    reg.register(MemorySearchSkill())
    ex.execute("memory.search", {"query": "a"}, SkillContext(user_role=Role.USER, caller="user"))
    assert ex._audit.stats()["total"] == 1
    last = ex._audit.recent(1)[0]
    assert last["skill_name"] == "memory.search"
    assert last["role"] == "user"
    assert last["success"] is True
