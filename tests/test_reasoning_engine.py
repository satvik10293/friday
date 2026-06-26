"""M12 — Reasoning engine: all strategies + the engineering-team collaboration."""

import pytest

from core.intelligence.base import InferenceRequest, TaskType
from core.intelligence.builtin_models import builtin_models
from core.intelligence.reasoning_engine import ReasoningEngine, ReasoningStrategy
from core.intelligence.registry import IntelligenceRegistry


@pytest.fixture
def engine():
    reg = IntelligenceRegistry()
    for m in builtin_models():
        m.load(); reg.register(m)
    return ReasoningEngine(reg)


def _req(task=TaskType.MATH.value, prompt="compute 2 + 3 * 4", **ctx):
    return InferenceRequest(task=task, prompt=prompt, context=ctx)


def test_chain_of_thought(engine):
    r = engine.chain_of_thought(_req())
    assert r.ok and "14" in r.answer and r.models_used == ["friday-math"]


def test_consensus(engine):
    r = engine.consensus(_req(task=TaskType.GENERAL.value, prompt="why is the sky blue"))
    assert r.ok and 0 <= r.agreement <= 1 and len(r.models_used) >= 1


def test_debate(engine):
    r = engine.debate(_req(task=TaskType.GENERAL.value, prompt="should we cache results"))
    assert r.strategy == "debate" and r.models_used


def test_tree_of_thought(engine):
    r = engine.tree_of_thought(_req(task=TaskType.GENERAL.value, prompt="plan a system"),
                               branches=3)
    assert r.ok and r.steps and "branches" in r.steps[0]


def test_self_correction(engine):
    r = engine.self_correction(_req(task=TaskType.GENERAL.value, prompt="x"))
    assert r.strategy in ("chain_of_thought", "self_correction")
    assert r.steps


def test_recursive(engine):
    req = InferenceRequest(task=TaskType.GENERAL.value, prompt="solve",
                           context={"subtasks": ["part a", "part b"]})
    r = engine.recursive(req)
    assert r.strategy == "recursive"
    assert "subresults" in r.structured


def test_parallel(engine):
    reqs = [_req(prompt=f"{i}+{i}") for i in range(5)]
    results = engine.parallel(reqs)
    assert len(results) == 5 and all(r.ok for r in results)


def test_collaborate_team(engine):
    r = engine.collaborate(_req(task=TaskType.CODING.value, prompt="review architecture",
                                architecture={"components": [1, 2], "auth": False}))
    # research → planning → worker → critic → executive synthesis
    assert "research" in r.structured and "plan" in r.structured and "critic" in r.structured
    assert r.models_used
    assert 0 <= r.confidence <= 1


def test_no_model_for_task():
    reg = IntelligenceRegistry()       # empty registry
    r = ReasoningEngine(reg).chain_of_thought(_req())
    assert not r.ok and "no model" in r.error


def test_reason_dispatch(engine):
    r = engine.reason(_req(), ReasoningStrategy.CONSENSUS)
    assert r.strategy == "consensus"
