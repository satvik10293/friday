"""M13 — Belief System: evolving beliefs, evidence, conflict resolution."""

import pytest

from core.cognition_core.belief_system import BeliefSystem
from core.cognition_core.metrics import CognitionMetrics
from core.cognition_core.models import BeliefStatus, Evidence
from core.cognition_core.repositories import (InMemoryBeliefRepository,
                                              SqliteBeliefRepository)


@pytest.fixture
def beliefs():
    return BeliefSystem(InMemoryBeliefRepository(), metrics=CognitionMetrics())


def test_assert_creates_belief(beliefs):
    b = beliefs.assert_belief("ENT_1", "is_open", True, confidence=0.6,
                              evidence=Evidence("sensor", "window visible"))
    assert b.value is True and b.confidence == 0.6
    assert b.supporting_evidence and b.status == BeliefStatus.ACTIVE.value


def test_reinforce_raises_confidence(beliefs):
    beliefs.assert_belief("ENT_1", "is_open", True, confidence=0.6)
    b = beliefs.assert_belief("ENT_1", "is_open", True, confidence=0.7,
                              evidence=Evidence("sensor2", "still visible"))
    assert b.confidence > 0.6                       # corroboration increases confidence
    assert len(beliefs.about("ENT_1")) == 1         # same belief, not a duplicate


def test_conflict_newcomer_wins(beliefs):
    beliefs.assert_belief("ENT_1", "is_open", True, confidence=0.5)
    beliefs.assert_belief("ENT_1", "is_open", False, confidence=0.9)
    active = [b for b in beliefs.about("ENT_1") if b.predicate == "is_open"]
    assert len(active) == 1 and active[0].value is False
    # the superseded belief records the contradiction
    superseded = beliefs.query(subject="ENT_1", active_only=False)
    assert any(b.status == BeliefStatus.SUPERSEDED.value for b in superseded)


def test_conflict_incumbent_holds(beliefs):
    strong = beliefs.assert_belief("ENT_1", "is_open", True, confidence=0.9)
    beliefs.assert_belief("ENT_1", "is_open", False, confidence=0.3)   # weaker challenge
    active = [b for b in beliefs.about("ENT_1") if b.predicate == "is_open"]
    assert len(active) == 1 and active[0].value is True
    assert active[0].contradicting_evidence            # records the challenge


def test_revise(beliefs):
    b = beliefs.assert_belief("ENT_1", "status", "idle", confidence=0.5)
    revised = beliefs.revise(b.belief_id, value="busy", confidence=0.8,
                             evidence=Evidence("cpu", "high load"))
    assert revised.value == "busy" and revised.confidence == 0.8


def test_retract(beliefs):
    b = beliefs.assert_belief("ENT_1", "x", 1, confidence=0.5)
    assert beliefs.retract(b.belief_id)
    assert beliefs.get(b.belief_id).status == BeliefStatus.RETRACTED.value
    assert beliefs.about("ENT_1") == []


def test_verify_updates_timestamp(beliefs):
    b = beliefs.assert_belief("ENT_1", "x", 1, confidence=0.5)
    import time as _t; _t.sleep(0.01)
    verified = beliefs.verify(b.belief_id, confidence=0.7)
    assert verified.last_verification >= b.timestamp and verified.confidence == 0.7


def test_query_filters(beliefs):
    beliefs.assert_belief("ENT_1", "p1", "a", confidence=0.5)
    beliefs.assert_belief("ENT_2", "p1", "b", confidence=0.5)
    assert len(beliefs.query(subject="ENT_1")) == 1
    assert len(beliefs.query(predicate="p1")) == 2


def test_repoint_subject(beliefs):
    beliefs.assert_belief("ENT_OLD", "role", "owner", confidence=0.8)
    moved = beliefs.repoint_subject("ENT_OLD", "ENT_NEW")
    assert moved == 1 and beliefs.about("ENT_NEW") and not beliefs.about("ENT_OLD")


def test_metrics(beliefs):
    beliefs.assert_belief("ENT_1", "x", 1, confidence=0.5)
    beliefs.assert_belief("ENT_1", "x", 2, confidence=0.9)   # conflict
    snap = beliefs._metrics.snapshot()
    assert snap["beliefs_asserted"] >= 1 and snap["belief_conflicts"] >= 1
    assert snap["avg_belief_update_ms"] >= 0.0


def test_sqlite_persistence(tmp_path):
    r1 = SqliteBeliefRepository(path=tmp_path / "c.db")
    bid = BeliefSystem(r1).assert_belief("ENT_1", "x", "v", confidence=0.7,
                                         evidence=Evidence("s", "d")).belief_id
    r1.close()
    r2 = SqliteBeliefRepository(path=tmp_path / "c.db")
    b = BeliefSystem(r2).get(bid)
    assert b.value == "v" and b.supporting_evidence[0].source == "s"
    r2.close()
