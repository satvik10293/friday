"""
core/audio/listener/events.py — FRIDAY 4.0 (M12.1)
The auditory event vocabulary + a lightweight bus. Listening is expressed as a
stream of events (speech detected, wake word, command boundaries, silence, speaker
change, noise, language/emotion changes, transcript ready, interruptions). These are
the seam into the M11 agent society and M10 Mission Control.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Optional


class AudioEvent(str, Enum):
    LISTENING_STATE_CHANGED = "listening.state_changed"
    SPEECH_DETECTED = "speech.detected"
    SILENCE_DETECTED = "silence.detected"
    NOISE_DETECTED = "noise.detected"
    WAKE_WORD_DETECTED = "wake_word.detected"
    COMMAND_STARTED = "command.started"
    COMMAND_FINISHED = "command.finished"
    TRANSCRIPT_READY = "transcript.ready"
    SPEAKER_CHANGED = "speaker.changed"
    LANGUAGE_CHANGED = "language.changed"
    EMOTION_DETECTED = "emotion.detected"
    INTERRUPT_REQUESTED = "interrupt.requested"


@dataclass
class Event:
    kind: str
    data: dict = field(default_factory=dict)
    ts: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {"kind": self.kind, "data": self.data, "ts": self.ts}


class AudioEventBus:
    """Synchronous, thread-safe pub/sub with a bounded history. Sync by design so
    the real-time audio loop is never blocked by async scheduling."""

    def __init__(self, history: int = 500) -> None:
        self._subs: dict[str, list[Callable[[Event], None]]] = {}
        self._any: list[Callable[[Event], None]] = []
        self._history: deque = deque(maxlen=history)
        self._lock = threading.Lock()

    def on(self, kind, handler: Callable[[Event], None]) -> None:
        key = kind.value if isinstance(kind, AudioEvent) else str(kind)
        with self._lock:
            self._subs.setdefault(key, []).append(handler)

    def on_any(self, handler: Callable[[Event], None]) -> None:
        with self._lock:
            self._any.append(handler)

    def emit(self, kind, data: Optional[dict] = None) -> Event:
        key = kind.value if isinstance(kind, AudioEvent) else str(kind)
        ev = Event(kind=key, data=data or {})
        with self._lock:
            handlers = list(self._subs.get(key, [])) + list(self._any)
            self._history.append(ev)
        for h in handlers:
            try:
                h(ev)
            except Exception:  # noqa: BLE001 — a bad subscriber never breaks listening
                pass
        return ev

    def recent(self, limit: int = 50, *, kind: Optional[str] = None) -> list[dict]:
        with self._lock:
            items = list(self._history)
        if kind:
            items = [e for e in items if e.kind == kind]
        return [e.to_dict() for e in items[-limit:][::-1]]

    def __len__(self) -> int:
        return len(self._history)
