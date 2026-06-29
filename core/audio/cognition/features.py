"""
core/audio/cognition/features.py — FRIDAY V3 (M15)
Acoustic feature extraction for environmental-sound recognition. Pure numpy (rFFT +
time-domain stats), so it is always available and sub-millisecond on a ~0.6 s window —
the detectors never depend on a heavy backend.

The features are the classical, model-free descriptors that separate the M15 sound
classes: energy, zero-crossing rate, spectral centroid/bandwidth/flatness/rolloff,
band-energy ratios, harmonicity + dominant pitch (autocorrelation), and temporal
structure (onset count + amplitude-modulation rate). Detectors score how well a window
matches a sound's feature *profile*; a learned classifier can later replace this via the
detection engine's ML hook without touching anything here.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

SAMPLE_RATE = 16000


@dataclass
class AudioFeatures:
    rms: float
    zcr: float
    centroid: float                  # Hz — spectral brightness
    bandwidth: float                 # Hz — spectral spread
    flatness: float                  # 0 tonal … 1 noisy (geometric/arithmetic mean ratio)
    rolloff: float                   # Hz — 85% energy roll-off
    low_ratio: float                 # band energy fractions (sum ~1)
    mid_ratio: float
    high_ratio: float
    harmonicity: float               # 0 inharmonic … 1 strongly periodic
    pitch: float                     # Hz — dominant pitch (0 if inharmonic)
    onset_count: float               # transient onsets in the window
    mod_rate: float                  # Hz — amplitude-modulation (envelope) rate
    duration_s: float

    def to_dict(self) -> dict:
        return {k: round(float(v), 5) for k, v in self.__dict__.items()}


def extract_features(window: np.ndarray, sr: int = SAMPLE_RATE) -> AudioFeatures:
    """Compute the acoustic feature vector for one analysis window (mono float32)."""
    x = np.asarray(window, dtype=np.float32)
    n = x.size
    if n == 0:
        return AudioFeatures(*([0.0] * 13), duration_s=0.0)

    energy = float(np.sqrt(np.mean(x.astype(np.float64) ** 2)))
    zcr = _zcr(x)

    # spectrum
    win = x * np.hanning(n).astype(np.float32)
    spec = np.abs(np.fft.rfft(win)) + 1e-12
    freqs = np.fft.rfftfreq(n, d=1.0 / sr)
    power = spec ** 2
    total = float(power.sum())
    centroid = float((freqs * power).sum() / total)
    bandwidth = float(np.sqrt(((freqs - centroid) ** 2 * power).sum() / total))
    flatness = float(np.exp(np.mean(np.log(spec))) / np.mean(spec))
    rolloff = _rolloff(freqs, power, total)
    low_ratio, mid_ratio, high_ratio = _band_ratios(freqs, power, total)

    harmonicity, pitch = _harmonicity(x, sr)
    onset_count, mod_rate = _temporal(x, sr)

    return AudioFeatures(
        rms=energy, zcr=zcr, centroid=centroid, bandwidth=bandwidth, flatness=flatness,
        rolloff=rolloff, low_ratio=low_ratio, mid_ratio=mid_ratio, high_ratio=high_ratio,
        harmonicity=harmonicity, pitch=pitch, onset_count=onset_count, mod_rate=mod_rate,
        duration_s=n / sr)


# ── helpers ─────────────────────────────────────────────────────────────────────────
def _zcr(x: np.ndarray) -> float:
    if x.size < 2:
        return 0.0
    s = np.signbit(x)
    return float(np.mean(s[1:] != s[:-1]))


def _rolloff(freqs: np.ndarray, power: np.ndarray, total: float, frac: float = 0.85) -> float:
    if total <= 0:
        return 0.0
    cumulative = np.cumsum(power)
    idx = int(np.searchsorted(cumulative, frac * total))
    idx = min(idx, len(freqs) - 1)
    return float(freqs[idx])


def _band_ratios(freqs: np.ndarray, power: np.ndarray, total: float) -> tuple:
    if total <= 0:
        return 0.0, 0.0, 0.0
    low = power[(freqs < 500)].sum()
    mid = power[(freqs >= 500) & (freqs < 2000)].sum()
    high = power[(freqs >= 2000)].sum()
    return float(low / total), float(mid / total), float(high / total)


def _harmonicity(x: np.ndarray, sr: int) -> tuple:
    """Autocorrelation-based periodicity + dominant pitch over 80–1000 Hz."""
    if x.size < sr // 50:
        return 0.0, 0.0
    x = x - x.mean()
    norm = float(np.dot(x, x)) + 1e-12
    ac = np.correlate(x, x, mode="full")[x.size - 1:]
    ac = ac / norm
    lo = max(1, sr // 1000)          # 1000 Hz
    hi = min(len(ac) - 1, sr // 80)  # 80 Hz
    if hi <= lo:
        return 0.0, 0.0
    seg = ac[lo:hi]
    k = int(np.argmax(seg))
    peak = float(seg[k])
    lag = lo + k
    pitch = sr / lag if lag > 0 else 0.0
    return max(0.0, min(1.0, peak)), float(pitch)


def _temporal(x: np.ndarray, sr: int, frame_ms: int = 20) -> tuple:
    """Onset count (sharp energy rises) + amplitude-modulation rate from the envelope."""
    step = max(1, sr * frame_ms // 1000)
    env = np.array([np.sqrt(np.mean(x[i:i + step] ** 2) + 1e-12)
                    for i in range(0, max(1, x.size - step), step)], dtype=np.float32)
    if env.size < 3:
        return 0.0, 0.0
    # onsets: positive flux above a relative threshold
    flux = np.diff(env)
    thresh = 0.5 * float(np.max(env))
    onsets = int(np.sum((flux > 0) & (env[1:] > thresh) & (env[:-1] <= thresh)))
    # modulation rate: dominant frequency of the (centered) envelope
    e = env - env.mean()
    if np.allclose(e, 0):
        return float(onsets), 0.0
    fr = max(1, sr // step)          # envelope sampling rate (Hz)
    spec = np.abs(np.fft.rfft(e * np.hanning(e.size)))
    mfreqs = np.fft.rfftfreq(e.size, d=1.0 / fr)
    band = mfreqs <= 20.0
    if band.sum() <= 1 or spec[band].sum() <= 0:
        return float(onsets), 0.0
    mod_rate = float(mfreqs[band][int(np.argmax(spec[band]))])
    return float(onsets), mod_rate
