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


# ── anaphora-aware retrieval ──────────────────────────────────────────────────

class _RecordingMemory:
    def __init__(self):
        self.queries = []

    def recall(self, query, k=8):
        self.queries.append(query)
        return []


def test_followup_prompts_anchor_retrieval_to_the_previous_turn():
    memory = _RecordingMemory()
    cb = ContextBuilder(memory_service=memory)
    seed = {"recent_turns": [
        {"role": "user", "text": "how far away is the moon"},
        {"role": "friday", "text": "About 384,400 kilometres."},
    ]}
    ctx = cb.build("what about in miles?", seed=seed)
    assert "moon" in memory.queries[0]           # the anchor rode along
    assert "miles" in memory.queries[0]
    assert "moon" in ctx["query"]


def test_standalone_prompts_retrieve_on_their_own_words():
    memory = _RecordingMemory()
    cb = ContextBuilder(memory_service=memory)
    seed = {"recent_turns": [{"role": "user", "text": "how far away is the moon"}]}
    cb.build("what is the tallest mountain on earth today", seed=seed)
    assert memory.queries[0] == "what is the tallest mountain on earth today"


def test_no_window_means_plain_retrieval():
    memory = _RecordingMemory()
    ContextBuilder(memory_service=memory).build("what about it?")
    assert memory.queries[0] == "what about it?"
