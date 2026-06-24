"""M9 — ProfileManager: update / merge / version history."""

from core.user_model.user_profile import ProfileManager


def test_profile_created_on_first_access(user_model_store):
    pm = ProfileManager(user_model_store)
    p = pm.get()
    assert p.version == 1
    assert pm.exists()


def test_update_replaces_fields(user_model_store):
    pm = ProfileManager(user_model_store)
    pm.update(name="Satvik", education="High school")
    p = pm.get()
    assert p.name == "Satvik" and p.education == "High school"


def test_display_name_prefers_preferred(user_model_store):
    pm = ProfileManager(user_model_store)
    pm.update(name="Satvik", preferred_name="Sat")
    assert pm.get().display_name() == "Sat"


def test_merge_unions_lists(user_model_store):
    pm = ProfileManager(user_model_store)
    pm.update(interests=["AI"])
    pm.merge(interests=["AI", "Robotics"])
    assert set(pm.get().interests) == {"AI", "Robotics"}


def test_merge_scalar_only_fills_empty(user_model_store):
    pm = ProfileManager(user_model_store)
    pm.update(name="Satvik")
    pm.merge(name="OtherName")          # should NOT overwrite existing
    assert pm.get().name == "Satvik"


def test_add_to_list_field(user_model_store):
    pm = ProfileManager(user_model_store)
    pm.add_to("skills", "Python", "Flask", "Python")   # dup ignored
    assert pm.get().skills == ["Python", "Flask"]


def test_add_to_rejects_non_list_field(user_model_store):
    pm = ProfileManager(user_model_store)
    try:
        pm.add_to("name", "x")
        assert False, "expected ValueError"
    except ValueError:
        pass


def test_version_increments_and_history(user_model_store):
    pm = ProfileManager(user_model_store)
    pm.update(name="A")
    pm.update(name="B")
    pm.update(name="C")
    assert pm.get().version == 4          # created(1) + 3 updates
    hist = pm.history()
    assert len(hist) >= 3


def test_revert_restores_prior(user_model_store):
    pm = ProfileManager(user_model_store)
    pm.update(name="First")               # version 2
    v2 = pm.get().version
    pm.update(name="Second")              # version 3
    pm.revert(v2)
    assert pm.get().name == "First"


def test_metadata_merge(user_model_store):
    pm = ProfileManager(user_model_store)
    pm.merge(metadata={"a": 1})
    pm.merge(metadata={"b": 2})
    meta = pm.get().metadata
    assert meta.get("a") == 1 and meta.get("b") == 2
