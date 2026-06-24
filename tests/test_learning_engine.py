"""Tests for the M7 LearningEngine + KnowledgeValidator."""

from core.knowledge.knowledge_models import (KnowledgeCategory, new_knowledge)
from core.knowledge.knowledge_validator import KnowledgeValidator
from core.knowledge.learning_engine import LearningEngine


# ── LearningEngine ────────────────────────────────────────────────────────────────
def test_extract_lesson_basic():
    eng = LearningEngine()
    text = ("Flask raised TemplateNotFound until I moved index.html into the "
            "templates folder. Templates must live under templates/.")
    entry = eng.extract_lesson(text)
    assert entry is not None
    assert entry.content.startswith("Flask raised")
    assert entry.category == KnowledgeCategory.FLASK


def test_extract_lesson_too_short():
    assert LearningEngine().extract_lesson("hi") is None


def test_extract_lesson_custom_title():
    eng = LearningEngine()
    e = eng.extract_lesson("some reasonably long lesson body here", title="My Lesson")
    assert e.title == "My Lesson"


def test_learn_from_memories():
    eng = LearningEngine()
    mems = [{"id": 1, "content": "sqlite needs one connection per thread"},
            {"id": 2, "content": "sqlite WAL allows concurrent readers"}]
    e = eng.learn_from_memories(mems, topic="SQLite threading")
    assert e is not None
    assert e.metadata["from_memories"] == [1, 2]


def test_promote_memory():
    eng = LearningEngine()
    e = eng.promote_memory({"id": 9, "topic": "Retries",
                            "content": "retry with exponential backoff and jitter"})
    assert e is not None and e.metadata["from_memory"] == 9


def test_promote_reflection_uses_lesson():
    eng = LearningEngine()
    e = eng.promote_reflection({"goal_id": "g1", "lesson": "Always validate inputs",
                                "summary": "did a thing"})
    assert e is not None
    assert e.content == "Always validate inputs"
    assert e.category == KnowledgeCategory.LESSON
    assert e.metadata["goal_id"] == "g1"


def test_promote_reflection_empty():
    assert LearningEngine().promote_reflection({"goal_id": "g"}) is None


def test_category_guess():
    eng = LearningEngine()
    assert eng.extract_lesson("use fastapi dependency injection here please").category \
        == KnowledgeCategory.FASTAPI


# ── KnowledgeValidator ────────────────────────────────────────────────────────────
def test_validator_clean_store(knowledge_store):
    v = KnowledgeValidator(knowledge_store)
    rep = v.validate(new_knowledge("Brand new", "totally novel content here"))
    assert rep.ok and rep.recommendation == "store"


def test_validator_detects_duplicate(knowledge_store):
    knowledge_store.create(new_knowledge("Flask templates folder",
                                         "templates must live under the templates directory"))
    v = KnowledgeValidator(knowledge_store)
    rep = v.validate(new_knowledge("Flask templates folder",
                                   "templates must live under the templates directory"))
    assert rep.duplicates and rep.recommendation == "update"


def test_validator_low_confidence(knowledge_store):
    v = KnowledgeValidator(knowledge_store)
    rep = v.validate(new_knowledge("Weak", "maybe possibly unsure", confidence=0.1))
    assert rep.low_confidence and rep.recommendation == "reject"


def test_validator_contradiction(knowledge_store):
    knowledge_store.create(new_knowledge(
        "Use global sqlite connection",
        "you can share one sqlite connection across all threads safely"))
    v = KnowledgeValidator(knowledge_store)
    rep = v.validate(new_knowledge(
        "Use global sqlite connection",
        "you should not share a sqlite connection across threads never do this"))
    # same subject, opposite polarity ⇒ flagged (duplicate OR contradiction)
    assert rep.contradictions or rep.duplicates
