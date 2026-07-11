"""
core/intelligence/mini_brains.py — FRIDAY 3.0-era M33
The Mini-Brain Cortex: a fast path of deterministic specialist brains that sit
in front of the model team. Each mini brain claims a task shape it can answer
exactly (math, clock, units, system status, memory recall) and answers in
milliseconds — this is how common tasks meet the <500 ms budget on a CPU-only
box, where a single language-model pass cannot honestly promise it.

Rules:
  · A mini brain answers only what it can answer EXACTLY — no guessing.
    A wrong fast answer is worse than a slow correct one, so every brain
    returns None the moment a prompt falls outside its competence.
  · Every answer is timed against the brain's latency budget (default 500 ms);
    violations are counted in stats, never hidden.
  · The cortex never blocks the pipeline: any exception in a mini brain means
    "no claim" and the prompt falls through to the model team.
"""

from __future__ import annotations

import ast
import logging
import operator
import re
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

log = logging.getLogger("friday.intelligence.mini")

_DEFAULT_BUDGET_MS = 500.0
_CLAIM_THRESHOLD = 0.6


@dataclass
class MiniAnswer:
    answer: str
    confidence: float
    brain: str
    elapsed_ms: float


class MiniBrain:
    """Base specialist. Subclasses implement claim() and answer()."""

    name = "mini"
    budget_ms = _DEFAULT_BUDGET_MS

    def claim(self, prompt: str) -> float:
        """0.0–1.0: how sure this brain is that the prompt is its task shape."""
        raise NotImplementedError

    def answer(self, prompt: str) -> Optional[str]:
        """Exact answer, or None if the prompt turns out to be out of scope."""
        raise NotImplementedError


# ── Math ───────────────────────────────────────────────────────────────────────

_MATH_OPS = {
    ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
    ast.Div: operator.truediv, ast.Mod: operator.mod, ast.Pow: operator.pow,
    ast.USub: operator.neg, ast.UAdd: operator.pos,
}


def _safe_eval(expr: str) -> float:
    """Arithmetic-only AST evaluation — no names, no calls, no attributes."""

    def _eval(node):
        if isinstance(node, ast.Expression):
            return _eval(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return node.value
        if isinstance(node, ast.BinOp) and type(node.op) in _MATH_OPS:
            left, right = _eval(node.left), _eval(node.right)
            if isinstance(node.op, ast.Pow) and (abs(right) > 12 or abs(left) > 1e6):
                raise ValueError("exponent out of bounds")
            return _MATH_OPS[type(node.op)](left, right)
        if isinstance(node, ast.UnaryOp) and type(node.op) in _MATH_OPS:
            return _MATH_OPS[type(node.op)](_eval(node.operand))
        raise ValueError(f"unsupported expression node: {type(node).__name__}")

    return _eval(ast.parse(expr, mode="eval"))


def _format_number(value: float) -> str:
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(round(value, 6))


class MathBrain(MiniBrain):
    name = "math"

    _PCT = re.compile(r"([\d.]+)\s*(?:%|percent)\s+of\s+([\d.]+)", re.IGNORECASE)
    _EXPR = re.compile(r"[-+]?[\d.][\d\s.+\-*/%^()]*")
    _STRIP = re.compile(
        r"^(?:what\s+is|what'?s|calculate|compute|how\s+much\s+is|solve|evaluate)\s+",
        re.IGNORECASE)
    # voice reality: STT transcribes "12 times 7", not "12*7" — spoken operators
    # are rewritten to symbols, but ONLY between digits so "how many times did
    # I ask" or "hand it over" never turn into arithmetic
    _WORD_OPS = [
        (re.compile(r"(?<=\d)\s+to\s+the\s+power\s+of\s+(?=[-\d.(])", re.IGNORECASE), "**"),
        (re.compile(r"(?<=\d)\s+(?:multiplied\s+by|times|x)\s+(?=[-\d.(])", re.IGNORECASE), "*"),
        (re.compile(r"(?<=\d)\s+(?:divided\s+by|over)\s+(?=[-\d.(])", re.IGNORECASE), "/"),
        (re.compile(r"(?<=\d)\s+plus\s+(?=[-\d.(])", re.IGNORECASE), "+"),
        (re.compile(r"(?<=\d)\s+minus\s+(?=[-\d.(])", re.IGNORECASE), "-"),
        (re.compile(r"(?<=\d)\s+mod(?:ulo)?\s+(?=[-\d.(])", re.IGNORECASE), "%"),
    ]

    def _extract(self, prompt: str) -> Optional[str]:
        raw = prompt.strip().rstrip("?!. ")
        has_cue = bool(self._STRIP.match(raw))   # explicit "what is/calculate/…"
        text = self._STRIP.sub("", raw)
        pct = self._PCT.search(text)
        if pct:
            return f"({pct.group(1)} / 100) * {pct.group(2)}"
        normalized = text.replace("^", "**").replace("×", "*").replace("÷", "/")
        for pat, op in self._WORD_OPS:
            normalized = pat.sub(op, normalized)
        m = self._EXPR.search(normalized)
        if not m:
            return None
        expr = m.group(0).strip()
        # require an actual operation, not a lone number
        if not re.search(r"\d\s*[+\-*/%]|\*\*", expr):
            return None
        # Computation INTENT is required: either an explicit cue, or the prompt
        # is essentially just the expression. Digits with a dash inside a
        # sentence ("call 555-2368 now") must never get a confident answer.
        if not has_cue and normalized.replace(expr, "", 1).strip():
            return None
        return expr

    def claim(self, prompt: str) -> float:
        return 0.95 if self._extract(prompt) else 0.0

    def answer(self, prompt: str) -> Optional[str]:
        expr = self._extract(prompt)
        if not expr:
            return None
        try:
            return _format_number(_safe_eval(expr))
        except Exception:  # noqa: BLE001 — out of scope → fall through
            return None


# ── Clock ──────────────────────────────────────────────────────────────────────

class ClockBrain(MiniBrain):
    name = "clock"

    _TIME = re.compile(r"\b(what time is it|current time|the time( now)?)\b", re.IGNORECASE)
    _DATE = re.compile(
        r"\b(what('?s| is) (today'?s )?(the )?date|today'?s date|"
        r"what date is it( today)?)\b", re.IGNORECASE)
    _DAY = re.compile(r"\bwhat day (is it|is today)\b", re.IGNORECASE)

    def claim(self, prompt: str) -> float:
        return 0.95 if (self._TIME.search(prompt) or self._DATE.search(prompt)
                        or self._DAY.search(prompt)) else 0.0

    def answer(self, prompt: str) -> Optional[str]:
        now = datetime.now()
        if self._TIME.search(prompt):
            return f"It's {now.strftime('%I:%M %p').lstrip('0')}."
        if self._DAY.search(prompt):
            return f"It's {now.strftime('%A')}."
        if self._DATE.search(prompt):
            return f"Today is {now.strftime('%A, %B %d, %Y')}."
        return None


# ── Units ──────────────────────────────────────────────────────────────────────

_UNIT_ALIASES = {
    "km": "km", "kilometer": "km", "kilometers": "km", "kilometre": "km", "kilometres": "km",
    "mi": "mi", "mile": "mi", "miles": "mi",
    "kg": "kg", "kilogram": "kg", "kilograms": "kg",
    "lb": "lb", "lbs": "lb", "pound": "lb", "pounds": "lb",
    "m": "m", "meter": "m", "meters": "m", "metre": "m", "metres": "m",
    "ft": "ft", "foot": "ft", "feet": "ft",
    "cm": "cm", "centimeter": "cm", "centimeters": "cm",
    "in": "in", "inch": "in", "inches": "in",
    "c": "c", "celsius": "c", "f": "f", "fahrenheit": "f",
}

_LINEAR = {  # (from, to) → factor
    ("km", "mi"): 0.621371, ("mi", "km"): 1.609344,
    ("kg", "lb"): 2.204623, ("lb", "kg"): 0.453592,
    ("m", "ft"): 3.28084, ("ft", "m"): 0.3048,
    ("cm", "in"): 0.393701, ("in", "cm"): 2.54,
}


class UnitBrain(MiniBrain):
    name = "units"

    _UNITS = "|".join(sorted(_UNIT_ALIASES, key=len, reverse=True))
    _PAT = re.compile(
        rf"([\d.]+)\s*({_UNITS})\b\s*(?:to|in|into|as)\s*({_UNITS})\b",
        re.IGNORECASE)
    # spoken phrasing puts the target first: "how many miles is 5 km"
    _PAT_REV = re.compile(
        rf"how\s+many\s+({_UNITS})\b\s*(?:is|are|in|make|per)\s*([\d.]+)\s*({_UNITS})\b",
        re.IGNORECASE)

    def _parse(self, prompt: str):
        m = self._PAT.search(prompt)
        if m:
            value, src, dst = float(m.group(1)), m.group(2), m.group(3)
        else:
            m = self._PAT_REV.search(prompt)
            if not m:
                return None
            dst, value, src = m.group(1), float(m.group(2)), m.group(3)
        src = _UNIT_ALIASES[src.lower()]
        dst = _UNIT_ALIASES[dst.lower()]
        if src == dst:
            return None
        return value, src, dst

    def claim(self, prompt: str) -> float:
        return 0.9 if self._parse(prompt) else 0.0

    def answer(self, prompt: str) -> Optional[str]:
        parsed = self._parse(prompt)
        if not parsed:
            return None
        value, src, dst = parsed
        if (src, dst) in _LINEAR:
            result = value * _LINEAR[(src, dst)]
        elif (src, dst) == ("c", "f"):
            result = value * 9 / 5 + 32
        elif (src, dst) == ("f", "c"):
            result = (value - 32) * 5 / 9
        else:
            return None
        return f"{_format_number(value)} {src} is {_format_number(round(result, 4))} {dst}."


# ── System status ──────────────────────────────────────────────────────────────

class SystemBrain(MiniBrain):
    name = "system"

    _PAT = re.compile(
        r"\b(cpu|processor|memory|ram|battery|disk space|system status)\b",
        re.IGNORECASE)
    _QUESTION = re.compile(r"\b(usage|status|level|how (much|full|is))\b", re.IGNORECASE)

    def claim(self, prompt: str) -> float:
        return 0.8 if (self._PAT.search(prompt) and self._QUESTION.search(prompt)) else 0.0

    def answer(self, prompt: str) -> Optional[str]:
        try:
            import psutil
        except ImportError:
            return None
        q = prompt.lower()
        parts = []
        if "cpu" in q or "processor" in q or "system status" in q:
            parts.append(f"CPU at {psutil.cpu_percent(interval=0.1):.0f}%")
        if "memory" in q or "ram" in q or "system status" in q:
            vm = psutil.virtual_memory()
            parts.append(f"RAM at {vm.percent:.0f}% "
                         f"({vm.used / 1e9:.1f} of {vm.total / 1e9:.1f} GB)")
        if "battery" in q or "system status" in q:
            bat = psutil.sensors_battery()
            if bat is not None:
                state = "charging" if bat.power_plugged else "on battery"
                parts.append(f"battery at {bat.percent:.0f}% ({state})")
        if "disk" in q:
            du = psutil.disk_usage("/")
            parts.append(f"disk at {du.percent:.0f}% used")
        return (". ".join(parts).capitalize() + ".") if parts else None


# ── Memory recall ──────────────────────────────────────────────────────────────

class RecallBrain(MiniBrain):
    name = "recall"

    _PAT = re.compile(
        r"\b(?:do you remember|what do you know about|have i told you about)\s+(.{3,80})",
        re.IGNORECASE)
    _MIN_SCORE = 0.35          # cosine floor — top-k always returns SOMETHING;
                               # only actually-relevant memories may be spoken

    def __init__(self, memory=None) -> None:
        # One Memory service (core/memory) — where the learning gate stores
        # everything FRIDAY is taught. The 3.0 chronicle is the fallback for
        # boxes that still carry old memories there.
        self._memory = memory

    def claim(self, prompt: str) -> float:
        return 0.85 if self._PAT.search(prompt) else 0.0

    def _recall_one_memory(self, topic: str) -> list[str]:
        if self._memory is None:
            return []
        rows = self._memory.recall(topic, k=3)
        topic_words = {w for w in re.findall(r"[a-z0-9']+", topic.lower())
                       if len(w) >= 3}
        keep = []
        for r in rows:
            score = r.get("score")
            content = (r.get("content") or "").strip()
            if not content:
                continue
            relevant = (score >= self._MIN_SCORE) if score is not None else \
                bool(topic_words & set(re.findall(r"[a-z0-9']+", content.lower())))
            if relevant:
                keep.append(content)
        return keep

    def answer(self, prompt: str) -> Optional[str]:
        m = self._PAT.search(prompt)
        if not m:
            return None
        topic = m.group(1).strip().rstrip("?!. ")
        try:
            contents = self._recall_one_memory(topic)
        except Exception:  # noqa: BLE001
            contents = []
        if not contents:
            try:
                from core.knowledge.friday_chronicle import search_keyword
                contents = [r["content"] for r in search_keyword(topic, limit=3)]
            except Exception:  # noqa: BLE001
                return None
        if not contents:
            return None
        snippets = "; ".join(c[:120].replace("\n", " ") for c in contents[:3])
        return f"Here's what I remember about {topic}: {snippets}"


# ── The cortex ─────────────────────────────────────────────────────────────────

class MiniBrainCortex:
    """Routes a prompt to the best-claiming specialist, times it against the
    budget, and keeps honest per-brain stats. Misses fall through silently."""

    def __init__(self, brains: Optional[list[MiniBrain]] = None, *,
                 memory=None) -> None:
        self.brains: list[MiniBrain] = brains if brains is not None else [
            MathBrain(), ClockBrain(), UnitBrain(), SystemBrain(),
            RecallBrain(memory=memory),
        ]
        self._stats: dict[str, dict] = {
            b.name: {"calls": 0, "hits": 0, "misses": 0,
                     "budget_violations": 0, "avg_ms": 0.0}
            for b in self.brains
        }

    def try_answer(self, prompt: str) -> Optional[MiniAnswer]:
        prompt = (prompt or "").strip()
        if not prompt:
            return None

        best: Optional[MiniBrain] = None
        best_score = 0.0
        for brain in self.brains:
            try:
                score = brain.claim(prompt)
            except Exception:  # noqa: BLE001 — a broken claim is a no-claim
                score = 0.0
            if score > best_score:
                best, best_score = brain, score
        if best is None or best_score < _CLAIM_THRESHOLD:
            return None

        st = self._stats[best.name]
        st["calls"] += 1
        t0 = time.perf_counter()
        try:
            text = best.answer(prompt)
        except Exception:  # noqa: BLE001 — never let a specialist break a turn
            log.debug("mini brain %s crashed", best.name, exc_info=True)
            text = None
        elapsed = (time.perf_counter() - t0) * 1000.0

        if not text:
            st["misses"] += 1
            return None
        st["hits"] += 1
        st["avg_ms"] += (elapsed - st["avg_ms"]) / st["hits"]
        if elapsed > best.budget_ms:
            st["budget_violations"] += 1
            log.warning("mini brain %s blew its budget: %.0fms > %.0fms",
                        best.name, elapsed, best.budget_ms)
        return MiniAnswer(answer=text,
                          confidence=min(0.95, 0.6 + best_score * 0.35),
                          brain=best.name, elapsed_ms=elapsed)

    def stats(self) -> dict:
        return {name: dict(s) for name, s in self._stats.items()}
