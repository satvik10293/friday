"""Tests for the M7 KnowledgeConsolidator + CodingKnowledge seed library."""

from core.knowledge.coding_knowledge import CodingKnowledge
from core.knowledge.knowledge_consolidator import KnowledgeConsolidator
from core.knowledge.knowledge_models import (KnowledgeCategory, KnowledgeStatus,
                                             new_knowledge)


# ── Consolidator ──────────────────────────────────────────────────────────────────
def _seed_cluster(store):
    store.create(new_knowledge("SQLite threading rule one",
                               "sqlite needs one connection per thread for safety",
                               category=KnowledgeCategory.SQLITE))
    store.create(new_knowledge("SQLite threading rule two",
                               "sqlite connection per thread avoids errors threads",
                               category=KnowledgeCategory.SQLITE))


def test_cluster_groups_similar(knowledge_store):
    _seed_cluster(knowledge_store)
    con = KnowledgeConsolidator(knowledge_store)
    entries = knowledge_store.list(category=KnowledgeCategory.SQLITE)
    clusters = con.cluster(entries)
    assert any(len(c) >= 2 for c in clusters)


def test_consolidate_creates_summary_and_archives(knowledge_store):
    _seed_cluster(knowledge_store)
    con = KnowledgeConsolidator(knowledge_store)
    result = con.consolidate(category=KnowledgeCategory.SQLITE)
    assert result.summaries_created == 1
    assert result.archived == 2
    # originals archived, summary active
    actives = knowledge_store.list(status=KnowledgeStatus.ACTIVE.value)
    assert len(actives) == 1
    assert actives[0].metadata.get("summary") is True


def test_consolidate_records_lineage(knowledge_store):
    _seed_cluster(knowledge_store)
    con = KnowledgeConsolidator(knowledge_store)
    result = con.consolidate(category=KnowledgeCategory.SQLITE)
    sid = result.summary_ids[0]
    summary = knowledge_store.get(sid)
    assert summary.metadata["sources"]
    hist = knowledge_store.history(sid)
    assert any(h["kind"] == "consolidated" for h in hist)


def test_consolidate_skips_singletons(knowledge_store):
    knowledge_store.create(new_knowledge("Lonely", "unique content no friends",
                                         category=KnowledgeCategory.PYTHON))
    con = KnowledgeConsolidator(knowledge_store)
    result = con.consolidate(category=KnowledgeCategory.PYTHON)
    assert result.summaries_created == 0


# ── CodingKnowledge ───────────────────────────────────────────────────────────────
def test_coding_patterns_available(knowledge_store):
    ck = CodingKnowledge(knowledge_store)
    pats = ck.patterns()
    assert len(pats) >= 4
    assert all(p.metadata.get("pattern") for p in pats)


def test_coding_seed_idempotent(knowledge_store):
    ck = CodingKnowledge(knowledge_store)
    first = ck.seed()
    assert len(first) >= 4
    second = ck.seed()
    assert second == []                 # nothing new the second time


def test_coding_find(knowledge_store):
    ck = CodingKnowledge(knowledge_store)
    ck.seed()
    hit = ck.find("how do I authenticate users in flask sessions")
    assert hit is not None
    assert hit.metadata.get("pattern") is True
