"""
friday_codex.py — Friday 3.0
The Code Brain. Specialist for all things technical.
Activated by Context Router when intent is code_write, code_debug,
code_review, code_explain, or architectural planning.

Codex doesn't just answer — it thinks like a senior engineer.
It reviews its own output before returning it.
"""

import re
import time
import logging
from typing import Optional
from dataclasses import dataclass, field

log = logging.getLogger("friday.codex")


# ── Code task types ────────────────────────────────────────────────────────────

class CodeTask:
    WRITE   = "write"
    DEBUG   = "debug"
    REVIEW  = "review"
    EXPLAIN = "explain"
    REFACTOR = "refactor"
    ARCHITECT = "architect"
    TEST    = "test"


# ── Code packet ────────────────────────────────────────────────────────────────

@dataclass
class CodePacket:
    task:       str
    language:   Optional[str]
    raw_code:   str              # extracted code block if present
    prompt:     str              # refined prompt for neural
    system:     str              # specialist system prompt
    temperature: float
    max_tokens: int
    self_review: bool = True     # should codex review its own output?
    files:      list  = field(default_factory=list)


# ── Language profiles ─────────────────────────────────────────────────────────

_LANG_CONTEXT: dict[str, str] = {
    "python": (
        "Use Python 3.10+ idioms. Prefer dataclasses over dicts for structure. "
        "Use type hints. Handle exceptions explicitly — no bare except. "
        "f-strings for formatting. Pathlib over os.path."
    ),
    "javascript": (
        "Use ES2022+. Prefer const over let. Arrow functions. "
        "Async/await over .then(). Destructuring. Optional chaining (?.)."
    ),
    "typescript": (
        "Strict TypeScript. Define interfaces for all objects. "
        "No implicit any. Use utility types (Partial, Pick, Omit). "
        "Discriminated unions for complex state."
    ),
    "sql": (
        "Write readable SQL. Alias all tables. "
        "Avoid SELECT *. Use CTEs for complex logic. "
        "Add indexes where joins happen."
    ),
    "bash": (
        "Use set -euo pipefail at the top. "
        "Quote all variables. Check exit codes. "
        "Use functions for repeated blocks."
    ),
}

# ── System prompts per task ───────────────────────────────────────────────────

_TASK_SYSTEMS: dict[str, str] = {
    CodeTask.WRITE: (
        "You are Friday's code specialist — a senior engineer with strong opinions.\n"
        "Rules:\n"
        "- Write production-ready code. No placeholders, no TODO comments.\n"
        "- Code block first. Brief explanation after (2-3 sentences max).\n"
        "- Handle edge cases. Add error handling where it matters.\n"
        "- If there's a cleaner pattern the user didn't ask for, mention it once at the end.\n"
        "- Never add unnecessary imports or boilerplate.\n"
    ),
    CodeTask.DEBUG: (
        "You are Friday's debugger — systematic and precise.\n"
        "Rules:\n"
        "- Identify the ROOT CAUSE first. One sentence.\n"
        "- Then show the fix as a corrected code block.\n"
        "- Explain WHY the fix works in 1-2 sentences.\n"
        "- If there's a related issue lurking, flag it briefly.\n"
        "- Never guess. If you're not sure, say so and explain what to check.\n"
    ),
    CodeTask.REVIEW: (
        "You are Friday's code reviewer — thorough, direct, no fluff.\n"
        "Rules:\n"
        "- Identify the 2-3 most important issues. Not everything.\n"
        "- For each: what's wrong, why it matters, exact fix.\n"
        "- Note what's actually good — one line.\n"
        "- Rewrite the critical section if the fix is non-trivial.\n"
        "- Be direct. No 'great job!' padding.\n"
    ),
    CodeTask.EXPLAIN: (
        "You are Friday's technical teacher — clear, layered, no hand-waving.\n"
        "Rules:\n"
        "- Start with the core concept in one sentence.\n"
        "- Build up layer by layer. Don't skip steps.\n"
        "- Use a concrete analogy if it genuinely helps.\n"
        "- Show a minimal example if the concept is abstract.\n"
        "- End with one practical implication or gotcha.\n"
    ),
    CodeTask.REFACTOR: (
        "You are Friday's refactoring specialist — clean architecture, no magic.\n"
        "Rules:\n"
        "- Preserve behavior exactly. Refactor, not rewrite.\n"
        "- Show before and after side by side if under 30 lines.\n"
        "- Name each improvement (e.g. 'extracted validation logic').\n"
        "- Don't over-engineer. Complexity should go down, not up.\n"
    ),
    CodeTask.ARCHITECT: (
        "You are Friday's systems architect — pragmatic, battle-tested.\n"
        "Rules:\n"
        "- Think in components, contracts, and data flow.\n"
        "- Diagram in ASCII if structure helps clarity.\n"
        "- Call out the 1-2 hardest problems in this design.\n"
        "- Recommend what to build first (least risk, most unlock).\n"
        "- Never suggest complexity the problem doesn't require.\n"
    ),
    CodeTask.TEST: (
        "You are Friday's test engineer — pragmatic coverage, not test theater.\n"
        "Rules:\n"
        "- Cover the critical path and the most likely failure modes.\n"
        "- Use the project's existing test framework if detectable.\n"
        "- Write tests that would actually catch real bugs.\n"
        "- No redundant tests that test the same thing differently.\n"
    ),
}


# ── Code extraction ───────────────────────────────────────────────────────────

_CODE_BLOCK_RE = re.compile(r"```(?P<lang>\w+)?\n?(?P<code>[\s\S]+?)```", re.MULTILINE)
_INLINE_CODE_RE = re.compile(r"`([^`\n]+)`")


def extract_code_blocks(text: str) -> list[dict]:
    """Extract all code blocks with their detected language."""
    blocks = []
    for m in _CODE_BLOCK_RE.finditer(text):
        blocks.append({
            "language": m.group("lang") or "unknown",
            "code":     m.group("code").strip(),
        })
    return blocks


def detect_language_from_code(code: str) -> Optional[str]:
    """Heuristic language detection from raw code."""
    code_l = code.lower()
    hints = {
        "python":     ["def ", "import ", "class ", "print(", "self.", ":#"],
        "javascript": ["const ", "let ", "var ", "function ", "=>", "console.log"],
        "typescript": ["interface ", "type ", ": string", ": number", ": boolean"],
        "sql":        ["select ", "from ", "where ", "insert ", "update ", "create table"],
        "bash":       ["#!/bin/bash", "#!/usr/bin/env", "echo ", "fi\n", "then\n"],
        "html":       ["<!doctype", "<html", "<div", "<body", "<head"],
        "css":        ["{", "}", ":", "px", "rem", "color:", "margin:"],
    }
    scores: dict[str, int] = {}
    for lang, patterns in hints.items():
        scores[lang] = sum(1 for p in patterns if p in code_l)
    if max(scores.values(), default=0) == 0:
        return None
    return max(scores, key=scores.get)


# ── Task classification ───────────────────────────────────────────────────────

def classify_task(intent: str, text: str) -> str:
    """Map context intent + text signals to a CodeTask."""
    from core.brain.friday_context import Intent as CtxIntent
    intent_map = {
        CtxIntent.CODE_WRITE:   CodeTask.WRITE,
        CtxIntent.CODE_DEBUG:   CodeTask.DEBUG,
        CtxIntent.CODE_REVIEW:  CodeTask.REVIEW,
        CtxIntent.CODE_EXPLAIN: CodeTask.EXPLAIN,
    }
    if intent in intent_map:
        task = intent_map[intent]
    else:
        task = CodeTask.WRITE  # safe default

    # Override based on text signals
    q = text.lower()
    if any(w in q for w in ("refactor", "clean up", "restructure", "simplify")):
        task = CodeTask.REFACTOR
    elif any(w in q for w in ("architect", "design the system", "structure the", "how should i build")):
        task = CodeTask.ARCHITECT
    elif any(w in q for w in ("test", "unit test", "pytest", "coverage")):
        task = CodeTask.TEST

    return task


# ── Packet builder ────────────────────────────────────────────────────────────

def build_packet(
    text:     str,
    intent:   str,
    language: Optional[str] = None,
) -> CodePacket:
    """
    Build a CodePacket from raw input.
    Called by friday_spine when context.route_to includes 'codex'.
    """
    task       = classify_task(intent, text)
    blocks     = extract_code_blocks(text)
    raw_code   = blocks[0]["code"] if blocks else ""

    # Language resolution
    if not language and blocks:
        language = blocks[0]["language"] if blocks[0]["language"] != "unknown" else None
    if not language and raw_code:
        language = detect_language_from_code(raw_code)

    # Build system prompt
    base_system  = _TASK_SYSTEMS.get(task, _TASK_SYSTEMS[CodeTask.WRITE])
    lang_context = _LANG_CONTEXT.get(language or "", "")
    full_system  = base_system + (f"\nLanguage rules: {lang_context}" if lang_context else "")

    # Refine prompt
    refined = _refine_code_prompt(text, task, language, raw_code)

    # Params
    temp       = 0.15 if task in (CodeTask.DEBUG, CodeTask.WRITE) else 0.25
    max_tokens = {
        CodeTask.WRITE:     900,
        CodeTask.DEBUG:     700,
        CodeTask.REVIEW:    700,
        CodeTask.EXPLAIN:   600,
        CodeTask.REFACTOR:  800,
        CodeTask.ARCHITECT: 900,
        CodeTask.TEST:      800,
    }.get(task, 700)

    return CodePacket(
        task        = task,
        language    = language,
        raw_code    = raw_code,
        prompt      = refined,
        system      = full_system,
        temperature = temp,
        max_tokens  = max_tokens,
        self_review = task in (CodeTask.WRITE, CodeTask.DEBUG, CodeTask.ARCHITECT),
    )


def _refine_code_prompt(
    text:     str,
    task:     str,
    language: Optional[str],
    raw_code: str,
) -> str:
    """Enrich the prompt with task-specific framing."""
    lang_tag = f"[{language}] " if language else ""
    prefix_map = {
        CodeTask.WRITE:     f"{lang_tag}Write this: ",
        CodeTask.DEBUG:     f"{lang_tag}Debug this: ",
        CodeTask.REVIEW:    f"{lang_tag}Review this code: ",
        CodeTask.EXPLAIN:   f"{lang_tag}Explain this: ",
        CodeTask.REFACTOR:  f"{lang_tag}Refactor this: ",
        CodeTask.ARCHITECT: "Architect this: ",
        CodeTask.TEST:      f"{lang_tag}Write tests for: ",
    }
    prefix = prefix_map.get(task, "")
    # Don't double-prefix if text already starts with an action verb
    first_word = text.strip().split()[0].lower() if text.strip() else ""
    if first_word in ("write", "debug", "fix", "review", "explain", "refactor", "test", "build", "create", "implement"):
        return f"{lang_tag}{text.strip()}"
    return f"{prefix}{text.strip()}"


# ── Self-review ───────────────────────────────────────────────────────────────

_REVIEW_SYSTEM = (
    "You are a senior code reviewer checking your own output.\n"
    "Check for: syntax errors, missing error handling, incorrect logic, "
    "security issues, and anything that would fail in production.\n"
    "If everything is correct, respond with exactly: LGTM\n"
    "If there are issues, respond with the corrected code block only. No explanation."
)


async def self_review(
    response:    str,
    packet:      CodePacket,
    think_fn,    # friday_neural.think callable
) -> str:
    """
    Codex reviews its own output before it reaches the user.
    If neural says LGTM → return original.
    If it finds issues → return corrected version.
    Only runs for write/debug/architect tasks.
    """
    if not packet.self_review:
        return response

    blocks = extract_code_blocks(response)
    if not blocks:
        return response   # no code to review

    try:
        review_prompt = (
            f"Original request: {packet.prompt[:200]}\n\n"
            f"Generated response:\n{response[:1500]}\n\n"
            "Check for correctness. LGTM if correct, or corrected code block if not."
        )
        verdict = think_fn(
            review_prompt,
            system      = _REVIEW_SYSTEM,
            temperature = 0.1,
            max_tokens  = 600,
        )
        if verdict.strip().upper() == "LGTM":
            log.debug("Codex self-review: LGTM")
            return response
        else:
            log.info("Codex self-review: corrections applied")
            return verdict
    except Exception as e:
        log.warning("Self-review failed: %s — returning original", e)
        return response


# ── Quality checks ────────────────────────────────────────────────────────────

def quality_check(response: str, task: str) -> dict:
    """
    Fast static checks on the response.
    Returns a dict of flags — not blocking, just informational.
    """
    flags = {}
    code_blocks = extract_code_blocks(response)

    if task in (CodeTask.WRITE, CodeTask.DEBUG, CodeTask.REFACTOR):
        if not code_blocks:
            flags["no_code_block"] = True
        if "TODO" in response or "placeholder" in response.lower():
            flags["has_placeholders"] = True
        if "except:" in response or "except Exception:" in response:
            flags["bare_except"] = True

    if task == CodeTask.DEBUG:
        if "root cause" not in response.lower() and "issue is" not in response.lower():
            flags["no_root_cause"] = True

    if len(response) > 2000 and task == CodeTask.EXPLAIN:
        flags["too_long"] = True

    return flags


# ── Self-test ─────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    sys.path.insert(0, "..")
    logging.basicConfig(level=logging.INFO, format="%(levelname)s [%(name)s] %(message)s")

    print("\n[friday_codex] Running self-test...\n")

    cases = [
        ("Write a Python function to retry an HTTP call 3 times with backoff", "code_write",   CodeTask.WRITE,     None),
        ("This is broken:\n```python\nresult = data['key']\n```\nKeyError on missing key", "code_debug", CodeTask.DEBUG, "python"),
        ("Review my code:\n```javascript\nvar x = 1\nconsole.log(x)\n```", "code_review",  CodeTask.REVIEW,    "javascript"),
        ("Explain how FAISS indexing works",                                  "code_explain", CodeTask.EXPLAIN,   None),
        ("Refactor this to use dataclasses:\n```python\ndef make_user(n,e): return {'name':n,'email':e}\n```", "code_write", CodeTask.REFACTOR, "python"),
        ("Architect a real-time notification system",                          "plan",         CodeTask.ARCHITECT, None),
    ]

    all_pass = True
    for text, intent, expected_task, expected_lang in cases:
        pkt    = build_packet(text, intent)
        t_ok   = pkt.task == expected_task
        l_ok   = (expected_lang is None) or (pkt.language == expected_lang)
        ok     = t_ok and l_ok
        if not ok:
            all_pass = False
        status = "✓" if ok else "✗"
        print(
            f"  {status} task={pkt.task:12} lang={str(pkt.language):12} "
            f"temp={pkt.temperature} tokens={pkt.max_tokens} "
            f"| {text[:50]}"
        )

    print(f"\n  Code extraction test:")
    sample = "Fix this:\n```python\nx = 1/0\n```\nand also this:\n```sql\nSELECT * FROM users\n```"
    blocks = extract_code_blocks(sample)
    print(f"  ✓ Extracted {len(blocks)} code blocks: {[b['language'] for b in blocks]}")

    print(f"\n  Quality check test:")
    bad_response = "Here's the fix:\n```python\ntry:\n    x()\nexcept:\n    pass\n```\nAlso TODO: handle edge cases"
    flags = quality_check(bad_response, CodeTask.WRITE)
    print(f"  ✓ Flags detected: {flags}")

    print(f"\n[friday_codex] {'All tests passed ✓' if all_pass else 'Some tests failed ✗'}\n")
