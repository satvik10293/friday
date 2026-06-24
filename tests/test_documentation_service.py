"""Tests for the M7 DocumentationService (local-first external bridge)."""

from core.knowledge.documentation_service import DocumentationService, summarize
from core.knowledge.knowledge_models import new_knowledge


def test_summarize_distils():
    raw = ("Intro sentence is short. "
           "This is a much longer and far more informative sentence that explains "
           "the actual mechanism in real detail and should be kept. "
           "Another fairly substantial sentence that also carries real meaning worth keeping. "
           "Tiny.")
    out = summarize(raw, max_sentences=2)
    assert "informative" in out
    assert len(out) <= 600
    assert out != raw           # never a full dump


def test_summarize_empty():
    assert summarize("") == ""


def test_offline_by_default(knowledge_store):
    svc = DocumentationService(knowledge_store)
    assert svc.can_fetch is False


def test_local_first_skips_external(knowledge_store):
    knowledge_store.create(new_knowledge("Flask routing", "use @app.route decorators"))
    calls = []

    def fetcher(q):
        calls.append(q)
        return "external text"

    svc = DocumentationService(knowledge_store, fetcher=fetcher)
    res = svc.lookup("flask routing")
    assert res["source"] == "local"
    assert calls == []          # external never consulted when local suffices


def test_external_used_only_when_local_insufficient(knowledge_store):
    def fetcher(q):
        return ("A long external explanation sentence that is informative enough. "
                "And a second meaningful sentence with real content to summarise.")

    svc = DocumentationService(knowledge_store, fetcher=fetcher)
    res = svc.lookup("totally unknown topic")
    assert res["source"] == "external"
    assert res["candidate"] is not None
    assert res["candidate"].metadata.get("summarized") is True
    assert res["candidate"].source == "external"


def test_no_fetcher_returns_none(knowledge_store):
    svc = DocumentationService(knowledge_store)
    res = svc.lookup("unknown")
    assert res["source"] == "none" and res["candidate"] is None


def test_fetcher_exception_safe(knowledge_store):
    def fetcher(q):
        raise RuntimeError("network down")

    svc = DocumentationService(knowledge_store, fetcher=fetcher)
    res = svc.lookup("unknown")      # must not raise
    assert res["source"] == "none"


def test_candidate_not_stored(knowledge_store):
    def fetcher(q):
        return ("Informative external sentence number one here for testing. "
                "Second informative external sentence with content for testing.")

    svc = DocumentationService(knowledge_store, fetcher=fetcher)
    svc.lookup("unknown topic xyz")
    # the service only proposes a candidate; it never writes to the store itself
    assert knowledge_store.counts()["total"] == 0
