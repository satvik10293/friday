"""Tests for the Skill base, registry, and built-in skills."""

import pytest

from core.skills import Permission, SkillContext, SkillRegistry
from core.skills.exceptions import DuplicateSkill, SkillNotFound, ValidationError
from core.skills.builtin import (
    MemorySearchSkill, MemoryStoreSkill, HealthCheckSkill, SystemStatusSkill, register_builtins,
)


def test_manifest_shape():
    m = MemorySearchSkill().manifest()
    assert m.name == "memory.search"
    assert m.permission == "SAFE"
    assert m.risk_level == "LOW"
    assert "query" in m.input_schema
    assert "type" in m.to_dict()["input_schema"]["query"]


def test_validate_missing_required():
    with pytest.raises(ValidationError):
        MemorySearchSkill().validate({})


def test_validate_wrong_type():
    with pytest.raises(ValidationError):
        MemorySearchSkill().validate({"query": 123})


def test_validate_tuple_type_ok():
    # importance accepts int or float
    MemoryStoreSkill().validate({"content": "x", "importance": 1})
    MemoryStoreSkill().validate({"content": "x", "importance": 0.5})


def test_memory_search_runs(memory_service):
    memory_service.remember("user", "python is a great language", topic="py")
    out = MemorySearchSkill().run(SkillContext(memory_service=memory_service), query="python")
    assert out["count"] >= 1


def test_memory_store_runs(memory_service):
    out = MemoryStoreSkill().run(SkillContext(memory_service=memory_service), content="a durable fact")
    assert out["id"] >= 1
    assert memory_service.recall("durable fact", k=3)


def test_health_skill(memory_service):
    out = HealthCheckSkill().run(SkillContext(memory_service=memory_service))
    assert out["ok"] is True
    assert "memory" in out


def test_system_status_skill():
    out = SystemStatusSkill().run(SkillContext())
    assert "available" in out


def test_registry_register_and_get():
    reg = SkillRegistry()
    reg.register(MemorySearchSkill())
    assert reg.get("memory.search").name == "memory.search"
    assert reg.has("memory.search")
    assert len(reg) == 1


def test_registry_duplicate_rejected():
    reg = SkillRegistry()
    reg.register(MemorySearchSkill())
    with pytest.raises(DuplicateSkill):
        reg.register(MemorySearchSkill())


def test_registry_get_missing():
    with pytest.raises(SkillNotFound):
        SkillRegistry().get("ghost")


def test_register_builtins_and_find_by_permission():
    reg = SkillRegistry()
    register_builtins(reg)
    names = {m.name for m in reg.list_skills()}
    assert {"memory.search", "memory.store", "system.health", "system.status"} <= names
    safe = {s.name for s in reg.find_by_permission(Permission.SAFE)}
    assert "memory.search" in safe and "memory.store" not in safe


def test_register_builtins_idempotent():
    reg = SkillRegistry()
    register_builtins(reg)
    count = len(reg)         # 4 reference skills + the M34 action catalog
    register_builtins(reg)   # second call must not raise
    assert len(reg) == count
    assert count >= 41
