"""
M59 sweep, module 3 (core/audio/listener): hearing survives device loss.

Before the fix, `mic.read()` sat OUTSIDE the try in the listener loop: a mic
exception (USB unplug, default-device switch) escaped, killed the daemon
thread, and she went permanently — and silently — deaf. `_read_frame_safe`
pins the new contract: exceptions never escape, reopen is attempted, and
recovery resets the failure counter.
"""

from __future__ import annotations

from core.audio.listener.pipeline import ListeningPipeline


class _FlakyMic:
    """Raises for the first N reads (device gone), then serves frames."""

    def __init__(self, failures):
        self.failures = failures
        self.reads = 0
        self.reopens = 0
        self.is_open = True

    def read(self):
        self.reads += 1
        if self.reads <= self.failures:
            raise OSError("device unavailable")
        return b"frame"

    def open(self):
        self.reopens += 1


def _pipeline(mic):
    p = ListeningPipeline.__new__(ListeningPipeline)   # lifecycle-only surface
    p.mic = mic
    p._mic_failures = 0
    return p


def test_device_loss_never_escapes_and_recovery_is_counted(monkeypatch):
    import core.audio.listener.pipeline as mod
    monkeypatch.setattr(mod.time, "sleep", lambda s: None)   # no real backoff
    mic = _FlakyMic(failures=3)
    p = _pipeline(mic)
    assert p._read_frame_safe() is None      # outage: swallowed, not raised
    assert p._read_frame_safe() is None
    assert p._read_frame_safe() is None
    assert p._mic_failures == 3
    assert p._read_frame_safe() == b"frame"  # device back → frames flow again
    assert p._mic_failures == 0              # recovery resets the counter


def test_reopen_is_attempted_during_a_long_outage(monkeypatch):
    import core.audio.listener.pipeline as mod
    monkeypatch.setattr(mod.time, "sleep", lambda s: None)
    mic = _FlakyMic(failures=25)
    p = _pipeline(mic)
    for _ in range(20):
        assert p._read_frame_safe() is None  # 20 straight failures, no crash
    assert mic.reopens == 2                  # reopen tried every ~10 failures
