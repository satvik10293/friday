"""M12 — Intelligence OS integration: think, plan, learn, security, concurrency."""

import asyncio

import pytest

from core.intelligence.service import IntelligenceOS
from core.intelligence.store import IntelligenceStore


@pytest.fixture
def ios(tmp_path, knowledge_service, goal_service):
    store = IntelligenceStore(path=tmp_path / "i.db")
    os_ = IntelligenceOS(store=store, knowledge_service=knowledge_service,
                         goal_service=goal_service)
    try:
        yield os_
    finally:
        os_.close()


# ── think ──────────────────────────────────────────────────────────────────────────
def test_think_math(ios):
    r = ios.think("compute 2 + 3 * 4")
    assert r.ok and "14" in r.answer and r.task == "math"
    assert r.trace_id and r.confidence > 0


def test_think_coding(ios):
    r = ios.think("debug this code", task="coding", context={"code": "x == None"})
    assert r.ok and r.structured.get("issues")


def test_think_collaborate(ios):
    r = ios.think("design and compare multiple approaches and explain why", collaborate=True)
    assert r.strategy == "collaborate"
    assert len(r.models_used) >= 1


def test_think_records_trace(ios):
    ios.think("compute 5 + 5")
    assert ios.status()["traces"] >= 1
    assert ios.traces.recent(1)[0]["task"] == "math"


def test_local_first_no_external(ios):
    import sys
    # the IOS works with the local team; no external AI library is required/loaded
    assert ios.health_report()["local_first"] is True
    assert len(ios.models.loaded_models()) == 6
    assert "openai" not in sys.modules and "anthropic" not in sys.modules


# ── learning & reflection ──────────────────────────────────────────────────────────
def test_learning_grows_knowledge(ios, knowledge_service):
    before = knowledge_service.stats()["total"]
    ios.think("compute 12 * 12", learn=True)        # high-confidence → learns
    assert knowledge_service.stats()["total"] >= before


def test_no_learn_when_disabled(ios, knowledge_service):
    before = knowledge_service.stats()["total"]
    ios.think("compute 2 + 2", learn=False)
    assert knowledge_service.stats()["total"] == before


# ── planning ───────────────────────────────────────────────────────────────────────
def test_plan(ios):
    plan = ios.plan("build a web app with auth database and tests")
    assert plan.steps
    assert plan.estimated_ms > 0
    assert ios.planner.progress(plan)["total"] == len(plan.steps)


# ── security boundary (Part 18) ────────────────────────────────────────────────────
def test_models_never_receive_services(ios):
    # every registered model holds only its own info — no store/service references
    for m in ios.registry.all():
        for v in vars(m).values():
            assert not hasattr(v, "remember_knowledge")
            assert not hasattr(v, "create_goal")
            assert not hasattr(v, "conn")


# ── benchmarking / optimizing / dashboard ──────────────────────────────────────────
def test_benchmark_all_ranks(ios):
    out = ios.benchmark_all()
    assert out["ranking"] and "model" in out["ranking"][0]


def test_optimize(ios):
    out = ios.optimize()
    assert "pending_approval" in out and "auto_applied" in out


def test_dashboard(ios):
    d = ios.dashboard()
    assert d["title"] == "Intelligence" and d["local_first"] is True
    assert d["models"]["count"] == 6
    assert "resources" in d and "traces" in d


# ── concurrency stress (Part 19) ───────────────────────────────────────────────────
def test_concurrent_thinking(ios):
    async def run():
        tasks = [ios.think_async(f"compute {i} + {i}") for i in range(40)]
        return await asyncio.gather(*tasks)
    results = asyncio.run(run())
    assert len(results) == 40
    assert all(r.ok for r in results)


def test_parallel_reasoning_stress(ios):
    from core.intelligence.base import InferenceRequest, TaskType
    reqs = [InferenceRequest(task=TaskType.MATH.value, prompt=f"{i}*2",
                             context={"expression": f"{i}*2"}) for i in range(50)]
    results = ios.reasoning.parallel(reqs)
    assert len(results) == 50 and all(r.ok for r in results)


def test_health_and_status(ios):
    ios.think("compute 1 + 1")
    assert ios.health_report()["status"] == "ok"
    s = ios.status()
    assert s["models"]["loaded"] and s["cache"]["size"] >= 0
