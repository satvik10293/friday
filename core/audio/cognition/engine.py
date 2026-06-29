"""
core/audio/cognition/engine.py — FRIDAY V3 (M15)
The Audio Event Detection engine. It accumulates the continuous mono frame stream into
a rolling analysis window, extracts acoustic features once per hop, scores every
registered detector, and emits the best-matching sound above the confidence threshold —
debounced per sound type so one real event isn't reported dozens of times.

The engine owns no domain knowledge: detectors are plugins (profile-based by default,
ML via the hook), and the sound vocabulary lives in the catalog. Adding a sound never
touches this file. Frame-driven and pure compute → fully testable from synthetic audio,
and safe to run off the real-time capture thread.
"""

from __future__ import annotations

import logging
import threading
import time
from collections import deque
from typing import Callable, Optional

import numpy as np

from .config import EventDetectionConfig
from .detector_base import AudioEventDetector
from .events import AuditoryEvent, SoundCatalog, default_catalog
from .features import SAMPLE_RATE, extract_features
from .profiles import build_profile_detectors

log = logging.getLogger("friday.audio.events")


class AudioEventEngine:
    def __init__(self, config: Optional[EventDetectionConfig] = None, *,
                 catalog: Optional[SoundCatalog] = None,
                 detectors: Optional[list] = None,
                 on_event: Optional[Callable[[AuditoryEvent], None]] = None,
                 session_id: str = "", sr: int = SAMPLE_RATE) -> None:
        self.config = config or EventDetectionConfig()
        self.catalog = catalog or default_catalog()
        self._detectors: list[AudioEventDetector] = (
            detectors if detectors is not None else build_profile_detectors(self.catalog))
        self._on_event = on_event
        self._session_id = session_id
        self._sr = sr
        self._win = max(1, int(self.config.window_s * sr))
        self._hop = max(1, int(self.config.hop_s * sr))
        self._buf: deque = deque(maxlen=self._win)
        self._since_hop = 0
        self._last_fired: dict[str, float] = {}
        self._metrics = {"windows": 0, "detections": 0, "suppressed": 0}
        self._recent: deque = deque(maxlen=100)
        self._lock = threading.Lock()           # guards the frame buffer + detection state

    # ── plugin management (extensibility) ────────────────────────────────────────
    def add_detector(self, detector: AudioEventDetector) -> None:
        self._detectors.append(detector)

    def detectors(self) -> list:
        return list(self._detectors)

    def set_session(self, session_id: str) -> None:
        self._session_id = session_id

    # ── frame-driven entry ───────────────────────────────────────────────────────
    def process_frame(self, frame: np.ndarray, *, ts: Optional[float] = None,
                      source: Optional[str] = None) -> Optional[AuditoryEvent]:
        """Feed one audio frame; returns an AuditoryEvent at most once per hop."""
        if not self.config.enabled:
            return None
        flat = np.asarray(frame, dtype=np.float32).ravel()
        with self._lock:
            self._buf.extend(flat)
            self._since_hop += int(flat.size)
            if len(self._buf) < self._win or self._since_hop < self._hop:
                return None
            self._since_hop = 0
            window = np.fromiter(self._buf, dtype=np.float32, count=len(self._buf))
        # analyze re-acquires the lock for its own state; the buffer lock is released
        return self.analyze(window, ts=ts, source=source)

    # ── direct window classification ─────────────────────────────────────────────
    def analyze(self, window: np.ndarray, *, ts: Optional[float] = None,
                source: Optional[str] = None) -> Optional[AuditoryEvent]:
        """Classify one window; emit + return the best detection above threshold."""
        ts = ts if ts is not None else time.time()
        # feature extraction + detector scoring are read-only (detectors are stateless),
        # so they run outside the lock; only shared-state mutations are guarded.
        features = extract_features(window, self._sr)
        best, best_score = None, 0.0
        for det in self._detectors:
            if det.sound in self.config.disabled_sounds:
                continue
            s = det.score(features)
            if s > best_score:
                best, best_score = det, s

        with self._lock:
            self._metrics["windows"] += 1
            if best is None or best_score < self.config.min_confidence:
                return None
            # per-type cooldown so a single event isn't reported every hop
            last = self._last_fired.get(best.sound, 0.0)
            if ts - last < self.config.per_type_cooldown_s:
                self._metrics["suppressed"] += 1
                return None
            self._last_fired[best.sound] = ts
            event = AuditoryEvent(
                sound=best.sound, category=best.category, confidence=best_score,
                timestamp=ts, source=source, session_id=self._session_id,
                features={k: features.to_dict()[k] for k in
                          ("centroid", "flatness", "harmonicity", "pitch",
                           "onset_count", "mod_rate")})
            self._metrics["detections"] += 1
            self._recent.append(event.to_dict())

        # the consumer runs outside the lock (it may reason / write memory / the World Model)
        if self._on_event is not None:
            try:
                self._on_event(event)
            except Exception:  # noqa: BLE001 — a consumer must never break detection
                log.debug("audio event consumer failed", exc_info=True)
        log.info("[Audio] %s detected (%d%%)", best.sound, round(best_score * 100))
        return event

    # ── observability ────────────────────────────────────────────────────────────
    def recent(self, limit: int = 20) -> list:
        return list(self._recent)[-limit:][::-1]

    def metrics(self) -> dict:
        return {**self._metrics, "detectors": len(self._detectors),
                "sounds": self.catalog.names()}

    def health(self) -> dict:
        unavailable = [d.sound for d in self._detectors if not d.available()]
        return {"status": "ok", "detectors": len(self._detectors),
                "unavailable": unavailable, "enabled": self.config.enabled}
