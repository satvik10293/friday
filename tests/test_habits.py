"""M9 — HabitTracker: pattern detection from reported activity (no surveillance)."""

import time

from core.user_model.habits import HabitTracker, bucket_for


def _evening():
    # a timestamp at 20:00 local time today
    lt = time.localtime()
    return time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday, 20, 0, 0, 0, 0, -1))


def test_bucket_for():
    assert bucket_for(20) == "evening"
    assert bucket_for(8) == "morning"
    assert bucket_for(2) == "night"


def test_record_activity_creates_habit(user_model_store):
    ht = HabitTracker(user_model_store)
    h = ht.record_activity("coding", bucket="evening")
    assert h.kind == "coding" and h.bucket == "evening" and h.count == 1


def test_confidence_grows_with_repetition(user_model_store):
    ht = HabitTracker(user_model_store)
    last = 0.0
    for _ in range(6):
        last = ht.record_activity("coding", bucket="evening").confidence
    assert last > 0.6


def test_discovered_threshold(user_model_store):
    ht = HabitTracker(user_model_store, discovery_threshold=0.6)
    for _ in range(6):
        ht.record_activity("study", bucket="morning")
    discovered = {h.key for h in ht.discovered()}
    assert "study@morning" in discovered


def test_typical_time(user_model_store):
    ht = HabitTracker(user_model_store)
    for _ in range(3):
        ht.record_activity("coding", bucket="evening")
    ht.record_activity("coding", bucket="morning")
    assert ht.typical_time("coding") == "evening"


def test_record_from_timestamp(user_model_store):
    ht = HabitTracker(user_model_store)
    h = ht.record_activity("research", at=_evening())
    assert h.bucket == "evening"


def test_habit_discovered_event(user_model_store):
    ht = HabitTracker(user_model_store, discovery_threshold=0.6)
    for _ in range(6):
        ht.record_activity("coding", bucket="evening")
    events = user_model_store.events("user.habit.discovered")
    assert any(e["data"].get("key") == "coding@evening" for e in events)


def test_list_by_kind(user_model_store):
    ht = HabitTracker(user_model_store)
    ht.record_activity("coding", bucket="evening")
    ht.record_activity("study", bucket="morning")
    assert len(ht.list(kind="coding")) == 1
