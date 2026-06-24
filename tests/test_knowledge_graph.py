"""Tests for the M7 KnowledgeGraph relationship engine."""

from core.knowledge.knowledge_graph import KnowledgeGraph
from core.knowledge.knowledge_models import KnowledgeRelation, new_knowledge


def _mk(store, title):
    e = new_knowledge(title, title.lower())
    store.create(e)
    return e.id


def test_related_is_symmetric(knowledge_store):
    g = KnowledgeGraph(knowledge_store)
    a = _mk(knowledge_store, "A"); b = _mk(knowledge_store, "B")
    g.add_relation(a, b, KnowledgeRelation.RELATED.value)
    assert b in g.neighbors(a)
    assert a in g.neighbors(b)


def test_parent_child_inverse(knowledge_store):
    g = KnowledgeGraph(knowledge_store)
    parent = _mk(knowledge_store, "Python"); child = _mk(knowledge_store, "Flask")
    g.add_relation(parent, child, KnowledgeRelation.PARENT.value)
    # parent --parent--> child, and child --child--> parent
    assert child in g.neighbors(parent, KnowledgeRelation.PARENT.value)
    assert parent in g.neighbors(child, KnowledgeRelation.CHILD.value)


def test_remove_relation(knowledge_store):
    g = KnowledgeGraph(knowledge_store)
    a = _mk(knowledge_store, "A"); b = _mk(knowledge_store, "B")
    g.add_relation(a, b)
    g.remove_relation(a, b)
    assert g.neighbors(a) == [] and g.neighbors(b) == []


def test_neighbors_filtered(knowledge_store):
    g = KnowledgeGraph(knowledge_store)
    a = _mk(knowledge_store, "A"); b = _mk(knowledge_store, "B"); c = _mk(knowledge_store, "C")
    g.add_relation(a, b, KnowledgeRelation.RELATED.value)
    g.add_relation(a, c, KnowledgeRelation.PARENT.value)
    assert set(g.neighbors(a, KnowledgeRelation.RELATED.value)) == {b}
    assert set(g.neighbors(a, KnowledgeRelation.PARENT.value)) == {c}


def test_traverse_bfs(knowledge_store):
    g = KnowledgeGraph(knowledge_store)
    a = _mk(knowledge_store, "A"); b = _mk(knowledge_store, "B"); c = _mk(knowledge_store, "C")
    g.add_relation(a, b); g.add_relation(b, c)
    visited = g.traverse(a)
    assert b in visited and c in visited


def test_traverse_depth_bound(knowledge_store):
    g = KnowledgeGraph(knowledge_store)
    a = _mk(knowledge_store, "A"); b = _mk(knowledge_store, "B"); c = _mk(knowledge_store, "C")
    g.add_relation(a, b); g.add_relation(b, c)
    assert g.traverse(a, max_depth=1) == [b]


def test_path(knowledge_store):
    g = KnowledgeGraph(knowledge_store)
    a = _mk(knowledge_store, "A"); b = _mk(knowledge_store, "B"); c = _mk(knowledge_store, "C")
    g.add_relation(a, b); g.add_relation(b, c)
    assert g.path(a, c) == [a, b, c]


def test_path_none(knowledge_store):
    g = KnowledgeGraph(knowledge_store)
    a = _mk(knowledge_store, "A"); b = _mk(knowledge_store, "B")
    assert g.path(a, b) == []


def test_explain_title_chain(knowledge_store):
    g = KnowledgeGraph(knowledge_store)
    py = _mk(knowledge_store, "Python"); fl = _mk(knowledge_store, "Flask")
    au = _mk(knowledge_store, "Authentication")
    g.add_relation(py, fl); g.add_relation(fl, au)
    assert g.explain(py, au) == "Python → Flask → Authentication"


def test_cycle_safe(knowledge_store):
    g = KnowledgeGraph(knowledge_store)
    a = _mk(knowledge_store, "A"); b = _mk(knowledge_store, "B")
    g.add_relation(a, b)            # related ⇒ already a 2-cycle
    visited = g.traverse(a, max_depth=10)
    assert b in visited            # terminates despite the cycle
