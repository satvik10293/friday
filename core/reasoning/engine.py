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
from core.reasoning import exact
from core.reasoning.substrate import Substrate
from core.society import worker_tasks as wt

log = logging.getLogger("friday.reasoning.engine")

_STEP_LEAD = re.compile(r"^\s*(?:step\s*\d+[:.)]?|\d+[:.)]|[-*•])\s*", re.I)
# a question complex enough to earn decomposition (System 2); anything else
# stays a single direct pass (System 1) so she doesn't over-think "hi"
_COMPLEX = re.compile(
    r"\b(and|then|after|before|steps?|how (?:do|to|can|does)|why|explain|"
    r"compare|difference between|pros and cons|walk me through|list)\b", re.I)
# a coding ask: the answer is code, so it gets the verify-repair loop
_CODE_RE = re.compile(
    r"\b(write|create|implement|fix|debug)\b.{0,40}\b(function|code|script|"
    r"python|program|method|class)\b", re.I)
# a recall-shaped step: consult the knowledge base, not the language faculty
_RECALL_RE = re.compile(
    r"\b(recall|remember|look up|search|find out|check (?:the |my )?"
    r"(?:notes|knowledge)|definition of|what is known about)\b", re.I)


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
                 decompose: bool = True, retriever=None,
                 tokenizer=None, think_in_tokens: bool = False) -> None:
        # NB: token thinking defaults OFF here and ON via build_reasoner
        # (config `reasoning.tokens`) — direct constructions (tests, embeds)
        # must never pay tokenizer training implicitly.
        self.substrate = substrate
        self.name = name
        self.self_consistency = max(1, int(self_consistency))
        self.max_steps = max(1, int(max_steps))
        self.decompose = decompose
        # retrieval as a reasoning tool: a callable(query) -> str that consults
        # her own knowledge base, so recall-shaped steps read notes instead of
        # asking the language faculty to "remember"
        self.retriever = retriever
        # (M57) she thinks in TOKENS: her own learned vocabulary carries every
        # internal stage — question, plan, steps, working memory, answer — and
        # natural language exists only at the boundary. The trace of a turn is
        # a readable program of her mind (<q> … <plan> <step> … <answer> …).
        self.tokenizer = tokenizer
        self.think_in_tokens = think_in_tokens
        self.last_thought: list[int] = []
        self.tokens_thought = 0
        self.asked = 0
        self.answered = 0
        self.failed = 0
        self.exact_answers = 0
        self.math_steps = 0
        self.recall_steps = 0
        self.code_checked = 0
        self.code_repaired = 0
        self.total_latency_ms = 0.0

    def available(self) -> bool:
        try:
            return self.substrate.available()
        except Exception:  # noqa: BLE001
            return False

    # ── (M57) her token mind ─────────────────────────────────────────────────────
    def _tok(self):
        if not self.think_in_tokens:
            return None
        if self.tokenizer is None:
            try:
                from core.reasoning.tokens import get_tokenizer
                self.tokenizer = get_tokenizer()
            except Exception:  # noqa: BLE001 — thinking still works untokenized
                log.debug("tokenizer unavailable", exc_info=True)
                self.think_in_tokens = False
                return None
        return self.tokenizer

    def _think(self, text: str, op: str) -> str:
        """Pass one internal payload through her token space: encode with the
        cognitive op, record it on the trace, and hand the DECODED form to the
        next stage — so every stage consumes what survived her vocabulary
        (lossless for printable text by construction, lowercased: thought has
        no capital letters)."""
        tok = self._tok()
        if tok is None or not (text or "").strip():
            return text
        ids = tok.encode(text, marker=op)
        self.last_thought.extend(ids)
        self.tokens_thought += len(ids)
        return tok.decode(ids)

    def thought_trace(self) -> dict:
        """The last turn's thinking, as tokens — inspectable, not a vibe."""
        tok = self._tok()
        if tok is None or not self.last_thought:
            return {"tokens": 0, "trace": "", "text": ""}
        return {"tokens": len(self.last_thought),
                "trace": " ".join(tok.explain(self.last_thought))[:2000],
                "text": tok.decode(self.last_thought)[:800]}

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
        try:                # a per-answer trust signal some substrates provide
            self.substrate.last_confidence = None
        except Exception:  # noqa: BLE001 — optional protocol extension
            pass

        # (M57) natural language ends here: the question enters her token
        # space, and every internal stage below consumes token-surviving text
        self.last_thought = []
        thought_q = self._think(question, "<q>") or question

        # 1. exact first: anything checkable (arithmetic incl. spoken operators,
        #    percent, powers, unit conversions, dates, comparisons) is COMPUTED,
        #    never guessed — full trust
        solved = exact.solve(thought_q)
        if solved is not None:
            self._think(solved, "<exact>")
            return Deliberation(answer=solved,
                                steps=[Step(question, "math", solved, 1.0)],
                                confidence=1.0, exact=True)

        # 1a. code REASONING: a question ABOUT a given snippet ("what does this
        #     print", "is this valid", "complexity", "explain", "bugs") is
        #     answered by RUNNING or AST-analysing it — proven, not guessed
        coded = self._code_reasoning(question)
        if coded is not None:
            self._think(coded, "<code>")
            return Deliberation(answer=coded,
                                steps=[Step(question, "code", coded, 1.0)],
                                confidence=0.97, exact=True)

        # 1b. a coding ask gets the verify-repair loop: generate → AST-check →
        #     repair once → confidence reflects whether the code actually parses
        if _CODE_RE.search(question or ""):
            deliberated = self._code(question, context, base)
            if (deliberated.answer or "").strip():
                self._think(deliberated.answer, "<code>")
            return deliberated

        # 2. adaptive depth: only complex questions earn System-2 decomposition;
        #    simple ones stay a single direct pass so she doesn't over-think
        if self._should_decompose(thought_q):
            plan = self._plan(thought_q, context)
            steps: list[Step] = []
            memory: list[str] = []
            for raw in plan[:self.max_steps]:
                raw = self._think(raw, "<step>") or raw      # step → token space
                step = self._solve_step(raw, thought_q, context, memory)
                if not step.result.strip():
                    continue                    # prune failed steps — no pollution
                op = {"math": "<exact>", "recall": "<recall>"}.get(step.kind,
                                                                   "<native>")
                result = self._think(step.result, op) or step.result
                step = Step(step.text, step.kind, result, step.confidence)
                steps.append(step)
                memory.append(f"{step.text} -> {step.result}")
            answer = self._synthesize(thought_q, memory, context)
            if self.self_consistency > 1:       # self-consistency verification
                answer = self._vote(thought_q, memory, context, first=answer)
            # honest trust: a per-answer signal (NativeMind coverage) beats the
            # static base; exact steps lift it, a barren decomposition sinks it
            dyn = getattr(self.substrate, "last_confidence", None)
            core = float(dyn) if dyn is not None else base
            exact_frac = (sum(1 for s in steps if s.kind == "math") / len(steps)
                          if steps else 0.0)
            conf = core + (1.0 - core) * exact_frac if memory else core * 0.5
        else:
            answer = self._synthesize(thought_q, [], context)  # direct pass
            dyn = getattr(self.substrate, "last_confidence", None)
            conf = float(dyn) if dyn is not None else base

        if not (answer or "").strip():
            self._think(question, "<defer>")     # the trace shows she declined
            return Deliberation(answer="", steps=[], confidence=0.15)
        # the answer leaves token space here — the BOUNDARY back to natural
        # language (the trace records its tokens; the user hears the words)
        self._think(answer, "<answer>")
        return Deliberation(answer=answer, confidence=round(min(conf, 1.0), 3))

    def _should_decompose(self, question: str) -> bool:
        if not self.decompose:
            return False
        q = (question or "").strip()
        if len(q) < 12:                         # trivial / greeting → direct
            return False
        return bool(q.count("?") > 1 or _COMPLEX.search(q)
                    or len(q.split()) >= 12)

    # ── code reasoning: run / analyse a GIVEN snippet, deterministically ─────────
    @staticmethod
    def _code_reasoning(question: str) -> Optional[str]:
        """Answer a question ABOUT a code snippet by executing or AST-analysing
        it (core/reasoning/code.py). None when there's no analysable code."""
        try:
            from core.reasoning import code as codemod
            return codemod.answer(question)
        except Exception:  # noqa: BLE001 — the code faculty never breaks a turn
            log.debug("code reasoning failed", exc_info=True)
            return None

    # ── coding: generate → verify (AST) → repair once ────────────────────────────
    def _code(self, question: str, context: Optional[dict], base: float
              ) -> Deliberation:
        """The answer is code, so it can be CHECKED: parse it with the real
        Python AST. Invalid code gets one repair pass with the actual issues;
        code that still doesn't parse is reported at low confidence so the
        caller escalates instead of shipping something broken."""
        prompt = (question + "\n\nGive only the code, as plain indented text, "
                  "no explanations, no markdown fences.")
        code = self.substrate.generate(prompt, context=context, temperature=0.2)
        if not (code or "").strip():
            return Deliberation(answer="", steps=[], confidence=0.15)
        self.code_checked += 1
        issues = self._lint(code)
        steps = [Step(question, "code", "draft generated", base)]
        if issues:
            fix_prompt = (question + "\n\nYour previous code:\n" + code
                          + "\n\nIt has these problems: " + "; ".join(issues[:4])
                          + "\nGive only the corrected code, plain text.")
            fixed = self.substrate.generate(fix_prompt, context=context,
                                            temperature=0.2)
            if (fixed or "").strip():
                new_issues = self._lint(fixed)
                if len(new_issues) < len(issues):
                    code, issues = fixed, new_issues
                    self.code_repaired += 1
                    steps.append(Step("repair", "code", "repaired", base))
        valid = not any("syntax" in i.lower() or "parse" in i.lower()
                        for i in issues)
        conf = min(0.85, base + 0.15) if valid and not issues else \
            (base * 0.9 if valid else 0.3)
        steps.append(Step("verify", "code",
                          "parses clean" if not issues else "; ".join(issues[:3]),
                          1.0 if not issues else 0.3))
        return Deliberation(answer=code.strip(), steps=steps,
                            confidence=round(conf, 3))

    @staticmethod
    def _lint(code: str) -> list[str]:
        """Real verification: the Python AST either parses the code or it
        doesn't. Non-Python answers simply report a parse issue → low trust."""
        try:
            result = wt.debug_python(code)
            return list(result.get("issues") or [])
        except SyntaxError as e:
            return [f"syntax error: {e.msg} (line {e.lineno})"]
        except Exception as e:  # noqa: BLE001
            return [f"could not parse: {e}"]

    # ── decomposition ────────────────────────────────────────────────────────────
    def _plan(self, question: str, context: Optional[dict]) -> list[str]:
        # a structured faculty (NativeMind) decomposes natively — no prompt
        if hasattr(self.substrate, "plan"):
            try:
                steps = [s for s in (self.substrate.plan(question) or []) if s]
                return steps[:self.max_steps] or [question]
            except Exception:  # noqa: BLE001 — fall back to the prompt path
                log.debug("native plan failed", exc_info=True)
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
        # exact tools first: a checkable step is computed, never generated
        solved = exact.solve(step)
        if solved is not None:
            self.math_steps += 1
            return Step(step, "math", solved, 1.0)
        # recall-shaped steps read her own notes, not the language faculty
        if self.retriever is not None and _RECALL_RE.search(step):
            try:
                found = (self.retriever(step) or "").strip()
            except Exception:  # noqa: BLE001 — retrieval faults fall to reasoning
                log.debug("retriever failed on step", exc_info=True)
                found = ""
            if found:
                self.recall_steps += 1
                return Step(step, "recall", found[:400], 0.75)
        # a structured faculty solves the step by reading her own material
        if hasattr(self.substrate, "solve_step"):
            try:
                result = (self.substrate.solve_step(step, question, memory)
                          or "").strip()
                return Step(step, "reason", result, 0.6 if result else 0.3)
            except Exception:  # noqa: BLE001 — fall back to the prompt path
                log.debug("native solve_step failed", exc_info=True)
        prior = ("\n".join(memory[-3:]) + "\n") if memory else ""
        prompt = (f"Question: {question}\n{prior}Now do this step and give only "
                  f"its result: {step}")
        result = self.substrate.generate(prompt, context=context, temperature=0.3)
        return Step(step, "reason", (result or "").strip(),
                    0.6 if result else 0.3)

    # ── synthesis ────────────────────────────────────────────────────────────────
    def _synthesize(self, question: str, memory: list[str],
                    context: Optional[dict], temperature: float = 0.3) -> str:
        # a structured faculty composes from the worked steps directly
        if hasattr(self.substrate, "synthesize"):
            try:
                return (self.substrate.synthesize(question, memory) or "").strip()
            except Exception:  # noqa: BLE001 — fall back to the prompt path
                log.debug("native synthesize failed", exc_info=True)
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
                "recall_steps": self.recall_steps,
                "code_checked": self.code_checked,
                "code_repaired": self.code_repaired,
                "has_retriever": self.retriever is not None,
                "thinks_in_tokens": bool(self.think_in_tokens),
                "tokens_thought": self.tokens_thought,
                "vocab": self.tokenizer.size if self.tokenizer else 0,
                "avg_latency_ms": round(self.total_latency_ms / self.answered, 1)
                if self.answered else 0.0}
