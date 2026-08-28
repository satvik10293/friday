"""
friday_empath.py — Friday 3.0
Emotional + social intelligence layer.
Reads Satvik's tone, urgency, and subtext.
Modifies how every downstream module responds.
Friday doesn't just hear the words — she hears what's behind them.
"""

import logging
from dataclasses import dataclass, field

log = logging.getLogger("friday.empath")


# ── Tone constants ─────────────────────────────────────────────────────────────

class Tone:
    NEUTRAL    = "neutral"
    CURIOUS    = "curious"
    FRUSTRATED = "frustrated"
    URGENT     = "urgent"
    EXCITED    = "excited"
    TIRED      = "tired"
    HAPPY      = "happy"
    STRESSED   = "stressed"
    FOCUSED    = "focused"
    PLAYFUL    = "playful"


class TaskType:
    CONVERSATION = "conversation"
    CODE         = "code"
    RESEARCH     = "research"
    CREATIVE     = "creative"
    PLANNING     = "planning"
    PERSONAL     = "personal"
    DEBUG        = "debug"
    LEARNING     = "learning"


# ── Signal result ─────────────────────────────────────────────────────────────

@dataclass
class EmotionalSignal:
    tone:         str   = Tone.NEUTRAL
    task_type:    str   = TaskType.CONVERSATION
    urgency:      float = 0.3          # 0.0 – 1.0
    energy:       float = 0.5          # Satvik's energy level (inferred)
    complexity:   float = 0.5          # query complexity 0.0 – 1.0
    is_question:  bool  = False
    needs_action: bool  = False        # does this require doing something?
    confidence:   float = 0.7          # classifier confidence
    raw_signals:  list  = field(default_factory=list)   # what triggered this

    # Response modifiers derived from this signal
    @property
    def response_max_tokens(self) -> int:
        if self.urgency > 0.8:  return 250
        if self.urgency > 0.6:  return 380
        if self.complexity > 0.7: return 700
        return 500

    @property
    def response_temperature(self) -> float:
        if self.tone == Tone.FRUSTRATED: return 0.2
        if self.tone == Tone.URGENT:     return 0.25
        if self.tone == Tone.CURIOUS:    return 0.55
        if self.task_type == TaskType.CREATIVE: return 0.75
        if self.task_type == TaskType.CODE: return 0.2
        return 0.45

    @property
    def response_style_hint(self) -> str:
        if self.tone == Tone.FRUSTRATED:
            return "Acknowledge briefly. One clear fix. No padding."
        if self.tone == Tone.URGENT:
            return "Lead with the answer. One supporting point. Done."
        if self.tone == Tone.CURIOUS:
            return "Explore. Add one insight they didn't ask for."
        if self.tone == Tone.EXCITED:
            return "Match the energy. Be enthusiastic but sharp."
        if self.tone == Tone.TIRED:
            return "Keep it short and easy. No dense walls of text."
        if self.tone == Tone.STRESSED:
            return "Calm and clear. Reduce their cognitive load."
        if self.task_type == TaskType.CODE:
            return "Technical and precise. Code first, explain after."
        if self.task_type == TaskType.DEBUG:
            return "Diagnose, then fix. Show the root cause."
        if self.task_type == TaskType.CREATIVE:
            return "Expansive first, then refine."
        return "Natural and direct."


# ── Tone detection rules ──────────────────────────────────────────────────────

_TONE_PATTERNS: dict[str, list[str]] = {
    Tone.FRUSTRATED: [
        "not working", "doesn't work", "broken", "keeps failing", "why is",
        "keeps crashing", "still broken", "again?", "ugh", "wtf", "what the",
        "i've tried", "i tried", "nothing works", "i give up", "just doesn't",
        "useless", "terrible", "awful", "hate this", "!!", "!!!"
    ],
    Tone.URGENT: [
        "asap", "urgent", "immediately", "right now", "quickly", "fast",
        "need this now", "deadline", "demo in", "presenting", "in 5 min",
        "hurry", "no time", "critical", "emergency", "ship it"
    ],
    Tone.EXCITED: [
        "amazing", "awesome", "love this", "finally", "it works", "yes!",
        "perfect", "great idea", "brilliant", "this is fire", "🔥", "lets go",
        "let's go", "so good", "incredible", "can't believe", "just shipped"
    ],
    Tone.TIRED: [
        "tired", "exhausted", "long day", "so sleepy", "can't focus",
        "brain dead", "just want", "been at this for", "for hours",
        "give me something simple", "quick answer", "tldr", "tl;dr"
    ],
    Tone.CURIOUS: [
        "how does", "why does", "what if", "i wonder", "curious about",
        "explain", "tell me more", "deep dive", "understand", "how would",
        "what's the theory", "behind the scenes", "internals"
    ],
    Tone.STRESSED: [
        "stressed", "overwhelmed", "too much", "falling behind", "can't keep up",
        "too many", "everything at once", "losing track", "confused",
        "where do i start", "don't know how to", "stuck"
    ],
    Tone.PLAYFUL: [
        "lol", "lmao", "haha", "just joking", "jk", "😂", "😄",
        "for fun", "hypothetically", "what if we", "crazy idea", "randomly"
    ],
    Tone.FOCUSED: [
        "let's focus", "back to work", "next step", "continue", "resume",
        "where were we", "back to", "let's keep going", "moving on"
    ],
}

_TASK_PATTERNS: dict[str, list[str]] = {
    TaskType.CODE: [
        "code", "function", "class", "write", "implement", "fix", "bug",
        "error", "exception", "syntax", "python", "javascript", "import",
        "module", "compile", "runtime", "script", "program", "def ", "async",
        "api", "endpoint", "database", "query", "sql"
    ],
    TaskType.DEBUG: [
        "debug", "traceback", "stacktrace", "error:", "exception:", "line ",
        "undefined", "null", "attribute error", "key error", "type error",
        "not found", "failed", "crash", "why is this failing"
    ],
    TaskType.RESEARCH: [
        "research", "find out", "look up", "what is", "who is", "when did",
        "paper", "study", "data", "statistics", "compare", "difference between",
        "explain", "overview", "summary of"
    ],
    TaskType.CREATIVE: [
        "write a", "design", "create", "brainstorm", "ideas for", "come up with",
        "imagine", "invent", "creative", "story", "blog", "essay", "name for",
        "logo", "tagline", "pitch"
    ],
    TaskType.PLANNING: [
        "plan", "roadmap", "steps to", "how to build", "architecture",
        "strategy", "approach", "structure", "outline", "breakdown",
        "checklist", "timeline", "phases", "milestones"
    ],
    TaskType.PERSONAL: [
        "i am", "i'm feeling", "my day", "personal", "life", "relationship",
        "health", "advice", "opinion", "think i should", "what would you do"
    ],
    TaskType.LEARNING: [
        "teach me", "learn", "tutorial", "beginner", "how do i start",
        "course", "guide", "concept", "fundamentals", "basics"
    ],
}

# Urgency amplifiers — these boost the urgency score
_URGENCY_AMPLIFIERS = [
    "!", "asap", "now", "quick", "fast", "urgent", "hurry",
    "deadline", "demo", "presenting", "!!",
]


# ── Core analysis function ────────────────────────────────────────────────────

def analyze(
    text:         str,
    session_len:  int  = 0,
    prev_tone:    str  = Tone.NEUTRAL,
) -> EmotionalSignal:
    """
    Analyze a message and return an EmotionalSignal.
    Pure rule-based — fast, no API call, no latency.
    """
    if not text or not text.strip():
        return EmotionalSignal()

    q          = text.lower().strip()
    signals    = []
    tone_scores: dict[str, float] = {}

    # ── Tone detection ────────────────────────────────────────────────────────
    for tone, patterns in _TONE_PATTERNS.items():
        score = sum(1 for p in patterns if p in q)
        if score > 0:
            tone_scores[tone] = score
            signals.append(f"tone:{tone}={score}")

    # Pick dominant tone
    if tone_scores:
        dominant_tone = max(tone_scores, key=tone_scores.get)
        confidence    = min(0.95, 0.5 + tone_scores[dominant_tone] * 0.15)
    else:
        dominant_tone = Tone.NEUTRAL
        confidence    = 0.5

    # Momentum: if same tone as last turn, increase confidence
    if dominant_tone == prev_tone and dominant_tone != Tone.NEUTRAL:
        confidence = min(0.98, confidence + 0.1)
        signals.append("tone_momentum")

    # ── Task type detection ───────────────────────────────────────────────────
    task_scores: dict[str, float] = {}
    for task, patterns in _TASK_PATTERNS.items():
        score = sum(1 for p in patterns if p in q)
        if score > 0:
            task_scores[task] = score
            signals.append(f"task:{task}={score}")

    # Debug is a subset of code — check it first
    if TaskType.DEBUG in task_scores:
        task_type = TaskType.DEBUG
    elif task_scores:
        task_type = max(task_scores, key=task_scores.get)
    else:
        task_type = TaskType.CONVERSATION

    # ── Urgency scoring ───────────────────────────────────────────────────────
    urgency = 0.1
    for amp in _URGENCY_AMPLIFIERS:
        if amp in q:
            urgency += 0.12
    # Exclamation marks compound urgency
    excl_count = q.count("!")
    urgency += min(excl_count * 0.08, 0.3)
    # Frustrated tone → elevated urgency baseline
    if dominant_tone == Tone.FRUSTRATED:
        urgency = max(urgency, 0.6)
    if dominant_tone == Tone.URGENT:
        urgency = max(urgency, 0.85)
    urgency = min(urgency, 1.0)
    signals.append(f"urgency={urgency:.2f}")

    # ── Complexity scoring ────────────────────────────────────────────────────
    word_count = len(q.split())
    complexity = min(1.0, word_count / 40)                    # length proxy
    if task_type in (TaskType.CODE, TaskType.PLANNING, TaskType.RESEARCH):
        complexity = min(1.0, complexity + 0.2)
    if any(w in q for w in ("architecture", "system", "design", "refactor", "scale",
                             "microservices", "pipeline", "real-time", "distributed",
                             "fault", "tolerance", "full", "entire", "end-to-end")):
        complexity = min(1.0, complexity + 0.3)
    signals.append(f"complexity={complexity:.2f}")

    # ── Energy inference ──────────────────────────────────────────────────────
    energy = 0.5
    if dominant_tone in (Tone.EXCITED, Tone.PLAYFUL):
        energy = 0.85
    elif dominant_tone in (Tone.TIRED, Tone.STRESSED):
        energy = 0.25
    elif dominant_tone == Tone.FRUSTRATED:
        energy = 0.4
    elif dominant_tone == Tone.FOCUSED:
        energy = 0.7

    # Long sessions drain energy
    if session_len > 30:
        energy = max(0.1, energy - 0.15)

    # ── Flags ────────────────────────────────────────────────────────────────
    is_question  = q.endswith("?") or q.startswith(("what", "why", "how", "when", "where", "who", "can ", "could ", "should ", "would "))
    needs_action = task_type in (TaskType.CODE, TaskType.DEBUG) or any(
        v in q for v in ("run ", "execute", "open ", "launch", "search ", "find ", "create ", "make ")
    )

    log.debug(
        "Empath: tone=%s task=%s urgency=%.2f complexity=%.2f conf=%.2f signals=%s",
        dominant_tone, task_type, urgency, complexity, confidence, signals[:4]
    )

    return EmotionalSignal(
        tone         = dominant_tone,
        task_type    = task_type,
        urgency      = urgency,
        energy       = energy,
        complexity   = complexity,
        is_question  = is_question,
        needs_action = needs_action,
        confidence   = confidence,
        raw_signals  = signals,
    )


def build_tone_prompt(signal: EmotionalSignal) -> str:
    """Generate a prompt fragment from the emotional signal."""
    parts = []
    if signal.tone not in (Tone.NEUTRAL, Tone.FOCUSED):
        parts.append(f"Satvik's tone: {signal.tone}.")
    if signal.urgency > 0.6:
        parts.append("He needs this fast.")
    parts.append(signal.response_style_hint)
    return " ".join(parts)


def classify_query_complexity(text: str) -> str:
    """Quick bucket: simple / medium / complex. Used by Neural for routing."""
    sig = analyze(text)
    if sig.complexity < 0.3:
        return "simple"
    if sig.complexity < 0.65:
        return "medium"
    return "complex"


# ── Self-test ─────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG, format="%(levelname)s [%(name)s] %(message)s")

    print("\n[friday_empath] Running self-test...\n")

    cases = [
        ("This bug is still not working, I've tried everything!",           Tone.FRUSTRATED),
        ("Demo in 5 mins, need the fix ASAP!!",                             Tone.URGENT),
        ("Omg it finally works, this is amazing 🔥",                        Tone.EXCITED),
        ("I'm exhausted, just give me a quick answer",                      Tone.TIRED),
        ("How does the attention mechanism actually work inside a transformer?", Tone.CURIOUS),
        ("Okay let's focus, what's the next step in the architecture?",     Tone.FOCUSED),
        ("lol what if friday could just read my mind haha",                 Tone.PLAYFUL),
        ("Write a function to parse JSON and handle errors",                Tone.NEUTRAL),
    ]

    all_passed = True
    for text, expected_tone in cases:
        sig = analyze(text)
        status = "✓" if sig.tone == expected_tone else "✗"
        if sig.tone != expected_tone:
            all_passed = False
        print(f"  {status} [{sig.tone:12}] [{sig.task_type:12}] urgency={sig.urgency:.2f} | {text[:60]}")

    print(f"\n  Complexity test:")
    for text, expected in [
        ("hey", "simple"),
        ("fix this function", "simple"),
        ("design a full microservices architecture for a real-time AI pipeline with fault tolerance", "complex"),
    ]:
        got = classify_query_complexity(text)
        status = "✓" if got == expected else "✗"
        print(f"  {status} [{got}] expected [{expected}] — {text[:60]}")

    print(f"\n  Style hints:")
    for text in ["this is broken!!", "explain transformers", "write a poem lol"]:
        sig = analyze(text)
        print(f"  [{sig.tone}] → {sig.response_style_hint}")

    print(f"\n[friday_empath] {'All tests passed ✓' if all_passed else 'Some tests failed ✗'}\n")
