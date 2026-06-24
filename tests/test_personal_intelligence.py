"""M9 — PersonalIntelligence (explainable personalization) + communication /
learning / relationship engines."""

from core.user_model.communication_model import CommunicationModel
from core.user_model.learning_profile import LearningProfile
from core.user_model.models import CommunicationAspect, LearningStyleType
from core.user_model.relationship_memory import RelationshipMemory


# ── PersonalIntelligence ──────────────────────────────────────────────────────────
def test_build_understanding(user_model_service):
    s = user_model_service
    s.profile.update(name="Satvik", preferred_name="Sat")
    s.interests.express("Python")
    s.projects.add_project("FRIDAY")
    u = s.intelligence.build_understanding()
    assert u["user"] == "Sat"
    assert any(i["name"] == "Python" for i in u["top_interests"])
    assert any(p["name"] == "FRIDAY" for p in u["active_projects"])


def test_suggest_knowledge_interest_boost(user_model_service):
    s = user_model_service
    s.knowledge_service.teach("Python decorators", "decorators wrap python functions")
    s.knowledge_service.teach("Soup recipe", "boil vegetables in water")
    for _ in range(4):
        s.interests.express("Python")
    recs = s.intelligence.suggest_knowledge("explain a topic", k=2)
    assert recs
    # the python item should be ranked first thanks to the interest boost
    assert "Python" in recs[0].item["title"]
    assert any(e.source == "interest" for e in recs[0].evidence)


def test_suggest_knowledge_no_service():
    from core.user_model.service import UserModelService
    from core.user_model.store import UserModelStore
    import tempfile, os
    d = tempfile.mkdtemp()
    svc = UserModelService(store=UserModelStore(path=os.path.join(d, "u.db")))
    assert svc.intelligence.suggest_knowledge("anything") == []
    svc.close()


def test_explain_has_evidence(user_model_service):
    s = user_model_service
    s.knowledge_service.teach("Genetics basics", "genes encode proteins")
    for _ in range(3):
        s.interests.express("Genetics")
    explanation = s.intelligence.explain("genetics")
    assert explanation["recommendation"]
    assert explanation["evidence"]
    assert "reason" in explanation and explanation["reason"]


def test_project_relevance_boosts_score(user_model_service):
    s = user_model_service
    s.knowledge_service.teach("FRIDAY architecture", "the friday system has layers")
    s.projects.add_project("FRIDAY")
    recs = s.intelligence.suggest_knowledge("architecture")
    assert any(e.source == "project" for r in recs for e in r.evidence)


def test_goal_relevance_and_prioritize(user_model_service):
    s = user_model_service
    g1 = s.goal_service.create_goal("Learn Python", priority=3)
    g2 = s.goal_service.create_goal("Buy groceries", priority=3)
    for _ in range(4):
        s.interests.express("Python")
    ranked = s.intelligence.prioritize_goals([g1, g2])
    assert ranked[0]["title"] == "Learn Python"


def test_personalize_response(user_model_service):
    s = user_model_service
    s.communication.wants_more_detail()
    out = s.intelligence.personalize_response("here is an answer")
    assert out["text"] == "here is an answer"
    assert "detail_level" in out["style"]


# ── CommunicationModel ────────────────────────────────────────────────────────────
def test_communication_adapts(user_model_store):
    cm = CommunicationModel(user_model_store)
    for _ in range(4):
        cm.wants_more_detail()
    assert cm.value(CommunicationAspect.DETAIL_LEVEL.value) > 0.6
    assert cm.style()[CommunicationAspect.DETAIL_LEVEL.value]["label"] == "detailed"


def test_communication_two_directions(user_model_store):
    cm = CommunicationModel(user_model_store)
    for _ in range(4):
        cm.wants_simpler()
    assert cm.value(CommunicationAspect.TECHNICAL_DEPTH.value) < 0.4


def test_adapt_hint(user_model_store):
    cm = CommunicationModel(user_model_store)
    hint = cm.adapt_hint()
    assert set(hint.keys()) == {a.value for a in CommunicationAspect}


# ── LearningProfile ───────────────────────────────────────────────────────────────
def test_learning_dominant(user_model_store):
    lp = LearningProfile(user_model_store)
    lp.observe_example(); lp.observe_example(); lp.observe_visual()
    assert lp.dominant() == LearningStyleType.EXAMPLE_DRIVEN.value


def test_learning_profile_distribution(user_model_store):
    lp = LearningProfile(user_model_store)
    lp.observe_deep_dive()
    prof = lp.profile()
    assert prof["dominant"] == LearningStyleType.DEEP_DIVE.value
    assert abs(sum(prof["distribution"].values()) - 1.0) < 1e-6


# ── RelationshipMemory (privacy gate) ─────────────────────────────────────────────
def test_proposal_inactive_until_approved(user_model_store):
    rm = RelationshipMemory(user_model_store)
    fact = rm.propose("User is building a robotics startup")
    assert fact.approved is False
    assert fact not in rm.active()
    rm.approve(fact.id)
    assert any(f.id == fact.id for f in rm.active())


def test_remember_is_approved(user_model_store):
    rm = RelationshipMemory(user_model_store)
    fact = rm.remember("Long-term goal: become a geneticist")
    assert fact.approved is True
    assert any(f.id == fact.id for f in rm.active())


def test_sensitive_flag_requires_approval(user_model_store):
    rm = RelationshipMemory(user_model_store)
    fact = rm.propose("a sensitive detail", sensitive=True)
    assert fact.sensitive is True and fact.approved is False
    assert fact.id in {f.id for f in rm.pending()}


def test_reject_keeps_inactive(user_model_store):
    rm = RelationshipMemory(user_model_store)
    fact = rm.propose("uncertain fact")
    rm.reject(fact.id)
    assert fact.id not in {f.id for f in rm.active()}
