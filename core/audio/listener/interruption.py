"""
core/audio/listener/interruption.py — FRIDAY 4.0 (M12.1)
Interruption / barge-in control. Lets the user interrupt FRIDAY while she's speaking,
lets FRIDAY interrupt herself, cancels the current response, resumes, and supports
nested conversations — all without blocking the listening loop (flag/stack based).
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ConversationFrame:
    topic: str
    started_at: float = field(default_factory=time.time)


class InterruptionController:
    def __init__(self) -> None:
        self._speaking = False
        self._interrupt = threading.Event()
        self._stack: list[ConversationFrame] = []
        self._lock = threading.Lock()
        self.last_source = ""

    # ── speaking state ──────────────────────────────────────────────────────────
    def begin_speaking(self) -> None:
        self._speaking = True
        self._interrupt.clear()

    def end_speaking(self) -> None:
        self._speaking = False
        self._interrupt.clear()

    @property
    def speaking(self) -> bool:
        return self._speaking

    # ── interruption ────────────────────────────────────────────────────────────
    def request_interrupt(self, source: str = "user") -> bool:
        """Request a barge-in. Returns True if FRIDAY was speaking (i.e. it matters)."""
        self.last_source = source
        was = self._speaking
        if was:
            self._interrupt.set()
        return was

    def user_interrupt(self) -> bool:
        return self.request_interrupt("user")

    def self_interrupt(self) -> bool:
        return self.request_interrupt("self")

    def should_stop(self) -> bool:
        """The response generator polls this to cancel without blocking."""
        return self._interrupt.is_set()

    def cancel(self) -> None:
        self._interrupt.set()
        self._speaking = False

    def resume(self) -> None:
        self._interrupt.clear()

    # ── nested conversations ────────────────────────────────────────────────────
    def push_context(self, topic: str) -> None:
        with self._lock:
            self._stack.append(ConversationFrame(topic=topic))

    def pop_context(self) -> Optional[ConversationFrame]:
        with self._lock:
            return self._stack.pop() if self._stack else None

    @property
    def depth(self) -> int:
        return len(self._stack)

    def status(self) -> dict:
        return {"speaking": self._speaking, "interrupt_pending": self._interrupt.is_set(),
                "nested_depth": self.depth, "last_source": self.last_source}
