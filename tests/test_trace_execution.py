"""M12 — Trace manager + execution manager (cache, backup fallback, health)."""

import pytest

from core.intelligence.base import (BaseModel, InferenceRequest, ModelInfo, TaskType)
from core.intelligence.builtin_models import MathModel, builtin_models
from core.intelligence.cache import IntelligenceCache, cache_key
from core.intelligence.execution_manager import ExecutionManager
from core.intelligence.health_monitor import HealthMonitor
from core.intelligence.registry import IntelligenceRegistry
from core.intelligence.store import IntelligenceStore
from core.intelligence.trace_manager import TraceManager


# ── trace manager ──────────────────────────────────────────────────────────────────
@pytest.fixture
def store(tmp_path):
    s = IntelligenceStore(path=tmp_path / "i.db")
    try:
        yield s
    finally:
        s.close()


def test_trace_lifecycle(store):
    tm = TraceManager(store)
    tr = tm.start("solve x", "math", context={"knowledge": [1], "memories": []})
    tm.finish(tr, outcome="x=2", confidence=0.8, models=["friday-math"], execution_ms=12.0)
    got = tm.get(tr.id)
    assert got["outcome"] == "x=2" and got["confidence"] == 0.8 and got["models"] == ["friday-math"]


def test_trace_search(store):
    tm = TraceManager(store)
    for i in range(3):
        tr = tm.start(f"goal about flask {i}", "research")
        tm.finish(tr, outcome="done", confidence=0.5, models=[], execution_ms=1.0)
    assert len(tm.search("flask")) == 3
    assert len(tm.search(task="research")) == 3
    assert tm.search("nonexistent") == []


# ── execution manager ──────────────────────────────────────────────────────────────
class _FailingModel(BaseModel):
    def __init__(self):
        super().__init__(ModelInfo(name="failer", capabilities={TaskType.MATH.value},
                                   avg_accuracy=0.99))   # ranks first, but always fails
    def _run(self, request):
        raise RuntimeError("always fails")


def _registry():
    reg = IntelligenceRegistry()
    for m in builtin_models():
        reg.register(m)
    return reg


def test_cache_hit():
    reg = _registry()
    cache = IntelligenceCache()
    ex = ExecutionManager(reg, cache=cache)
    req = InferenceRequest(task=TaskType.MATH.value, prompt="x", context={"expression": "2+2"})
    ex.run(reg.get("friday-math"), req)
    ex.run(reg.get("friday-math"), req)
    assert cache.stats()["hits"] >= 1


def test_health_recorded_on_run():
    reg = _registry()
    health = HealthMonitor()
    ex = ExecutionManager(reg, health=health)
    ex.run(reg.get("friday-math"),
           InferenceRequest(task=TaskType.MATH.value, context={"expression": "2+2"}))
    assert health.model_report()[0]["successes"] >= 1


def test_backup_fallback_on_failure():
    reg = _registry()
    reg.register(_FailingModel())     # highest accuracy → tried first, but fails
    ex = ExecutionManager(reg, retries=2)
    res = ex.execute(InferenceRequest(task=TaskType.MATH.value, context={"expression": "3+3"}))
    assert res.ok and res.model == "friday-math"     # fell back to the working model


def test_execute_no_model():
    ex = ExecutionManager(IntelligenceRegistry())
    res = ex.execute(InferenceRequest(task="nonexistent_task"))
    assert not res.ok


def test_cache_key_stable():
    assert cache_key("a", 1, [2, 3]) == cache_key("a", 1, [2, 3])
    assert cache_key("a") != cache_key("b")
