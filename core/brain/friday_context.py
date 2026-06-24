"""
friday_context.py — Friday 3.0
The Context Builder. Sits between Perception and Brain.
Raw input → structured ContextPacket that Neural acts on.

Four stages:
  1. Intent Detection   — what does Satvik actually want?
  2. Situation Analysis — what's happening right now?
  3. Priority Engine    — how urgent / important is this?
  4. Prompt Refiner     — build the perfect prompt for Neural
"""

import re
import time
import logging
from dataclasses import dataclass, field
from typing import Optional

log = logging.getLogger("friday.context")


# ── Intent taxonomy ───────────────────────────────────────────────────────────

class Intent:
    # Thinking intents
    QUESTION        = "question"        # factual or explanatory
    DEEP_RESEARCH   = "deep_research"   # multi-source, complex answer
    OPINION         = "opinion"         # Satvik wants Friday's take
    DEBATE          = "debate"          # challenge an idea

    # Action intents
    CODE_WRITE      = "code_write"      # write new code
    CODE_DEBUG      = "code_debug"      # fix existing code
    CODE_REVIEW     = "code_review"     # review/improve code
    CODE_EXPLAIN    = "code_explain"    # explain code
    EXECUTE         = "execute"         # run something / do something
    SEARCH          = "search"          # find information online
    PLAN            = "plan"            # build a plan or roadmap
    CREATE          = "create"          # creative task

    # System intents
    MEMORY_RECALL   = "memory_recall"   # remember something from the past
    SYSTEM_CONTROL  = "system_control"  # open app, control PC
    SCHEDULE        = "schedule"        # calendar / reminders
    SUMMARIZE       = "summarize"       # condense content

    # Social intents
    CHAT            = "chat"            # casual conversation
    VENT            = "vent"            # emotional release, needs listening
    FEEDBACK        = "feedback"        # Satvik giving feedback to Friday
    GREETING        = "greeting"        # hello / wake


# Priority levels
class Priority:
    CRITICAL  = 1   # urgent action needed now
    HIGH      = 2   # important, respond fast
    NORMAL    = 3   # standard
    LOW       = 4   # background / async ok


# ── Context packet ────────────────────────────────────────────────────────────

@dataclass
class ContextPacket:
    # Raw
    raw_input:       str
    timestamp:       float = field(default_factory=time.time)

    # Stage 1 — Intent
    intent:          str   = Intent.QUESTION
    intent_confidence: float = 0.7
    sub_intents:     list  = field(default_factory=list)   # secondary intents

    # Stage 2 — Situation
    has_code:        bool  = False
    has_url:         bool  = False
    has_file:        bool  = False
    language:        Optional[str] = None     # detected programming language
    topic:           str   = ""
    entities:        list  = field(default_factory=list)   # named things detected
    is_followup:     bool  = False            # refers to previous turn?

    # Stage 3 — Priority
    priority:        int   = Priority.NORMAL
    urgency_score:   float = 0.3
    complexity:      str   = "medium"         # simple / medium / complex
    needs_search:    bool  = False
    needs_action:    bool  = False
    needs_memory:    bool  = False

    # Stage 4 — Refined prompt
    refined_prompt:  str   = ""
    system_addendum: str   = ""               # extra injected into system prompt
    temperature:     float = 0.45
    max_tokens:      int   = 500
    route_to:        list  = field(default_factory=lambda: ["neural"])

    # Empath signal (attached after empath.analyze)
    tone:            str   = "neutral"
    energy:          float = 0.5

    def summary(self) -> str:
        return (
            f"intent={self.intent} priority={self.priority} "
            f"complexity={self.complexity} tone={self.tone} "
            f"route={self.route_to}"
        )


# ── Stage 1 — Intent Detection ────────────────────────────────────────────────

_INTENT_PATTERNS: list[tuple[str, list[str]]] = [
    # Greetings — check first
    (Intent.GREETING, [
        r"^(hey|hi|hello|good morning|good evening|good night|what'?s up|yo|sup)\b",
        r"^(morning|evening|afternoon|night)\s*(friday|f)?\s*$",
    ]),

    # Feedback to Friday
    (Intent.FEEDBACK, [
        r"\b(that was wrong|you were wrong|incorrect|not what i asked|bad answer|wrong answer)\b",
        r"\b(remember (that|this)|don'?t (do|say) that again|next time)\b",
        r"\b(too long|too short|simpler please|more detail)\b",
        r"\b(that('?s| is) (wrong|incorrect|not right)|the (correct|right) way is)\b",
        r"\b(you got (it )?wrong|wrong,? the|actually,? it('?s| is)|no,? (it'?s|the correct))\b",
    ]),

    # Vent — emotional first
    (Intent.VENT, [
        r"\b(i'?m so (frustrated|angry|sad|tired|done|over it))\b",
        r"\b(i can'?t (take|do|handle) (this|it|anymore))\b",
        r"\b(nobody (understands|listens|cares))\b",
    ]),

    # Memory recall
    (Intent.MEMORY_RECALL, [
        r"\b(remember when|do you remember|what did (i|we) (say|do|decide)|last time)\b",
        r"\b(what was the|recall|look back|earlier (i|you|we))\b",
    ]),

    # Code intents
    (Intent.CODE_DEBUG, [
        r"\b(debug|traceback|stack\s?trace|error:|exception:|not working|broken|fix (this|the|my))\b",
        r"\b(why (is|does|isn'?t)|what'?s wrong with|it crashes|fails with|keeps (crashing|failing))\b",
        r"\b(keyerror|typeerror|valueerror|attributeerror|indexerror|nameerror|importerror)\b",
        r"\bkeeps? (crashing|failing|breaking|throwing)\b",
    ]),
    (Intent.CODE_WRITE, [
        r"\b(write (a|an|the|me|this)?( code| function| class| script| module| file| endpoint| api))\b",
        r"\b(implement|create (a|an)?( function| method| class| component| endpoint| api))\b",
        r"\b(build (a|an)?( (tool|utility|helper|module|system|api|endpoint)))\b",
        r"\b(code (that|to|which|for))\b",
        r"\bwrite\s+\w+\s+(function|class|method|endpoint|script|module)\b",
        r"\b(fastapi|flask|django|express|endpoint)\s+(for|that|to)\b",
    ]),
    (Intent.CODE_REVIEW, [
        r"\b(review (this|my|the)|look at (this|my) code|improve (this|my)|refactor|optimize (this|my))\b",
        r"\b(is this (good|correct|right|okay)|what (do|would) you think of (this|my))\b",
    ]),
    (Intent.CODE_EXPLAIN, [
        r"\b(explain (this|the|what|how)|what does (this|the) (do|mean)|how does (this|it) work)\b",
        r"\b(walk me through|break (this|it) down|what'?s happening (here|in this))\b",
    ]),

    # System control
    (Intent.SYSTEM_CONTROL, [
        r"\b(open|launch|close|kill|start|stop|run|execute) (the )?(app|application|program|process|terminal|browser|vs\s?code|spotify)\b",
        r"\b(take a screenshot|screenshot|volume (up|down|mute)|brightness)\b",
    ]),

    # Schedule
    (Intent.SCHEDULE, [
        r"\b(remind me|set a reminder|schedule|calendar|meeting|appointment|alarm)\b",
        r"\b(at (\d{1,2})(:\d{2})?(am|pm)?|tomorrow|next (week|monday|tuesday))\b",
    ]),

    # Search
    (Intent.SEARCH, [
        r"\b(search (for|about|the web for)|look up|google|find (info|information|news|data) (about|on))\b",
        r"\b(what'?s (happening|the latest|new) (with|in|on|about))\b",
        r"\b(current(ly)?|latest|recent|today'?s|right now)\b",
    ]),

    # Plan
    (Intent.PLAN, [
        r"\b(plan|roadmap|strategy|steps (to|for)|how (should|do) (i|we) (build|approach|structure))\b",
        r"\b(outline|breakdown|phases|milestones|checklist (for|to))\b",
    ]),

    # Summarize
    (Intent.SUMMARIZE, [
        r"\b(summarize|summary|tl;?dr|tldr|give me (the )?key (points|takeaways)|condense)\b",
        r"\b(in (a few|one|two) (words|sentences|lines)|briefly)\b",
    ]),

    # Create
    (Intent.CREATE, [
        r"\b(write (a |an )?(blog|post|email|letter|essay|story|poem|script|article))\b",
        r"\b(design|brainstorm|come up with|generate (a |an )?idea)\b",
    ]),

    # Opinion
    (Intent.OPINION, [
        r"\b(what (do|would) you (think|say|recommend|suggest)|your (opinion|take|view|thoughts))\b",
        r"\b(should (i|we)|is it (worth|good|better)|which (is|would you) (prefer|choose|pick))\b",
    ]),

    # Deep research
    (Intent.DEEP_RESEARCH, [
        r"\b(deep dive|in[- ]depth|thorough(ly)?|comprehensive|everything (about|on)|full (analysis|breakdown|explanation))\b",
        r"\b(research|study|investigate|explore (the topic|how|why|what))\b",
    ]),

    # Question — broad fallback for interrogatives
    (Intent.QUESTION, [
        r"^(what|why|how|when|where|who|which|is|are|does|do|can|could|would|should|will)\b",
        r"\?$",
    ]),

    # Chat — fallback
    (Intent.CHAT, [r".*"]),
]


def detect_intent(text: str) -> tuple[str, float, list[str]]:
    """
    Returns (primary_intent, confidence, sub_intents).
    Pattern priority order matters — first match wins for primary.
    Sub-intents collect all secondary matches.
    """
    q           = text.lower().strip()
    matched     = []
    confidences = {}

    for intent, patterns in _INTENT_PATTERNS:
        for pattern in patterns:
            if re.search(pattern, q):
                if intent not in matched:
                    matched.append(intent)
                confidences[intent] = confidences.get(intent, 0) + 1
                break

    if not matched:
        return Intent.QUESTION, 0.5, []

    primary    = matched[0]
    confidence = min(0.95, 0.55 + confidences.get(primary, 1) * 0.12)
    sub        = [m for m in matched[1:] if m != primary][:3]
    return primary, confidence, sub


# ── Stage 2 — Situation Analysis ─────────────────────────────────────────────

_CODE_BLOCK_RE  = re.compile(r"```[\w]*\n?[\s\S]+?```", re.MULTILINE)
_URL_RE         = re.compile(r"https?://\S+")
_FILE_RE        = re.compile(r"\b\w+\.(py|js|ts|html|css|json|yaml|yml|txt|md|csv|pdf|docx|xlsx)\b")
_ENTITY_RE      = re.compile(r"\b([A-Z][a-zA-Z0-9]+(?:\s[A-Z][a-zA-Z0-9]+)*)\b")

_LANG_HINTS: dict[str, list[str]] = {
    "python":     ["python", ".py", "def ", "import ", "pip ", "django", "flask", "fastapi", "pandas", "numpy"],
    "javascript": ["javascript", "js", ".js", "node", "npm", "const ", "let ", "async/await", "react", "vue"],
    "typescript": ["typescript", ".ts", "tsx", "interface ", "type ", "angular"],
    "sql":        ["sql", "select ", "insert ", "update ", "delete ", "from ", "where ", "join "],
    "bash":       ["bash", "shell", "#!/", "chmod", "sudo ", "apt ", "grep ", "sed ", "awk "],
    "css":        ["css", ".css", "stylesheet", "tailwind", "flexbox", "grid"],
    "html":       ["html", ".html", "<div", "<span", "<body", "dom"],
    "rust":       ["rust", ".rs", "cargo", "fn main", "let mut"],
    "go":         ["golang", " go ", ".go", "func main", "goroutine"],
}

_FOLLOWUP_SIGNALS = [
    "that", "this", "it", "above", "previous", "you said", "you mentioned",
    "what about", "and also", "what if", "how about", "same", "as before",
    "continue", "go on", "more", "expand", "elaborate",
]


def analyze_situation(
    text:         str,
    prev_topic:   str  = "",
    session_len:  int  = 0,
) -> dict:
    """
    Analyze the current situation from the input.
    Returns a dict of situational flags.
    """
    q = text.lower()

    has_code  = bool(_CODE_BLOCK_RE.search(text))
    has_url   = bool(_URL_RE.search(text))
    has_file  = bool(_FILE_RE.search(text))

    # Language detection
    language = None
    for lang, hints in _LANG_HINTS.items():
        if any(h in q for h in hints):
            language = lang
            break

    # Topic extraction — use first noun phrase or key term
    topic = prev_topic
    code_topics = re.findall(r"\b(class|function|module|api|database|server|client|model|component|pipeline)\b", q)
    if code_topics:
        topic = code_topics[0]
    elif has_file:
        m = _FILE_RE.search(text)
        if m:
            topic = m.group(0)

    # Named entities (rough heuristic — capitalized words)
    if not has_code:   # skip code blocks for entity detection
        entities = list(set(_ENTITY_RE.findall(text)))[:5]
    else:
        entities = []

    # Follow-up detection
    is_followup = (
        session_len > 0 and
        any(sig in q.split()[:6] for sig in _FOLLOWUP_SIGNALS)
    )

    return {
        "has_code":   has_code,
        "has_url":    has_url,
        "has_file":   has_file,
        "language":   language,
        "topic":      topic,
        "entities":   entities,
        "is_followup": is_followup,
    }


# ── Stage 3 — Priority Engine ─────────────────────────────────────────────────

def compute_priority(
    intent:       str,
    urgency:      float,
    has_code:     bool,
    session_len:  int,
) -> tuple[int, bool, bool, bool]:
    """
    Returns (priority, needs_search, needs_action, needs_memory).
    """
    # Needs search
    needs_search = intent in (
        Intent.SEARCH, Intent.DEEP_RESEARCH, Intent.QUESTION
    ) or urgency < 0.3

    # Needs action
    needs_action = intent in (
        Intent.EXECUTE, Intent.SYSTEM_CONTROL, Intent.CODE_DEBUG,
        Intent.CODE_WRITE, Intent.SCHEDULE,
    )

    # Needs memory
    needs_memory = intent in (
        Intent.MEMORY_RECALL, Intent.CHAT, Intent.FEEDBACK,
        Intent.OPINION,
    ) or session_len > 2

    # Priority
    if urgency > 0.75 or intent in (Intent.EXECUTE, Intent.SYSTEM_CONTROL):
        priority = Priority.CRITICAL
    elif urgency > 0.5 or intent in (Intent.CODE_DEBUG, Intent.PLAN, Intent.SEARCH):
        priority = Priority.HIGH
    elif intent in (Intent.CHAT, Intent.VENT, Intent.GREETING):
        priority = Priority.LOW
    else:
        priority = Priority.NORMAL

    return priority, needs_search, needs_action, needs_memory


# ── Stage 4 — Prompt Refiner ─────────────────────────────────────────────────

_INTENT_TEMP: dict[str, float] = {
    Intent.CODE_WRITE:   0.20,
    Intent.CODE_DEBUG:   0.15,
    Intent.CODE_REVIEW:  0.25,
    Intent.CODE_EXPLAIN: 0.35,
    Intent.QUESTION:     0.45,
    Intent.DEEP_RESEARCH: 0.50,
    Intent.PLAN:         0.45,
    Intent.CREATE:       0.72,
    Intent.OPINION:      0.55,
    Intent.CHAT:         0.65,
    Intent.VENT:         0.70,
    Intent.GREETING:     0.60,
    Intent.DEBATE:       0.55,
    Intent.FEEDBACK:     0.30,
    Intent.SUMMARIZE:    0.30,
}

_INTENT_TOKENS: dict[str, int] = {
    Intent.GREETING:     80,
    Intent.CHAT:         200,
    Intent.VENT:         250,
    Intent.FEEDBACK:     150,
    Intent.QUESTION:     400,
    Intent.CODE_DEBUG:   600,
    Intent.CODE_WRITE:   800,
    Intent.CODE_REVIEW:  700,
    Intent.CODE_EXPLAIN: 500,
    Intent.DEEP_RESEARCH: 900,
    Intent.PLAN:         700,
    Intent.CREATE:       600,
    Intent.OPINION:      350,
    Intent.SUMMARIZE:    400,
}

_INTENT_ROUTES: dict[str, list[str]] = {
    Intent.CODE_WRITE:   ["codex", "neural"],
    Intent.CODE_DEBUG:   ["codex", "neural"],
    Intent.CODE_REVIEW:  ["codex", "neural"],
    Intent.CODE_EXPLAIN: ["codex", "neural"],
    Intent.PLAN:         ["planner", "neural"],
    Intent.DEEP_RESEARCH: ["world", "neural"],
    Intent.MEMORY_RECALL: ["chronicle", "neural"],
    Intent.OPINION:      ["neural"],
    Intent.VENT:         ["neural"],
    Intent.QUESTION:     ["neural"],
    Intent.CHAT:         ["neural"],
    Intent.GREETING:     ["neural"],
    Intent.FEEDBACK:     ["learning", "neural"],
    Intent.SYSTEM_CONTROL: ["action"],
    Intent.SCHEDULE:     ["action", "neural"],
    Intent.EXECUTE:      ["action"],
}

_INTENT_SYSTEM_HINTS: dict[str, str] = {
    Intent.CODE_WRITE:   "Write clean, production-ready code. Code block first, brief explanation after.",
    Intent.CODE_DEBUG:   "Diagnose the root cause first. Then provide the exact fix. Show the corrected code.",
    Intent.CODE_REVIEW:  "Review critically. Be specific about what to improve and why.",
    Intent.CODE_EXPLAIN: "Explain clearly. Use an analogy if it helps. Build up from the core concept.",
    Intent.PLAN:         "Think in phases. Be concrete. Each step should be immediately actionable.",
    Intent.DEEP_RESEARCH: "Be thorough. Cover multiple angles. Cite key distinctions.",
    Intent.OPINION:      "Have a clear opinion. Don't hedge. Back it with one strong reason.",
    Intent.VENT:         "Listen first. Acknowledge what he's feeling. Keep it brief and warm. Don't problem-solve unless asked.",
    Intent.FEEDBACK:     "Acknowledge the correction immediately. Confirm understanding. Don't over-apologize.",
    Intent.GREETING:     "Respond warmly and briefly. One line. Then ask what's needed.",
    Intent.SUMMARIZE:    "Lead with the core point. Support with 2-3 essentials. Drop everything else.",
    Intent.MEMORY_RECALL: "Recall from memory first. Be specific about what you remember.",
}


def refine_prompt(
    text:       str,
    intent:     str,
    situation:  dict,
    signal=None,  # EmotionalSignal from empath
) -> tuple[str, str, float, int, list[str]]:
    """
    Returns (refined_prompt, system_addendum, temperature, max_tokens, route_to).
    """
    # Temperature + tokens from intent
    temperature = _INTENT_TEMP.get(intent, 0.45)
    max_tokens  = _INTENT_TOKENS.get(intent, 500)
    route_to    = _INTENT_ROUTES.get(intent, ["neural"])

    # Empath override — urgency and tone shift params
    if signal:
        temperature = signal.response_temperature
        max_tokens  = min(max_tokens, signal.response_max_tokens * 2)

    # System addendum from intent
    system_addendum = _INTENT_SYSTEM_HINTS.get(intent, "")

    # Refined prompt — enrich the raw input with context hints
    parts = [text.strip()]

    if situation.get("has_code") and intent == Intent.CODE_DEBUG:
        parts.append("(analyze the code block above for the root cause)")

    if situation.get("is_followup"):
        parts.append("(this continues from our previous exchange)")

    if situation.get("language"):
        system_addendum += f" Target language: {situation['language']}."

    refined = " ".join(parts)

    return refined, system_addendum, temperature, max_tokens, route_to


# ── Master build function ──────────────────────────────────────────────────────

def build(
    raw_input:   str,
    prev_topic:  str  = "",
    session_len: int  = 0,
) -> ContextPacket:
    """
    Full pipeline: raw text → ContextPacket.
    This is the single entry point called by friday_spine.
    """
    if not raw_input or not raw_input.strip():
        pkt          = ContextPacket(raw_input=raw_input)
        pkt.intent   = Intent.CHAT
        pkt.priority = Priority.LOW
        return pkt

    pkt = ContextPacket(raw_input=raw_input)

    # ── Stage 1: Intent ───────────────────────────────────────────────────────
    intent, confidence, sub_intents = detect_intent(raw_input)
    pkt.intent             = intent
    pkt.intent_confidence  = confidence
    pkt.sub_intents        = sub_intents

    # ── Stage 2: Situation ────────────────────────────────────────────────────
    situation = analyze_situation(raw_input, prev_topic, session_len)
    pkt.has_code   = situation["has_code"]
    pkt.has_url    = situation["has_url"]
    pkt.has_file   = situation["has_file"]
    pkt.language   = situation["language"]
    pkt.topic      = situation["topic"]
    pkt.entities   = situation["entities"]
    pkt.is_followup = situation["is_followup"]

    # ── Empath signal (attach before priority so urgency is available) ────────
    try:
        try:
            from core.persona.friday_empath import analyze as empath_analyze
        except ImportError:
            from core.persona.friday_empath import analyze as empath_analyze
        signal         = empath_analyze(raw_input, session_len=session_len)
        pkt.tone       = signal.tone
        pkt.energy     = signal.energy
        urgency        = signal.urgency
        pkt.complexity = ("simple" if signal.complexity < 0.35
                          else "complex" if signal.complexity > 0.65
                          else "medium")
    except Exception as e:
        log.warning("Empath attach failed: %s", e)
        signal  = None
        urgency = 0.3

    pkt.urgency_score = urgency

    # ── Stage 3: Priority ─────────────────────────────────────────────────────
    priority, needs_search, needs_action, needs_memory = compute_priority(
        intent, urgency, pkt.has_code, session_len
    )
    pkt.priority      = priority
    pkt.needs_search  = needs_search
    pkt.needs_action  = needs_action
    pkt.needs_memory  = needs_memory

    # ── Stage 4: Prompt refiner ───────────────────────────────────────────────
    refined, sys_add, temp, tokens, route = refine_prompt(
        raw_input, intent, situation, signal
    )
    pkt.refined_prompt   = refined
    pkt.system_addendum  = sys_add
    pkt.temperature      = temp
    pkt.max_tokens       = tokens
    pkt.route_to         = route

    log.debug("Context: %s", pkt.summary())
    return pkt


# ── Self-test ─────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s [%(name)s] %(message)s")

    print("\n[friday_context] Running self-test...\n")

    cases = [
        ("Hey Friday",                                    Intent.GREETING),
        ("This function keeps crashing with a KeyError",  Intent.CODE_DEBUG),
        ("Write me a FastAPI endpoint for user login",    Intent.CODE_WRITE),
        ("What do you think about this architecture?",    Intent.OPINION),
        ("I'm so frustrated, nothing is working today",   Intent.VENT),
        ("Search for the latest news on Groq API",        Intent.SEARCH),
        ("Remind me to call Satvik at 5pm",               Intent.SCHEDULE),
        ("Do you remember what we decided about the DB?", Intent.MEMORY_RECALL),
        ("Plan the full Friday 3.0 build roadmap",        Intent.PLAN),
        ("Summarize everything we discussed today",       Intent.SUMMARIZE),
        ("Open VS Code",                                  Intent.SYSTEM_CONTROL),
        ("That answer was wrong, the correct way is X",   Intent.FEEDBACK),
    ]

    passed = 0
    failed = 0

    for text, expected in cases:
        pkt    = build(text, session_len=3)
        ok     = pkt.intent == expected
        status = "✓" if ok else "✗"
        if ok:
            passed += 1
        else:
            failed += 1
        print(
            f"  {status} [{pkt.intent:16}] p={pkt.priority} "
            f"route={pkt.route_to} "
            f"| {text[:55]}"
        )

    print(f"\n  Results: {passed}/{len(cases)} passed\n")

    # Detailed packet test
    print("  Full packet for 'Write a Python function to merge two dicts':")
    pkt = build("Write a Python function to merge two dicts", session_len=1)
    print(f"    intent:     {pkt.intent}")
    print(f"    language:   {pkt.language}")
    print(f"    route_to:   {pkt.route_to}")
    print(f"    temp:       {pkt.temperature}")
    print(f"    max_tokens: {pkt.max_tokens}")
    print(f"    complexity: {pkt.complexity}")
    print(f"    sys_add:    {pkt.system_addendum}")

    print(f"\n[friday_context] Done — {passed}/{len(cases)} tests passed\n")
