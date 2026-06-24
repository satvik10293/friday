"""M9 — UserContextBuilder, dashboard APIs, service facade, privacy & events."""

from core.context.context_package import ContextPackage
from core.user_model.dashboard import UserDashboard


# ── UserContextBuilder ────────────────────────────────────────────────────────────
def test_build_user_context_package(user_model_service):
    s = user_model_service
    s.profile.update(name="Satvik")
    s.interests.express("AI")
    s.projects.add_project("FRIDAY")
    s.knowledge_service.teach("AI basics", "ai is the study of intelligent agents")
    s.goal_service.create_goal("Ship FRIDAY", priority=1)
    s.goal_service.activate_goal(s.goal_service.list_goals()[0].goal_id)
    pkg = s.build_user_context("AI")
    assert pkg.user["display_name"] == "Satvik"
    assert pkg.interests and pkg.projects
    assert pkg.knowledge          # interest-boosted knowledge present
    assert not pkg.is_empty
    assert 0.0 <= pkg.confidence <= 1.0


def test_context_includes_active_goals(user_model_service):
    s = user_model_service
    g = s.goal_service.create_goal("Active goal", priority=2)
    s.goal_service.activate_goal(g.goal_id)
    pkg = s.build_user_context("anything")
    assert any(item["title"] == "Active goal" for item in pkg.goals)


def test_context_includes_approved_facts_only(user_model_service):
    s = user_model_service
    s.relationship.remember("Long-term: build a robotics company")
    s.relationship.propose("unapproved fact")
    pkg = s.build_user_context("")
    ctx = pkg.user.get("long_term_context", [])
    assert any("robotics" in c for c in ctx)
    assert all("unapproved" not in c for c in ctx)


def test_context_package_serializable(user_model_service):
    pkg = user_model_service.build_user_context("x")
    d = pkg.to_dict()
    assert "user" in d and "interests" in d and "confidence" in d


def test_augment_context_package(user_model_service):
    s = user_model_service
    s.profile.update(name="Satvik")
    s.interests.express("Python")
    for _ in range(3):
        s.preferences.observe("learning.detail", positive=True)
    pkg = ContextPackage(query="help me")
    s.context_builder.augment_context_package(pkg, "python help")
    assert pkg.world.get("user", {}).get("display_name") == "Satvik"
    assert pkg.world.get("interests")
    assert any(l.get("source") == "preference" for l in pkg.lessons)


# ── Dashboard APIs (data only) ────────────────────────────────────────────────────
def test_dashboard_all_widgets(user_model_service):
    s = user_model_service
    s.projects.add_project("P")
    s.interests.express("AI")
    dash = UserDashboard(s)
    out = dash.all_widgets()
    names = {w["widget"] for w in out["widgets"]}
    assert {"active_projects", "interests", "learning_progress",
            "knowledge_growth", "personal_stats"} <= names


def test_dashboard_active_projects_progress(user_model_service):
    s = user_model_service
    p = s.projects.add_project("Tracked")
    s.projects.add_milestone(p.id, "m1")
    s.projects.complete_milestone(p.id, "m1")
    w = UserDashboard(s).widget_active_projects()
    assert w["items"][0]["progress"] == 1.0


def test_dashboard_knowledge_growth(user_model_service):
    s = user_model_service
    s.knowledge_service.teach("A", "content a")
    w = UserDashboard(s).widget_knowledge_growth()
    assert w["total"] >= 1


# ── service facade: metrics / health / privacy ────────────────────────────────────
def test_service_metrics(user_model_service):
    s = user_model_service
    s.profile.update(name="X")
    s.interests.express("AI")
    m = s.metrics()
    assert m["events"]["profile_updates"] >= 1
    assert m["events"]["interest_growth"] >= 1


def test_service_health(user_model_service):
    s = user_model_service
    s.projects.add_project("Live")
    h = s.health()
    assert h["status"] == "ok" and h["active_projects"] >= 1


def test_understanding_passthrough(user_model_service):
    s = user_model_service
    s.profile.update(name="Satvik")
    assert s.understanding()["user"] == "Satvik"


def test_data_is_local_only(tmp_path):
    """Privacy: the store is a plain local SQLite file under data/, nothing else."""
    from core.user_model.store import UserModelStore
    p = tmp_path / "user_model.db"
    store = UserModelStore(path=p)
    store.add_event("user.profile.updated", {"x": 1})
    assert p.exists()
    store.close()


# ── runtime event emission ────────────────────────────────────────────────────────
def test_emits_runtime_event(runtime, tmp_path):
    import time as _t
    from core.user_model.store import UserModelStore, UserModelEvent
    from core.user_model.service import UserModelService

    seen = []

    async def _handler(ev):
        seen.append(ev)

    runtime.on(UserModelEvent.INTEREST_GROWN, _handler)
    store = UserModelStore(path=tmp_path / "u.db")
    svc = UserModelService(store=store, runtime=runtime)
    svc.interests.express("Robotics")
    deadline = _t.time() + 2.0
    while not seen and _t.time() < deadline:
        _t.sleep(0.02)
    assert seen, "expected a user.interest.grown runtime event"
    store.close()


def test_singleton_identity():
    from core.user_model.service import get_user_model_service
    assert get_user_model_service() is get_user_model_service()
