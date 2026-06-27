"""M12.1 — microphone sources + rolling audio buffer."""

import numpy as np
import pytest

from core.audio.listener.audio_buffer import RollingBuffer
from core.audio.listener.microphone import (ArraySource, FRAME_SIZE, MicrophoneSource,
                                            SAMPLE_RATE, noise, silence, tone)


# ── microphone ─────────────────────────────────────────────────────────────────────
def test_array_source_yields_frames():
    src = ArraySource(tone(0.1))      # 0.1s → 5 frames of 20ms
    src.open()
    frames = []
    while True:
        f = src.read()
        if f is None:
            break
        frames.append(f)
    assert all(len(f) == FRAME_SIZE for f in frames)
    assert len(frames) == int(0.1 * SAMPLE_RATE) // FRAME_SIZE


def test_array_source_exhausts():
    src = ArraySource(tone(0.04))     # exactly 2 frames
    assert src.read() is not None
    assert src.read() is not None
    assert src.read() is None


def test_privacy_disable_returns_silence():
    src = ArraySource(tone(0.1, amplitude=0.5))
    src.disable()
    f = src.read()
    assert f is not None and np.allclose(f, 0.0)   # silence, never blocks
    assert not src.enabled
    src.enable()
    assert src.enabled


def test_feed_appends():
    src = ArraySource()
    src.feed(tone(0.04))
    assert src.remaining_frames == 2


def test_status():
    src = ArraySource()
    src.open()
    st = src.status()
    assert st["open"] and st["enabled"] and st["sample_rate"] == SAMPLE_RATE


# ── rolling buffer ─────────────────────────────────────────────────────────────────
def test_buffer_holds_recent():
    buf = RollingBuffer(seconds=0.1)   # ~5 frames
    for _ in range(20):
        buf.append(np.ones(FRAME_SIZE, dtype=np.float32))
    assert buf.frames_held == buf.capacity_frames   # bounded
    assert buf.seconds_held <= 0.12


def test_buffer_snapshot_order():
    buf = RollingBuffer(seconds=1.0)
    buf.append(np.zeros(FRAME_SIZE, dtype=np.float32))
    buf.append(np.ones(FRAME_SIZE, dtype=np.float32))
    snap = buf.snapshot()
    assert len(snap) == 2 * FRAME_SIZE
    assert snap[-1] == 1.0 and snap[0] == 0.0       # newest last


def test_buffer_preroll_recovers_clipped_speech():
    buf = RollingBuffer(seconds=1.0)
    for i in range(10):
        buf.append(np.full(FRAME_SIZE, i, dtype=np.float32))
    pre = buf.preroll_frames(3)
    assert len(pre) == 3 and pre[-1][0] == 9.0       # the 3 most recent frames


def test_buffer_clear():
    buf = RollingBuffer(seconds=1.0)
    buf.append(np.ones(FRAME_SIZE, dtype=np.float32))
    buf.clear()
    assert buf.frames_held == 0 and len(buf.snapshot()) == 0


def test_buffer_bounded_memory_long_run():
    buf = RollingBuffer(seconds=0.2)
    for _ in range(5000):             # simulate a long runtime
        buf.append(np.zeros(FRAME_SIZE, dtype=np.float32))
    assert buf.frames_held <= buf.capacity_frames    # constant memory
