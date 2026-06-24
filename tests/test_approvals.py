"""Tests for the approval workflow (manager + executor integration)."""

import threading
import time
from types import SimpleNamespace

import pytest

from core.security import ApprovalManager, Role
from core.skills import Permission, SkillContext
from core.skills.exceptions import ApprovalTimeout
from core.skills.skill import Skill
from core.skills.builtin import MemoryStoreSkill


def test_executor_auto_approve_stores(make_executor, memory_service):
    appr = ApprovalManager(auto_decider=lambda req: True)
    ex, reg = make_executor(approvals=appr)
    reg.register(MemoryStoreSkill())
    ctx = SkillContext(memory_service=memory_service, user_role=Role.USER, caller="user")
    r = ex.execute("memory.store", {"content": "approved content"}, ctx)
    assert r.success and r.data["stored"] is True


def test_executor_auto_reject(make_executor, memory_service):
    appr = ApprovalManager(auto_decider=lambda req: False)
    ex, reg = make_executor(approvals=appr)
    reg.register(MemoryStoreSkill())
    ctx = SkillContext(memory_service=memory_service, user_role=Role.USER)
    r = ex.execute("memory.store", {"content": "x"}, ctx)
    assert not r.success
    assert r.error_type == "ApprovalRejected"
    assert ex._security.stats()["by_type"]["failed_approval"] >= 1


def test_manager_external_approve():
    appr = ApprovalManager(default_timeout=2.0)
    ctx = SkillContext(user_role=Role.USER, caller="user", trace_id="t1")
    out = {}

    def worker():
        d = appr.request_and_wait(SimpleNamespace(name="x"), {"a": 1}, ctx)
        out["approved"] = d.approved

    t = threading.Thread(target=worker)
    t.start()
    time.sleep(0.15)
    pending = appr.list_pending()
    assert len(pending) == 1
    appr.approve(pending[0]["id"])
    t.join(2)
    assert out["approved"] is True


def test_manager_external_reject():
    appr = ApprovalManager(default_timeout=2.0)
    ctx = SkillContext(user_role=Role.USER, caller="user")
    out = {}

    def worker():
        d = appr.request_and_wait(SimpleNamespace(name="x"), {}, ctx)
        out["approved"] = d.approved

    t = threading.Thread(target=worker)
    t.start()
    time.sleep(0.15)
    appr.reject(appr.list_pending()[0]["id"], reason="no")
    t.join(2)
    assert out["approved"] is False


def test_manager_timeout():
    appr = ApprovalManager(default_timeout=0.2)
    with pytest.raises(ApprovalTimeout):
        appr.request_and_wait(SimpleNamespace(name="x"), {}, SkillContext(user_role=Role.USER))


def test_policy_requires_approval_for_messaging(make_executor):
    class Msg(Skill):
        name = "msg.send"
        permission = Permission.SAFE          # SAFE, but messaging policy forces approval
        tags = ("messaging",)

        def run(self, context, *, to="x"):
            return {"sent": True, "to": to}

    approved = ApprovalManager(auto_decider=lambda r: True)
    ex, reg = make_executor(approvals=approved)
    reg.register(Msg())
    r = ex.execute("msg.send", {"to": "bob"}, SkillContext(user_role=Role.USER))
    assert r.success and r.data["sent"] is True

    rejected = ApprovalManager(auto_decider=lambda r: False)
    ex2, reg2 = make_executor(approvals=rejected)
    reg2.register(Msg())
    r2 = ex2.execute("msg.send", {"to": "bob"}, SkillContext(user_role=Role.USER))
    assert not r2.success and r2.error_type == "ApprovalRejected"
