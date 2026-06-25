"""M10 — Embedding abstraction + hardened retrieval pipeline."""

from core.embeddings.registry import (EmbeddingRegistry, available_backends,
                                      get_embedding_backend, resolve_backend_name)
from core.retrieval.semantic_search import SemanticSearch


# ── embedding abstraction (no hardcoded model) ────────────────────────────────────
def test_registry_lists_all_backends():
    reg = EmbeddingRegistry()
    names = reg.names()
    assert {"hashing", "minilm", "bge-small", "nomic"} <= set(names)


def test_hashing_always_available():
    assert "hashing" in available_backends()


def test_create_hashing_backend():
    reg = EmbeddingRegistry()
    emb = reg.create("hashing")
    assert emb.name == "hashing" and emb.dim == 256
    import numpy as np
    v = emb.encode("hello world")
    assert isinstance(v, np.ndarray)


def test_unknown_backend_falls_back():
    reg = EmbeddingRegistry()
    emb = reg.create("does-not-exist")
    assert emb.name == "hashing"


def test_resolve_respects_env(monkeypatch):
    monkeypatch.setenv("FRIDAY_EMBEDDING_MODEL", "hashing")
    assert resolve_backend_name() == "hashing"
    assert resolve_backend_name("bge-small") == "bge-small"   # explicit wins


def test_custom_backend_registration():
    reg = EmbeddingRegistry()
    import numpy as np

    class Dummy:
        name = "dummy"; dim = 4
        def encode(self, t): return np.ones(4, dtype="float32")
    reg.register("dummy", lambda: Dummy())
    assert "dummy" in reg.available()
    assert reg.create("dummy").name == "dummy"


def test_get_embedding_backend_default():
    emb = get_embedding_backend()
    assert hasattr(emb, "encode") and hasattr(emb, "dim")


# ── retrieval pipeline ────────────────────────────────────────────────────────────
def _hash_search(knowledge_service):
    emb = get_embedding_backend("hashing")
    return SemanticSearch(knowledge_service, embedder=emb)


def test_semantic_search_ranks(knowledge_service):
    knowledge_service.teach("Flask routing", "flask maps urls to python view functions")
    knowledge_service.teach("Soup recipe", "boil vegetables in water with salt")
    ss = _hash_search(knowledge_service)
    res = ss.search("how does flask route urls to functions")
    assert res.found
    assert res.source in ("semantic", "knowledge")
    assert "Flask" in res.items[0]["title"]
    assert "semantic" in res.trace


def test_pipeline_order_trace(knowledge_service):
    knowledge_service.teach("Topic", "some content about a topic")
    ss = _hash_search(knowledge_service)
    res = ss.search("topic")
    assert res.trace[0] == "working"
    assert "knowledge" in res.trace


def test_metrics_recorded(knowledge_service):
    knowledge_service.teach("A", "alpha content here")
    ss = _hash_search(knowledge_service)
    ss.search("alpha")
    snap = ss.metrics.snapshot()
    assert snap["searches"] == 1
    assert snap["avg_latency_ms"] >= 0.0


def test_evaluate_precision(knowledge_service):
    a = knowledge_service.teach("Python decorators", "decorators wrap python functions")
    knowledge_service.teach("Gardening", "how to grow tomatoes")
    ss = _hash_search(knowledge_service)
    p = ss.evaluate("python decorators wrapping functions", [a.id], k=1)
    assert p == 1.0
    assert ss.metrics.snapshot()["retrieval_accuracy"] is not None


def test_empty_knowledge(knowledge_service):
    ss = _hash_search(knowledge_service)
    res = ss.search("nothing here")
    assert not res.found
    assert res.source == "none"


def test_health(knowledge_service):
    ss = _hash_search(knowledge_service)
    h = ss.health()
    assert h["status"] == "ok" and h["backend"] == "hashing"
