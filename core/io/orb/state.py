"""
core/io/orb/state.py — FRIDAY V3 (M20 revision: Orb UI)

The Orb's data model: its animation states, emotional overlays, interaction mode
(voice/text), and the persisted window settings (position, monitor, size, opacity, mode).
Pure data + validation + persistence — no UI, no cognition, side-effect free to import.

The full per-state *shader* parameters (colours, vibration, pulse, spin…) live with the
renderer in `ui/orb.js` (ported faithfully from the provided `stateConfig.ts`); Python only
needs the canonical state list, labels, CSS accent colours, and the mode/settings model.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional

log = logging.getLogger("friday.orb.state")


class OrbState(str, Enum):
    IDLE = "idle"
    LISTENING = "listening"
    THINKING = "thinking"
    SPEAKING = "speaking"
    HAPPY = "happy"
    WARNING = "warning"
    ERROR = "error"
    OFFLINE = "offline"
    SLEEPING = "sleeping"


class Emotion(str, Enum):
    NEUTRAL = "neutral"
    HAPPY = "happy"
    CURIOUS = "curious"
    CONCERNED = "concerned"
    FOCUSED = "focused"


class InteractionMode(str, Enum):
    VOICE = "voice"
    TEXT = "text"


VALID_STATES = frozenset(s.value for s in OrbState)
VALID_EMOTIONS = frozenset(e.value for e in Emotion)
VALID_MODES = frozenset(m.value for m in InteractionMode)

# Canonical labels + accent colours (mirrors ui/orb.js STATE_CONFIG; used for badges,
# notifications, diagnostics). Kept minimal on the Python side.
STATE_LABELS = {
    "idle": "Idle", "listening": "Listening", "thinking": "Thinking", "speaking": "Speaking",
    "happy": "Happy", "warning": "Warning", "error": "Error", "offline": "Offline",
    "sleeping": "Sleeping",
}
STATE_ACCENT = {
    "idle": "#4f80ff", "listening": "#22d3ee", "thinking": "#a78bfa", "speaking": "#34d399",
    "happy": "#60a5fa", "warning": "#fbbf24", "error": "#f87171", "offline": "#4b5563",
    "sleeping": "#334155",
}

# FRIDAY's runtime voice-state vocabulary (core/io/friday_face) -> orb state.
VOICE_STATE_TO_ORB = {
    "idle": "idle", "hearing": "listening", "listening": "listening",
    "thinking": "thinking", "speaking": "speaking",
}


def coerce_state(value: str, *, default: str = "idle") -> str:
    """Map an arbitrary state/voice-state string onto a valid orb state (never raises)."""
    v = str(value or "").lower()
    if v in VALID_STATES:
        return v
    return VOICE_STATE_TO_ORB.get(v, default)


def coerce_amplitude(value) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return 0.0


@dataclass
class OrbSettings:
    """Persisted orb window settings. Restored on startup so the orb reappears exactly
    where the user left it."""
    x: Optional[int] = None
    y: Optional[int] = None
    monitor: int = 0
    width: int = 340
    height: int = 340
    opacity: float = 1.0
    mode: str = InteractionMode.VOICE.value          # default interaction mode: VOICE
    always_on_top: bool = True

    def sanitized(self) -> "OrbSettings":
        self.mode = self.mode if self.mode in VALID_MODES else InteractionMode.VOICE.value
        self.opacity = max(0.15, min(1.0, float(self.opacity or 1.0)))
        self.width = max(120, int(self.width or 340))
        self.height = max(120, int(self.height or 340))
        self.monitor = int(self.monitor or 0)
        return self

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Optional[dict]) -> "OrbSettings":
        data = data or {}
        known = {f: data[f] for f in cls.__dataclass_fields__ if f in data}  # type: ignore[attr-defined]
        return cls(**known).sanitized()


class SettingsStore:
    """Loads/saves OrbSettings as JSON. Never raises — persistence is best-effort."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    def load(self) -> OrbSettings:
        try:
            if self.path.exists():
                return OrbSettings.from_dict(json.loads(self.path.read_text(encoding="utf-8")))
        except (OSError, ValueError) as e:
            log.warning("[Orb] could not read settings (%s); using defaults", e)
        return OrbSettings()

    def save(self, settings: OrbSettings) -> bool:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(settings.sanitized().to_dict(), indent=2),
                                 encoding="utf-8")
            return True
        except OSError as e:
            log.warning("[Orb] could not save settings (%s)", e)
            return False
