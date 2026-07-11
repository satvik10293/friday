"""
Tests for core/memory/service.py — the Memory Service (charter API).
Uses the deterministic HashingEmbedder + NumpyFlatIndex so no heavy ML deps
are needed. Covers remember/recall, embed_id linkage, forget, amend,
consolidate, rebuild_index, working memory, and runtime attach.
"""

import pytest

from core.memory import MemoryService, MemoryStore, HashingEmbedder, NumpyFlatIndex
from core.runtime import Runtime


@pytest.fixture
def service(tmp_path):
    emb = HashingEmbedder()
    store = MemoryStore(path=tmp_path / "mem.db")
    idx = NumpyFlatIndex(emb.dim)
    svc = MemoryService(store=store, index=idx, embedder=emb)
    yield svc
    store.close()


def test_remember_writes_embed_id_in_row(service):
    mid = service.remember("user", "I am building Friday the AI")
    row = service._store.get(mid)
    assert row["embed_id"] == mid           # the in-row link 3.0 never wrote
    assert service.stats()["index_size"] == 1


def test_recall_ranks_relevant_first(service):
    service.remember("user", "python is my favourite programming language")
    service.remember("user", "the weather today is sunny and warm")
    service.remember("user", "I use python and faiss for vector search")
    hits = service.recall("python programming", k=2)
    assert len(hits) == 2
    assert "python" in hits[0]["content"].lower()
    assert hits[0]["score"] is not None     # provenance for the Decision Log


def test_forget_soft_excludes_from_recall(service):
    a = service.remember("user", "secret token alpha bravo")
    assert any(h["id"] == a for h in service.recall("secret token", k=5))
    assert service.forget(a) is True
    assert all(h["id"] != a for h in service.recall("secret token", k=5))
    # soft-delete keeps the row for audit
    assert service._store.get(a)["deleted"] is True


def test_forget_hard_purges(service):
    a = service.remember("user", "ephemeral note zulu")
    assert service.forget(a, hard=True) is True
    assert service._store.get(a) is None


def test_remember_deduplicates_identical_content(service):
    """Teaching the same fact twice reinforces the existing memory instead of
    growing the index with near-identical rows."""
    a = service.remember("friday", "The Moon is 384,400 km from Earth.",
                         importance=0.5)
    b = service.remember("friday", "The Moon is 384,400 km from Earth.",
                         importance=0.7)
    assert a == b
    assert service.stats()["index_size"] == 1
    row = service._store.get(a)
    assert row["importance"] == 0.7           # reinforcement keeps the max
    assert row["access_count"] >= 1


def test_remember_keeps_genuinely_different_content(service):
    a = service.remember("friday", "The Moon is 384,400 km from Earth.")
    b = service.remember("friday", "Mars is the fourth planet from the Sun.")
    assert a != b
    assert service.stats()["index_size"] == 2


def test_amend_with_identical_content_is_a_noop(service):
    """Dedup must never let an amend supersede the memory with ITSELF."""
    old = service.remember("user", "the capital of australia is canberra")
    same = service.amend(old, "the capital of australia is canberra")
    assert same == old
    row = service._store.get(old)
    assert not row["deleted"] and row["superseded_by"] is None


def test_amend_supersedes_with_lineage(service):
    old = service.remember("user", "the capital of australia is sydney")
    new = service.amend(old, "the capital of australia is canberra")
    assert new is not None and new != old
    assert service._store.get(old)["superseded_by"] == new
    # recall returns the correction, not the superseded original
    hits = service.recall("capital of australia", k=5)
    ids = [h["id"] for h in hits]
    assert new in ids and old not in ids


def test_consolidate_summarizes_and_archives(service):
    # three episodic memories on one topic, forced old via older_than_s=0
    for i in range(3):
        service.remember("user", f"note {i} about the friday project", topic="friday")
    captured = {}

    def fake_summarizer(topic, items):
        captured["topic"] = topic
        captured["n"] = len(items)
        return f"consolidated {len(items)} notes on {topic}"

    result = service.consolidate(summarizer=fake_summarizer, older_than_s=0, min_cluster=2)
    assert result["summaries_created"] == 1
    assert result["archived"] == 3
    assert captured == {"topic": "friday", "n": 3}
    # a semantic summary now exists and the raw notes are archival
    assert service.stats()["semantic"] == 1
    assert service.stats()["archival"] == 3


def test_rebuild_index_recovers_from_reset(service):
    service.remember("user", "alpha content one")
    service.remember("user", "beta content two")
    service._index.reset()                  # simulate a corrupted/lost index
    assert service.stats()["index_size"] == 0
    n = service.rebuild_index()
    assert n == 2
    assert service.stats()["index_size"] == 2
    assert len(service.recall("alpha", k=2)) >= 1


def test_keyword_fallback_when_index_empty(tmp_path):
    emb = HashingEmbedder()
    store = MemoryStore(path=tmp_path / "m.db")
    svc = MemoryService(store=store, index=NumpyFlatIndex(emb.dim), embedder=emb)
    # insert directly into the store (no vector) to force the keyword path
    store.insert("user", "orphan memory without a vector", topic="x")
    hits = svc.recall("orphan memory", k=3)
    assert any("orphan" in h["content"] for h in hits)
    store.close()


def test_working_memory_buffer(service):
    for i in range(30):
        service.remember("user", f"turn {i}")
    assert len(service.working()) == service.working().capacity  # bounded


def test_attach_registers_health_and_schedule(service):
    rt = Runtime(workers=1)
    rt.start()
    try:
        service.attach(rt, consolidate_every_s=3600)
        h = rt.health()
        assert "memory" in h
        assert h["memory"]["index_backend"] == "numpy-flat"
    finally:
        rt.stop()


def test_assemble_context_budget(service):
    service.remember("user", "friday is a local first cognitive system")
    ctx = service.assemble_context("cognitive system", max_chars=500)
    assert "friday" in ctx.lower()
    assert len(ctx) <= 600
