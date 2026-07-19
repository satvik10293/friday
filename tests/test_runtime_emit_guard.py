"""
M59 sweep, module 2 (core/runtime): emit() must be safe on a runtime that was
never started (or already stopped).

Every headless/driver boot constructs the Runtime without starting its loop;
components still fire events (goals, knowledge, nervous relay). Before the
guard, each of those emits created a coroutine no loop would ever schedule —
'RuntimeWarning: coroutine AsyncEventBus.emit was never awaited' leaked into
every run, and a stopped loop could raise into fire-and-forget callers.
"""

from __future__ import annotations

import warnings

from core.runtime.runtime import Runtime
from core.runtime.bus import Signal


def _any_signal():
    return next(iter(Signal))


def test_emit_on_unstarted_runtime_is_clean_and_silent():
    rt = Runtime()                          # constructed, never started
    with warnings.catch_warnings():
        warnings.simplefilter("error", RuntimeWarning)   # a leak = a failure
        fut = rt.emit(_any_signal(), data={"x": 1}, source="test")
    assert fut.done() and fut.result() is None            # fire-and-forget OK


def test_emit_never_raises_into_callers():
    rt = Runtime()
    for _ in range(3):
        assert rt.emit(_any_signal()).done()              # repeatable, quiet
