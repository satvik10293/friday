"""
core/services/emotion_service.py — FRIDAY V3 (M16)
EmotionService — a PLACEHOLDER affect seam. Salient spatial/auditory events can nudge
affect (e.g. someone entered, an alarming change); for now it forwards to an injected
emotion backend if present and otherwise records the nudge. Stable API so callers are
unchanged when a real emotion model lands.
"""

from __future__ import annotations

import logging
import time
from collections import deque

log = logging.getLogger("friday.services.emotion")


class EmotionService:
    name = "emotion"

    def __init__(self, backend=None, *, buffer: int = 500) -> None:
        self._backend = backend
        self._buffer: deque = deque(maxlen=buffer)

    def nudge(self, signal: dict) -> None:
        self._buffer.append({"signal": signal, "ts": time.time()})
        if self._backend is None:
            return
        for method in ("nudge", "observe", "on_audio", "on_event"):
            fn = getattr(self._backend, method, None)
            if callable(fn):
                try:
                    fn(signal)
                except Exception:  # noqa: BLE001
                    log.debug("emotion backend nudge failed", exc_info=True)
                return

    def health(self) -> dict:
        status = "ok" if self._backend is not None else "placeholder"
        return {"status": status, "nudges": len(self._buffer)}
