"""M12 — Intelligence Router: classification, complexity, strategy, routing."""

import pytest

from core.intelligence.base import Complexity, TaskType
from core.intelligence.builtin_models import builtin_models
from core.intelligence.confidence_engine import ConfidenceEngine
from core.intelligence.critic import CriticEngine
from core.intelligence.reasoning_engine import ReasoningEngine, ReasoningStrategy
from core.intelligence.registry import IntelligenceRegistry
from core.intelligence.router import IntelligenceRouter


@pytest.fixture
def router():
    reg = IntelligenceRegistry()
    for m in builtin_models():
        m.load(); reg.register(m)
    reasoning = ReasoningEngine(reg)
    return IntelligenceRouter(reg, reasoning)


def test_classify_math(router):
    task, _ = router.classify("compute 2 + 3 * 4")
    assert task == TaskType.MATH.value


def test_classify_coding(router):
    task, _ = router.classify("there is a bug in my python function please debug")
    assert task == TaskType.CODING.value


def test_classify_planning(router):
    task, _ = router.classify("make a plan with milestones and steps")
    assert task == TaskType.PLANNING.value


def test_classify_general_fallback(router):
    task, _ = router.classify("hello there")
    assert task == TaskType.GENERAL.value


def test_complexity_levels(router):
    assert router._complexity("hi") == Complexity.TRIVIAL.value
    assert router._complexity("a" * 300) == Complexity.LARGE.value
    big = "design and compare multiple options then explain how and why"
    assert router._complexity(big) == Complexity.LARGE.value


def test_strategy_selection(router):
    assert router.choose_strategy("math", Complexity.TRIVIAL.value) == ReasoningStrategy.CHAIN_OF_THOUGHT
    assert router.choose_strategy("general", Complexity.LARGE.value) == ReasoningStrategy.CONSENSUS
    assert router.choose_strategy("general", Complexity.SMALL.value) == ReasoningStrategy.SELF_CORRECTION


def test_select_models(router):
    sel = router.select_models(TaskType.MATH.value)
    assert sel["primary"] == "friday-math"
    assert "friday-math" in sel["available"]


def test_route_math(router):
    resp = router.route("compute 2 + 3 * 4")
    assert resp.ok and resp.task == TaskType.MATH.value
    assert "14" in resp.answer
    assert resp.confidence > 0
    assert resp.latency_ms >= 0
    assert resp.trace_id


def test_route_is_sub_second(router):
    resp = router.route("compute 5 * 5")
    assert resp.latency_ms < 1000      # sub-second routing


def test_route_collaborate(router):
    resp = router.route("design and compare multiple architectures and explain why",
                        collaborate=True)
    assert resp.strategy == "collaborate"
    assert len(resp.models_used) >= 1


def test_route_explicit_task(router):
    resp = router.route("debug this", task="coding", context={"code": "x == None"})
    assert resp.task == "coding"
    assert resp.structured.get("issues")
