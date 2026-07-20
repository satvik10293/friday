"""
Coding-reasoning faculty (M60): she PROVES code behaviour, not guesses it.

She runs a snippet in a restricted sandbox and reports the real output, or
AST-analyses it for validity / complexity / structure / bugs — the coding
equivalent of the exact-math toolbox. Safety is load-bearing: the sandbox
refuses imports, filesystem, eval/exec, dunder access, and runaway loops.
"""

from __future__ import annotations

from core.reasoning import code, exact
from core.reasoning.engine import DeliberateReasoner


# ── execution: real output, proven ────────────────────────────────────────────

def test_runs_a_loop_and_reports_the_real_output():
    out = code.answer("what does this print: for i in range(3): print(i * i)")
    assert "0" in out and "1" in out and "4" in out


def test_evaluates_a_last_expression_like_a_repl():
    out = code.answer("run this: sum([x for x in range(1, 11)])")
    assert "55" in out


def test_reports_a_runtime_error_faithfully():
    r = code.run_code("x = 1 / 0")
    assert not r["ok"] and "ZeroDivision" in r["error"]


# ── static analysis ───────────────────────────────────────────────────────────

def test_validity():
    assert code.valid_python("x = [i for i in range(5)]")["valid"] is True
    bad = code.valid_python("def f(x) return x")
    assert bad["valid"] is False and "line 1" in bad["error"]


def test_complexity_from_loop_nesting():
    assert "O(1)" in code.complexity("x = 1 + 2")
    assert "O(n)" in code.complexity("for i in range(n):\n    print(i)")
    assert "O(n^2)" in code.complexity(
        "for i in range(n):\n    for j in range(n):\n        print(i, j)")


def test_explain_is_structural_and_factual():
    out = code.explain("def add(a, b):\n    return a + b")
    assert "add" in out and "1 function" in out


def test_bugs_finds_static_issues():
    out = code.bugs("def f(x):\n    if x == None:\n        return\n    try:\n"
                    "        return 1 / x\n    except:\n        pass")
    assert "is None" in out and "bare except" in out


# ── safety: the sandbox refuses, never runs ───────────────────────────────────

def test_imports_are_blocked():
    r = code.run_code("import os\nos.system('echo hi')")
    assert not r["ok"] and "import" in r["error"].lower()


def test_filesystem_and_eval_are_blocked():
    assert not code.run_code("open('/etc/passwd').read()")["ok"]
    assert not code.run_code("eval('2+2')")["ok"]
    assert not code.run_code("exec('x=1')")["ok"]


def test_dunder_escape_is_blocked():
    # the classic sandbox escape via ().__class__.__bases__...
    r = code.run_code("().__class__.__bases__[0].__subclasses__()")
    assert not r["ok"] and "underscore" in r["error"].lower()


def test_infinite_loop_times_out_without_corrupting_stdout(capsys):
    r = code.run_code("while True: pass", timeout=1.0)
    assert not r["ok"] and "timed out" in r["error"]
    print("stdout still works")               # must not have been redirected away
    assert "stdout still works" in capsys.readouterr().out


# ── the front door only fires on real code ────────────────────────────────────

def test_non_code_questions_are_left_alone():
    assert code.answer("what is the capital of France") is None
    assert code.answer("why is the sky blue") is None


# ── engine integration + composite math (smarter thinking) ────────────────────

class _Sub:
    base_confidence = 0.5

    def available(self):
        return True

    def generate(self, prompt, *, context=None, temperature=0.3):
        return "a guess"


def test_engine_runs_code_before_generating():
    brain = DeliberateReasoner(_Sub(), think_in_tokens=False)
    ans = brain.reason("what does this print: print(2 ** 10)")
    assert "1024" in ans.answer and ans.confidence >= 0.9   # executed, high trust


def test_composite_percent_is_chained_whole():
    # the bare percent solver would drop the '+ 10'; composite computes it all
    assert exact.solve("what is 15% of 240 plus 10") == "15% of 240 + 10 = 46"
    assert exact.solve("what is 50% of 80 minus 5") == "50% of 80 - 5 = 35"


# ── number theory: provable facts (smarter thinking) ──────────────────────────

def test_primality():
    assert exact.solve("is 17 prime") == "Yes, 17 is prime."
    assert "isn't prime" in exact.solve("is 18 prime") and "9" in exact.solve("is 18 prime")


def test_parity_and_perfect_square():
    assert exact.solve("is 42 even") == "Yes, 42 is even."
    assert "odd" in exact.solve("is 7 even")            # honest correction
    assert "4^2" in exact.solve("is 16 a perfect square")
    assert "isn't" in exact.solve("is 15 a perfect square")


def test_factors_and_prime_factors():
    assert exact.solve("factors of 24") == "The factors of 24 are 1, 2, 3, 4, 6, 8, 12, 24."
    assert "2, 2, 3, 5" in exact.solve("prime factors of 60")


def test_gcd_lcm_and_base_conversion():
    assert exact.solve("gcd of 12 and 18") == "The GCD of 12 and 18 is 6."
    assert exact.solve("lcm of 4 and 6") == "The LCM of 4 and 6 is 12."
    assert exact.solve("255 in hex") == "255 in hexadecimal is FF."
    assert exact.solve("10 in binary") == "10 in binary is 1010."
