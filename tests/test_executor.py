"""Tests for the Skill Executor — the single governed execution path."""

import pytest

from core.skills import Permission, SkillContext
from core.skills.permissions import RiskLevel
from core.skills.skill import Skill
from core.skills.builtin import MemorySearchSkill, MemoryStoreSkill
from core.security import Role


def test_execute_safe_success(make_executor, memory_service):
    ex, reg = make_executor()
    reg.register(MemorySearchSkill())
    memory_service.remember("user", "alpha bravo charlie", topic="x")
    ctx = SkillContext(memory_service=memory_service, user_role=Role.USER, caller="user")
    r = ex.execute("memory.search", {"query": "alpha"}, ctx)
    assert r.success
    assert r.data["count"] >= 1
    assert r.duration_ms >= 0
    assert r.metadata["skill"] == "memory.search"


def test_skill_not_found_is_structured_failure(make_executor):
    ex, _ = make_executor()
    r = ex.execute("ghost", {}, SkillContext(user_role=Role.USER))
    assert not r.success
    assert r.error_type == "SkillNotFound"


def test_validation_failure(make_executor):
    ex, reg = make_executor()
    reg.register(MemorySearchSkill())
    r = ex.execute("memory.search", {}, SkillContext(user_role=Role.USER))
    assert not r.success
    assert r.error_type == "ValidationError"


def test_role_denied_records_security(make_executor, memory_service):
    ex, reg = make_executor()
    reg.register(MemoryStoreSkill())  # USER_APPROVAL — guest has no clearance
    ctx = SkillContext(memory_service=memory_service, user_role=Role.GUEST, caller="guest")
    r = ex.execute("memory.store", {"content": "x"}, ctx)
    assert not r.success
    assert r.error_type == "PermissionDenied"
    assert ex._security.stats()["by_type"]["permission_violation"] >= 1


def test_async_skill_executes(make_executor):
    class AsyncPing(Skill):
        name = "async.ping"
        permission = Permission.SAFE
        risk_level = RiskLevel.LOW

        async def run(self, context):
            import asyncio
            await asyncio.sleep(0.01)
            return {"pong": True}

    ex, reg = make_executor()
    reg.register(AsyncPing())
    r = ex.execute("async.ping", {}, SkillContext(user_role=Role.USER))
    assert r.success and r.data["pong"] is True


def test_trace_propagates_to_decision_log(make_executor, memory_service):
    ex, reg = make_executor()
    reg.register(MemorySearchSkill())
    ctx = SkillContext(memory_service=memory_service, user_role=Role.USER, trace_id="trace-xyz")
    ex.execute("memory.search", {"query": "a"}, ctx)
    rows = ex._decision_log.by_trace("trace-xyz")
    assert len(rows) == 1
    assert rows[0]["skills_invoked"] == ["memory.search"]
    assert rows[0]["outcome"] == "success"


def test_metrics_increment(make_executor):
    ex, reg = make_executor()
    reg.register(MemorySearchSkill())
    ex.execute("memory.search", {"query": "a"}, SkillContext(user_role=Role.USER))
    ex.execute("memory.search", {"query": "b"}, SkillContext(user_role=Role.USER))
    m = ex.metrics()
    assert m["executions"] == 2
    assert m["success"] == 2


def test_skill_crash_is_isolated(make_executor):
    class Boom(Skill):
        name = "boom"
        permission = Permission.SAFE

        def run(self, context):
            raise RuntimeError("kaboom")

    ex, reg = make_executor()
    reg.register(Boom())
    r = ex.execute("boom", {}, SkillContext(user_role=Role.USER))
    assert not r.success
    assert "kaboom" in r.error
    # the executor survived and recorded the failure
    assert ex.metrics()["failure"] == 1


def test_policy_denies_shell_tagged_skill(make_executor):
    class FakeShell(Skill):
        name = "danger.shell"
        permission = Permission.ADMIN_ONLY
        tags = ("shell",)

        def run(self, context):
            return {"ran": True}

    ex, reg = make_executor()
    reg.register(FakeShell())
    r = ex.execute("danger.shell", {}, SkillContext(user_role=Role.SYSTEM))
    assert not r.success
    assert r.error_type == "PolicyViolation"
    assert ex._security.stats()["by_type"]["policy_violation"] >= 1
