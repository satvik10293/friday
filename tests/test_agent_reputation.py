"""M11 — Worker reputation system."""

import pytest

from core.society.reputation import ReputationSystem
from core.society.store import SocietyStore


@pytest.fixture
def store(tmp_path):
    s = SocietyStore(path=tmp_path / "society.db")
    try:
        yield s
    finally:
        s.close()


def test_first_record_creates_score(store):
    rep = ReputationSystem(store)
    r = rep.record("Math Solver", success=True, duration_ms=50, expected_ms=200)
    assert r["samples"] == 1 and r["score"] > 0


def test_success_beats_failure(store):
    rep = ReputationSystem(store)
    for _ in range(5):
        rep.record("Good", success=True, duration_ms=50)
        rep.record("Bad", success=False, duration_ms=50)
    assert rep.score("Good") > rep.score("Bad")


def test_speed_affects_score(store):
    rep = ReputationSystem(store)
    rep.record("Fast", success=True, duration_ms=50, expected_ms=200)
    rep.record("Slow", success=True, duration_ms=2000, expected_ms=200)
    assert rep.score("Fast") > rep.score("Slow")


def test_success_rate_tracks(store):
    rep = ReputationSystem(store)
    rep.record("X", success=True, duration_ms=10)
    rep.record("X", success=False, duration_ms=10)
    rep.record("X", success=True, duration_ms=10)
    assert abs(rep.get("X")["success_rate"] - (2 / 3)) < 1e-6


def test_preferred_threshold(store):
    rep = ReputationSystem(store, preferred_threshold=0.7)
    for _ in range(6):
        rep.record("Star", success=True, duration_ms=40, expected_ms=200, accuracy=1.0)
    rep.record("Weak", success=False, duration_ms=40)
    assert rep.is_preferred("Star")
    assert "Star" in rep.preferred()
    assert "Weak" not in rep.preferred()


def test_top_templates_ranked(store):
    rep = ReputationSystem(store)
    for _ in range(4):
        rep.record("Best", success=True, duration_ms=30)
    rep.record("Mid", success=True, duration_ms=30)
    rep.record("Worst", success=False, duration_ms=30)
    top = [t["template"] for t in rep.top_templates(3)]
    assert top[0] == "Best" and "Worst" in top[-1:] + ["Worst"]


def test_persistence(tmp_path):
    s1 = SocietyStore(path=tmp_path / "society.db")
    ReputationSystem(s1).record("Persisted", success=True, duration_ms=20)
    s1.close()
    s2 = SocietyStore(path=tmp_path / "society.db")
    assert ReputationSystem(s2).score("Persisted") > 0
    s2.close()
