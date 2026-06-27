"""M12.1 — VAD, noise suppression, speech detector, silence detector."""

import numpy as np

from core.audio.listener.microphone import FRAME_SIZE, noise, silence, tone
from core.audio.listener.silence_detector import SilenceDetector, SilenceState
from core.audio.listener.speech_detector import SpeechDetector
from core.audio.listener.vad import (AudioClass, NoiseSuppressor,
                                     VoiceActivityDetector, rms, zero_crossing_rate)


def _frame(wav, i=0):
    return wav[i * FRAME_SIZE:(i + 1) * FRAME_SIZE]


# ── primitives ─────────────────────────────────────────────────────────────────────
def test_rms_and_zcr():
    assert rms(silence(0.02)) == 0.0
    assert rms(tone(0.02, amplitude=0.5)) > 0.0
    assert 0.0 <= zero_crossing_rate(tone(0.02, 300)) <= 1.0


# ── VAD ────────────────────────────────────────────────────────────────────────────
def test_silence_classified():
    vad = VoiceActivityDetector()
    cls, _ = vad.classify(silence(0.02))
    assert cls == AudioClass.SILENCE.value


def test_speech_classified():
    vad = VoiceActivityDetector()
    # warm up the noise floor on silence, then a voiced tone
    for _ in range(5):
        vad.classify(silence(0.02))
    cls, conf = vad.classify(tone(0.02, 300, 0.3))
    assert cls == AudioClass.SPEECH.value and conf > 0


def test_loud_noise_not_speech():
    vad = VoiceActivityDetector()
    for _ in range(5):
        vad.classify(silence(0.02))
    cls, _ = vad.classify(noise(0.02, amplitude=0.4))
    assert cls != AudioClass.SPEECH.value      # broadband noise is ignored as speech


def test_noise_floor_adapts():
    vad = VoiceActivityDetector(min_floor=1.0)   # absurdly high floor
    for _ in range(50):
        vad.classify(silence(0.02))
    assert vad.noise_floor < 1.0                 # adapted downward


# ── noise suppressor ───────────────────────────────────────────────────────────────
def test_suppressor_preserves_length():
    ns = NoiseSuppressor()
    out = ns.process(tone(0.02, 300, 0.3))
    assert len(out) == FRAME_SIZE


def test_suppressor_attenuates_low_noise():
    ns = NoiseSuppressor()
    ns.noise_floor = 0.05
    quiet = noise(0.02, amplitude=0.01)
    out = ns.process(quiet)
    assert rms(out) <= rms(quiet) + 1e-6         # near-floor frames attenuated


# ── speech detector (hysteresis) ───────────────────────────────────────────────────
def test_speech_detector_hysteresis():
    det = SpeechDetector(start_frames=2, end_frames=4)
    voiced = tone(0.02, 300, 0.3)
    quiet = silence(0.02)
    # warm floor
    for _ in range(3):
        det.process(quiet)
    a1, _, _ = det.process(voiced)
    a2, _, _ = det.process(voiced)
    assert a2 is True            # became active after start_frames
    for _ in range(4):
        det.process(quiet)
    assert det.active is False   # ended after end_frames of silence


# ── silence detector ───────────────────────────────────────────────────────────────
def test_silence_detector_pause_then_long():
    sd = SilenceDetector(pause_ms=40, long_pause_ms=120)   # 2 / 6 frames
    assert sd.update(True) == SilenceState.NONE
    sd.update(False)
    assert sd.update(False) == SilenceState.PAUSE          # 2 silent frames
    for _ in range(4):
        last = sd.update(False)
    assert last == SilenceState.LONG_PAUSE
    assert sd.update(True) == SilenceState.NONE            # speech resets
