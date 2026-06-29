"""
core/audio/cognition/events.py — FRIDAY V3 (M15)
The auditory-event vocabulary and data model for environmental sound cognition.

Sound *types* live in an open registry (`SoundCatalog`), not a closed enum, so new
sounds are added by registering a `SoundType` — never by editing core logic. Each
sound declares a category (used for attention priorities and context reasoning) and a
human-readable description. `AuditoryEvent` is the structured detection that flows from
the detection engine through context reasoning, memory, and attention.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class SoundCategory(str, Enum):
    """Coarse grouping that drives attention priority + reasoning."""
    EMERGENCY = "emergency"          # glass breaking, alarm, crying — always salient
    ALERT = "alert"                  # doorbell, knock, phone, timer — needs a response
    HUMAN = "human"                  # laughter, crying (also emergency), non-speech vocal
    ACTIVITY = "activity"            # keyboard, mouse, running water — ambient user activity
    ANIMAL = "animal"                # dog bark, cat meow
    AMBIENT = "ambient"              # generic background


@dataclass(frozen=True)
class SoundType:
    """A registrable kind of environmental sound."""
    name: str                        # stable id, e.g. "doorbell"
    category: SoundCategory
    label: str                       # human label, e.g. "Doorbell"
    description: str = ""

    def to_dict(self) -> dict:
        return {"name": self.name, "category": self.category.value,
                "label": self.label, "description": self.description}


class SoundCatalog:
    """Open registry of sound types. Adding a sound = `register(SoundType(...))`."""

    def __init__(self) -> None:
        self._by_name: dict[str, SoundType] = {}

    def register(self, sound: SoundType) -> SoundType:
        self._by_name[sound.name] = sound
        return sound

    def get(self, name: str) -> Optional[SoundType]:
        return self._by_name.get(name)

    def names(self) -> list[str]:
        return sorted(self._by_name)

    def all(self) -> list[SoundType]:
        return list(self._by_name.values())

    def category_of(self, name: str) -> SoundCategory:
        s = self._by_name.get(name)
        return s.category if s else SoundCategory.AMBIENT

    def __contains__(self, name: str) -> bool:
        return name in self._by_name


# ── the built-in catalog (extend via catalog.register(...)) ─────────────────────────
def default_catalog() -> SoundCatalog:
    c = SoundCatalog()
    for s in (
        SoundType("door_knock", SoundCategory.ALERT, "Door knock",
                  "Repeated low-frequency impacts on a door."),
        SoundType("doorbell", SoundCategory.ALERT, "Doorbell",
                  "A tonal chime, often two-tone."),
        SoundType("alarm", SoundCategory.EMERGENCY, "Alarm",
                  "A loud repetitive high-pitched alert."),
        SoundType("timer", SoundCategory.ALERT, "Timer",
                  "A regular periodic beep — a timer/oven finishing."),
        SoundType("phone_ringing", SoundCategory.ALERT, "Phone ringing",
                  "A periodic ringtone cadence."),
        SoundType("keyboard_typing", SoundCategory.ACTIVITY, "Keyboard typing",
                  "Rapid irregular broadband key clicks."),
        SoundType("mouse_clicking", SoundCategory.ACTIVITY, "Mouse clicking",
                  "Isolated sharp transient clicks."),
        SoundType("laughter", SoundCategory.HUMAN, "Laughter",
                  "Voiced, strongly amplitude-modulated human laughter."),
        SoundType("crying", SoundCategory.EMERGENCY, "Crying",
                  "Sustained high-pitch voiced human distress."),
        SoundType("glass_breaking", SoundCategory.EMERGENCY, "Glass breaking",
                  "A bright broadband shatter transient."),
        SoundType("running_water", SoundCategory.ACTIVITY, "Running water",
                  "Sustained broadband water noise."),
        SoundType("dog_barking", SoundCategory.ANIMAL, "Dog barking",
                  "Short harmonic mid-pitch bursts."),
        SoundType("cat_meowing", SoundCategory.ANIMAL, "Cat meowing",
                  "A tonal harmonic glide."),
    ):
        c.register(s)
    return c


def new_event_id() -> str:
    return "AUD_" + uuid.uuid4().hex[:12]


@dataclass
class AuditoryEvent:
    """One detected environmental sound, with provenance for memory + reasoning."""
    sound: str                       # SoundType.name
    category: str                    # SoundCategory value
    confidence: float
    timestamp: float = field(default_factory=time.time)
    source: Optional[str] = None     # optional spatial/source hint (mic id, direction)
    session_id: str = ""
    features: dict = field(default_factory=dict)     # the salient features that fired it
    event_id: str = field(default_factory=new_event_id)

    def to_dict(self) -> dict:
        return {"event_id": self.event_id, "sound": self.sound, "category": self.category,
                "confidence": round(float(self.confidence), 4), "timestamp": self.timestamp,
                "source": self.source, "session_id": self.session_id,
                "features": self.features}


# Runtime-bus event keys (str so they are first-class on the M1 bus, like the
# vision/perception events). Mission Control + downstream subscribe here.
class AudioCognitionEvent(str, Enum):
    SOUND_DETECTED = "audio.sound.detected"
    SOUND_CONTEXT = "audio.sound.context"
    WAKE_DETECTED = "audio.wake.detected"
    WAKE_SUPPRESSED = "audio.wake.suppressed"
    SPEECH_DUPLICATE = "audio.speech.duplicate"
    EMERGENCY = "audio.emergency"
