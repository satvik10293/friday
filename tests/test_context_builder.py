"""M12 — Context builder: gathering, compression, and the security boundary."""

import json

import pytest

from core.intelligence.context_builder import ContextBuilder


def test_empty_context_no_services():
    ctx = ContextBuilder().build("anything")
    assert ctx["query"] == "anything"
    assert ctx["memories"] == [] and ctx["knowledge"] == []


def test_gathers_from_services(knowledge_service, goal_service):
    knowledge_service.teach("Python", "a programming language")
    g = goal_service.create_goal("Ship", priority=1); goal_service.activate_goal(g.goal_id)
    cb = ContextBuilder(knowledge_service=knowledge_service, goal_service=goal_service)
    ctx = cb.build("python")
    assert any(k["title"] == "Python" for k in ctx["knowledge"])
    assert any(go["title"] == "Ship" for go in ctx["goals"])


def test_context_is_primitives_only(knowledge_service):
    """Security boundary: the context handed to models holds no service objects."""
    knowledge_service.teach("Topic", "content here")
    ctx = ContextBuilder(knowledge_service=knowledge_service).build("topic")
    json.dumps(ctx)            # fully JSON-serializable → no live objects leaked


def test_compression_respects_budget():
    cb = ContextBuilder(token_budget=20)
    big = {"query": "q",
           "knowledge": [{"content": "x" * 200} for _ in range(10)],
           "memories": [{"content": "y" * 200} for _ in range(10)]}
    out = cb.compress(big)
    assert out["_tokens"] <= cb.token_budget or len(out["knowledge"]) == 1


def test_resilient_to_failing_service():
    class Boom:
        def recall(self, *a, **k): raise RuntimeError("down")
    ctx = ContextBuilder(memory_service=Boom()).build("x")
    assert ctx["memories"] == []      # degraded, not crashed


def test_token_estimate_present():
    ctx = ContextBuilder().build("hello")
    assert "_tokens" in ctx and ctx["_tokens"] >= 1
