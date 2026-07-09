"""
core/audio/listener/service.py — FRIDAY 4.0 (M12.1)
The listening service facade: constructs and owns the pipeline, exposes start/stop
+ privacy, surfaces a Mission Control dashboard payload, and attaches to the M1
runtime. Wires the M12 Intelligence OS so every spoken command becomes an
intelligence request.
"""

from __future__ import annotations

import logging
import threading
from typing import Optional

from .pipeline import ListeningPipeline

log = logging.getLogger("friday.audio.service")


class ListeningService:
    def __init__(self, *, intelligence_os=None, microphone=None, wake_required: bool = True,
                 store_audio: bool = False, verify: bool = False,
                 conversation_window_s: float = 8.0) -> None:
        verifier = None
        if verify:
            from .verifier import ConversationState, TranscriptVerifier
            verifier = TranscriptVerifier(
                require_wake=wake_required,
                conversation=ConversationState(window_s=conversation_window_s))
        self.pipeline = ListeningPipeline(
            microphone=microphone, intelligence_os=intelligence_os,
            verifier=verifier, wake_required=wake_required, store_audio=store_audio)

    @property
    def bus(self):
        return self.pipeline.bus

    # ── lifecycle ───────────────────────────────────────────────────────────────
    def start(self) -> None:
        self.pipeline.start()

    def stop(self) -> None:
        self.pipeline.stop()

    def set_privacy(self, enabled: bool) -> None:
        self.pipeline.set_privacy(enabled)

    # ── Mission Control ─────────────────────────────────────────────────────────
    def dashboard(self) -> dict:
        st = self.pipeline.status()
        return {"title": "Listening", "local": True, **st,
                "recent_events": self.bus.recent(20)}

    def status(self) -> dict:
        return self.pipeline.status()

    def health(self) -> dict:
        return self.pipeline.health()

    def attach(self, runtime) -> None:
        try:
            runtime.register_health("listening", self.health)
        except Exception:  # noqa: BLE001
            log.debug("attach failed", exc_info=True)


_service: Optional[ListeningService] = None
_lock = threading.Lock()


def get_listening_service(**kw) -> ListeningService:
    global _service
    with _lock:
        if _service is None:
            _service = ListeningService(**kw)
    return _service
