"""Tests for the M8 unified KnowledgeSearch cascade."""

from core.knowledge.knowledge_search import KnowledgeSearch, SearchTier


def test_knowledge_tier_hit(knowledge_service):
    knowledge_service.teach("Flask templates", "templates live under templates/ folder")
    s = KnowledgeSearch(knowledge_service)
    res = s.search("where do flask templates live")
    assert res.found
    assert res.tier == SearchTier.KNOWLEDGE.value
    assert SearchTier.KNOWLEDGE.value in res.trace


def test_search_order_prefers_working_memory(knowledge_service, memory_service):
    memory_service.remember("user", "the deploy token rotates every friday",
                            topic="ops", importance=0.6)
    s = KnowledgeSearch(knowledge_service, memory_service)
    res = s.search("deploy token rotation")
    # working memory holds the just-remembered item ⇒ it wins the cascade
    assert res.tier in (SearchTier.WORKING.value, SearchTier.MEMORY.value)
    assert res.trace[0] == SearchTier.WORKING.value


def test_no_external_by_default(knowledge_service):
    s = KnowledgeSearch(knowledge_service, threshold=0.99)
    res = s.search("a completely unknown subject xyz")
    assert SearchTier.EXTERNAL.value not in res.trace
    assert res.candidate is None


def test_external_last_resort_opt_in(tmp_path):
    from core.knowledge.knowledge_store import KnowledgeStore
    from core.knowledge.knowledge_index import KnowledgeIndex
    from core.knowledge.knowledge_service import KnowledgeService
    from core.knowledge.vault import ObsidianVault

    def fetcher(q):
        return ("A sufficiently long and informative external sentence about it. "
                "A second informative sentence so the summary has real content.")

    store = KnowledgeStore(path=tmp_path / "k.db")
    svc = KnowledgeService(store=store, index=KnowledgeIndex(),
                           vault=ObsidianVault(root=tmp_path / "v"), fetcher=fetcher)
    s = KnowledgeSearch(svc, threshold=0.9)
    res = s.search("unknown topic", allow_external=True)
    assert SearchTier.EXTERNAL.value in res.trace
    assert res.tier == SearchTier.EXTERNAL.value
    assert res.candidate is not None
    store.close()


def test_related_attached_for_knowledge_hit(knowledge_service):
    from core.knowledge.knowledge_models import KnowledgeRelation
    py = knowledge_service.teach("Python", "a programming language")
    fl = knowledge_service.teach("Flask routing maps urls",
                                 "flask maps urls to python view functions with routes")
    knowledge_service.relate(fl.id, py.id, KnowledgeRelation.RELATED.value)
    s = KnowledgeSearch(knowledge_service)
    res = s.search("flask routing urls python")
    assert res.tier == SearchTier.KNOWLEDGE.value
    assert any(r["id"] == py.id for r in res.related)


def test_result_serializable(knowledge_service):
    knowledge_service.teach("Topic", "some content about the topic here")
    s = KnowledgeSearch(knowledge_service)
    d = s.search("topic").to_dict()
    assert "tier" in d and "items" in d and "trace" in d


def test_empty_query_no_crash(knowledge_service):
    s = KnowledgeSearch(knowledge_service)
    res = s.search("")
    assert res.tier in (SearchTier.NONE.value, SearchTier.KNOWLEDGE.value)


def test_confidence_threshold_gates_tier(knowledge_service):
    # a low-confidence knowledge entry shouldn't satisfy a high threshold
    knowledge_service.remember_knowledge("Weakish", "weak-ish knowledge content",
                                         confidence=0.3, validate=False)
    s = KnowledgeSearch(knowledge_service, threshold=0.8)
    res = s.search("weakish")
    # found, but confidence below threshold ⇒ tier kept as best local, not a clean pass
    assert res.confidence < 0.8
