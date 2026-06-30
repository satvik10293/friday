"""M17-rev — Memory Brain: tiered promotion, recall reinforcement, forgetting,
consolidation, durable persistence, knowledge-graph threading, semantic Knowledge Graph."""

import pytest

from core.brains.memory import KnowledgeGraph, MemoryBrain, MemoryTier, NodeKind, TieredMemory
from core.services import ServiceName, build_default_container


# ── tiered memory ────────────────────────────────────────────────────────────────────
def test_tier_promotion_by_importance_and_confidence():
    tm = TieredMemory()
    low = tm.store("trivial", importance=0.2, confidence=0.3)
    high = tm.store("important fact", importance=0.9, confidence=0.9, user_confirmed=True)
    assert low.tier == MemoryTier.WORKING
    assert high.tier == MemoryTier.CORE                # user-confirmed + high → core


def test_promotion_via_reinforcement():
    tm = TieredMemory()
    item = tm.store("repeated event", importance=0.4, confidence=0.5)
    start = item.tier
    for _ in range(6):
        tm.reinforce(item.mem_id)
    promotions = tm.promote()
    assert tm._items[item.mem_id].tier > start
    assert any(p["mem_id"] == item.mem_id for p in promotions)


def test_recall_reinforces():
    tm = TieredMemory()
    item = tm.store("the wifi password is hunter2", importance=0.5, confidence=0.6)
    before = item.reinforcement
    hits = tm.recall("wifi")
    assert hits and tm._items[item.mem_id].reinforcement > before


def test_forget_and_forget_stale():
    import time
    tm = TieredMemory(stale_after_s=0.0)
    item = tm.store("forgettable", importance=0.2, confidence=0.2)
    assert tm.forget_stale(now=time.time() + 1) == 1
    assert tm.forget(item.mem_id) is False             # already gone


def test_consolidation_clusters_episodic():
    tm = TieredMemory()
    for i in range(4):
        it = tm.store(f"meeting about project alpha number {i}", importance=0.5, confidence=0.5)
        it.tier = MemoryTier.EPISODIC
    results = tm.consolidate(min_cluster=3)
    assert results and results[0]["merged"] >= 3
    assert tm.by_tier(MemoryTier.SEMANTIC)             # produced a semantic summary


# ── memory brain ─────────────────────────────────────────────────────────────────────
def test_memory_brain_remember_recall():
    mb = MemoryBrain(services=build_default_container())
    mb.remember("user likes tea", importance=0.6, confidence=0.7)
    assert mb.recall("tea")


def test_memory_brain_durable_persist():
    persisted = []

    class Durable:
        name = "memory"
        def remember(self, content, *, kind="event", metadata=None): persisted.append(content)
        def recall(self, q, *, limit=8): return []
        def health(self): return {"status": "ok"}
    c = build_default_container()
    c.register(ServiceName.MEMORY, Durable())
    mb = MemoryBrain(services=c)
    mb.remember("core identity fact", importance=0.95, confidence=0.95, user_confirmed=True)
    assert persisted                                   # core-tier memory persisted to backend


def test_memory_brain_remember_situation_threads_graph():
    mb = MemoryBrain(services=build_default_container())
    mb.remember_situation({"summary": "user working", "location": "office",
                           "related_objects": ["laptop"], "related_people": ["Satvik"],
                           "confidence": 0.8, "priority": 0.6})
    assert mb.graph.find("office", kind=NodeKind.ROOM)
    assert mb.related(NodeKind.OBJECT, "laptop")       # laptop in_room office


def test_memory_brain_lifecycle_report():
    mb = MemoryBrain(services=build_default_container())
    mb.remember("a", importance=0.9, confidence=0.9, user_confirmed=True)
    r = mb.tick()
    assert r is not None and r.category == "memory"


# ── knowledge graph ──────────────────────────────────────────────────────────────────
def test_knowledge_graph_nodes_edges():
    kg = KnowledgeGraph()
    kg.connect(NodeKind.PERSON, "Satvik", "owns", NodeKind.DEVICE, "laptop")
    kg.connect(NodeKind.DEVICE, "laptop", "in_room", NodeKind.ROOM, "office")
    assert kg.counts()["nodes"] == 3 and kg.counts()["edges"] == 2
    rel = kg.related(NodeKind.PERSON, "Satvik")
    assert any(r["relation"] == "owns" for r in rel)


def test_knowledge_graph_path():
    kg = KnowledgeGraph()
    kg.connect(NodeKind.PERSON, "Satvik", "owns", NodeKind.DEVICE, "laptop")
    kg.connect(NodeKind.DEVICE, "laptop", "in_room", NodeKind.ROOM, "office")
    path = kg.path("person:satvik", "room:office")
    assert path and path[0] == "person:satvik" and path[-1] == "room:office"


def test_knowledge_graph_find_by_kind():
    kg = KnowledgeGraph()
    kg.upsert_node(NodeKind.PREFERENCE, "dark mode")
    kg.upsert_node(NodeKind.PERSON, "Satvik")
    assert len(kg.by_kind(NodeKind.PREFERENCE)) == 1
    assert kg.find("satvik", kind=NodeKind.PERSON)
