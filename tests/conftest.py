"""Shared pytest fixtures for FRIDAY 4.0 tests."""

import pytest

from core.runtime import Runtime


@pytest.fixture(autouse=True)
def _isolated_core_memory(tmp_path, monkeypatch):
    """Standing memory (M43) is file-backed and singleton-accessed; re-root it
    per test so bridge-based tests never write the real data/core_memory."""
    import core.memory.core_memory as core_memory
    monkeypatch.setattr(core_memory, "_instance",
                        core_memory.CoreMemory(root=tmp_path / "core_memory"))


@pytest.fixture
def runtime():
    """A started runtime, torn down after the test."""
    rt = Runtime(workers=2)
    rt.start(timeout=10)
    try:
        yield rt
    finally:
        rt.stop(timeout=10)


@pytest.fixture
def memory_service(tmp_path):
    """An isolated Memory Service backed by the dependency-free hashing embedder."""
    from core.memory import MemoryService, MemoryStore, HashingEmbedder, NumpyFlatIndex
    emb = HashingEmbedder()
    store = MemoryStore(path=tmp_path / "mem.db")
    svc = MemoryService(store=store, index=NumpyFlatIndex(emb.dim), embedder=emb)
    try:
        yield svc
    finally:
        store.close()


@pytest.fixture
def goal_service(tmp_path, memory_service):
    """A GoalService over an isolated temp store, wired to the memory fixture."""
    from core.goals import GoalService, GoalStore
    store = GoalStore(path=tmp_path / "goals_svc.db")
    svc = GoalService(store=store, memory_service=memory_service)
    try:
        yield svc
    finally:
        store.close()


@pytest.fixture
def knowledge_store(tmp_path):
    """An isolated KnowledgeStore over a temp DB (M7)."""
    from core.knowledge.knowledge_store import KnowledgeStore
    store = KnowledgeStore(path=tmp_path / "knowledge.db")
    try:
        yield store
    finally:
        store.close()


@pytest.fixture
def knowledge_service(tmp_path):
    """An isolated KnowledgeService (store + numpy index + temp vault, M7)."""
    from core.knowledge.knowledge_store import KnowledgeStore
    from core.knowledge.knowledge_index import KnowledgeIndex
    from core.knowledge.knowledge_service import KnowledgeService
    from core.knowledge.vault import ObsidianVault
    store = KnowledgeStore(path=tmp_path / "knowledge.db")
    svc = KnowledgeService(store=store, index=KnowledgeIndex(),
                           vault=ObsidianVault(root=tmp_path / "vault"))
    try:
        yield svc
    finally:
        store.close()


@pytest.fixture
def user_model_store(tmp_path):
    """An isolated UserModelStore over a temp DB (M9)."""
    from core.user_model.store import UserModelStore
    store = UserModelStore(path=tmp_path / "user_model.db")
    try:
        yield store
    finally:
        store.close()


@pytest.fixture
def user_model_service(tmp_path, knowledge_service, goal_service, memory_service):
    """An isolated UserModelService wired to the M2/M4/M7 fixtures (M9)."""
    from core.user_model.store import UserModelStore
    from core.user_model.service import UserModelService
    store = UserModelStore(path=tmp_path / "user_model.db")
    svc = UserModelService(store=store, knowledge_service=knowledge_service,
                           goal_service=goal_service, memory_service=memory_service)
    try:
        yield svc
    finally:
        store.close()


@pytest.fixture
def make_executor(tmp_path):
    """Factory: build a SkillExecutor with isolated temp audit/security/decision DBs.

    Usage: ex, reg = make_executor(approvals=..., policies=...)
    """
    from core.skills import SkillRegistry, SkillExecutor
    from core.skills.audit import AuditLog
    from core.security.security_log import SecurityLog
    from core.observability import DecisionLog

    created: list = []

    def _make(approvals=None, policies=None, registry=None, runtime=None):
        n = len(created)
        reg = registry or SkillRegistry()
        ex = SkillExecutor(
            registry=reg,
            audit=AuditLog(tmp_path / f"audit_{n}.db"),
            security_log=SecurityLog(tmp_path / f"sec_{n}.db"),
            decision_log=DecisionLog(tmp_path / f"dec_{n}.db"),
            approvals=approvals,
            policies=policies,
            runtime=runtime,
        )
        created.append(ex)
        return ex, reg

    return _make
