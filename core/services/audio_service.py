"""
core/services/audio_service.py — FRIDAY V3 (M16)
AudioService — decoupled source of auditory cues used by spatial cognition for presence
and localization (e.g. typing/keyboard → user at desk; speech → user present). Adapts an
injected M15 `AuditoryCognition` (its event engine's recent detections) or any object
exposing `recent_events()`. Graceful and empty when no audio is wired.
"""

from __future__ import annotations

import logging

log = logging.getLogger("friday.services.audio")


class AudioService:
    name = "audio"

    def __init__(self, audio=None, *, provider=None) -> None:
        self._audio = audio
        self._provider = provider

    def recent_events(self, *, limit: int = 20) -> list:
        if self._provider is not None:
            try:
                return list(self._provider())[:limit]
            except Exception:  # noqa: BLE001
                return []
        if self._audio is None:
            return []
        if hasattr(self._audio, "recent_events"):
            try:
                return list(self._audio.recent_events(limit=limit))
            except Exception:  # noqa: BLE001
                return []
        try:                                   # AuditoryCognition exposes engine.recent()
            return list(self._audio.engine.recent(limit))
        except Exception:  # noqa: BLE001
            log.debug("audio recent_events failed", exc_info=True)
            return []

    def health(self) -> dict:
        return {"status": "ok", "backend": "audio_cognition" if (self._audio or self._provider)
                else "absent"}
