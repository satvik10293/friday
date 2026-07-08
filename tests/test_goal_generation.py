"""
M28 — Autonomous goal generation (Phase D completion, docs/FRIDAY_5X_ROADMAP.md).

FRIDAY proposes her own goals from failures, curiosity and concerns; every
proposal is human-gated (the scheduler never activates one until Satvik
approves); rejections are remembered and never re-proposed; and at least one
self-generated goal completes end-to-end through the approval gate — the
Phase D exit criterion.
"""

from __future__ import annotations

import pytest

from core.cognition.background import BackgroundCognition
from core.cognition.thoughts import ThoughtStream
from core.goals import GoalGenerator, GoalService, GoalStatus, GoalStore
from core.launcher.conversation import ConversationBridge, _SpeechOutput


@pytest.fixture()
def svc(tmp_path):
    return GoalService(store=GoalStore(tmp_path / "goals.db"))


def _generator(svc, thoughts=None, **kw):
    return GoalGenerator(svc, thoughts=thoughts, **kw)


# ── generation sources ────────────────────────────────────────────────────────

def test_a_failed_goal_becomes_a_remediation_proposal(svc):
    g = svc.create_goal("integrate the weather API")
    svc.fail_goal(g.goal_id, reason="missing API credentials")
    report = _generator(svc).propose()
    assert len(report["proposed"]) == 1
    proposal = svc.list_proposals()[0]
    assert proposal.title.startswith("Address:")
    assert "credential" in proposal.title.lower()
    assert proposal.metadata["proposed_by"] == "friday"
    assert proposal.metadata["source"] == "failure"
    assert "weather API" in proposal.metadata["evidence"]


def test_a_curiosity_hypothesis_becomes_a_learning_proposal(svc):
    thoughts = ThoughtStream()
    thoughts.think("hypothesis", "'spatial reasoning' keeps coming up — worth "
                   "learning more about it.", source="background")
    report = _generator(svc, thoughts).propose()
    assert report["proposed"] == ["Learn more about spatial reasoning"]
    assert svc.list_proposals()[0].metadata["source"] == "curiosity"


def test_a_high_confidence_concern_becomes_an_investigation_proposal(svc):
    thoughts = ThoughtStream()
    thoughts.think("concern", "Memory pressure at 91% — I should avoid loading "
                   "more models.", source="background", confidence=0.8)
    thoughts.think("concern", "mild worry", source="background", confidence=0.3)
    report = _generator(svc, thoughts).propose()
    assert report["proposed"] == ["Investigate: Memory pressure at 91%"]
    assert svc.list_proposals()[0].metadata["source"] == "concern"


# ── dedup, cap, and rejection memory ──────────────────────────────────────────

def test_the_same_proposal_is_never_made_twice(svc):
    g = svc.create_goal("sync the vault")
    svc.fail_goal(g.goal_id, reason="dependency missing")
    gen = _generator(svc)
    assert len(gen.propose()["proposed"]) == 1
    assert gen.propose()["proposed"] == []          # dedup against open proposal
    assert len(svc.list_proposals()) == 1


def test_rejected_proposals_are_archived_and_not_reproposed(svc):
    g = svc.create_goal("sync the vault")
    svc.fail_goal(g.goal_id, reason="dependency missing")
    gen = _generator(svc)
    gen.propose()
    proposal = svc.list_proposals()[0]
    rejected = svc.reject_proposal(proposal.goal_id, reason="not now")
    assert rejected.status == GoalStatus.ARCHIVED
    assert rejected.metadata["proposal_status"] == "rejected"
    assert svc.list_proposals() == []
    assert gen.propose()["proposed"] == []          # rejection is remembered


def test_open_proposals_are_capped(svc):
    for i in range(3):
        svc.propose_goal(f"proposal {i}", source="test")
    g = svc.create_goal("one more failure")
    svc.fail_goal(g.goal_id, reason="timeout")
    gen = _generator(svc)
    report = gen.propose()
    assert report["proposed"] == [] and gen.skipped == 1
    assert len(svc.list_proposals()) == 3


def test_proposals_never_chain_off_failed_proposals(svc):
    p = svc.propose_goal("self-proposed work", source="test")
    svc.approve_proposal(p.goal_id)
    svc.fail_goal(p.goal_id, reason="timeout")
    assert _generator(svc).propose()["proposed"] == []


# ── the human gate ────────────────────────────────────────────────────────────

def test_the_scheduler_never_activates_an_unapproved_proposal(svc):
    svc.propose_goal("reorganize the knowledge vault", source="test")
    for _ in range(3):
        result = svc.tick()
        assert result["activated"] == []
    assert svc.list_proposals()[0].status == GoalStatus.PENDING


def test_an_approved_proposal_enters_the_normal_lifecycle(svc):
    p = svc.propose_goal("reorganize the knowledge vault", source="test")
    svc.approve_proposal(p.goal_id, by="satvik")
    result = svc.tick()
    assert p.goal_id in result["activated"]
    assert svc.get_goal(p.goal_id).metadata["approved_by"] == "satvik"


def test_approve_and_reject_only_act_on_open_proposals(svc):
    g = svc.create_goal("a normal goal")
    assert svc.approve_proposal(g.goal_id) is None
    assert svc.reject_proposal(g.goal_id) is None
    assert svc.approve_proposal("nonexistent") is None


# ── Phase D exit criterion: end-to-end through the gate ───────────────────────

def test_a_self_generated_goal_completes_end_to_end(svc):
    failed = svc.create_goal("call the calendar API")
    svc.fail_goal(failed.goal_id, reason="unauthorized token")

    report = _generator(svc).propose()              # FRIDAY proposes
    assert len(report["proposed"]) == 1
    proposal = svc.list_proposals()[0]

    svc.approve_proposal(proposal.goal_id)          # Satvik approves
    assert proposal.goal_id in svc.tick()["activated"]

    svc.complete_goal(proposal.goal_id, "credentials fixed and verified")
    record = svc.reflect(proposal.goal_id)          # lesson drawn
    assert record is not None and record.status == "completed"
    assert svc.get_goal(proposal.goal_id).status == GoalStatus.COMPLETED
    assert svc.metrics()["proposed"] == 1
    assert svc.metrics()["proposals_approved"] == 1


# ── background cognition wiring ───────────────────────────────────────────────

def test_background_tick_runs_the_generator_and_thinks_about_it(svc):
    g = svc.create_goal("index the archive")
    svc.fail_goal(g.goal_id, reason="dependency missing")
    thoughts = ThoughtStream()
    cognition = BackgroundCognition(thoughts=thoughts, goals=svc,
                                    generator=_generator(svc, thoughts))
    report = cognition.tick()
    if report["budget"] == "full":
        assert report["proposals"]["status"] == "ok"
        assert len(report["proposals"]["proposed"]) == 1
        assert any(t.kind == "planning" and "proposed a goal" in t.text
                   for t in thoughts.recent())


def test_background_tick_survives_a_broken_generator():
    class Broken:
        def propose(self):
            raise RuntimeError("store gone")

    cognition = BackgroundCognition(thoughts=ThoughtStream(), generator=Broken())
    report = cognition.tick()                        # must not raise
    if report["budget"] == "full":
        assert report["proposals"]["status"] == "failed"


# ── voice gate through the conversation bridge ────────────────────────────────

class _Log:
    def __init__(self):
        self.rows = []

    def log(self, **row):
        self.rows.append(row)
        return len(self.rows)


class _NeverThinkIOS:
    def think(self, *a, **kw):
        raise AssertionError("proposal questions must not reach the LLM")


def _bridge(svc):
    return ConversationBridge(_NeverThinkIOS(), decision_log=_Log(), goals=svc,
                              speech=_SpeechOutput(synthesizer=lambda t: None))


def test_voice_can_list_and_approve_proposals(svc):
    svc.propose_goal("tidy the download folder", source="test")
    bridge = _bridge(svc)

    listed = bridge.think("do you have any proposals?")
    assert "tidy the download folder" in listed.answer
    assert bridge._decision_log.rows[0]["route"] == ["goal_proposals"]

    approved = bridge.think("approve the proposal")
    assert "Approved" in approved.answer
    assert svc.list_proposals() == []
    assert svc.get_goal(svc.list_goals(GoalStatus.PENDING)[0].goal_id) is not None


def test_voice_can_reject_a_proposal(svc):
    svc.propose_goal("tidy the download folder", source="test")
    response = _bridge(svc).think("reject that proposal")
    assert "dropped" in response.answer
    assert svc.list_proposals() == []
    assert svc.list_goals(GoalStatus.ARCHIVED)[0].metadata["proposal_status"] == "rejected"


def test_voice_answers_gracefully_with_no_open_proposals(svc):
    response = _bridge(svc).think("any proposals for me?")
    assert "no goal proposals" in response.answer
