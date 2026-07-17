"""
core/reasoning/exact.py — FRIDAY 5.x (M54 perfection pass)
Exact truth tools for the deliberate mind.

The one place FRIDAY genuinely competes with a frontier model on her CPU box
is the class of questions where truth is CHECKABLE: a frontier model
approximates arithmetic, dates, and conversions from patterns — she computes
them. Every solver here returns either an exact, verifiable answer string or
None (not our kind of question); nothing guesses, nothing calls a model.

Voice-first: STT transcribes spoken math as words ("48 times 12 plus 5"), so
questions are normalized (operator words → symbols) before matching. All
solvers share the intent guard so "born in 1990" is never 'solved'.

Solvers, tried in order by solve():
    comparison   "which is bigger, 2^10 or 999?"        → both computed
    percent      "what is 15% of 240"                    → computed
    power        "2 to the power of 10", "5 squared"     → computed
    units        "convert 10 km to miles", "how many pounds is 5 kg"
    dates        "days between 2020-03-05 and 2020-06-01", "what day of the
                 week is 2026-07-17", "how many days until December 25"
    arithmetic   "what is 48 times 12 plus 5"            → computed
"""

from __future__ import annotations

import datetime as _dt
import re
from typing import Callable, Optional

from core.society import worker_tasks as wt

# ── shared helpers ────────────────────────────────────────────────────────────

def _fmt(value) -> str:
    """Render a computed number cleanly (2.0 → 2; long floats rounded)."""
    if isinstance(value, float):
        if value.is_integer():
            return str(int(value))
        return str(round(value, 4))
    return str(value)


def _safe_eval(expr: str) -> Optional[float]:
    """Exact arithmetic through the sandboxed AST evaluator; None if the
    expression isn't pure arithmetic."""
    try:
        return wt.math_solve(expr)["value"]
    except Exception:  # noqa: BLE001 — not arithmetic; the caller falls through
        return None


# spoken operators → symbols, so voice-transcribed math is computable.
# Order matters: multi-word phrases first. "minus" only between number-ish
# contexts is not enforced — the arithmetic guard (intent + computable
# expression) keeps prose like "minus the shipping" from being 'solved'.
_WORD_OPS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\bto the power of\b|\braised to(?: the power of)?\b", re.I), "**"),
    (re.compile(r"\bmultiplied by\b|\btimes\b", re.I), "*"),
    (re.compile(r"\bdivided by\b", re.I), "/"),
    (re.compile(r"\bplus\b", re.I), "+"),
    (re.compile(r"\bminus\b", re.I), "-"),
    (re.compile(r"(\d)\s*squared\b", re.I), r"\1**2"),
    (re.compile(r"(\d)\s*cubed\b", re.I), r"\1**3"),
    (re.compile(r"\bpercent\b", re.I), "%"),
]


def normalize(question: str) -> str:
    """Spoken math → symbolic math ('48 times 12 plus 5' → '48 * 12 + 5')."""
    q = question or ""
    for pattern, repl in _WORD_OPS:
        q = pattern.sub(repl, q)
    return q


_CALC_INTENT = re.compile(
    r"\b(calculate|compute|what(?:'s| is)|how much is|how many|solve|sum of|"
    r"product of|convert|difference)\b", re.I)


def _has_intent(q: str) -> bool:
    stripped = re.sub(r"[\d\s.+\-*/%()^,?]", "", q)
    return bool(_CALC_INTENT.search(q)) or len(stripped) <= 4


# ── arithmetic (incl. percent + power) ────────────────────────────────────────

_EXPR = re.compile(r"\d[\d\s.,]*(?:\s*(?:\*\*|[-+*/%])\s*\(?\d[\d\s.,]*\)?)+")
_PERCENT_OF = re.compile(r"(\d+(?:\.\d+)?)\s*%\s*of\s+(\d+(?:\.\d+)?)", re.I)
_POWER = re.compile(r"(\d+(?:\.\d+)?)\s*(?:\^|\*\*)\s*(\d+(?:\.\d+)?)")


def _clean_expr(expr: str) -> str:
    return expr.replace(",", "").strip()


def percent(question: str) -> Optional[str]:
    q = normalize(question)
    m = _PERCENT_OF.search(q)
    if not m or not (_has_intent(q) or "%" in q):
        return None
    val = float(m.group(1)) / 100.0 * float(m.group(2))
    return f"{m.group(1)}% of {m.group(2)} = {_fmt(val)}"


def power(question: str) -> Optional[str]:
    q = normalize(question)
    m = _POWER.search(q)
    if not m or not _has_intent(q):
        return None
    val = _safe_eval(f"{m.group(1)} ** {m.group(2)}")
    if val is None:
        return None
    return f"{m.group(1)}^{m.group(2)} = {_fmt(val)}"


def arithmetic(question: str) -> Optional[str]:
    q = normalize(question)
    m = _EXPR.search(q)
    if not m:
        return None
    expr = _clean_expr(m.group(0))
    if not re.search(r"[-+*/%]", expr) or not _has_intent(q):
        return None
    val = _safe_eval(expr)
    if val is None:
        return None
    return f"{expr} = {_fmt(val)}"


# ── comparison: compute both sides, then compare ──────────────────────────────

_COMPARE = re.compile(
    r"\b(?:which|what)\s+is\s+(bigger|larger|greater|smaller|less)\b[,:]?\s*"
    r"(.+?)\s+or\s+(.+?)\s*\??$", re.I)


def comparison(question: str) -> Optional[str]:
    m = _COMPARE.search(normalize(question))
    if not m:
        return None
    direction, left_s, right_s = m.group(1).lower(), m.group(2), m.group(3)
    left = _safe_eval(_clean_expr(left_s))
    right = _safe_eval(_clean_expr(right_s))
    if left is None or right is None:
        return None                      # not numerically computable → reason
    smaller_wanted = direction in ("smaller", "less")
    if left == right:
        return f"They're equal: both are {_fmt(left)}."
    win_s, win_v, lose_s, lose_v = (
        (left_s, left, right_s, right)
        if (left < right) == smaller_wanted else (right_s, right, left_s, left))
    word = "smaller" if smaller_wanted else "larger"
    return (f"{win_s.strip()} ({_fmt(win_v)}) is {word} than "
            f"{lose_s.strip()} ({_fmt(lose_v)}).")


# ── unit conversions ──────────────────────────────────────────────────────────

_ALIASES = {
    "kilometers": "km", "kilometer": "km", "kms": "km", "km": "km",
    "miles": "mi", "mile": "mi", "mi": "mi",
    "meters": "m", "meter": "m", "metres": "m", "metre": "m",
    "feet": "ft", "foot": "ft", "ft": "ft",
    "inches": "in", "inch": "in",
    "centimeters": "cm", "centimeter": "cm", "centimetres": "cm", "cm": "cm",
    "kilograms": "kg", "kilogram": "kg", "kilos": "kg", "kilo": "kg", "kg": "kg",
    "pounds": "lb", "pound": "lb", "lbs": "lb", "lb": "lb",
    "grams": "g", "gram": "g",
    "ounces": "oz", "ounce": "oz", "oz": "oz",
    "liters": "l", "liter": "l", "litres": "l", "litre": "l",
    "gallons": "gal", "gallon": "gal", "gal": "gal",
    "celsius": "c", "centigrade": "c",
    "fahrenheit": "f",
}
_FACTORS: dict[tuple, float] = {
    ("km", "mi"): 0.621371, ("mi", "km"): 1.609344,
    ("m", "ft"): 3.28084, ("ft", "m"): 0.3048,
    ("cm", "in"): 0.393701, ("in", "cm"): 2.54,
    ("kg", "lb"): 2.204623, ("lb", "kg"): 0.453592,
    ("g", "oz"): 0.035274, ("oz", "g"): 28.349523,
    ("l", "gal"): 0.264172, ("gal", "l"): 3.785412,
}
_UNIT_WORDS = "|".join(sorted(_ALIASES, key=len, reverse=True))
_CONVERT = re.compile(
    rf"(\d+(?:\.\d+)?)\s*(?:degrees\s+)?({_UNIT_WORDS})\b"
    rf"\s+(?:to|in|into|as)\s+(?:degrees\s+)?({_UNIT_WORDS})\b", re.I)
_HOW_MANY = re.compile(
    rf"how many\s+({_UNIT_WORDS})\b.{{0,12}}?\b(?:is|are|in|make)\b.{{0,8}}?"
    rf"(\d+(?:\.\d+)?)\s*(?:degrees\s+)?({_UNIT_WORDS})\b", re.I)


def _convert_value(value: float, src: str, dst: str) -> Optional[float]:
    if src == dst:
        return value
    if (src, dst) == ("c", "f"):
        return value * 9.0 / 5.0 + 32.0
    if (src, dst) == ("f", "c"):
        return (value - 32.0) * 5.0 / 9.0
    factor = _FACTORS.get((src, dst))
    return value * factor if factor is not None else None


def units(question: str) -> Optional[str]:
    q = question or ""
    m = _CONVERT.search(q)
    if m:
        value, src_w, dst_w = float(m.group(1)), m.group(2), m.group(3)
    else:
        m = _HOW_MANY.search(q)
        if not m:
            return None
        dst_w, value, src_w = m.group(1), float(m.group(2)), m.group(3)
    src, dst = _ALIASES[src_w.lower()], _ALIASES[dst_w.lower()]
    out = _convert_value(value, src, dst)
    if out is None:
        return None                      # incompatible units → not exact for us
    return f"{_fmt(value)} {src} = {_fmt(out)} {dst}"


# ── date arithmetic ───────────────────────────────────────────────────────────

_DATE_FORMATS = ("%Y-%m-%d", "%d %B %Y", "%B %d %Y", "%d %b %Y", "%b %d %Y",
                 "%B %d", "%d %B", "%b %d", "%d %b")
_DATE_TOKEN = (r"(\d{4}-\d{2}-\d{2}|(?:\d{1,2}(?:st|nd|rd|th)?\s+)?[A-Za-z]+"
               r"(?:\s+\d{1,2}(?:st|nd|rd|th)?)?(?:,?\s+\d{4})?)")
_BETWEEN = re.compile(
    rf"how (?:many days|long)\s+(?:is (?:it )?)?between\s+{_DATE_TOKEN}\s+and\s+"
    rf"{_DATE_TOKEN}", re.I)
_WEEKDAY = re.compile(
    rf"(?:what|which) day(?: of the week)?\s+(?:is|was|will)\b.{{0,8}}?"
    rf"{_DATE_TOKEN}", re.I)
_UNTIL = re.compile(
    rf"how many days\s+(until|till|since|to)\s+{_DATE_TOKEN}", re.I)


def _parse_date(text: str, *, today: Optional[_dt.date] = None) -> Optional[_dt.date]:
    text = re.sub(r"(\d{1,2})(st|nd|rd|th)\b", r"\1", (text or "").strip())
    text = text.replace(",", "").strip()
    for fmt in _DATE_FORMATS:
        try:
            parsed = _dt.datetime.strptime(text, fmt)
        except ValueError:
            continue
        if "%Y" not in fmt:              # year-less ("December 25") → this year
            base = today or _dt.date.today()
            try:
                return parsed.date().replace(year=base.year)
            except ValueError:
                return None
        return parsed.date()
    return None


def dates(question: str, *, today: Optional[_dt.date] = None) -> Optional[str]:
    q = question or ""
    m = _BETWEEN.search(q)
    if m:
        a, b = _parse_date(m.group(1), today=today), _parse_date(m.group(2), today=today)
        if a and b:
            return f"There are {abs((b - a).days)} days between {a} and {b}."
    m = _WEEKDAY.search(q)
    if m:
        d = _parse_date(m.group(1), today=today)
        if d:
            return f"{d} is a {d.strftime('%A')}."
    m = _UNTIL.search(q)
    if m:
        d = _parse_date(m.group(2), today=today)
        if d:
            now = today or _dt.date.today()
            delta = (d - now).days
            if m.group(1).lower() == "since":
                return f"It has been {abs(delta)} days since {d}."
            if delta < 0:                # "until" a date already passed this year
                try:
                    d = d.replace(year=d.year + 1)
                    delta = (d - now).days
                except ValueError:
                    return None
            return f"There are {delta} days until {d}."
    return None


# ── the front door ────────────────────────────────────────────────────────────

_SOLVERS: list[Callable[[str], Optional[str]]] = [
    comparison, percent, power, units, dates, arithmetic]


def solve(question: str) -> Optional[str]:
    """Try every exact tool; the first verifiable answer wins. None means
    'not checkable — reason about it instead'. Never raises."""
    for solver in _SOLVERS:
        try:
            answer = solver(question)
        except Exception:  # noqa: BLE001 — an exact tool must never break a turn
            continue
        if answer:
            return answer
    return None
