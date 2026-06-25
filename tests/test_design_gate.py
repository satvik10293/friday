"""M10 — Design Challenge Gate."""

from core.review.design_gate import (DesignGate, DesignQuestion, DesignReview,
                                     QUESTIONS, get_design_gate)


def _full_answers():
    return {q: f"a substantive answer for {q} that is clearly long enough" for q in QUESTIONS}


def test_eight_questions():
    assert len(QUESTIONS) == 8
    assert DesignQuestion.SECURITY.value in QUESTIONS


def test_incomplete_review_fails():
    gate = DesignGate()
    r = DesignReview("MX").answer(DesignQuestion.EXISTS, "because we need it badly here")
    result = gate.evaluate(r)
    assert not result.passed
    assert len(result.missing) == 7


def test_weak_answers_flagged():
    gate = DesignGate()
    r = DesignReview("MX")
    for q in QUESTIONS:
        r.answer(q, "short")          # under the min length
    result = gate.evaluate(r)
    assert not result.passed
    assert len(result.weak) == 8


def test_complete_review_passes():
    gate = DesignGate()
    r = DesignReview("M10", answers=_full_answers())
    result = gate.evaluate(r)
    assert result.passed
    assert result.missing == [] and result.weak == []


def test_non_additive_blocked():
    gate = DesignGate(require_additive=True)
    r = DesignReview("MX", answers=_full_answers(), additive=False)
    result = gate.evaluate(r)
    assert not result.passed
    assert "additive" in result.notes


def test_submit_records_passing_review():
    gate = DesignGate()
    r = DesignReview("M10", answers=_full_answers())
    res = gate.submit(r)
    assert res.passed
    assert gate.passes("M10")
    assert gate.get_review("M10") is not None


def test_submit_rejects_failing_review():
    gate = DesignGate()
    gate.submit(DesignReview("MX"))
    assert not gate.passes("MX")


def test_unknown_question_rejected():
    r = DesignReview("MX")
    try:
        r.answer("not_a_question", "x")
        assert False
    except KeyError:
        pass


def test_persistence_roundtrip(tmp_path):
    path = tmp_path / "reviews.json"
    g1 = DesignGate(store_path=path)
    g1.submit(DesignReview("M10", answers=_full_answers()))
    assert path.exists()
    g2 = DesignGate(store_path=path)
    assert g2.load() == 1
    assert g2.passes("M10")


def test_health_and_singleton():
    g = get_design_gate()
    assert g is get_design_gate()
    assert g.health()["questions"] == 8
