"""M15 — Audio Event Detection: features, profile detectors, engine windowing,
confidence gate, per-type cooldown, disabling, and extensibility (new sounds as data)."""

import numpy as np
import pytest

from core.audio.cognition.config import EventDetectionConfig
from core.audio.cognition.engine import AudioEventEngine
from core.audio.cognition.events import SoundCategory, SoundType, default_catalog
from core.audio.cognition.features import extract_features
from core.audio.cognition.profiles import register_profile
from core.audio.cognition.detector_base import ProfileDetector, FeatureProfile

SR = 16000


def tone(f, sec=0.6, amp=0.3):
    t = np.arange(int(sec * SR)) / SR
    return (amp * np.sin(2 * np.pi * f * t)).astype(np.float32)


def noise(sec=0.6, amp=0.3, seed=0):
    return (amp * np.random.default_rng(seed).standard_normal(int(sec * SR))).astype(np.float32)


# ── features ─────────────────────────────────────────────────────────────────────────
def test_features_tonal_vs_noisy():
    tonal = extract_features(tone(440))
    noisy = extract_features(noise(seed=2))
    assert tonal.flatness < noisy.flatness          # tone is far more tonal
    assert tonal.harmonicity > noisy.harmonicity
    assert 300 < tonal.pitch < 600                  # dominant pitch ≈ 440 Hz


def test_features_centroid_tracks_brightness():
    low = extract_features(tone(200))
    high = extract_features(tone(4000))
    assert high.centroid > low.centroid


def test_silence_has_no_energy():
    f = extract_features(np.zeros(int(0.6 * SR), dtype=np.float32))
    assert f.rms == 0.0


# ── engine detection ──────────────────────────────────────────────────────────────────
def test_silence_detects_nothing():
    eng = AudioEventEngine(EventDetectionConfig(min_confidence=0.4))
    assert eng.analyze(np.zeros(int(0.6 * SR), dtype=np.float32)) is None


def test_tone_detects_a_tonal_sound():
    eng = AudioEventEngine(EventDetectionConfig(min_confidence=0.45, per_type_cooldown_s=0.0))
    ev = eng.analyze(tone(700))
    assert ev is not None and ev.confidence >= 0.45
    # a pure tone is harmonic → a tonal class (alert chime / animal / human), never broadband
    assert ev.category in (SoundCategory.ALERT.value, SoundCategory.ANIMAL.value,
                           SoundCategory.HUMAN.value)


def test_broadband_detects_a_noisy_sound():
    eng = AudioEventEngine(EventDetectionConfig(min_confidence=0.45, per_type_cooldown_s=0.0))
    ev = eng.analyze(noise(seed=5))
    assert ev is not None
    assert ev.sound in ("glass_breaking", "running_water", "keyboard_typing")


def test_per_type_cooldown_debounces():
    eng = AudioEventEngine(EventDetectionConfig(min_confidence=0.45, per_type_cooldown_s=2.0))
    first = eng.analyze(tone(700), ts=100.0)
    assert first is not None
    # same sound 0.5 s later → suppressed by cooldown
    again = eng.analyze(tone(700), ts=100.5)
    assert again is None
    # after the cooldown → allowed again
    later = eng.analyze(tone(700), ts=103.0)
    assert later is not None


def test_disabled_sound_not_reported():
    cfg = EventDetectionConfig(min_confidence=0.4, per_type_cooldown_s=0.0,
                               disabled_sounds=["glass_breaking", "running_water",
                                                "keyboard_typing", "mouse_clicking"])
    eng = AudioEventEngine(cfg)
    ev = eng.analyze(noise(seed=7))
    assert ev is None or ev.sound not in cfg.disabled_sounds


def test_frame_driven_windowing():
    eng = AudioEventEngine(EventDetectionConfig(window_s=0.4, hop_s=0.4,
                                                min_confidence=0.45, per_type_cooldown_s=0.0))
    sig = tone(700, sec=0.6)
    detections = []
    for i in range(0, sig.size, 320):
        ev = eng.process_frame(sig[i:i + 320])
        if ev is not None:
            detections.append(ev)
    assert eng.metrics()["windows"] >= 1


# ── extensibility (new sound = data, no core change) ────────────────────────────────
def test_register_new_sound_profile():
    catalog = default_catalog()
    detector = register_profile(
        catalog, SoundType("whistle", SoundCategory.HUMAN, "Whistle"),
        {"harmonicity": (0.5, None, 2.0), "pitch": (1000, 3000, 2.0)})
    assert "whistle" in catalog
    eng = AudioEventEngine(EventDetectionConfig(min_confidence=0.4, per_type_cooldown_s=0.0),
                           catalog=catalog, detectors=[detector])
    ev = eng.analyze(tone(2000))
    assert ev is not None and ev.sound == "whistle"


def test_detector_never_raises_on_bad_features():
    det = ProfileDetector("x", "ambient", FeatureProfile({"pitch": (1, 2, 1)}))
    # feed a degenerate window; score must be a float in [0,1], never an exception
    score = det.score(extract_features(np.zeros(10, dtype=np.float32)))
    assert 0.0 <= score <= 1.0


def test_catalog_has_all_milestone_sounds():
    names = set(default_catalog().names())
    for s in ("door_knock", "doorbell", "alarm", "timer", "phone_ringing",
              "keyboard_typing", "mouse_clicking", "laughter", "crying",
              "glass_breaking", "running_water", "dog_barking", "cat_meowing"):
        assert s in names
