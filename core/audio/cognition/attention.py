"""
core/audio/cognition/attention.py — FRIDAY V3 (M15)
Audio Attention. Not every sound deserves equal cognitive priority. This module assigns
each auditory signal a salience and ranks competing signals so the rest of the system
focuses on what matters, in the milestone's fixed order:

    emergency  >  wake word  >  human speech  >  environmental events  >  background

Priorities are configuration-driven (no hardcoded constants) and *dynamic*: a burst of
recent activity in a band gently raises its salience for a short, decaying window, so a
repeatedly-ringing phone or an ongoing emergency rises in focus. It integrates with the
M5 Attention System by projecting auditory signals into the shape `rank_observations`
consumes — audio competes for attention alongside goals, memories, and vision.
"""

from __future__ import annotations

import threading
import time
from typing import Optional

from .config import AttentionConfig
from .events import SoundCategory

# map a signal to its base priority band
_BAND_FOR_CATEGORY = {
    SoundCategory.EMERGENCY.value: "emergency",
    SoundCategory.ALERT.value: "environmental",
    SoundCategory.HUMAN.value: "environmental",
    SoundCategory.ACTIVITY.value: "environmental",
    SoundCategory.ANIMAL.value: "environmental",
    SoundCategory.AMBIENT.value: "background",
}


class AudioAttention:
    def __init__(self, config: Optional[AttentionConfig] = None, *, attention_system=None) -> None:
        self.config = config or AttentionConfig()
        self._attention = attention_system        # optional core.attention.AttentionSystem
        self._recent_boost: dict[str, float] = {}  # band -> (decaying) boost
        self._last_update: dict[str, float] = {}
        # guards the dynamic-boost state, which is updated from both the capture thread
        # (environmental sounds) and the bus thread (wake-word activity).
        self._lock = threading.Lock()

    # ── priority bands ───────────────────────────────────────────────────────────
    def base_priority(self, band: str) -> float:
        return float(getattr(self.config, band, self.config.background))

    def priority_for_signal(self, *, kind: str, category: Optional[str] = None,
                            confidence: float = 1.0, now: Optional[float] = None) -> float:
        """Salience in [0, 1] for an auditory signal.
        `kind` ∈ {emergency, wake_word, speech, environmental, background}; a sound
        `category` maps to its band when kind is not given explicitly."""
        now = now if now is not None else time.time()
        band = kind if kind in ("emergency", "wake_word", "speech", "environmental",
                                "background") else _BAND_FOR_CATEGORY.get(category, "background")
        base = self.base_priority(band)
        boost = self._current_boost(band, now) if self.config.dynamic else 0.0
        return max(0.0, min(1.0, base * (0.5 + 0.5 * confidence) + boost))

    def note_activity(self, band_or_category: str, *, now: Optional[float] = None) -> None:
        """Register recent activity in a band so its salience rises briefly (dynamic)."""
        if not self.config.dynamic:
            return
        now = now if now is not None else time.time()
        band = band_or_category if band_or_category in (
            "emergency", "wake_word", "speech", "environmental", "background") \
            else _BAND_FOR_CATEGORY.get(band_or_category, "background")
        current = self._current_boost(band, now)            # locks internally
        with self._lock:
            self._recent_boost[band] = min(0.2, current + 0.05)
            self._last_update[band] = now

    def _current_boost(self, band: str, now: float) -> float:
        with self._lock:
            boost = self._recent_boost.get(band, 0.0)
            if boost <= 0:
                return 0.0
            elapsed = now - self._last_update.get(band, now)
            decayed = boost * max(0.0, 1.0 - elapsed / 5.0)   # 5 s linear decay
            self._recent_boost[band] = decayed
        return decayed

    # ── ranking ──────────────────────────────────────────────────────────────────
    def rank(self, signals: list, *, now: Optional[float] = None) -> list:
        """Rank a list of signal dicts {kind?, category?, confidence?, label?, id?} by
        salience (desc). Returns the same dicts with a `priority` field added."""
        now = now if now is not None else time.time()
        scored = []
        for s in signals:
            p = self.priority_for_signal(kind=s.get("kind", ""), category=s.get("category"),
                                         confidence=float(s.get("confidence", 1.0)), now=now)
            scored.append({**s, "priority": round(p, 4)})
        return sorted(scored, key=lambda x: x["priority"], reverse=True)

    def focus(self, signals: list, *, now: Optional[float] = None):
        ranked = self.rank(signals, now=now)
        return ranked[0] if ranked else None

    # ── M5 Attention System bridge ───────────────────────────────────────────────
    def submit_to_attention(self, signals: list, *, now: Optional[float] = None) -> list:
        """Project auditory signals into the M5 AttentionSystem.rank_observations shape
        so audio competes alongside goals/memories/vision. Returns the M5 scores (or the
        local ranking if no attention system is wired)."""
        now = now if now is not None else time.time()
        if self._attention is None:
            return self.rank(signals, now=now)
        obs = []
        for s in self.rank(signals, now=now):
            obs.append({"id": s.get("id", s.get("label", "audio")),
                        "name": s.get("label", s.get("category", "audio")),
                        "ts": now, "importance": s["priority"],
                        "urgency": s["priority"], "priority": s["priority"]})
        try:
            return self._attention.rank_observations(obs, now=now)
        except Exception:  # noqa: BLE001
            return self.rank(signals, now=now)

    def bands(self) -> dict:
        return {b: self.base_priority(b) for b in
                ("emergency", "wake_word", "speech", "environmental", "background")}
