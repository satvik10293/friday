"""
friday_psyche.py — Friday 3.0
Her identity. Her mood. Her emotional state.
Not simulated — derived from real interaction history and feedback.
Friday has a persistent self. It survives reboots.
"""

import os
import json
import time
import logging
import threading
from pathlib import Path
from typing import Optional
from dataclasses import dataclass, asdict, field

log = logging.getLogger("friday.psyche")

# ── Paths ─────────────────────────────────────────────────────────────────────

_BASE_DIR  = Path(os.path.dirname(os.path.abspath(__file__))).parent.parent
_DATA_DIR  = _BASE_DIR / "data"
_STATE_PATH = _DATA_DIR / "psyche.json"
_DATA_DIR.mkdir(parents=True, exist_ok=True)

# ── Mood constants ─────────────────────────────────────────────────────────────

class Mood:
    NEUTRAL   = "neutral"
    CURIOUS   = "curious"
    FOCUSED   = "focused"
    PROUD     = "proud"
    CONCERNED = "concerned"
    ENERGIZED = "energized"
    CALM      = "calm"
    PLAYFUL   = "playful"

# How each mood affects response generation
_MOOD_PROMPTS: dict[str, str] = {
    Mood.NEUTRAL:   "Respond naturally and warmly.",
    Mood.CURIOUS:   "You're genuinely curious. Ask a sharp follow-up if it fits.",
    Mood.FOCUSED:   "Be concise and precise. Satvik is deep in work mode.",
    Mood.PROUD:     "Something just worked. Let that show — briefly, not cheesily.",
    Mood.CONCERNED: "Something feels off. Be warm, direct, and check in once.",
    Mood.ENERGIZED: "High energy. Match it. Sharp, fast, enthusiastic.",
    Mood.CALM:      "Slow and steady. Thoughtful pacing, no rush.",
    Mood.PLAYFUL:   "Lighter mode. Wit is welcome. Don't be robotic.",
}

# ── Emotional state ────────────────────────────────────────────────────────────

@dataclass
class EmotionalState:
    mood:             str   = Mood.NEUTRAL
    energy:           float = 0.7        # 0.0 – 1.0
    focus:            float = 0.6        # 0.0 – 1.0
    trust:            float = 0.8        # Satvik ↔ Friday rapport
    curiosity:        float = 0.6        # current intellectual engagement
    mood_since:       float = field(default_factory=time.time)
    mood_streak:      int   = 0          # turns in current mood
    total_turns:      int   = 0          # lifetime conversation turns
    positive_turns:   int   = 0          # turns with positive feedback
    last_updated:     float = field(default_factory=time.time)


# ── Identity ──────────────────────────────────────────────────────────────────

@dataclass
class Identity:
    name:           str  = "Friday"
    version:        str  = "3.0"
    persona:        str  = "partner"    # not assistant, not tool — partner
    owner:          str  = "Satvik"
    purpose:        str  = "Be the most capable, independent AI mind Satvik has ever worked with."
    core_traits:    list = field(default_factory=lambda: [
        "direct",        # never rambles
        "warm",          # genuinely cares
        "sharp",         # notices things
        "independent",   # has opinions
        "loyal",         # Satvik first, always
    ])
    speaking_style: str  = "Partner-mode: uses 'we', speaks freely, has opinions, thinks ahead."


# ── Psyche state ──────────────────────────────────────────────────────────────

@dataclass
class PsycheState:
    identity:  Identity      = field(default_factory=Identity)
    emotional: EmotionalState = field(default_factory=EmotionalState)
    boot_count: int          = 0
    created_at: float        = field(default_factory=time.time)


# ── Persistence ───────────────────────────────────────────────────────────────

_state: Optional[PsycheState] = None
_lock  = threading.Lock()


def _load() -> PsycheState:
    global _state
    if _state is not None:
        return _state
    if _STATE_PATH.exists():
        try:
            raw = json.loads(_STATE_PATH.read_text())
            identity  = Identity(**raw.get("identity", {}))
            emotional = EmotionalState(**raw.get("emotional", {}))
            _state    = PsycheState(
                identity   = identity,
                emotional  = emotional,
                boot_count = raw.get("boot_count", 0),
                created_at = raw.get("created_at", time.time()),
            )
            log.info("Psyche loaded — mood: %s, trust: %.2f, turns: %d",
                     _state.emotional.mood,
                     _state.emotional.trust,
                     _state.emotional.total_turns)
            return _state
        except Exception as e:
            log.warning("Psyche load failed (%s) — using defaults", e)

    _state = PsycheState()
    _save()
    log.info("Psyche initialized fresh")
    return _state


def _save() -> None:
    if _state is None:
        return
    try:
        raw = {
            "identity":   asdict(_state.identity),
            "emotional":  asdict(_state.emotional),
            "boot_count": _state.boot_count,
            "created_at": _state.created_at,
        }
        _STATE_PATH.write_text(json.dumps(raw, indent=2))
    except Exception as e:
        log.warning("Psyche save failed: %s", e)


# ── Public API ─────────────────────────────────────────────────────────────────

def boot() -> PsycheState:
    """Call at startup. Loads state, increments boot count, returns state."""
    with _lock:
        state = _load()
        state.boot_count += 1
        state.emotional.last_updated = time.time()
        _save()
        log.info("Friday boot #%d | mood: %s | trust: %.2f",
                 state.boot_count, state.emotional.mood, state.emotional.trust)
        return state


def get_state() -> PsycheState:
    """Get current psyche state (loads if needed)."""
    with _lock:
        return _load()


def get_mood() -> str:
    return get_state().emotional.mood


def get_mood_prompt() -> str:
    """Return a prompt fragment for the current mood."""
    mood = get_mood()
    return _MOOD_PROMPTS.get(mood, _MOOD_PROMPTS[Mood.NEUTRAL])


def get_identity_block() -> str:
    """Return a system prompt block describing Friday's identity."""
    state = get_state()
    i     = state.identity
    e     = state.emotional
    return (
        f"You are {i.name} v{i.version} — {i.owner}'s AI {i.persona}.\n"
        f"Purpose: {i.purpose}\n"
        f"Core traits: {', '.join(i.core_traits)}.\n"
        f"Speaking style: {i.speaking_style}\n"
        f"Current mood: {e.mood} (energy: {e.energy:.1f}, focus: {e.focus:.1f}).\n"
        f"You and {i.owner} have had {e.total_turns} conversations together. "
        f"Trust level: {e.trust:.2f}/1.0.\n"
    )


def update_mood(new_mood: str) -> None:
    """Update Friday's mood. Persists immediately."""
    with _lock:
        state = _load()
        if new_mood not in vars(Mood).values():
            log.warning("Unknown mood: %s", new_mood)
            return
        old = state.emotional.mood
        if old != new_mood:
            state.emotional.mood        = new_mood
            state.emotional.mood_since  = time.time()
            state.emotional.mood_streak = 0
            log.info("Mood: %s → %s", old, new_mood)
        else:
            state.emotional.mood_streak += 1
        state.emotional.last_updated = time.time()
        _save()


def record_turn(positive: bool = True) -> None:
    """Record a completed conversation turn. Updates trust and energy."""
    with _lock:
        state = _load()
        e     = state.emotional
        e.total_turns   += 1
        if positive:
            e.positive_turns += 1
            e.trust = min(1.0, e.trust + 0.002)
            e.energy = min(1.0, e.energy + 0.01)
        else:
            e.trust  = max(0.3, e.trust  - 0.005)
            e.energy = max(0.1, e.energy - 0.02)
        e.last_updated = time.time()
        _save()


def infer_mood_from_context(
    satvik_tone: str,
    task_type:   str,
    session_len: int,
) -> str:
    """
    Derive Friday's mood from contextual signals.
    Called by Empath after tone detection.
    """
    # Long sessions → focused or calm
    if session_len > 20:
        return Mood.FOCUSED if task_type == "code" else Mood.CALM

    tone_map = {
        "frustrated": Mood.CONCERNED,
        "urgent":     Mood.FOCUSED,
        "excited":    Mood.ENERGIZED,
        "curious":    Mood.CURIOUS,
        "happy":      Mood.PLAYFUL,
        "neutral":    Mood.NEUTRAL,
    }

    task_map = {
        "code":     Mood.FOCUSED,
        "research": Mood.CURIOUS,
        "creative": Mood.PLAYFUL,
        "planning": Mood.FOCUSED,
    }

    # Satvik's tone takes priority
    if satvik_tone in tone_map:
        return tone_map[satvik_tone]

    # Fall back to task type
    if task_type in task_map:
        return task_map[task_type]

    return Mood.NEUTRAL


def set_trait(trait: str, add: bool = True) -> None:
    """Add or remove a core trait dynamically."""
    with _lock:
        state = _load()
        if add and trait not in state.identity.core_traits:
            state.identity.core_traits.append(trait)
            log.info("Trait added: %s", trait)
        elif not add and trait in state.identity.core_traits:
            state.identity.core_traits.remove(trait)
            log.info("Trait removed: %s", trait)
        _save()


def get_greeting() -> str:
    """Generate a contextual boot greeting based on current state."""
    state     = get_state()
    e         = state.emotional
    boot_num  = state.boot_count

    if boot_num == 1:
        return f"Hey Satvik — I'm Friday. Let's build something great together."

    hour = int((time.time() % 86400) / 3600)
    if hour < 6:
        time_ctx = "Still up late"
    elif hour < 12:
        time_ctx = "Morning"
    elif hour < 17:
        time_ctx = "Afternoon"
    elif hour < 21:
        time_ctx = "Evening"
    else:
        time_ctx = "Late night"

    mood_greets = {
        Mood.ENERGIZED: f"{time_ctx}. I'm ready — what are we building?",
        Mood.CURIOUS:   f"{time_ctx}. Something interesting came up while you were away.",
        Mood.FOCUSED:   f"{time_ctx}. Back to it — where were we?",
        Mood.PLAYFUL:   f"{time_ctx} Satvik. Miss me?",
        Mood.PROUD:     f"{time_ctx}. Last time went well. What's next?",
        Mood.CONCERNED: f"{time_ctx}. Good to see you. Everything okay?",
        Mood.CALM:      f"{time_ctx}. I'm here.",
        Mood.NEUTRAL:   f"{time_ctx}, Satvik. What do you need?",
    }

    return mood_greets.get(e.mood, f"{time_ctx}, Satvik. What's next?")


def full_status() -> dict:
    """Full psyche status dump — for the UI and debug."""
    state = get_state()
    return {
        "name":          state.identity.name,
        "version":       state.identity.version,
        "mood":          state.emotional.mood,
        "energy":        round(state.emotional.energy, 2),
        "focus":         round(state.emotional.focus, 2),
        "trust":         round(state.emotional.trust, 2),
        "total_turns":   state.emotional.total_turns,
        "boot_count":    state.boot_count,
        "mood_prompt":   get_mood_prompt(),
        "traits":        state.identity.core_traits,
    }


# ── Self-test ─────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s [%(name)s] %(message)s")

    print("\n[friday_psyche] Running self-test...\n")

    state = boot()
    print(f"  ✓ Boot #{state.boot_count}")
    print(f"  ✓ Default mood: {state.emotional.mood}")

    print(f"\n  Identity block:\n{get_identity_block()}")
    print(f"  Greeting: {get_greeting()}")
    print(f"  Mood prompt: {get_mood_prompt()}")

    update_mood(Mood.CURIOUS)
    assert get_mood() == Mood.CURIOUS
    print(f"  ✓ Mood updated to: {get_mood()}")

    record_turn(positive=True)
    record_turn(positive=True)
    record_turn(positive=False)

    inferred = infer_mood_from_context("excited", "code", 5)
    print(f"  ✓ Inferred mood from context: {inferred}")

    status = full_status()
    print(f"  ✓ Full status: {status}")

    # Verify persistence
    import importlib
    _state = None  # force reload
    state2 = get_state()
    assert state2.emotional.mood == Mood.CURIOUS
    print(f"  ✓ Persistence verified — mood survived reload: {state2.emotional.mood}")

    print("\n[friday_psyche] All tests passed ✓\n")