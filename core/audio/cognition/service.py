"""
core/audio/cognition/service.py — FRIDAY V3 (M15)
The Auditory Cognition facade: the single object that turns FRIDAY's hearing into
understanding. It composes the M15 subsystems —

  Audio Event Engine → Context Reasoner (→ World Model via Perception) →
  Auditory Memory + Audio Attention; plus Wake-word control + Speech de-duplication
  for the speech path —

behind one dependency-injected seam, and integrates with the existing Runtime, World
Model, Memory/Chronicle, Executive Brain, Emotion system, and M12.1 Listening pipeline
without modifying any of them. Environmental sound becomes contextual observations;
meaningful events are remembered; emergencies and wake words are prioritized.

Every collaborator is optional; with none wired it still detects sounds and reasons
locally. Nothing here deliberates — interpretation only; decisions belong to the
Executive. Side-effect-free to import; no microphone opens until frames are fed.
"""

from __future__ import annotations

import json
import logging
import threading
import uuid
from pathlib import Path
from typing import Optional

import numpy as np

from .attention import AudioAttention
from .config import AudioCognitionConfig
from .context import AudioContextReasoner
from .dedup import SpeechDeduplicator
from .engine import AudioEventEngine
from .events import AudioCognitionEvent, AuditoryEvent, SoundCategory, default_catalog
from .memory import AuditoryMemory
from .wake import WakeWordController

log = logging.getLogger("friday.audio.cognition")

_MANIFEST_PATH = Path(__file__).resolve().parent / "architecture.json"


class AuditoryCognition:
    def __init__(self, config: Optional[AudioCognitionConfig] = None, *, runtime=None,
                 perception=None, world_model=None, world_feed=None, attention_system=None,
                 chronicle=None, executive=None, emotion=None, wake_engine=None,
                 catalog=None) -> None:
        self.config = config or AudioCognitionConfig()
        self.session_id = self.config.session_id or ("S_" + uuid.uuid4().hex[:8])
        self._runtime = runtime
        self._executive = executive
        self._emotion = emotion
        self.catalog = catalog or default_catalog()

        # context routing: prefer the perception manager (no World-Model bypass); else a
        # plain WorldFeed over the world model; else local-only.
        if world_feed is None and perception is None and world_model is not None:
            from core.perception.world_feed import WorldFeed
            world_feed = WorldFeed(world_model)
        self.reasoner = AudioContextReasoner(perception=perception, world_feed=world_feed)

        self.engine = AudioEventEngine(self.config.events, catalog=self.catalog,
                                       on_event=self._on_sound, session_id=self.session_id)
        self.memory = AuditoryMemory(
            self.config.auditory_memory_path() if self.config.memory.persistent else None,
            persistent=self.config.memory.persistent,
            significance_threshold=self.config.memory.significance_threshold,
            chronicle=chronicle)
        self.attention = AudioAttention(self.config.attention, attention_system=attention_system)

        if wake_engine is None:
            from core.audio.listener.wake_word import WakeWordEngine
            wake_engine = WakeWordEngine()
        self.wake = WakeWordController(wake_engine, self.config.wake)
        self.dedup = SpeechDeduplicator(self.config.speech)

        self._lock = threading.Lock()
        self._emergencies = 0

    # ── environmental sound (frame-driven) ───────────────────────────────────────
    def process_frame(self, frame: np.ndarray, *, ts: Optional[float] = None,
                      source: Optional[str] = None) -> Optional[AuditoryEvent]:
        """Feed one audio frame to the environmental-sound engine. Returns a detection
        at a hop boundary, else None. Never raises."""
        try:
            return self.engine.process_frame(frame, ts=ts, source=source)
        except Exception:  # noqa: BLE001
            log.debug("audio frame processing failed", exc_info=True)
            return None

    def analyze_window(self, window: np.ndarray, *, ts: Optional[float] = None,
                       source: Optional[str] = None) -> Optional[AuditoryEvent]:
        return self.engine.analyze(window, ts=ts, source=source)

    def _on_sound(self, event: AuditoryEvent) -> None:
        """Pipeline for a detected environmental sound: reason → remember → prioritize →
        publish → (emergency) notify the Executive."""
        is_emergency = event.category == SoundCategory.EMERGENCY.value \
            or event.sound in self.config.events.emergency_sounds
        self.attention.note_activity(event.category)

        # 1) context reasoning → contextual AUDIO observation → World Model (no bypass)
        try:
            obs = self.reasoner.reason(event)
        except Exception:  # noqa: BLE001
            obs = None
            log.debug("context reasoning failed", exc_info=True)

        # 2) auditory memory (meaningful only; emergencies always significant)
        if self.config.memory.store_audio_events:
            significance = 1.0 if is_emergency else event.confidence
            self.memory.remember(event, significance=significance)

        # 3) publish + structured log
        self._emit(AudioCognitionEvent.SOUND_DETECTED, event.to_dict())
        if obs is not None:
            self._emit(AudioCognitionEvent.SOUND_CONTEXT,
                       {"sound": event.sound, "reasoning": obs.payload.get("reasoning"),
                        "observation_id": obs.id})
        log.info("[Audio] %s detected (%d%%)", event.sound, round(event.confidence * 100))

        # 4) emergency → raise attention + notify the Executive Brain
        if is_emergency:
            with self._lock:
                self._emergencies += 1
            priority = self.attention.priority_for_signal(kind="emergency",
                                                          confidence=event.confidence)
            self._emit(AudioCognitionEvent.EMERGENCY,
                       {"sound": event.sound, "confidence": event.confidence, "priority": priority})
            self._notify_executive(event, priority)

        # 5) emotion hook for human vocal sounds (if appropriate)
        if event.category == SoundCategory.HUMAN.value or event.sound in ("laughter", "crying"):
            self._notify_emotion(event)

    # ── speech path (dedup + wake control) ───────────────────────────────────────
    def on_transcript(self, payload) -> dict:
        """Process a recognized transcript: reject duplicates, gate the wake word
        (confidence + cooldown + self-speech aware). Accepts a dict or an M12.1 Event."""
        data = getattr(payload, "data", payload) or {}
        text = data.get("text", "")
        audio_conf = float(data.get("confidence", 1.0))

        dedup = self.dedup.check(text)
        if not dedup.accepted:
            self._emit(AudioCognitionEvent.SPEECH_DUPLICATE,
                       {"text": text, "similarity": dedup.similarity})
            log.info("[Audio] duplicate speech ignored")
            return {"accepted": False, "reason": "duplicate", "similarity": dedup.similarity}

        wake = self.wake.detect(text, audio_confidence=audio_conf)
        if wake.suppressed:
            self._emit(AudioCognitionEvent.WAKE_SUPPRESSED,
                       {"word": wake.word, "reason": wake.reason})
            return {"accepted": True, "wake": False, "suppressed": True, "reason": wake.reason}
        if wake.hit:
            self.attention.note_activity("wake_word")
            self._emit(AudioCognitionEvent.WAKE_DETECTED,
                       {"word": wake.word, "confidence": wake.confidence})
            log.info("[Audio] Wake word detected")
        else:
            log.info("[Audio] Speech recognized")
        return {"accepted": True, "wake": wake.hit, "confidence": wake.confidence,
                "command": self.wake.strip_wake_word(text) if wake.hit else text}

    # ── speaking state (ignore FRIDAY's own TTS, resume after) ───────────────────
    def speaking_started(self) -> None:
        self.wake.on_speaking_started()

    def speaking_finished(self) -> None:
        self.wake.on_speaking_finished()

    @property
    def should_resume_listening(self) -> bool:
        return self.wake.should_resume

    # ── M12.1 listening integration (additive; pipeline untouched) ───────────────
    def bind_listening(self, listening_service) -> None:
        """Subscribe to a ListeningService/pipeline bus so recognized transcripts flow
        through dedup + wake control. The M12.1 pipeline is not modified."""
        from core.audio.listener.events import AudioEvent
        bus = listening_service.bus
        bus.on(AudioEvent.TRANSCRIPT_READY, self.on_transcript)

    # ── attention queries ────────────────────────────────────────────────────────
    def prioritize(self, signals: list) -> list:
        """Rank mixed auditory signals (emergency/wake/speech/environmental/background)."""
        return self.attention.rank(signals)

    # ── runtime / executive / emotion bridges (duck-typed, guarded) ──────────────
    def _notify_executive(self, event: AuditoryEvent, priority: float) -> None:
        if self._executive is None:
            return
        for method in ("on_audio_event", "notify", "handle_event", "observe"):
            fn = getattr(self._executive, method, None)
            if callable(fn):
                try:
                    fn({"type": "audio", "sound": event.sound, "category": event.category,
                        "confidence": event.confidence, "priority": priority,
                        "emergency": True})
                    return
                except Exception:  # noqa: BLE001
                    log.debug("executive notify via %s failed", method, exc_info=True)
                    return

    def _notify_emotion(self, event: AuditoryEvent) -> None:
        if self._emotion is None:
            return
        for method in ("on_audio", "observe", "nudge"):
            fn = getattr(self._emotion, method, None)
            if callable(fn):
                try:
                    fn({"sound": event.sound, "confidence": event.confidence})
                    return
                except Exception:  # noqa: BLE001
                    log.debug("emotion notify via %s failed", method, exc_info=True)
                    return

    def _emit(self, event: AudioCognitionEvent, data: dict) -> None:
        if self._runtime is None:
            return
        try:
            self._runtime.emit(event, data=data, source="audio")
        except Exception:  # noqa: BLE001
            log.debug("audio event emit failed", exc_info=True)

    # ── observability ────────────────────────────────────────────────────────────
    def dashboard(self) -> dict:
        return {"title": "Auditory Cognition", "session": self.session_id,
                "engine": self.engine.metrics(), "context": self.reasoner.metrics(),
                "memory": self.memory.metrics(), "wake": self.wake.metrics(),
                "dedup": self.dedup.metrics(), "attention": self.attention.bands(),
                "emergencies": self._emergencies, "recent_sounds": self.engine.recent(15)}

    def metrics(self) -> dict:
        return {"session": self.session_id, "engine": self.engine.metrics(),
                "memory": self.memory.metrics(), "wake": self.wake.metrics(),
                "dedup": self.dedup.metrics(), "emergencies": self._emergencies}

    def health(self) -> dict:
        return {"status": "ok", "session": self.session_id,
                "engine": self.engine.health(), "memory": self.memory.health(),
                "detectors": len(self.engine.detectors())}

    def manifest(self) -> dict:
        try:
            return json.loads(_MANIFEST_PATH.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def attach(self, runtime) -> None:
        self._runtime = runtime
        try:
            runtime.register_health("auditory_cognition", self.health)
        except Exception:  # noqa: BLE001
            log.debug("attach failed", exc_info=True)

    def close(self) -> None:
        self.memory.close()


_instance: Optional[AuditoryCognition] = None
_lock = threading.Lock()


def get_auditory_cognition(**kw) -> AuditoryCognition:
    global _instance
    with _lock:
        if _instance is None:
            _instance = AuditoryCognition(**kw)
    return _instance
