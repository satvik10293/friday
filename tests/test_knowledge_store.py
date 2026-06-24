"""Tests for the M7 KnowledgeStore + models."""

from core.knowledge.knowledge_models import (KnowledgeCategory, KnowledgeEntry,
                                             KnowledgeLink, KnowledgeStatus,
                                             new_knowledge, slugify)


def test_slugify_basic():
    assert slugify("Flask Template Not Found!") == "flask-template-not-found"
    assert slugify("   ") == "untitled"


def test_new_knowledge_defaults():
    e = new_knowledge("Title", "body", category=KnowledgeCategory.FLASK, confidence=2.0)
    assert e.id and len(e.id) == 12
    assert e.confidence == 1.0          # clamped
    assert e.created_at > 0 and e.updated_at > 0
    assert e.status == KnowledgeStatus.ACTIVE.value


def test_entry_roundtrip_dict():
    e = new_knowledge("T", "C", metadata={"x": 1})
    d = e.to_dict()
    again = KnowledgeEntry.from_dict(d)
    assert again.id == e.id and again.metadata == {"x": 1}


def test_create_and_get(knowledge_store):
    e = new_knowledge("Indexing", "use an index")
    knowledge_store.create(e)
    got = knowledge_store.get(e.id)
    assert got is not None and got.title == "Indexing"


def test_update(knowledge_store):
    e = new_knowledge("A", "first")
    knowledge_store.create(e)
    e.content = "second"
    knowledge_store.update(e)
    assert knowledge_store.get(e.id).content == "second"


def test_delete_removes_links(knowledge_store):
    a = new_knowledge("A", "a"); b = new_knowledge("B", "b")
    knowledge_store.create(a); knowledge_store.create(b)
    knowledge_store.add_link(KnowledgeLink(a.id, b.id, "related"))
    knowledge_store.delete(a.id)
    assert knowledge_store.get(a.id) is None
    assert knowledge_store.links_for(b.id) == []


def test_list_filters(knowledge_store):
    knowledge_store.create(new_knowledge("P", "p", category=KnowledgeCategory.PYTHON))
    knowledge_store.create(new_knowledge("F", "f", category=KnowledgeCategory.FLASK))
    pys = knowledge_store.list(category=KnowledgeCategory.PYTHON)
    assert len(pys) == 1 and pys[0].category == KnowledgeCategory.PYTHON


def test_search_text(knowledge_store):
    knowledge_store.create(new_knowledge("Retry backoff", "exponential backoff with jitter"))
    knowledge_store.create(new_knowledge("Unrelated", "nothing here"))
    hits = knowledge_store.search_text("backoff")
    assert any("backoff" in h.title.lower() for h in hits)


def test_find_by_title(knowledge_store):
    knowledge_store.create(new_knowledge("Exact Title", "x", category=KnowledgeCategory.AI))
    assert knowledge_store.find_by_title("exact title") is not None
    assert knowledge_store.find_by_title("exact title", KnowledgeCategory.FLASK) is None


def test_touch_usage_and_status(knowledge_store):
    e = new_knowledge("U", "u")
    knowledge_store.create(e)
    knowledge_store.touch_usage(e.id)
    assert knowledge_store.get(e.id).usage_count == 1
    knowledge_store.set_status(e.id, KnowledgeStatus.ARCHIVED.value)
    assert knowledge_store.get(e.id).status == KnowledgeStatus.ARCHIVED.value


def test_links_symmetricish(knowledge_store):
    a = new_knowledge("A", "a"); b = new_knowledge("B", "b")
    knowledge_store.create(a); knowledge_store.create(b)
    knowledge_store.add_link(KnowledgeLink(a.id, b.id, "related"))
    assert len(knowledge_store.links_for(a.id)) == 1
    knowledge_store.remove_link(a.id, b.id, "related")
    assert knowledge_store.links_for(a.id) == []


def test_history_and_metrics(knowledge_store):
    e = new_knowledge("H", "h")
    knowledge_store.create(e)
    knowledge_store.add_history(e.id, "created", {"k": "v"})
    hist = knowledge_store.history(e.id)
    assert hist and hist[0]["kind"] == "created" and hist[0]["data"]["k"] == "v"
    knowledge_store.record_metric("knowledge.created", 1.0)   # smoke


def test_counts_and_health(knowledge_store):
    knowledge_store.create(new_knowledge("A", "a"))
    knowledge_store.create(new_knowledge("B", "b"))
    c = knowledge_store.counts()
    assert c["total"] == 2 and c["active"] == 2
    assert knowledge_store.health()["status"] == "ok"


def test_export_import(knowledge_store, tmp_path):
    knowledge_store.create(new_knowledge("A", "a"))
    dump = knowledge_store.export()
    from core.knowledge.knowledge_store import KnowledgeStore
    other = KnowledgeStore(path=tmp_path / "other.db")
    n = other.import_(dump)
    assert n == 1 and other.counts()["total"] == 1
    other.close()


def test_by_ids(knowledge_store):
    a = new_knowledge("A", "a"); b = new_knowledge("B", "b")
    knowledge_store.create(a); knowledge_store.create(b)
    got = knowledge_store.by_ids([a.id, b.id])
    assert {g.id for g in got} == {a.id, b.id}


def test_side_effect_free_import():
    import importlib
    # importing the package/module must not create the DB or touch the network
    importlib.import_module("core.knowledge.knowledge_store")
    importlib.import_module("core.knowledge.knowledge_models")
