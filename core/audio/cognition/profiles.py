"""
core/audio/cognition/profiles.py — FRIDAY V3 (M15)
The built-in environmental-sound profiles. Each entry is *data* — a feature profile for
one sound class — so adding a new sound means appending a profile here (or registering
one at runtime), never editing the detection engine. Profiles encode the classical
acoustic signatures that separate the M15 classes (tonal vs broadband, harmonic vs
inharmonic, pitch, brightness, transient/onset structure, amplitude modulation).

These are deliberately broad, soft templates: the engine picks the best-matching sound
above threshold, and a learned classifier can override them via the engine's ML hook.
"""

from __future__ import annotations

from .detector_base import FeatureProfile, ProfileDetector
from .events import SoundType

# feature ranges: name -> (low|None, high|None, weight)
_PROFILES: dict[str, dict] = {
    "door_knock": {
        "low_ratio": (0.35, None, 2.0),        # energy concentrated low
        "centroid": (80, 1200, 2.0),
        "harmonicity": (None, 0.45, 1.0),
        "onset_count": (2, 7, 2.0),            # a few impacts
        "flatness": (None, 0.6, 1.0),
    },
    "doorbell": {
        "harmonicity": (0.45, None, 2.0),      # tonal chime
        "flatness": (None, 0.3, 2.0),
        "pitch": (350, 1600, 2.0),
        "centroid": (300, 2200, 1.5),
        "onset_count": (1, 4, 1.0),
        "mod_rate": (None, 4.0, 1.0),
    },
    "alarm": {
        "harmonicity": (0.3, None, 1.0),
        "flatness": (None, 0.45, 1.0),
        "pitch": (700, 3500, 1.5),
        "centroid": (1500, 6000, 1.5),
        "mod_rate": (2.0, 12.0, 2.5),          # repetitive beeping
        "onset_count": (3, 30, 2.0),
    },
    "timer": {
        "harmonicity": (0.3, None, 1.0),
        "flatness": (None, 0.45, 1.0),
        "pitch": (1200, 4500, 1.5),
        "centroid": (1500, 6000, 1.5),
        "mod_rate": (1.0, 6.0, 2.0),           # regular short beeps
        "onset_count": (2, 12, 2.0),
    },
    "phone_ringing": {
        "harmonicity": (0.3, None, 1.0),
        "flatness": (None, 0.5, 1.0),
        "pitch": (300, 1600, 1.5),
        "mod_rate": (3.0, 14.0, 2.5),          # ring cadence
        "onset_count": (2, 18, 1.5),
    },
    "keyboard_typing": {
        "flatness": (0.25, None, 2.0),         # broadband clicks
        "zcr": (0.12, None, 1.5),
        "harmonicity": (None, 0.35, 1.5),
        "onset_count": (5, 60, 2.5),           # many rapid keystrokes
        "centroid": (1500, 7000, 1.0),
    },
    "mouse_clicking": {
        "flatness": (0.2, None, 1.5),
        "harmonicity": (None, 0.35, 1.5),
        "onset_count": (1, 4, 2.0),            # isolated clicks
        "high_ratio": (0.3, None, 1.5),
        "duration_s": (None, 1.0, 0.5),
    },
    "laughter": {
        "harmonicity": (0.4, None, 2.0),       # voiced
        "pitch": (150, 520, 1.5),
        "mod_rate": (3.0, 9.0, 2.5),           # rhythmic "ha-ha-ha"
        "onset_count": (3, 14, 1.5),
        "centroid": (300, 2800, 1.0),
    },
    "crying": {
        "harmonicity": (0.4, None, 2.0),       # voiced, sustained
        "pitch": (300, 900, 2.0),
        "mod_rate": (0.5, 6.0, 1.5),
        "onset_count": (1, 8, 1.0),
        "centroid": (400, 3200, 1.0),
    },
    "glass_breaking": {
        "centroid": (3000, 8000, 2.5),         # very bright
        "high_ratio": (0.45, None, 2.5),
        "flatness": (0.3, None, 1.5),          # noisy shatter
        "harmonicity": (None, 0.3, 1.5),
        "zcr": (0.2, None, 1.0),
    },
    "running_water": {
        "flatness": (0.4, None, 2.5),          # broadband noise
        "harmonicity": (None, 0.3, 2.0),
        "mod_rate": (None, 2.5, 2.0),          # stationary
        "onset_count": (None, 4, 1.5),
        "zcr": (0.1, None, 1.0),
        "centroid": (1200, 6000, 1.0),
    },
    "dog_barking": {
        "harmonicity": (0.3, None, 1.5),
        "pitch": (200, 950, 2.0),
        "onset_count": (1, 7, 1.5),
        "mod_rate": (0.5, 6.0, 1.0),
        "centroid": (400, 2800, 1.0),
    },
    "cat_meowing": {
        "harmonicity": (0.4, None, 2.0),       # tonal glide
        "pitch": (300, 1100, 2.0),
        "onset_count": (1, 3, 1.5),
        "mod_rate": (None, 4.0, 1.0),
        "centroid": (400, 2600, 1.0),
    },
}


def build_profile_detectors(catalog) -> list:
    """Instantiate a ProfileDetector for every catalogued sound that has a profile."""
    detectors = []
    for sound in catalog.all():
        ranges = _PROFILES.get(sound.name)
        if ranges is None:
            continue
        detectors.append(ProfileDetector(sound.name, sound.category.value,
                                         FeatureProfile(ranges)))
    return detectors


def register_profile(catalog, sound: SoundType, ranges: dict) -> ProfileDetector:
    """Register a brand-new sound + its profile at runtime (extensibility helper).
    No core logic changes — just data."""
    catalog.register(sound)
    _PROFILES[sound.name] = ranges
    return ProfileDetector(sound.name, sound.category.value, FeatureProfile(ranges))
