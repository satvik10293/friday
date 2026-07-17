"""
core/reasoning/engine.py — FRIDAY 5.x (M54)
Her own reasoning brain — the deliberate mind (System 2).

This is the part that is genuinely HERS. Not a model call: a cognitive
controller we author, which turns a question into an *answer she reasoned to*:

    1. Exact first   — if the question is a calculation, COMPUTE it (real
                       arithmetic), never guess. Truth you can check is never
                       left to a language model.
    2. Decompose     — break the question into ordered reasoning steps (a plan
                       she writes), capped so she stays on task.
    3. Work the steps— each step is solved into WORKING MEMORY; steps that are
                       exact (arithmetic) are computed, the rest reasoned via
                       the substrate, each grounded in what came before.
    4. Synthesize    — compose the worked steps into the final answer.
    5. Verify        — optional self-consistency: reason it more than once and
                       keep the answer the runs agree on (guards a shaky
                       substrate against a one-off blunder).

The intelligence lives in this architecture — decomposition, working memory,
tool-grounded truth, self-verification. The substrate (engine-agnostic; see
substrate.py) is only the language faculty it thinks with, so the same brain
runs over the pulled local model or the builtin team.

Contract: `reason(question, context) -> ReasonedAnswer` — identical to the
LocalReasoner/CloudReasoner surface, so it drops straight into the local chain.
Never raises.
"""

from __future__ import annotations

import logging
import re
import time
from collections import Counter
from dataclasses import dataclass, field
from typing import Optional

from core.intelligence.cloud_reasoner import ReasonedAnswer  # shared contract
from core.reasoning.substrate import Substrate
from core.society import worker_tasks as wt

log = logging.getLogger("friday.reasoning.engine")

# a run of numbers/operators/parens with at least one binary operator between
# operands — a computable arithmetic expression embedded in prose
_EXPR = re.compile(r"\d[\d\s.]*(?:\s*(?:\*\*|[-+*/%])\s*\(?\d[\d\s.]*\)?)+")
_PERCENT_OF = re.compile(r"(\d+(?:\.\d+)?)\s*%\s*of\s+(\d+(?:\.\d+)?)", re.I)
_POWER = re.compile(
    r"(\d+(?:\.\d+)?)\s*(?:\^|\*\*|to the power of|raised to(?: the power of)?)\s*"
    r"(\d+(?:\.\d+)?)", re.I)
_CALC_INTENT = re.compile(
    r"\b(calculate|compute|what(?:'s| is)|how much is|solve|sum of|product of|"
    r"times|plus|minus|divided by|multiplied by|percent|power)\b", re.I)
_STEP_LEAD = re.compile(r"^\s*(?:step\s*\d+[:.)]?|\d+[:.)]|[-*•])\s*", re.I)
# a question complex enough to earn decomposition (System 2); anything else
# stays a single direct pass (System 1) so she doesn't over-think "hi"
_COMPLEX = re.compile(
    r"\b(and|then|after|before|steps?|how (?:do|to|can|does)|why|explain|"
    r"compare|difference between|pros and cons|walk me through|list)\b", re.I)


def _fmt(value) -> str:
    """Render a computed number cleanly (2.0 → 2)."""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


@dataclass
class Step:
    text: str
    kind: str            # "math" | "reason"
    result: str
    confidence: float = 0.0


@dataclass
class Deliberation:
    answer: str
    steps: list = field(default_factory=list)
    confidence: float = 0.0
    exact: bool = False


class DeliberateReasoner:
    """FRIDAY's deliberate reasoning brain. Substrate-agnostic; never raises."""

    def __init__(self, substrate: Substrate, *, name: str = "deliberate",
                 self_consistency: int = 1, max_steps: int = 4,
                 decompose: bool = True) -> None:
        self.substrate = substrate
        self.name = name
        self.self_consistency = max(1, int(self_consistency))
        self.max_steps = max(1, int(max_steps))
        self.decompose = decompose
        self.asked = 0
        self.answered = 0
        self.failed = 0
        self.exact_answers = 0
        self.math_steps = 0
        self.total_latency_ms = 0.0

    def available(self) -> bool:
        try:
            return self.substrate.available()
        except Exception:  # noqa: BLE001
            return False

    # ── the public contract (mirrors LocalReasoner/CloudReasoner) ────────────────
    def reason(self, question: str, *, context: Optional[dict] = None) -> ReasonedAnswer:
        if not self.available():
            return ReasonedAnswer(ok=False, error="reasoner unavailable")
        self.asked += 1
        t0 = time.perf_counter()
        try:
            d = self._deliberate(question or "", context)
        except Exception as e:  # noqa: BLE001 — a reasoning fault must never crash a turn
            self.failed += 1
            log.debug("deliberation failed", exc_info=True)
            return ReasonedAnswer(ok=False, error=str(e),
                                  latency_ms=(time.perf_counter() - t0) * 1000.0)
        latency = (time.perf_counter() - t0) * 1000.0
        if not (d.answer or "").strip():
            self.failed += 1
            return ReasonedAnswer(ok=False, error="no answer reached",
                                  latency_ms=latency)
        self.answered += 1
        if d.exact:
            self.exact_answers += 1
        self.total_latency_ms += latency
        return ReasonedAnswer(ok=True, answer=d.answer, model=self.name,
                              latency_ms=latency, confidence=d.confidence)

    # ── the deliberate loop ──────────────────────────────────────────────────────
    def _deliberate(self, question: str, context: Optional[dict]) -> Deliberation:
        base = float(getattr(self.substrate, "base_confidence", 0.6))

        # 1. exact first: a calculation is COMPUTED, never guessed (full trust)
        exact = self._exact_arithmetic(question)
        if exact is not None:
            return Deliberation(answer=exact,
                                steps=[Step(question, "math", exact, 1.0)],
                                confidence=1.0, exact=True)

        # 2. adaptive depth: only complex questions earn System-2 decomposition;
        #    simple ones stay a single direct pass so she doesn't over-think
        if self._should_decompose(question):
            plan = self._plan(question, context)
            steps: list[Step] = []
            memory: list[str] = []
            for raw in plan[:self.max_steps]:
                step = self._solve_step(raw, question, context, memory)
                if not step.result.strip():
                    continue                    # prune failed steps — no pollution
                steps.append(step)
                memory.append(f"{step.text} -> {step.result}")
            answer = self._synthesize(question, memory, context)
            if self.self_consistency > 1:       # self-consistency verification
                answer = self._vote(question, memory, context, first=answer)
            # exact steps lift confidence; a barren decomposition sinks it
            exact_frac = (sum(1 for s in steps if s.kind == "math") / len(steps)
                          if steps else 0.0)
            conf = base + (1.0 - base) * exact_frac if memory else base * 0.5
        else:
            answer = self._synthesize(question, [], context)   # direct pass
            conf = base

        if not (answer or "").strip():
            return Deliberation(answer="", steps=[], confidence=0.15)
        return Deliberation(answer=answer, confidence=round(min(conf, 1.0), 3))

    def _should_decompose(self, question: str) -> bool:
        if not self.decompose:
            return False
        q = (question or "").strip()
        if len(q) < 12:                         # trivial / greeting → direct
            return False
        return bool(q.count("?") > 1 or _COMPLEX.search(q)
                    or len(q.split()) >= 12)

    # ── exact truth: real arithmetic, not a guess ────────────────────────────────
    def _exact_arithmetic(self, question: str) -> Optional[str]:
        """If the question is essentially a calculation, compute it exactly —
        percent-of, powers, and general arithmetic. Guarded: needs calculation
        intent (or a near-bare expression) so 'born in 1990' isn't 'solved'."""
        q = question or ""
        stripped = re.sub(r"[\d\s.+\-*/%()^]", "", q)
        near_bare = len(stripped) <= 4
        intent = bool(_CALC_INTENT.search(q))

        pm = _PERCENT_OF.search(q)              # "15% of 200"
        if pm and (intent or near_bare or "%" in q):
            val = float(pm.group(1)) / 100.0 * float(pm.group(2))
            return f"{pm.group(1)}% of {pm.group(2)} = {_fmt(val)}"

        pw = _POWER.search(q)                   # "2^10", "2 to the power of 10"
        if pw and (intent or near_bare):
            try:
                val = wt.math_solve(f"{pw.group(1)} ** {pw.group(2)}")["value"]
            except Exception:  # noqa: BLE001
                return None
            return f"{pw.group(1)}^{pw.group(2)} = {_fmt(val)}"

        m = _EXPR.search(q)                      # general "48 * 12 + 5"
        if not m:
            return None
        expr = m.group(0).strip()
        if not re.search(r"[-+*/%]", expr) or not (intent or near_bare):
            return None
        try:
            value = wt.math_solve(expr)["value"]
        except Exception:  # noqa: BLE001 — not really arithmetic; fall through
            return None
        return f"{expr} = {_fmt(value)}"

    # ── decomposition ────────────────────────────────────────────────────────────
    def _plan(self, question: str, context: Optional[dict]) -> list[str]:
        prompt = (
            "Break the following question into 2 to 4 short, ordered reasoning "
            "steps needed to answer it. One step per line, no explanations, no "
            "numbering words — just the step.\n\nQuestion: " + question)
        raw = self.substrate.generate(prompt, context=context, temperature=0.2)
        steps = []
        for line in (raw or "").splitlines():
            line = _STEP_LEAD.sub("", line).strip()
            if len(line) >= 3:
                steps.append(line)
        return steps[:self.max_steps] or [question]

    def _solve_step(self, step: str, question: str, context: Optional[dict],
                    memory: list[str]) -> Step:
        exact = self._exact_arithmetic(step)
        if exact is not None:
            self.math_steps += 1
            return Step(step, "math", exact, 1.0)
        prior = ("\n".join(memory[-3:]) + "\n") if memory else ""
        prompt = (f"Question: {question}\n{prior}Now do this step and give only "
                  f"its result: {step}")
        result = self.substrate.generate(prompt, context=context, temperature=0.3)
        return Step(step, "reason", (result or "").strip(),
                    0.6 if result else 0.3)

    # ── synthesis ────────────────────────────────────────────────────────────────
    def _synthesize(self, question: str, memory: list[str],
                    context: Optional[dict], temperature: float = 0.3) -> str:
        if not memory:
            return self.substrate.generate(question, context=context,
                                           temperature=temperature).strip()
        worked = "\n".join(f"- {m}" for m in memory)
        prompt = (f"Question: {question}\n\nWorked-out steps:\n{worked}\n\n"
                  "Using these steps, give the final answer concisely. Do not "
                  "restate the steps.")
        return self.substrate.generate(prompt, context=context,
                                       temperature=temperature).strip()

    # ── verification: self-consistency ───────────────────────────────────────────
    def _vote(self, question: str, memory: list[str], context: Optional[dict],
              *, first: str) -> str:
        """Reason the synthesis a few times and keep the answer the runs agree
        on. A shaky substrate's one-off blunder loses to the consensus."""
        answers = [first]
        for i in range(self.self_consistency - 1):
            answers.append(self._synthesize(question, memory, context,
                                            temperature=0.3 + 0.2 * (i + 1)))
        answers = [a for a in answers if a.strip()]
        if not answers:
            return first
        counts = Counter(re.sub(r"\s+", " ", a.strip().lower()) for a in answers)
        winner_norm, _ = counts.most_common(1)[0]
        for a in answers:                       # return the original casing
            if re.sub(r"\s+", " ", a.strip().lower()) == winner_norm:
                return a
        return first

    def status(self) -> dict:
        return {"primary": "local", "available": self.available(),
                "engine": self.name, "self_consistency": self.self_consistency,
                "max_steps": self.max_steps,
                "asked": self.asked, "answered": self.answered,
                "failed": self.failed, "exact_answers": self.exact_answers,
                "math_steps": self.math_steps,
                "avg_latency_ms": round(self.total_latency_ms / self.answered, 1)
                if self.answered else 0.0}
