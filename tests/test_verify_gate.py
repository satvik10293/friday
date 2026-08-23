"""
The Verify gate (core/verify), extracted from friday-v0's OPVER loop.

Pins the tier design and the single result contract:
· Tier 1 objective  — file_exists / file_contains / command(exit code) decide
  by fact, and a path that escapes the workspace root is refused.
· Tier 2 differential — an injected second judge's PASS/FAIL wins over
  self-report; a judge that abstains (or raises) falls through, never crashes.
· Tier 3 self-report — with no criteria and no judge, the producer's own
  confidence decides against the threshold; no confidence → optimistic pass.

Also pins that the LearningGate's `verified` flag withholds ONLY the answer-
quality store paths (substantive / taught), leaving explicit-remember and
personal-info storage untouched.
"""

from __future__ import annotations

from core.verify import Verifier, VerifyResult


# ── Tier 1: objective ───────────────────────────────────────────────────────────────
def test_file_exists_pass_and_fail(tmp_path):
    (tmp_path / "made.txt").write_text("hi", encoding="utf-8")
    v = Verifier()
    ok = v.verify(criteria={"type": "file_exists", "path": "made.txt"},
                  workspace=str(tmp_path))
    assert ok.success and ok.verdict == "pass" and ok.tier == 1
    missing = v.verify(criteria={"type": "file_exists", "path": "nope.txt"},
                       workspace=str(tmp_path))
    assert missing.success is False and missing.verdict == "fail" and missing.tier == 1


def test_file_contains(tmp_path):
    (tmp_path / "app.py").write_text("def main():\n    return 42\n", encoding="utf-8")
    v = Verifier()
    hit = v.verify(criteria={"type": "file_contains", "path": "app.py",
                             "substring": "return 42"}, workspace=str(tmp_path))
    assert hit.success and hit.tier == 1
    miss = v.verify(criteria={"type": "file_contains", "path": "app.py",
                              "substring": "return 43"}, workspace=str(tmp_path))
    assert miss.success is False and miss.tier == 1


def test_workspace_escape_is_refused(tmp_path):
    # a path climbing out of the workspace resolves to None → treated as missing
    v = Verifier()
    escaped = v.verify(criteria={"type": "file_exists", "path": "../secret.txt"},
                       workspace=str(tmp_path))
    assert escaped.success is False and escaped.tier == 1


def test_command_uses_injected_runner_only():
    v = Verifier()
    crit = {"type": "command", "cmd": "pytest -q", "expect_exit": 0}
    # no runner → command cannot be checked, fails safe (never executes anything)
    assert v.verify(criteria=crit).success is False
    passed = v.verify(criteria=crit, runner=lambda cmd: {"exit_code": 0, "output": "ok"})
    assert passed.success and passed.tier == 1
    failed = v.verify(criteria=crit, runner=lambda cmd: {"exit_code": 1, "error": "boom"})
    assert failed.success is False and failed.tier == 1


# ── Tier 2: differential (a second, blind judge) ────────────────────────────────────
def test_differential_pass_and_fail():
    v = Verifier()
    yes = v.verify(artifact="Paris", checker=lambda c, a: "PASS — capital is right")
    assert yes.success and yes.verdict == "pass" and yes.tier == 2
    no = v.verify(artifact="Berlin", checker=lambda c, a: "FAIL: wrong capital")
    assert no.success is False and no.verdict == "fail" and no.tier == 2


def test_differential_abstain_falls_through_to_self_report():
    v = Verifier()
    # judge gives no PASS/FAIL verdict → drop to self-report tier
    out = v.verify(artifact="x", checker=lambda c, a: "hmm, unsure",
                   self_confidence=0.9)
    assert out.tier == 3 and out.success


def test_differential_checker_that_raises_never_crashes():
    def broken(_c, _a):
        raise RuntimeError("judge exploded")

    v = Verifier()
    out = v.verify(artifact="x", checker=broken, self_confidence=0.2)
    assert out.tier == 3 and out.success is False   # abstained → self-report


# ── Tier 3: self-report ─────────────────────────────────────────────────────────────
def test_self_report_threshold():
    v = Verifier(self_report_threshold=0.5)
    assert v.verify(artifact="x", self_confidence=0.8).success
    assert v.verify(artifact="x", self_confidence=0.4).success is False
    # no confidence at all → optimistic pass, marked low tier (friday-v0 behaviour)
    none = v.verify(artifact="x")
    assert none.success and none.tier == 3


def test_result_contract_shape():
    r = VerifyResult(True, "pass", 3, "why")
    assert r.to_dict() == {"success": True, "verdict": "pass",
                           "tier": 3, "detail": "why"}


def test_verify_never_raises_on_garbage():
    v = Verifier()
    # criteria missing its path, weird types — a fault is data, not an exception
    out = v.verify(criteria={"type": "file_contains"}, workspace="/no/such/root")
    assert isinstance(out, VerifyResult) and out.success is False


# ── the LearningGate `verified` flag ────────────────────────────────────────────────
def test_learning_gate_withholds_unverified_substantive():
    from core.memory.learning_gate import LearningGate
    gate = LearningGate()
    verified = gate.decide("what is the capital of france", "Paris",
                           confidence=0.9, verified=True)
    assert verified.store and verified.reason == "substantive"
    unverified = gate.decide("what is the capital of france", "Prob. Marseille?",
                             confidence=0.9, verified=False)
    assert unverified.store is False and unverified.reason == "unverified_answer"


def test_learning_gate_explicit_remember_ignores_verify():
    from core.memory.learning_gate import LearningGate
    gate = LearningGate()
    # an explicit "remember" is the user's own data — verify must not gate it
    d = gate.decide("remember that my dentist is Dr. Lee", "ok",
                    confidence=0.1, verified=False)
    assert d.store and d.reason == "explicit_request" and d.private


def test_a_question_is_never_stored_as_a_personal_fact():
    # "What is my name?" matches _PERSONAL_RE ("my name") but is a QUESTION —
    # it must NOT become a personal fact (that once polluted core memory with
    # the question itself). A real statement of the same fact still stores.
    from core.memory.learning_gate import LearningGate
    gate = LearningGate()
    q = gate.decide("what is my name?", "Satvik", confidence=0.9)
    assert q.reason != "personal_info"
    stated = gate.decide("my name is Satvik", "ok", confidence=0.9)
    assert stated.store and stated.reason == "personal_info" and stated.private
