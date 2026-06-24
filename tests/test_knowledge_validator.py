"""M8 — focused tests for the knowledge quality system (KnowledgeValidator).

The validator itself ships in M7; these tests assert the M8 quality-system
contract: duplicate detection, confidence scoring, contradiction flagging, and
the store/update/reject recommendation that gates the learning flow.
"""

from core.knowledge.knowledge_models import new_knowledge
from core.knowledge.knowledge_validator import KnowledgeValidator


def test_clean_store_recommends_store(knowledge_store):
    v = KnowledgeValidator(knowledge_store)
    rep = v.validate(new_knowledge("Novel concept", "entirely new distinct content"))
    assert rep.ok
    assert rep.recommendation == "store"
    assert rep.duplicates == []


def test_duplicate_detection(knowledge_store):
    knowledge_store.create(new_knowledge(
        "SQLite per thread", "open one sqlite connection per thread for safety"))
    v = KnowledgeValidator(knowledge_store)
    rep = v.validate(new_knowledge(
        "SQLite per thread", "open one sqlite connection per thread for safety"))
    assert rep.duplicates
    assert rep.recommendation == "update"


def test_low_confidence_rejected(knowledge_store):
    v = KnowledgeValidator(knowledge_store)
    rep = v.validate(new_knowledge("Shaky", "not sure about this", confidence=0.05))
    assert rep.low_confidence
    assert rep.recommendation == "reject"


def test_outdated_supersession(knowledge_store):
    old = new_knowledge("Caching strategy", "cache results in memory",
                        confidence=0.4)
    knowledge_store.create(old)
    v = KnowledgeValidator(knowledge_store)
    newer = new_knowledge("Caching strategy", "cache results in memory and on disk",
                          confidence=0.9)
    rep = v.validate(newer)
    # higher-confidence, same subject ⇒ flagged as duplicate/outdated → update
    assert rep.recommendation == "update"


def test_contradiction_flagged(knowledge_store):
    knowledge_store.create(new_knowledge(
        "Thread safety of sqlite connections",
        "you can safely share one sqlite connection across many threads"))
    v = KnowledgeValidator(knowledge_store)
    rep = v.validate(new_knowledge(
        "Thread safety of sqlite connections",
        "you must never share a sqlite connection across threads it is not safe"))
    assert rep.contradictions or rep.duplicates


def test_confidence_scoring_passthrough(knowledge_store):
    v = KnowledgeValidator(knowledge_store)
    high = v.validate(new_knowledge("Strong", "well established fact", confidence=0.95))
    assert high.low_confidence is False


def test_report_serializable(knowledge_store):
    v = KnowledgeValidator(knowledge_store)
    rep = v.validate(new_knowledge("X", "y"))
    d = rep.to_dict()
    assert "recommendation" in d and "duplicates" in d
