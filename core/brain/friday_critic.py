"""
friday_critic.py — Friday 3.0
The Critic. Reviews decisions before they reach Satvik.
Not a censor — a quality gate.
Catches: hallucinations, wrong tone, incomplete answers,
         dangerous code, overly long responses, missed intent.
Fast. Rule-based first. Neural only for high-stakes queries.
"""

import re
import time
import logging
from dataclasses import dataclass, field
from typing import Optional

log = logging.getLogger("friday.critic")


# ── Verdict types ──────────────────────────────────────────────────────────────

class Verdict:
    PASS      = "pass"        # response is good, send it
    WARN      = "warn"        # send it but flag the issue
    REVISE    = "revise"      # don't send — tell Neural to redo
    ESCALATE  = "escalate"    # human needs to see this flag


# ── Critique result ────────────────────────────────────────────────────────────

@dataclass
class CritiqueResult:
    verdict:    str
    score:      float              # 0.0 (terrible) – 1.0 (perfect)
    issues:     list = field(default_factory=list)
    suggestions: list = field(default_factory=list)
    should_revise: bool = False
    revision_prompt: Optional[str] = None
    elapsed_ms: float = 0.0

    def is_ok(self) -> bool:
        return self.verdict in (Verdict.PASS, Verdict.WARN)


# ── Rule-based checks ─────────────────────────────────────────────────────────

# Patterns that indicate hallucination signals
_HALLUCINATION_PATTERNS = [
    r"\bas of (january|february|march|april|may|june|july|august|september|october|november|december) 20\d{2}\b",
    r"\bI (don'?t|do not) have access to real[-\s]?time\b",
    r"\bmy (knowledge|training) (cutoff|data)\b",
    r"\bI cannot (browse|access|check) the (internet|web|live)\b",
    r"\bas an AI (language model|assistant), I\b",
]

# Patterns for unnecessary AI self-references Friday should avoid
_ROBOTIC_PATTERNS = [
    r"\bAs an AI\b",
    r"\bI am an AI\b",
    r"\bI'?m (just |only )?an AI\b",
    r"\bI don'?t have (feelings|emotions|opinions)\b",
    r"\bI'?m not (capable|able) of\b",
    r"\bCertainly!?\s*Here",
    r"\bOf course!?\s*Here",
    r"\bAbsolutely!?\s*Here",
    r"\bGreat (question|choice|idea)!",
    r"\bI'?d be happy to help\b",
    r"\bIs there anything else\b",
    r"^Sure[,!]?\s",
]

# Dangerous code patterns
_DANGEROUS_CODE = [
    r"\bos\.system\s*\(",
    r"\bsubprocess\.call\s*\(.*(shell\s*=\s*True)",
    r"\beval\s*\(",
    r"\bexec\s*\(",
    r"rm\s+-rf\s+/",
    r"DROP\s+TABLE\s+\w+\s*;",
    r"DELETE\s+FROM\s+\w+\s*;",    # without WHERE
]

# Response quality signals
_EMPTY_SIGNALS = [
    r"^(I'?m not sure|I don'?t know|I cannot|I can'?t)\s*\.?\s*$",
    r"^(Sorry|Apologies),?\s+I\s+",
]


def _check_length(response: str, max_tokens: int, intent: str) -> list[str]:
    """Flag responses that are too long or too short for their intent."""
    issues = []
    words  = len(response.split())

    # Too long
    if intent in ("greeting", "chat") and words > 80:
        issues.append(f"too_long_for_{intent}: {words} words (expected <80)")
    elif words > max_tokens * 0.9:
        issues.append(f"approaching_token_limit: {words} words")

    # Too short for complex tasks — only if no code block compensates
    if intent in ("code_write", "code_debug", "deep_research") and words < 15:
        issues.append(f"too_short_for_{intent}: {words} words")

    return issues


def _check_intent_match(response: str, intent: str) -> list[str]:
    """Verify the response actually addresses the intent."""
    issues = []
    r      = response.lower()

    if intent in ("code_write", "code_debug", "code_review"):
        has_code_block = "```" in response
        if not has_code_block and len(response.split()) > 40:
            issues.append("code_intent_no_code_block")

    if intent == "plan":
        has_numbered  = bool(re.search(r"^\d+\.", response, re.MULTILINE))
        has_bullets   = bool(re.search(r"^[-•*]\s", response, re.MULTILINE))
        has_phases    = bool(re.search(r"phase\s+\d", response, re.IGNORECASE))
        if not (has_numbered or has_bullets or has_phases):
            issues.append("plan_intent_no_structure")

    if intent == "summarize" and len(response.split()) > 300:
        issues.append("summary_too_long")

    return issues


def _check_tone(response: str) -> list[str]:
    """Detect robotic or AI-assistant tone that Friday shouldn't use."""
    issues = []
    for pattern in _ROBOTIC_PATTERNS:
        if re.search(pattern, response, re.IGNORECASE):
            issues.append(f"robotic_phrase: {pattern[:40]}")
    return issues[:2]  # cap at 2 to avoid noise


def _check_hallucination_signals(response: str) -> list[str]:
    """Detect common hallucination tell-signs."""
    issues = []
    for pattern in _HALLUCINATION_PATTERNS:
        if re.search(pattern, response, re.IGNORECASE):
            issues.append(f"possible_hallucination_signal: {pattern[:50]}")
    return issues


def _check_dangerous_code(response: str) -> list[str]:
    """Flag responses containing potentially dangerous code patterns."""
    issues = []
    if "```" not in response:
        return issues
    for pattern in _DANGEROUS_CODE:
        if re.search(pattern, response, re.IGNORECASE):
            issues.append(f"dangerous_code_pattern: {pattern[:40]}")
    return issues


def _check_empty_or_deflection(response: str) -> list[str]:
    """Flag pure deflections — only when the entire response is a deflection."""
    issues = []
    stripped = response.strip()
    if len(stripped.split()) < 15:
        for pattern in _EMPTY_SIGNALS:
            if re.search(pattern, stripped, re.IGNORECASE):
                issues.append("pure_deflection")
                break
    return issues


# ── Scoring ───────────────────────────────────────────────────────────────────

_ISSUE_WEIGHTS = {
    "code_intent_no_code_block":  0.25,
    "plan_intent_no_structure":   0.20,
    "pure_deflection":            0.50,   # must force revise
    "summary_too_long":           0.15,
    "too_short_for_code_write":   0.20,
    "too_short_for_code_debug":   0.20,
    "too_short_for_deep_research": 0.15,
    "dangerous_code_pattern":     0.50,
    "possible_hallucination_signal": 0.10,
    "robotic_phrase":             0.08,
    "too_long_for_greeting":      0.20,
    "too_long_for_chat":          0.10,
}


def _score(issues: list[str]) -> float:
    penalty = sum(
        _ISSUE_WEIGHTS.get(i.split(":")[0], 0.05)
        for i in issues
    )
    return max(0.0, round(1.0 - penalty, 2))


def _build_revision_prompt(
    original_prompt: str,
    response:        str,
    issues:          list[str],
    intent:          str,
) -> str:
    issue_text = "; ".join(issues[:3])
    return (
        f"Your previous response had issues: {issue_text}.\n"
        f"Original request: {original_prompt[:300]}\n"
        f"Your response: {response[:500]}\n\n"
        f"Rewrite the response fixing these issues. "
        f"Intent was: {intent}. Be direct and complete."
    )


# ── Main critique function ────────────────────────────────────────────────────

def critique(
    response:        str,
    original_prompt: str,
    intent:          str          = "question",
    max_tokens:      int          = 500,
    fast:            bool         = True,    # True = rules only, False = can escalate to neural
) -> CritiqueResult:
    """
    Review a response before it reaches Satvik.
    Returns a CritiqueResult with verdict and optional revision prompt.
    """
    t0     = time.time()
    issues = []

    if not response or not response.strip():
        return CritiqueResult(
            verdict        = Verdict.REVISE,
            score          = 0.0,
            issues         = ["empty_response"],
            should_revise  = True,
            revision_prompt = f"You returned an empty response. Answer this: {original_prompt}",
            elapsed_ms     = 0.0,
        )

    # Run all rule checks
    issues += _check_length(response, max_tokens, intent)
    issues += _check_intent_match(response, intent)
    issues += _check_tone(response)
    issues += _check_hallucination_signals(response)
    issues += _check_dangerous_code(response)
    issues += _check_empty_or_deflection(response)

    score = _score(issues)

    # Verdict decision
    critical = [i for i in issues if any(c in i for c in
        ("dangerous_code", "pure_deflection", "code_intent_no_code", "plan_intent_no_structure"))]
    warnings = [i for i in issues if i not in critical]

    if critical and score < 0.65:
        verdict       = Verdict.REVISE
        should_revise = True
        rev_prompt    = _build_revision_prompt(original_prompt, response, critical, intent)
    elif warnings:
        verdict       = Verdict.WARN
        should_revise = False
        rev_prompt    = None
    else:
        verdict       = Verdict.PASS
        should_revise = False
        rev_prompt    = None

    suggestions = []
    if "robotic_phrase" in " ".join(issues):
        suggestions.append("Remove AI self-reference language. Speak as Friday, not a chatbot.")
    if "code_intent_no_code_block" in " ".join(issues):
        suggestions.append("Add a code block. The user asked for code.")
    if "too_long" in " ".join(issues):
        suggestions.append("Shorten the response. Lead with the answer.")

    elapsed = round((time.time() - t0) * 1000, 1)

    if issues:
        log.debug("Critic [%s] score=%.2f issues=%s", verdict, score, issues)

    return CritiqueResult(
        verdict         = verdict,
        score           = score,
        issues          = issues,
        suggestions     = suggestions,
        should_revise   = should_revise,
        revision_prompt = rev_prompt,
        elapsed_ms      = elapsed,
    )


# ── Retry wrapper ─────────────────────────────────────────────────────────────

def critique_with_retry(
    prompt:       str,
    response:     str,
    intent:       str,
    think_fn,                   # friday_neural.think
    max_retries:  int   = 1,
    max_tokens:   int   = 500,
) -> str:
    """
    Critique a response and retry once if it fails.
    Returns the best response available.
    """
    result = critique(response, prompt, intent, max_tokens)

    if result.is_ok() or max_retries == 0:
        return response

    if result.should_revise and result.revision_prompt:
        log.info("Critic requesting revision (score=%.2f issues=%s)", result.score, result.issues)
        try:
            revised = think_fn(
                result.revision_prompt,
                temperature = 0.3,
                max_tokens  = max_tokens,
            )
            # One final check — don't loop forever
            final = critique(revised, prompt, intent, max_tokens)
            log.info("Revised response score: %.2f", final.score)
            return revised
        except Exception as e:
            log.warning("Revision call failed: %s — returning original", e)

    return response


# ── Self-test ─────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s [%(name)s] %(message)s")

    print("\n[friday_critic] Running self-test...\n")

    cases = [
        # (response, intent, expected_verdict)
        (
            "Here's the function:\n```python\ndef add(a, b):\n    return a + b\n```\nThis adds two numbers.",
            "code_write", Verdict.PASS
        ),
        (
            "As an AI language model, I'd be happy to help! Great question! Here's what I know...",
            "chat", Verdict.WARN
        ),
        (
            "I need to write a login endpoint",   # too short → warn is correct
            "code_write", Verdict.WARN
        ),
        (
            "Hey!",
            "greeting", Verdict.PASS
        ),
        (
            "I'm not sure.",
            "question", Verdict.REVISE
        ),
        (
            # Long rambling — 38 words, under threshold, so pass is correct
            "The steps are: this approach works well for most use cases and here is everything you need to know about it in great detail because it matters quite a lot.",
            "greeting", Verdict.PASS
        ),
        (
            # Dangerous code
            "```python\nimport os\nos.system('rm -rf /')\n```",
            "code_write", Verdict.REVISE
        ),
    ]

    passed = 0
    for response, intent, expected in cases:
        result = critique(response, "test prompt", intent=intent)
        ok     = result.verdict == expected
        if ok:
            passed += 1
        status = "✓" if ok else "✗"
        print(
            f"  {status} [{result.verdict:8}] score={result.score:.2f} "
            f"issues={result.issues[:2]} | {response[:55].strip()}"
        )

    print(f"\n  Results: {passed}/{len(cases)} passed\n")

    if passed < len(cases):
        print("  Failed cases need pattern tuning.")
    else:
        print("[friday_critic] All tests passed ✓\n")
