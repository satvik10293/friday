"""Tests for the M7 KnowledgeService (public API) + Obsidian vault integration."""

from core.knowledge.knowledge_models import (KnowledgeCategory, KnowledgeRelation,
                                             KnowledgeStatus, new_knowledge)
from core.knowledge.knowledge_service import (KnowledgeEvent, KnowledgeService,
                                              get_knowledge_service)
from core.knowledge.vault import ObsidianVault


# ── write / read ──────────────────────────────────────────────────────────────────
def test_remember_and_search(knowledge_service):
    e = knowledge_service.remember_knowledge(
        "Flask template folder", "templates must live under templates/",
        category=KnowledgeCategory.FLASK)
    hits = knowledge_service.search_knowledge("where do flask templates go")
    assert any(h.id == e.id for h in hits)


def test_remember_writes_vault_note(knowledge_service, tmp_path):
    e = knowledge_service.remember_knowledge("Vaulted", "this should hit disk")
    assert e.vault_path
    assert (tmp_path / "vault" / e.vault_path).exists()


def test_teach_is_trusted(knowledge_service):
    e = knowledge_service.teach("Owner", "Satvik owns Friday", confidence=0.95)
    assert e.source == "user"
    assert knowledge_service.get(e.id) is not None


def test_duplicate_refines_in_place(knowledge_service):
    a = knowledge_service.remember_knowledge(
        "SQLite per thread", "one sqlite connection per thread", confidence=0.5)
    b = knowledge_service.remember_knowledge(
        "SQLite per thread", "one sqlite connection per thread", confidence=0.8)
    # second is a duplicate ⇒ refine, not a new row
    assert b.id == a.id
    assert knowledge_service.store.counts()["total"] == 1
    assert knowledge_service.get(a.id).confidence == 0.8


def test_low_confidence_rejected(knowledge_service):
    before = knowledge_service.store.counts()["total"]
    knowledge_service.remember_knowledge("junk", "unsure maybe", confidence=0.05)
    assert knowledge_service.store.counts()["total"] == before


def test_update_knowledge(knowledge_service):
    e = knowledge_service.remember_knowledge("T", "original")
    upd = knowledge_service.update_knowledge(e.id, content="revised")
    assert upd.content == "revised"


# ── learning / integration ────────────────────────────────────────────────────────
def test_learn_distils_and_stores(knowledge_service):
    e = knowledge_service.learn(
        "Flask raised TemplateNotFound until index.html went under templates folder")
    assert e is not None
    assert knowledge_service.get(e.id) is not None


def test_promote_reflection(knowledge_service):
    e = knowledge_service.promote_reflection(
        {"goal_id": "g1", "lesson": "Validate user input before the database call",
         "summary": "fixed a bug"})
    assert e is not None and e.category == KnowledgeCategory.LESSON


def test_learn_from_goal_alias(knowledge_service):
    e = knowledge_service.learn_from_goal(
        {"goal_id": "g2", "lesson": "Cache expensive computations once"})
    assert e is not None


def test_promote_memory(knowledge_service):
    e = knowledge_service.promote_memory(
        {"id": 7, "topic": "Backoff", "content": "retry with exponential backoff jitter"})
    assert e is not None


# ── relationships ─────────────────────────────────────────────────────────────────
def test_relate_and_explain(knowledge_service):
    py = knowledge_service.teach("Python", "the language")
    fl = knowledge_service.teach("Flask", "a python web framework")
    knowledge_service.relate(py.id, fl.id, KnowledgeRelation.RELATED.value)
    assert "Python" in knowledge_service.explain(py.id, fl.id)


# ── answer (local-first, external last) ───────────────────────────────────────────
def test_answer_local_first(knowledge_service):
    knowledge_service.teach("Friday owner", "Satvik is the owner of Friday")
    res = knowledge_service.answer("who owns friday")
    assert res["source"] == "local" and res["entries"]


def test_answer_no_external_by_default(knowledge_service):
    res = knowledge_service.answer("some completely unknown subject")
    assert res["source"] == "none"


def test_answer_external_opt_in(tmp_path):
    from core.knowledge.knowledge_store import KnowledgeStore
    from core.knowledge.knowledge_index import KnowledgeIndex

    def fetcher(q):
        return ("A sufficiently informative external sentence about the topic here. "
                "A second informative sentence so the summary has real content too.")

    store = KnowledgeStore(path=tmp_path / "k.db")
    svc = KnowledgeService(store=store, index=KnowledgeIndex(),
                           vault=ObsidianVault(root=tmp_path / "v"), fetcher=fetcher)
    res = svc.answer("unknown thing", allow_external=True)
    assert res["source"] == "external" and res["candidate"] is not None
    store.close()


# ── consolidation / maintenance ───────────────────────────────────────────────────
def test_consolidate(knowledge_service):
    knowledge_service.remember_knowledge(
        "SQLite threads one", "sqlite one connection per thread safety",
        category=KnowledgeCategory.SQLITE)
    knowledge_service.remember_knowledge(
        "SQLite threads two", "sqlite connection per thread threads safety",
        category=KnowledgeCategory.SQLITE)
    result = knowledge_service.consolidate(category=KnowledgeCategory.SQLITE)
    assert result.summaries_created == 1


def test_archive(knowledge_service):
    e = knowledge_service.remember_knowledge("Temp", "to be archived")
    knowledge_service.archive(e.id)
    assert knowledge_service.get(e.id).status == KnowledgeStatus.ARCHIVED.value


def test_seed_coding_patterns(knowledge_service):
    created = knowledge_service.seed_coding_patterns()
    assert len(created) >= 4
    hits = knowledge_service.search_knowledge("sqlite connection per thread")
    assert hits


def test_validate_api(knowledge_service):
    rep = knowledge_service.validate("Anything", "fresh content")
    assert rep.recommendation in ("store", "update", "reject")


def test_stats_and_health(knowledge_service):
    knowledge_service.remember_knowledge("A", "a")
    stats = knowledge_service.stats()
    assert stats["total"] >= 1 and "index" in stats and "vault" in stats
    assert knowledge_service.health()["status"] == "ok"


# ── runtime events ────────────────────────────────────────────────────────────────
def test_emits_runtime_event(runtime, tmp_path):
    import time as _t
    from core.knowledge.knowledge_store import KnowledgeStore
    from core.knowledge.knowledge_index import KnowledgeIndex

    seen = []

    async def _handler(ev):
        seen.append(ev)

    runtime.on(KnowledgeEvent.CREATED, _handler)
    store = KnowledgeStore(path=tmp_path / "k.db")
    svc = KnowledgeService(store=store, index=KnowledgeIndex(),
                           vault=ObsidianVault(root=tmp_path / "v"), runtime=runtime)
    svc.remember_knowledge("Eventful", "fires an event")
    deadline = _t.time() + 2.0
    while not seen and _t.time() < deadline:
        _t.sleep(0.02)
    assert seen, "expected a knowledge.created runtime event"
    store.close()


# ── vault integration ─────────────────────────────────────────────────────────────
def test_vault_render_parse_roundtrip(tmp_path):
    v = ObsidianVault(root=tmp_path / "vault")
    e = new_knowledge("Roundtrip", "the body of the note", category=KnowledgeCategory.PYTHON)
    rel = v.write(e)
    parsed = v.read(rel)
    assert parsed is not None
    assert parsed.id == e.id and parsed.title == "Roundtrip"
    assert "the body of the note" in parsed.content


def test_vault_preserves_manual_edits(tmp_path):
    v = ObsidianVault(root=tmp_path / "vault")
    e = new_knowledge("Editable", "machine content")
    rel = v.write(e)
    # simulate a manual edit with a newer timestamp
    edited = v.read(rel)
    edited.content = "HUMAN EDITED CONTENT"
    edited.updated_at = e.updated_at + 100
    v.write(edited, force=True)
    # now Friday tries to overwrite with the stale machine copy, no force
    v.write(e)
    assert "HUMAN EDITED CONTENT" in v.read(rel).content


def test_vault_scan(tmp_path):
    v = ObsidianVault(root=tmp_path / "vault")
    v.write(new_knowledge("One", "first"))
    v.write(new_knowledge("Two", "second"))
    found = v.scan()
    assert len(found) == 2


def test_rebuild_from_vault(tmp_path):
    from core.knowledge.knowledge_store import KnowledgeStore
    from core.knowledge.knowledge_index import KnowledgeIndex
    vault = ObsidianVault(root=tmp_path / "vault")
    # author two notes directly into the vault
    vault.write(new_knowledge("Alpha", "alpha body"))
    vault.write(new_knowledge("Beta", "beta body"))
    store = KnowledgeStore(path=tmp_path / "k.db")
    svc = KnowledgeService(store=store, index=KnowledgeIndex(), vault=vault)
    n = svc.rebuild_from_vault()
    assert n == 2
    assert svc.store.counts()["total"] == 2
    store.close()


def test_singleton_identity():
    assert get_knowledge_service() is get_knowledge_service()
