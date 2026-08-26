"""
core/reasoning/activity.py — the request beacon.

A tiny, process-global signal for "a user turn is being handled right now."
Pure stdlib and dependency-free on purpose, so the live turn path can import it
with no cost and no import cycle.

Why it exists: the neural core trains in the background forever, in bursts that
can run tens of seconds of CPU. On a CPU-only box that can contend with the live
voice/answer path. The trainer consults this beacon to (a) not START a cycle
while a turn is in flight and (b) YIELD a burst already running the moment a turn
arrives — so cognition always defers to the person in front of her.

The turn path marks activity via `request_active()` (or begin/end); the trainer
reads it via `is_busy()`. Nothing here reaches back into the trainer, so there is
no coupling in that direction.
"""

from __future__ import annotations

import threading
import time

_lock = threading.Lock()
_inflight = 0            # turns currently being handled (a counter — nesting-safe)
_last_active = 0.0       # monotonic time the last turn finished


def begin_request() -> None:
    """Mark that a user turn has started being handled."""
    global _inflight
    with _lock:
        _inflight += 1


def end_request() -> None:
    """Mark that a user turn has finished; stamp the time for the idle grace."""
    global _inflight, _last_active
    with _lock:
        _inflight = max(0, _inflight - 1)
        _last_active = time.monotonic()


class request_active:
    """Context manager around a single turn: `with request_active(): ...`.
    Counter-based, so nested/overlapping turns are handled correctly."""

    def __enter__(self) -> "request_active":
        begin_request()
        return self

    def __exit__(self, *exc) -> bool:
        end_request()
        return False        # never swallow the turn's exceptions


def is_busy(idle_grace: float = 1.5) -> bool:
    """True if a turn is in flight, or one finished within `idle_grace` seconds.

    The grace window keeps a training burst from starting in the small gaps
    between rapid back-and-forth turns (where the person is still interacting)."""
    with _lock:
        if _inflight > 0:
            return True
        return (time.monotonic() - _last_active) < idle_grace
