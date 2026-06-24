"""
friday_learning.py — Friday 3.0
The Learning Engine. Friday gets better with every interaction.

Three mechanisms:
  1. Correction capture  — when Satvik says "that's wrong", Friday learns
  2. Pattern recognition — what kinds of queries get good outcomes?
  3. Preference learning — how does Satvik like responses formatted?

Feeds into Chronicle (persistent) and Psyche (behavioral).
"""

import re
import time
import json
import logging
from typing import Optional
from dataclasses import dataclass, field, asdict
from pathlib import Path

log = logging.getLogger("friday.learning")

# ── Paths ─────────────────────────────────────────────────────────────────────

_BASE_DIR   = Path(__file__).resolve().parents[2]
_DATA_DIR   = _BASE_DIR / "data"
_LOG_PATH   = _DATA_DIR / "learning.jsonl"
_DATA_DIR.mkdir(parents=True, exist_ok=True)


# ── Learning record types ──────────────────────────────────────────────────────

class LearnType:
    CORRECTION   = "correction"    # Satvik corrected Friday
    APPROVAL     = "approval"      # Satvik explicitly approved
    PREFERENCE   = "preference"    # Satvik stated a preference
    PATTERN      = "pattern"       # Friday inferred a usage pattern
    FAILURE      = "failure"       # response was revised by Critic


@dataclass
class LearningRecord:
    id:            str
    type:          str
    timestamp:     float    = field(default_factory=time.time)
    intent:        str      = ""
    original:      str      = ""    # original Friday response
    correction:    str      = ""    # what Satvik said instead
    pattern_key:   str      = ""    # e.g. "code_write.python.length"
    pattern_value: str      = ""    # e.g. "concise"
    weight:        float    = 1.0   # reinforcement strength
    applied:       bool     = False # has this been used to improve a response?


# ── Correction detector ───────────────────────────────────────────────────────

_CORRECTION_PATTERNS = [
    r"\b(that('?s| is) (wrong|incorrect|not right|not what i (meant|asked|wanted)))\b",
    r"\b(you got (it )?wrong|wrong[,.])\b",
    r"\b(actually[,.]?\s+(?:it'?s|the|no|that'?s))\b",
    r"\b(not quite[,.]|not exactly[,.]|close but)\b",
    r"\b(the correct (way|answer|approach|format) is)\b",
    r"\b(i said|i meant|i wanted|i asked for)\b",
    r"\b(next time[,.]?\s*(please|keep|use|be|don'?t)?|remember (to|that))\b",
    r"\b(don'?t (do|say|use|add) that|stop (doing|saying|adding))\b",
    r"\b(too (long|short|verbose|brief|formal|casual|technical))\b",
]

_APPROVAL_PATTERNS = [
    r"\b(perfect[!.]?\s|exactly[!.]?\s|that'?s (it|right|correct|what i wanted))\b",
    r"^perfect[!.]?\s*$",
    r"\b(yes[!,]?\s+(that'?s|exactly|perfect|right))\b",
    r"\b(great (answer|response|explanation)|well (done|explained|said))\b",
    r"\b(this is (great|perfect|exactly right|what i needed))\b",
    r"\b(nailed it|spot on|you got it)\b",
]

_PREFERENCE_PATTERNS = {
    "length": [
        (r"\btoo long\b",         "shorter"),
        (r"\btoo short\b",        "longer"),
        (r"\bmore (detail|depth)\b", "detailed"),
        (r"\bkeep it (brief|concise|short)\b", "concise"),
        (r"\btl;?dr\b",           "concise"),
    ],
    "format": [
        (r"\buse bullet(s| points)\b",  "bullets"),
        (r"\bno bullet(s| points)\b",   "no_bullets"),
        (r"\buse (a )?table\b",         "table"),
        (r"\bplain text\b",             "plain_text"),
        (r"\bshow (the )?code\b",       "code_first"),
        (r"\bexplain (first|before)\b", "explain_first"),
    ],
    "tone": [
        (r"\bmore (formal|professional)\b",    "formal"),
        (r"\bmore (casual|relaxed|friendly)\b", "casual"),
        (r"\bless (technical|jargon)\b",        "simple_language"),
        (r"\bmore (direct|concise|brief)\b",    "direct"),
    ],
}


def detect_correction(text: str) -> bool:
    """Returns True if this message is correcting Friday."""
    q = text.lower()
    return any(re.search(p, q) for p in _CORRECTION_PATTERNS)


def detect_approval(text: str) -> bool:
    """Returns True if this message is approving Friday's last response."""
    q = text.lower()
    return any(re.search(p, q) for p in _APPROVAL_PATTERNS)


def extract_preferences(text: str) -> list[tuple[str, str]]:
    """
    Extract explicit preferences from text.
    Returns list of (category, value) tuples.
    e.g. [("length", "concise"), ("format", "bullets")]
    """
    q       = text.lower()
    found   = []
    for category, patterns in _PREFERENCE_PATTERNS.items():
        for pattern, value in patterns:
            if re.search(pattern, q):
                found.append((category, value))
    return found


# ── Learning engine ────────────────────────────────────────────────────────────

_session_patterns: dict[str, list[str]] = {}   # intent → [outcomes]
_session_prefs:    dict[str, str]        = {}   # category → value


def record_correction(
    user_message:     str,
    friday_response:  str,
    intent:           str,
    session_id:       str = "",
) -> Optional[LearningRecord]:
    """
    Called when Satvik corrects Friday.
    Extracts what was wrong and stores it.
    """
    if not detect_correction(user_message):
        return None

    import uuid
    record = LearningRecord(
        id         = str(uuid.uuid4())[:8],
        type       = LearnType.CORRECTION,
        intent     = intent,
        original   = friday_response[:500],
        correction = user_message[:500],
        weight     = 1.2,    # corrections count more
    )

    # Extract any preference signals embedded in the correction
    prefs = extract_preferences(user_message)
    for category, value in prefs:
        _session_prefs[category] = value
        _persist_preference(category, value, weight=1.5)

    _write_record(record)
    _persist_to_chronicle(record)
    log.info("Correction recorded: intent=%s", intent)
    return record


def record_approval(
    user_message:    str,
    friday_response: str,
    intent:          str,
) -> Optional[LearningRecord]:
    """Called when Satvik approves Friday's response. Positive reinforcement."""
    if not detect_approval(user_message):
        return None

    import uuid
    record = LearningRecord(
        id         = str(uuid.uuid4())[:8],
        type       = LearnType.APPROVAL,
        intent     = intent,
        original   = friday_response[:300],
        weight     = 1.0,
    )

    # Pattern: this intent → good outcome
    _session_patterns.setdefault(intent, []).append("good")

    _write_record(record)
    log.debug("Approval recorded: intent=%s", intent)
    return record


def record_feedback(
    user_message:    str,
    friday_response: str,
    intent:          str,
) -> Optional[LearningRecord]:
    """
    Master entry point — detects type and routes.
    Called by friday_spine on every user turn.
    """
    if detect_correction(user_message):
        return record_correction(user_message, friday_response, intent)
    if detect_approval(user_message):
        return record_approval(user_message, friday_response, intent)

    # Check for preference signals even in non-correction turns
    prefs = extract_preferences(user_message)
    if prefs:
        for category, value in prefs:
            _session_prefs[category] = value
            _persist_preference(category, value)
        log.debug("Preferences captured: %s", prefs)

    return None


def record_critic_failure(
    prompt:   str,
    response: str,
    issues:   list[str],
    intent:   str,
) -> None:
    """Called when Critic flags a bad response. Logged for pattern analysis."""
    import uuid
    record = LearningRecord(
        id          = str(uuid.uuid4())[:8],
        type        = LearnType.FAILURE,
        intent      = intent,
        original    = response[:300],
        correction  = "; ".join(issues[:3]),
        pattern_key = f"critic_failure.{intent}",
        weight      = 0.8,
    )
    _write_record(record)
    _session_patterns.setdefault(f"fail.{intent}", []).append("; ".join(issues[:2]))
    log.debug("Critic failure recorded: %s", issues[:2])


# ── Preference retrieval ──────────────────────────────────────────────────────

def get_preferences() -> dict[str, str]:
    """
    Return current learned preferences.
    Merges session prefs with persisted Chronicle prefs.
    """
    prefs = {}

    # Load from Chronicle
    try:
        from core.knowledge.friday_chronicle import get_preferences as chron_prefs
        for p in chron_prefs(category="learning"):
            prefs[p["key"]] = p["value"]
    except Exception:
        pass

    # Session overrides (most recent wins)
    prefs.update(_session_prefs)
    return prefs


def build_preference_hint() -> str:
    """
    Build a system prompt fragment from learned preferences.
    Injected by Neural before each response.
    """
    prefs = get_preferences()
    if not prefs:
        return ""

    hints = []
    if prefs.get("length") == "concise":
        hints.append("Keep responses concise — Satvik prefers brief answers.")
    elif prefs.get("length") == "detailed":
        hints.append("Satvik prefers detailed, thorough responses.")

    if prefs.get("format") == "bullets":
        hints.append("Use bullet points when listing items.")
    elif prefs.get("format") == "no_bullets":
        hints.append("Avoid bullet points — use prose.")
    elif prefs.get("format") == "code_first":
        hints.append("Show code before explanation.")

    if prefs.get("tone") == "direct":
        hints.append("Be maximally direct. No preamble.")
    elif prefs.get("tone") == "casual":
        hints.append("Keep it casual and conversational.")

    return " ".join(hints)


def get_pattern_stats() -> dict:
    """Return session-level pattern statistics."""
    stats = {}
    for key, outcomes in _session_patterns.items():
        total = len(outcomes)
        good  = outcomes.count("good")
        stats[key] = {
            "total":   total,
            "good":    good,
            "success": round(good / total, 2) if total else 0,
        }
    return stats


# ── Persistence ───────────────────────────────────────────────────────────────

def _write_record(record: LearningRecord) -> None:
    """Append to JSONL log. Non-blocking — if it fails, skip."""
    try:
        with open(_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(asdict(record)) + "\n")
    except Exception as e:
        log.warning("Learning log write failed: %s", e)


def _persist_preference(category: str, value: str, weight: float = 1.0) -> None:
    """Persist a preference to Chronicle."""
    try:
        from core.knowledge.friday_chronicle import save_preference
        save_preference("learning", category, value, weight=weight)
    except Exception as e:
        log.warning("Preference persist failed: %s", e)


def _persist_to_chronicle(record: LearningRecord) -> None:
    """Save correction as a fact in Chronicle for long-term recall."""
    try:
        from core.knowledge.friday_chronicle import save_fact
        save_fact(
            subject    = "friday",
            predicate  = "learned_correction",
            object_    = record.correction[:200],
            source     = "learning",
            confidence = 0.9,
            metadata   = {"intent": record.intent, "id": record.id},
        )
    except Exception as e:
        log.warning("Chronicle persist failed: %s", e)


def get_recent_corrections(limit: int = 5) -> list[dict]:
    """Load recent corrections from the JSONL log."""
    if not _LOG_PATH.exists():
        return []
    try:
        records = []
        with open(_LOG_PATH, "r", encoding="utf-8") as f:
            for line in f:
                try:
                    r = json.loads(line.strip())
                    if r.get("type") == LearnType.CORRECTION:
                        records.append(r)
                except Exception:
                    continue
        return records[-limit:]
    except Exception as e:
        log.warning("Correction load failed: %s", e)
        return []


# ── Self-test ─────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s [%(name)s] %(message)s")

    print("\n[friday_learning] Running self-test...\n")

    # Correction detection
    correction_cases = [
        ("That's wrong, it should use async/await",           True),
        ("Actually, the correct way is to use a context manager", True),
        ("Next time, keep it shorter please",                  True),
        ("Too long, I wanted a one-liner",                     True),
        ("What time is it?",                                   False),
        ("Thanks Friday!",                                     False),
    ]

    print("  Correction detection:")
    corr_pass = 0
    for text, expected in correction_cases:
        got    = detect_correction(text)
        ok     = got == expected
        if ok: corr_pass += 1
        print(f"  {'✓' if ok else '✗'} [{str(got):5}] {text[:55]}")

    # Approval detection
    print("\n  Approval detection:")
    approval_cases = [
        ("Perfect! That's exactly what I needed", True),
        ("Yes, that's right!",                    True),
        ("Nailed it",                             True),
        ("What does this function do?",           False),
        ("Fix the bug",                           False),
    ]
    appr_pass = 0
    for text, expected in approval_cases:
        got = detect_approval(text)
        ok  = got == expected
        if ok: appr_pass += 1
        print(f"  {'✓' if ok else '✗'} [{str(got):5}] {text[:55]}")

    # Preference extraction
    print("\n  Preference extraction:")
    pref_cases = [
        ("Keep it brief please",            [("length", "concise")]),
        ("Use bullet points next time",     [("format", "bullets")]),
        ("Be more direct",                  [("tone", "direct")]),
        ("Too long, no bullets please",     [("length", "shorter"), ("format", "no_bullets")]),
    ]
    pref_pass = 0
    for text, expected_cats in pref_cases:
        prefs = extract_preferences(text)
        cats  = [c for c, v in prefs]
        ok    = all(ec in cats for ec, ev in expected_cats)
        if ok: pref_pass += 1
        print(f"  {'✓' if ok else '✗'} prefs={prefs} | {text}")

    # record_feedback
    print("\n  record_feedback:")
    dummy_response = "Here is a very detailed and lengthy explanation of everything..."
    rec = record_feedback(
        "That was too long, keep it concise next time",
        dummy_response,
        "question"
    )
    print(f"  ✓ Correction captured: type={rec.type if rec else None}")

    rec2 = record_feedback("Perfect!", dummy_response, "code_write")
    print(f"  ✓ Approval captured: type={rec2.type if rec2 else None}")

    # Preference hint
    hint = build_preference_hint()
    print(f"\n  Preference hint: '{hint}'")

    # Stats
    stats = get_pattern_stats()
    print(f"  Pattern stats: {stats}")

    total = corr_pass + appr_pass + pref_pass
    total_cases = len(correction_cases) + len(approval_cases) + len(pref_cases)
    print(f"\n[friday_learning] {total}/{total_cases} detection tests passed ✓\n")
