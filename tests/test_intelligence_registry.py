"""M12 — Intelligence model registry (runtime model roster, hot loading)."""

import pytest

from core.intelligence.base import TaskType
from core.intelligence.builtin_models import MathModel, ReasonerModel, builtin_models
from core.intelligence.registry import IntelligenceRegistry
from core.intelligence.store import IntelligenceStore


def test_register_and_get():
    reg = IntelligenceRegistry()
    m = MathModel(); reg.register(m)
    assert reg.get("friday-math") is m
    assert "friday-math" in reg.names()


def test_hot_unregister():
    reg = IntelligenceRegistry()
    reg.register(MathModel())
    assert reg.unregister("friday-math")
    assert reg.get("friday-math") is None
    assert not reg.unregister("nope")


def test_by_capability_ranked():
    reg = IntelligenceRegistry()
    for m in builtin_models():
        reg.register(m)
    math = reg.by_capability(TaskType.MATH.value)
    assert math and math[0].info.name == "friday-math"


def test_general_capability_matches_all():
    reg = IntelligenceRegistry()
    reg.register(ReasonerModel())     # has GENERAL capability
    # a model with GENERAL supports any task
    assert reg.by_capability(TaskType.ROBOTICS.value)


def test_best_for():
    reg = IntelligenceRegistry()
    for m in builtin_models():
        reg.register(m)
    assert reg.best_for(TaskType.CODING.value).info.name == "friday-coder"


def test_update_stats_ewma():
    reg = IntelligenceRegistry()
    reg.register(MathModel())
    reg.update_stats("friday-math", latency_ms=100, success=True, accuracy=0.9)
    info = reg.get("friday-math").info
    assert info.avg_speed_ms > 0 and 0 < info.reliability <= 1


def test_persisted_snapshot(tmp_path):
    store = IntelligenceStore(path=tmp_path / "i.db")
    reg = IntelligenceRegistry(store)
    reg.register(MathModel())
    assert any(m["name"] == "friday-math" for m in store.all_models())
    store.close()


def test_health():
    reg = IntelligenceRegistry()
    for m in builtin_models():
        reg.register(m)
    h = reg.health()
    assert h["models"] == 6 and "by_capability" in h


def test_infos_serializable():
    reg = IntelligenceRegistry()
    reg.register(MathModel())
    import json
    json.dumps(reg.infos())            # must be JSON-serializable (capabilities sorted list)
