"""
core/io/orb/events.py — FRIDAY V3 (M20 revision: Orb UI)

The Orb's event vocabulary on the **Runtime Event Bus** (the shared `Signal` taxonomy). This
is the ONLY channel between FRIDAY's cognition and the Orb UI — the orb never imports the
Executive Brain, Memory, or any cognitive module, and contains no AI logic.

Two groups of signals reach the Orb Controller:

  1. Existing FRIDAY *expression* signals it simply reflects — `SPEAK_START`, `SPEAK_DONE`,
     `THINKING_START`, `THINKING_DONE`, `WAKE_WORD`, `MOOD_UPDATED`. This is why the orb
     shows real cognition without any new wiring in the brain.
  2. Orb-specific signals (added to the taxonomy, M20 revision) for things the expression
     signals don't carry — real audio amplitude, speech text, notifications, mode, and the
     dashboard. And the inbound interaction signals the orb emits back to FRIDAY.

Import is side-effect free.
"""

from __future__ import annotations

from core.infra.friday_signal import Signal

# ── FRIDAY -> Orb (controller subscribes) ─────────────────────────────────────────
ORB_STATE = Signal.ORB_STATE
ORB_EMOTION = Signal.ORB_EMOTION
ORB_SPEECH_SHOW = Signal.ORB_SPEECH_SHOW
ORB_SPEECH_HIDE = Signal.ORB_SPEECH_HIDE
ORB_AMPLITUDE = Signal.ORB_AMPLITUDE
ORB_NOTIFY = Signal.ORB_NOTIFY
ORB_DASHBOARD_OPEN = Signal.ORB_DASHBOARD_OPEN
ORB_DASHBOARD_CLOSE = Signal.ORB_DASHBOARD_CLOSE
ORB_MODE = Signal.ORB_MODE

# ── Orb -> FRIDAY (controller emits from user interactions) ───────────────────────
ORB_WAKE = Signal.ORB_WAKE
ORB_DASHBOARD_TOGGLE = Signal.ORB_DASHBOARD_TOGGLE
ORB_COMMAND = Signal.ORB_COMMAND
ORB_MODE_SET = Signal.ORB_MODE_SET

# ── Existing expression signals the orb reflects (state only) ─────────────────────
# signal -> (orb state to enter, whether it also toggles the speech panel)
EXPRESSION_TO_STATE = {
    Signal.WAKE_WORD:      ("listening", False),
    Signal.USER_VOICE:     ("listening", False),
    Signal.THINKING_START: ("thinking", False),
    Signal.THINKING_DONE:  ("idle", False),      # unless speech follows immediately
    Signal.SPEAK_START:    ("speaking", True),   # data may carry the spoken text
    Signal.SPEAK_DONE:     ("idle", True),        # hide the panel, return to idle
}

# all inbound expression signals the controller subscribes to
REFLECTED_SIGNALS = tuple(EXPRESSION_TO_STATE.keys()) + (Signal.MOOD_UPDATED,)

# mood (psyche) -> orb emotion overlay
MOOD_TO_EMOTION = {
    "happy": "happy", "playful": "happy", "excited": "happy",
    "curious": "curious", "focused": "focused", "study": "focused",
    "concerned": "concerned", "sad": "concerned", "neutral": "neutral",
}

# notification kind -> orb reaction (glow colour + brief state), per the directive:
#   new message -> blue glow, reminder -> purple pulse, warning -> amber, error -> red.
NOTIFY_REACTION = {
    "message":  {"glow": "#4f80ff", "state": "happy"},
    "reminder": {"glow": "#a78bfa", "state": "thinking"},
    "warning":  {"glow": "#fbbf24", "state": "warning"},
    "error":    {"glow": "#f87171", "state": "error"},
}
