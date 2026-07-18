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


# spoken numbers → digits ("forty eight" → 48), because STT sometimes writes
# numbers out as words. Conversion is harmless in prose: the solvers still
# require calculation intent + a computable shape before anything is 'solved'.
_ONES = {"zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
         "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
         "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14,
         "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18,
         "nineteen": 19}
_TENS_W = {"twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60,
           "seventy": 70, "eighty": 80, "ninety": 90}
_SCALES = {"hundred": 100, "thousand": 1_000, "million": 1_000_000}
_NUM_WORD = re.compile(
    r"\b(?:(?:" + "|".join(list(_ONES) + list(_TENS_W) + list(_SCALES))
    + r")(?:[\s-]+(?:and[\s-]+)?)?)+\b", re.I)


def _words_to_int(phrase: str) -> Optional[int]:
    total, current, saw = 0, 0, False
    for word in re.split(r"[\s-]+", phrase.lower().strip()):
        if word == "and":
            continue
        if word in _ONES:
            current += _ONES[word]; saw = True
        elif word in _TENS_W:
            current += _TENS_W[word]; saw = True
        elif word == "hundred":
            current = (current or 1) * 100; saw = True
        elif word in _SCALES:
            total += (current or 1) * _SCALES[word]; current = 0; saw = True
        else:
            return None
    return total + current if saw else None


def _numberize(question: str) -> str:
    """'forty eight times twelve' → '48 times 12'."""
    def _sub(m: re.Match) -> str:
        value = _words_to_int(m.group(0))
        return m.group(0) if value is None else f" {value} "
    return _NUM_WORD.sub(_sub, question or "")


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
    """Spoken math → symbolic math: number words become digits, operator words
    become symbols ('forty eight times twelve plus five' → '48 * 12 + 5')."""
    q = _numberize(question or "")
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
    return re.sub(r"\s+", " ", expr.replace(",", "")).strip()


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


# ── inverse algebra: solve for the unknown, exactly ──────────────────────────

_X = r"(?:x|it|a number|what number|which number|some number|the number)"
_EQ = r"(?:is|equals|makes|gives|will be|=)"
# "what number plus 5 makes 12" / "if x * 3 is 21"
_ALG_LEFT = re.compile(
    rf"(?:if\s+)?{_X}\s*([+\-*/])\s*(\d+(?:\.\d+)?)\s+{_EQ}\s+(\d+(?:\.\d+)?)",
    re.I)
# "5 plus what number is 12" / "20 minus what is 8"
_ALG_RIGHT = re.compile(
    rf"(\d+(?:\.\d+)?)\s*([+\-*/])\s*(?:{_X}|what)\s+{_EQ}\s+(\d+(?:\.\d+)?)",
    re.I)


def algebra(question: str) -> Optional[str]:
    q = normalize(question)
    m = _ALG_LEFT.search(q)
    if m:                                   # x OP n = m  →  invert the OP
        op, n, target = m.group(1), float(m.group(2)), float(m.group(3))
        if op == "/" and n == 0:
            return None
        x = {"+": target - n, "-": target + n, "*": (target / n if n else None),
             "/": target * n}[op]
        if x is None:
            return None
        return f"The number is {_fmt(x)}  ({_fmt(x)} {op} {_fmt(n)} = {_fmt(target)})."
    m = _ALG_RIGHT.search(q)
    if m:                                   # n OP x = m
        n, op, target = float(m.group(1)), m.group(2), float(m.group(3))
        x = {"+": target - n, "-": n - target,
             "*": (target / n if n else None),
             "/": (n / target if target else None)}[op]
        if x is None:
            return None
        return f"The number is {_fmt(x)}  ({_fmt(n)} {op} {_fmt(x)} = {_fmt(target)})."
    return None


# ── word problems: track the quantities, compute the answer ──────────────────
# "I have 3 apples and buy 4 more, then eat 2. How many apples do I have?"
# Deterministic state tracking: gain verbs add, loss verbs subtract. Only
# fires on a "how many" ask with at least two quantity events — never on
# ordinary prose that happens to contain numbers.

_GAIN = r"(?:have|has|had|buy|buys|bought|get|gets|got|find|finds|found|" \
        r"receive|receives|received|pick|picks|picked(?:\s+up)?|win|wins|won|" \
        r"make|makes|made|add|adds|added|start(?:s|ed)? with)"
_LOSS = r"(?:lose|loses|lost|give|gives|gave(?:\s+away)?|eat|eats|ate|" \
        r"sell|sells|sold|drop|drops|dropped|spend|spends|spent|use|uses|" \
        r"used|break|breaks|broke)"
_QTY_EVENT = re.compile(
    rf"\b(?P<verb>{_GAIN}|{_LOSS})\b[^.\d]{{0,24}}?(?P<n>\d+(?:\.\d+)?)", re.I)
_HOW_MANY_LEFT = re.compile(
    r"\bhow many\b.{0,40}\b(?:do|does|did|are|is|will|have|has|left|now|"
    r"remain|in total|altogether)\b", re.I)
_LOSS_RE = re.compile(rf"^{_LOSS}$", re.I)


def word_problem(question: str) -> Optional[str]:
    q = normalize(question)
    if not _HOW_MANY_LEFT.search(q):
        return None
    events = list(_QTY_EVENT.finditer(q))
    if len(events) < 2:
        return None                      # one number is not a word problem
    total = 0.0
    trace = []
    for ev in events:
        n = float(ev.group("n"))
        verb = re.sub(r"\s+up$|\s+away$", "", ev.group("verb").lower())
        if _LOSS_RE.match(verb):
            total -= n
            trace.append(f"- {_fmt(n)}")
        else:
            total += n
            trace.append(f"+ {_fmt(n)}")
    shown = " ".join(trace)[2:]                     # drop the leading "+ "
    return f"{_fmt(total)}  ({shown})"


_PCT_CHANGE = re.compile(
    r"\bpercent(?:age)?\s+(increase|decrease|change)\s+from\s+"
    r"(\d+(?:\.\d+)?)\s+to\s+(\d+(?:\.\d+)?)", re.I)


def percent_change(question: str) -> Optional[str]:
    # numberize only — full normalize() rewrites the word "percent" to "%"
    m = _PCT_CHANGE.search(_numberize(question))
    if not m:
        return None
    old, new = float(m.group(2)), float(m.group(3))
    if old == 0:
        return None                      # undefined — refuse, don't guess
    pct = (new - old) / old * 100.0
    word = "increase" if pct >= 0 else "decrease"
    return f"From {_fmt(old)} to {_fmt(new)} is a {_fmt(abs(round(pct, 2)))}% {word}."


# ── aggregates: series sums and averages ─────────────────────────────────────

_SERIES = re.compile(
    r"sum of (?:all )?(?:the )?(?:numbers?|integers?)\s+(?:from|between)\s+"
    r"(\d+)\s+(?:to|and)\s+(\d+)", re.I)
_AVERAGE = re.compile(
    r"\b(?:average|mean)\s+of\s+((?:\d+(?:\.\d+)?(?:\s*,\s*|\s+and\s+|\s+))+"
    r"\d+(?:\.\d+)?)", re.I)


def aggregate(question: str) -> Optional[str]:
    q = normalize(question)
    m = _SERIES.search(q)
    if m:
        a, b = int(m.group(1)), int(m.group(2))
        lo, hi = min(a, b), max(a, b)
        total = (lo + hi) * (hi - lo + 1) // 2      # arithmetic series, exact
        return f"The sum of the numbers from {lo} to {hi} is {total}."
    m = _AVERAGE.search(q)
    if m:
        nums = [float(x) for x in re.findall(r"\d+(?:\.\d+)?", m.group(1))]
        if len(nums) >= 2:
            return (f"The average of {', '.join(_fmt(n) for n in nums)} "
                    f"is {_fmt(sum(nums) / len(nums))}.")
    return None


# ── syllogisms: SHE deduces, no model anywhere ───────────────────────────────
# "All cats are animals. Sam is a cat. Is Sam an animal?" → chained deduction
# over subset/membership/disjointness facts stated IN the question. Answers
# only what the premises entail — anything else returns None (never guesses).

_S_ALL = re.compile(r"\b(?:all|every)\s+([a-z]+?)s?\s+(?:are|is)\s+"
                    r"(?:a\s+|an\s+)?([a-z]+?)s?\b", re.I)
_S_NO = re.compile(r"\bno\s+([a-z]+?)s?\s+(?:are|is)\s+(?:a\s+|an\s+)?"
                   r"([a-z]+?)s?\b", re.I)
_S_ISA = re.compile(r"\b([a-z]+)\s+is\s+(?:a|an)\s+([a-z]+?)s?\b", re.I)
_S_ASK = re.compile(r"\bis\s+([a-z]+)\s+(?:a|an)\s+([a-z]+?)s?\s*\?", re.I)


def _sing(word: str) -> str:
    w = word.lower()
    return w[:-1] if w.endswith("s") and len(w) > 3 else w


def _an(word: str) -> str:
    return f"an {word}" if word[:1] in "aeiou" else f"a {word}"


def syllogism(question: str) -> Optional[str]:
    q = question or ""
    ask = _S_ASK.search(q)
    if not ask:
        return None
    premises = q[:ask.start()]                      # facts stated before the ask
    subset: dict[str, set] = {}                     # class → superclasses
    disjoint: set[tuple] = set()
    member: dict[str, set] = {}                     # entity → classes
    for a, b in _S_ALL.findall(premises):
        subset.setdefault(_sing(a), set()).add(_sing(b))
    for a, b in _S_NO.findall(premises):
        disjoint.add((_sing(a), _sing(b)))
        disjoint.add((_sing(b), _sing(a)))
    for e, c in _S_ISA.findall(premises):
        if e.lower() not in ("all", "every", "no", "it", "that", "this"):
            member.setdefault(e.lower(), set()).add(_sing(c))
    entity, target = ask.group(1).lower(), _sing(ask.group(2))
    if entity not in member:
        return None
    # BFS the subset lattice from every class the entity belongs to
    reached: dict[str, Optional[str]] = {c: None for c in member[entity]}
    frontier = list(member[entity])
    while frontier:
        c = frontier.pop(0)
        for parent in subset.get(c, ()):  # noqa: B909 — reached grows, fine
            if parent not in reached:
                reached[parent] = c
                frontier.append(parent)
    def _chain(to: str) -> str:
        hops = []
        node = to
        while reached.get(node) is not None:
            hops.append(f"every {reached[node]} is {_an(node)}")
            node = reached[node]
        return ((f"{entity.capitalize()} is {_an(node)}"
                 + (", and " + ", and ".join(reversed(hops)) if hops else "")))
    if target in reached:
        return (f"Yes — {_chain(target)}, so {entity.capitalize()} is "
                f"{_an(target)}.")
    for c in reached:                               # a reached class excludes it?
        if (c, target) in disjoint:
            return (f"No — {_chain(c)}, and no {c} is {_an(target)}, so "
                    f"{entity.capitalize()} is not {_an(target)}.")
    return None                                     # premises don't entail it


# ── transitive relations: order chains, deduced not guessed ──────────────────
# "Tom is taller than Sam. Sam is taller than Ann. Who is the tallest?" /
# "Is Tom taller than Ann?" — build the order from the stated comparatives and
# walk the transitive closure. Opposite poles map onto one canonical order.

_R_EDGE = re.compile(r"\b([A-Za-z]+)\s+is\s+([a-z]+er)\s+than\s+([A-Za-z]+)", re.I)
_R_SUPER = re.compile(r"\bwho\s+is\s+the\s+([a-z]+est)\b", re.I)
_R_ASK = re.compile(r"\bis\s+([A-Za-z]+)\s+([a-z]+er)\s+than\s+([A-Za-z]+)\s*\?", re.I)
_R_INVERSE = {"shorter": "taller", "younger": "older", "smaller": "bigger",
              "slower": "faster", "weaker": "stronger", "lighter": "heavier",
              "lower": "higher", "colder": "hotter", "cheaper": "pricier"}


def _canon(cmp_word: str) -> tuple[str, bool]:
    """Map a comparative onto its canonical pole. ('shorter' → 'taller',
    inverted)."""
    w = cmp_word.lower()
    return (_R_INVERSE[w], True) if w in _R_INVERSE else (w, False)


def _superlative_to_comparative(word: str) -> str:
    return word[:-3] + "er" if word.lower().endswith("est") else word


def relations(question: str) -> Optional[str]:
    q = question or ""
    edges_raw = _R_EDGE.findall(q)
    if len(edges_raw) < 1:
        return None
    graphs: dict[str, dict[str, set]] = {}          # rel → {greater: {lesser}}
    for a, cmp_w, b in edges_raw:
        rel, inverted = _canon(cmp_w)
        a, b = a.lower(), b.lower()
        hi, lo = (b, a) if inverted else (a, b)
        graphs.setdefault(rel, {}).setdefault(hi, set()).add(lo)

    def _above(rel: str, x: str) -> set:
        """Everything x outranks, transitively."""
        seen, frontier = set(), [x]
        while frontier:
            for below in graphs.get(rel, {}).get(frontier.pop(0), ()):
                if below not in seen:
                    seen.add(below)
                    frontier.append(below)
        return seen

    m = _R_ASK.search(q)
    if m:                                           # "is A taller than C?"
        a, cmp_w, b = m.group(1).lower(), m.group(2), m.group(3).lower()
        rel, inverted = _canon(cmp_w)
        hi, lo = (b, a) if inverted else (a, b)
        if lo in _above(rel, hi):
            return (f"Yes — {m.group(1).capitalize()} is {cmp_w.lower()} than "
                    f"{m.group(3).capitalize()}, by the chain of comparisons.")
        if hi in _above(rel, lo):
            return (f"No — it's the other way around: "
                    f"{m.group(3).capitalize()} is {cmp_w.lower()} than "
                    f"{m.group(1).capitalize()}.")
        return None                                 # not entailed → don't guess
    m = _R_SUPER.search(q)
    if m and len(edges_raw) >= 2:                   # "who is the tallest?"
        rel, inverted = _canon(_superlative_to_comparative(m.group(1)))
        graph = graphs.get(rel)
        if not graph:
            return None
        names = set(graph) | {n for lows in graph.values() for n in lows}
        want_top = not inverted
        winners = [n for n in names
                   if len(_above(rel, n)) == len(names) - 1] if want_top else \
                  [n for n in names
                   if all(n in _above(rel, o) for o in names if o != n)]
        if len(winners) == 1:
            order = sorted(names, key=lambda n: -len(_above(rel, n)))
            return (f"{winners[0].capitalize()} is the {m.group(1).lower()}: "
                    + " > ".join(n.capitalize() for n in order) + ".")
    return None


# ── exact text operations: the class frontier models famously fumble ─────────
# "How many r's are in strawberry?" — a language model TOKENIZES and guesses;
# she COUNTS. Letter counts, spelling, reversal, nth letter: provably perfect.

_T_COUNT_LETTER = re.compile(
    r"how many (?:times does )?(?:the letter )?['\"]?([a-z])['\"]?s?\s+"
    r"(?:appear |are (?:there )?|is (?:there )?|occur )?in (?:the word )?"
    r"['\"]?([a-z]+)['\"]?", re.I)
_T_COUNT_LETTERS = re.compile(
    r"how many (?:letters|characters) (?:are (?:there )?)?in (?:the word )?"
    r"['\"]?([a-z]+)['\"]?", re.I)
_T_BACKWARDS = re.compile(
    r"(?:spell|say|write)\s+(?:the word )?['\"]?([a-z]+)['\"]?\s+backwards?\b|"
    r"reverse (?:the word )?['\"]?([a-z]+)['\"]?", re.I)
_T_SPELL = re.compile(
    r"(?:how do you )?spell (?:the word )?['\"]?([a-z]+)['\"]?\s*\??$", re.I)
_T_NTH = re.compile(
    r"what(?:'s| is) the (first|second|third|fourth|fifth|last)\s+letter\s+"
    r"(?:of|in) (?:the word )?['\"]?([a-z]+)['\"]?", re.I)
_ORDINAL = {"first": 0, "second": 1, "third": 2, "fourth": 3, "fifth": 4,
            "last": -1}


def text_ops(question: str) -> Optional[str]:
    q = (question or "").strip()
    m = _T_COUNT_LETTER.search(q)
    if m:
        letter, word = m.group(1).lower(), m.group(2).lower()
        if len(word) > 1:                # "in strawberry", not "in a"
            n = word.count(letter)
            positions = [i + 1 for i, ch in enumerate(word) if ch == letter]
            where = (" (positions " + ", ".join(map(str, positions)) + ")"
                     if 0 < n <= 6 else "")
            plural = "s" if n != 1 else ""
            return (f"There {'are' if n != 1 else 'is'} {n} "
                    f"'{letter}'{plural} in \"{word}\"{where}.")
    m = _T_COUNT_LETTERS.search(q)
    if m and len(m.group(1)) > 2:
        word = m.group(1)
        return f"\"{word}\" has {len(word)} letters."
    m = _T_BACKWARDS.search(q)
    if m:
        word = (m.group(1) or m.group(2) or "").lower()
        if len(word) > 2:
            return f"\"{word}\" backwards is \"{word[::-1]}\"."
    m = _T_NTH.search(q)
    if m:
        word = m.group(2).lower()
        idx = _ORDINAL[m.group(1).lower()]
        if len(word) > abs(idx):
            pos = m.group(1).lower()
            return f"The {pos} letter of \"{word}\" is '{word[idx]}'."
    m = _T_SPELL.search(q)
    if m and len(m.group(1)) > 3:
        word = m.group(1).lower()
        return f"{word}: {'-'.join(word.upper())}"
    return None


# ── exact list operations: min / max / sort / median over stated numbers ─────

_L_NUMS = re.compile(r"-?\d+(?:\.\d+)?")
_L_ASK = re.compile(
    r"\b(largest|biggest|greatest|highest|smallest|lowest|least|sort|order|"
    r"median)\b.{0,30}?((?:-?\d+(?:\.\d+)?\s*(?:,|and|\s)\s*){2,}-?\d+(?:\.\d+)?)",
    re.I)


def list_ops(question: str) -> Optional[str]:
    m = _L_ASK.search(_numberize(question or ""))
    if not m:
        return None
    op = m.group(1).lower()
    nums = [float(x) for x in _L_NUMS.findall(m.group(2))]
    if len(nums) < 3:
        return None                      # two-way is the comparison solver's job
    if op in ("largest", "biggest", "greatest", "highest"):
        return f"The largest is {_fmt(max(nums))}."
    if op in ("smallest", "lowest", "least"):
        return f"The smallest is {_fmt(min(nums))}."
    if op == "median":
        s = sorted(nums)
        mid = len(s) // 2
        med = s[mid] if len(s) % 2 else (s[mid - 1] + s[mid]) / 2
        return f"The median is {_fmt(med)}."
    if op in ("sort", "order"):
        desc = re.search(r"\b(descending|decreasing|high(?:est)? to low)", question or "", re.I)
        s = sorted(nums, reverse=bool(desc))
        return "Sorted: " + ", ".join(_fmt(n) for n in s) + "."
    return None


# ── the front door ────────────────────────────────────────────────────────────

_SOLVERS: list[Callable[[str], Optional[str]]] = [
    syllogism, relations, text_ops, comparison, percent_change, percent, power,
    units, dates, word_problem, algebra, list_ops, aggregate, arithmetic]


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
