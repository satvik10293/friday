"""M9 — ProjectTracker: lifecycle, milestones, and cross-system links."""

from core.user_model.models import ProjectStatus
from core.user_model.project_tracker import ProjectTracker


def test_add_project(user_model_store):
    pt = ProjectTracker(user_model_store)
    p = pt.add_project("FRIDAY 4.0", description="local AI companion")
    assert p.name == "FRIDAY 4.0" and p.status == ProjectStatus.ACTIVE.value


def test_add_project_idempotent_by_name(user_model_store):
    pt = ProjectTracker(user_model_store)
    a = pt.add_project("Same")
    b = pt.add_project("Same")
    assert a.id == b.id
    assert len(pt.list()) == 1


def test_status_transitions(user_model_store):
    pt = ProjectTracker(user_model_store)
    p = pt.add_project("Thing")
    pt.pause(p.id)
    assert pt.get(p.id).status == ProjectStatus.PAUSED.value
    pt.resume(p.id)
    assert pt.get(p.id).status == ProjectStatus.ACTIVE.value
    pt.complete(p.id)
    assert pt.get(p.id).status == ProjectStatus.COMPLETED.value


def test_active_filter(user_model_store):
    pt = ProjectTracker(user_model_store)
    a = pt.add_project("Active one")
    b = pt.add_project("Done one")
    pt.complete(b.id)
    actives = {p.id for p in pt.active()}
    assert a.id in actives and b.id not in actives


def test_milestones_and_progress(user_model_store):
    pt = ProjectTracker(user_model_store)
    p = pt.add_project("Milestoned")
    pt.add_milestone(p.id, "design")
    pt.add_milestone(p.id, "build")
    assert pt.progress(p.id) == 0.0
    pt.complete_milestone(p.id, "design")
    assert pt.progress(p.id) == 0.5


def test_link_goal_knowledge_memory(user_model_store):
    pt = ProjectTracker(user_model_store)
    p = pt.add_project("Linked")
    pt.link_goal(p.id, "goal-1")
    pt.link_knowledge(p.id, "know-1")
    pt.link_memory(p.id, 42)
    fresh = pt.get(p.id)
    assert "goal-1" in fresh.goals
    assert "know-1" in fresh.knowledge_ids
    assert 42 in fresh.memory_ids


def test_link_dedupe(user_model_store):
    pt = ProjectTracker(user_model_store)
    p = pt.add_project("Dedup")
    pt.link_goal(p.id, "g")
    pt.link_goal(p.id, "g")
    assert pt.get(p.id).goals == ["g"]


def test_find_by_name(user_model_store):
    pt = ProjectTracker(user_model_store)
    pt.add_project("Findable Project")
    assert pt.find("findable project") is not None
    assert pt.find("nope") is None


def test_project_update_event(user_model_store):
    pt = ProjectTracker(user_model_store)
    pt.add_project("Eventful")
    events = user_model_store.events("user.project.updated")
    assert any(e["data"].get("name") == "Eventful" for e in events)
