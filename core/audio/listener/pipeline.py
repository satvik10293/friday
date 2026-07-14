"""
core/audio/listener/pipeline.py — FRIDAY 4.0 (M12.1)
The listening pipeline — a continuously running state machine that wires every
stage together:

  microphone → buffer → noise suppression → VAD/speech detection → wake word →
  segmentation → language → transcription → confidence → speaker → emotion →
  events → Intelligence OS (M12).

It never blocks, never restarts the mic between utterances, honours privacy mode,
and emits events for Mission Control + the agent society. Frame-driven, so it is
fully testable from synthetic audio without hardware.
"""

from __future__ import annotations

import logging
import queue
import threading
import time
from collections import deque
from enum import Enum
from typing import Optional

import numpy as np

from .audio_buffer import RollingBuffer
from .confidence import ConfidenceAnalyzer
from .emotion import EmotionEstimator
from .events import AudioEvent, AudioEventBus
from .language_detector import LanguageDetector
from .metrics import ListeningMetrics
from .microphone import FRAME_SIZE, SAMPLE_RATE, ArraySource, MicrophoneSource
from .interruption import InterruptionController
from .speaker import SpeakerRecognizer
from .speech_segmenter import Segment, SpeechSegmenter
from .transcription import Transcriber, get_transcriber
from .vad import AudioClass, NoiseSuppressor, VoiceActivityDetector, rms
from .verifier import TranscriptVerifier, VerdictAction
from .wake_word import WakeWordEngine

log = logging.getLogger("friday.audio.pipeline")


class ListeningState(str, Enum):
    DISABLED = "disabled"
    IDLE = "idle"
    LISTENING = "listening"
    PROCESSING = "processing"


class ListeningPipeline:
    def __init__(self, *, microphone: Optional[MicrophoneSource] = None,
                 intelligence_os=None, bus: Optional[AudioEventBus] = None,
                 transcriber: Optional[Transcriber] = None,
                 wake_engine: Optional[WakeWordEngine] = None,
                 segmenter: Optional[SpeechSegmenter] = None,
                 verifier: Optional[TranscriptVerifier] = None,
                 wake_required: bool = True, store_audio: bool = False,
                 buffer_seconds: float = 8.0, async_segments: bool = False) -> None:
        self.mic = microphone if microphone is not None else ArraySource()
        self.ios = intelligence_os
        self.bus = bus if bus is not None else AudioEventBus()
        self.buffer = RollingBuffer(seconds=buffer_seconds)
        self.suppressor = NoiseSuppressor()
        self.vad = VoiceActivityDetector()
        self.segmenter = segmenter or SpeechSegmenter()
        self.wake = wake_engine or WakeWordEngine()
        self.transcriber = transcriber or get_transcriber()
        self.language = LanguageDetector()
        self.confidence = ConfidenceAnalyzer()
        self.speaker = SpeakerRecognizer()
        self.emotion = EmotionEstimator()
        self.interruption = InterruptionController()
        self.metrics = ListeningMetrics()
        # optional human-level verification gate (M31); None → legacy routing
        self.verifier = verifier

        self.wake_required = wake_required
        self.store_audio = store_audio          # raw audio retained only if True (privacy)
        self.state = ListeningState.IDLE
        self.stage = "idle"
        self.volume = 0.0
        self.noise_level = 0.0
        self.last_speaker = "unknown"
        self.last_language = "en"
        self.last_confidence = 0.0
        self.last_latency_ms = 0.0
        self._was_collecting = False
        self._noise_run = False
        self._stored: deque = deque(maxlen=64)  # opt-in raw audio, bounded
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        # async segments (production): transcription + cognition can take
        # seconds (whisper on CPU, the cloud reasoner) — handled inline they
        # starve the frame loop, the sounddevice buffer overflows, and speech
        # spoken while FRIDAY thinks is LOST. A worker thread processes
        # segments while the frame loop keeps the mic drained. Synchronous by
        # default so process_frame()/pump() stay deterministic for tests.
        self.async_segments = async_segments
        self._segment_queue: Optional[queue.Queue] = None
        self._worker: Optional[threading.Thread] = None

    # ── privacy ─────────────────────────────────────────────────────────────────
    def set_privacy(self, enabled: bool) -> None:
        """Privacy mode: instantly stop (or resume) capturing audio."""
        if enabled:
            self.mic.disable()
            self._set_state(ListeningState.DISABLED)
        else:
            self.mic.enable()
            self._set_state(ListeningState.IDLE)

    @property
    def privacy(self) -> bool:
        return not self.mic.enabled

    # ── frame processing ────────────────────────────────────────────────────────
    def process_frame(self, frame: np.ndarray, *, ts: Optional[float] = None
                      ) -> Optional[dict]:
        """Process one 20 ms frame. Returns a command result dict at a command
        boundary, else None. The single unit of the real-time loop."""
        ts = ts if ts is not None else time.time()
        if not self.mic.enabled:
            return None
        self.buffer.append(frame)
        self.volume = round(rms(frame), 5)

        cls, _conf = self.vad.classify(frame)
        self.suppressor.update_floor(self.volume, cls == AudioClass.SILENCE.value)
        self.noise_level = round(self.suppressor.noise_floor, 6)
        clean = self.suppressor.process(frame)

        if cls == AudioClass.NOISE.value:
            if not self._noise_run:
                self._noise_run = True
                self.bus.emit(AudioEvent.NOISE_DETECTED, {"level": self.volume})
        else:
            self._noise_run = False

        segment = self.segmenter.process(clean, ts=ts)

        # speech onset → COMMAND_STARTED
        if self.segmenter.collecting and not self._was_collecting:
            self._set_state(ListeningState.LISTENING)
            self.bus.emit(AudioEvent.SPEECH_DETECTED, {"ts": ts})
            self.bus.emit(AudioEvent.COMMAND_STARTED, {"ts": ts})
        self._was_collecting = self.segmenter.collecting

        if segment is not None:
            self.bus.emit(AudioEvent.SILENCE_DETECTED, {"ts": ts})
            if self._segment_queue is not None:
                try:
                    self._segment_queue.put_nowait(segment)
                except queue.Full:       # worker badly behind — newest speech wins
                    try:
                        self._segment_queue.get_nowait()
                    except queue.Empty:
                        pass
                    self._segment_queue.put_nowait(segment)
                return None
            return self._handle_segment(segment)
        return None

    def _handle_segment(self, segment: Segment) -> dict:
        self._set_state(ListeningState.PROCESSING)
        t0 = time.perf_counter()

        self.stage = "transcription"
        transcript = self.transcriber.transcribe(segment.audio)
        text = transcript.text or ""

        self.stage = "language"
        lang = self.language.detect(text)
        if lang.language != self.last_language:
            self.last_language = lang.language
            self.bus.emit(AudioEvent.LANGUAGE_CHANGED, {"language": lang.language})

        self.stage = "wake_word"
        hit, word, wake_conf = self.wake.detect(text)
        if hit:
            self.metrics.record_wake()
            self.bus.emit(AudioEvent.WAKE_WORD_DETECTED,
                          {"word": word, "confidence": wake_conf})

        self.stage = "speaker"
        spk = self.speaker.identify(segment.audio)
        if spk.label != self.last_speaker:
            self.last_speaker = spk.label
            self.bus.emit(AudioEvent.SPEAKER_CHANGED, {"speaker": spk.label})

        self.stage = "emotion"
        emo = self.emotion.estimate(segment.audio)
        self.bus.emit(AudioEvent.EMOTION_DETECTED, emo.to_dict())

        self.stage = "confidence"
        conf = self.confidence.analyze(
            signal_rms=rms(segment.audio), noise_floor=self.suppressor.noise_floor,
            language_confidence=lang.confidence, wake_confidence=wake_conf,
            transcription_confidence=transcript.confidence)
        self.last_confidence = conf.overall

        self.bus.emit(AudioEvent.TRANSCRIPT_READY,
                      {"text": text, "confidence": conf.overall,
                       "language": lang.language, "speaker": spk.label})

        if self.store_audio:
            self._stored.append(segment.audio)

        command = self.wake.strip_wake_word(text) if hit else text

        # wake word alone ("Friday?") — acknowledge and open the follow-up
        # window instead of silently discarding the empty command; the user's
        # next words route without re-waking
        if hit and not command.strip():
            if self.verifier is not None:
                self.verifier.note_response(spk.label)
            ack = getattr(self.ios, "wake_acknowledge", None)
            if callable(ack):
                try:
                    ack(spk.label)
                except Exception:  # noqa: BLE001
                    log.debug("wake acknowledge failed", exc_info=True)
            log.info("heard %r -> wake word only; acknowledged, window open",
                     text[:80])

        # verification gate (M31): decide, like a human, whether this was meant
        # for her and whether it was finished — before cognition ever sees it
        verdict = None
        if self.verifier is not None:
            self.stage = "verification"
            verdict = self.verifier.verify(
                command, audio_confidence=conf.overall, wake_hit=hit,
                speaker=spk.label, speaker_known=spk.known)
            routed = verdict.action == VerdictAction.ACCEPT
            self.bus.emit(AudioEvent.TRANSCRIPT_VERIFIED, verdict.to_dict())
        else:
            routed = (not self.wake_required) or hit

        # every heard segment leaves a truthful console trace — "she heard
        # nothing" and "she heard you and chose not to answer" must be
        # distinguishable without a debugger (real-world silence report)
        if command.strip() or text.strip():
            outcome = ("routed" if routed and command.strip() else
                       verdict.action.value if verdict is not None else
                       "no wake word" if self.wake_required and not hit else
                       "empty")
            log.info("heard %r (conf %.2f, wake=%s) -> %s",
                     text[:80], conf.overall, hit, outcome)

        response = None
        if routed and command.strip() and self.ios is not None:
            self.stage = "intelligence"
            try:
                response = self.ios.think(command, context={
                    "source": "voice", "emotion": emo.emotion, "speaker": spk.label,
                    "language": lang.language, "audio_confidence": conf.overall})
                if self.verifier is not None:
                    self.verifier.note_response(spk.label)   # open follow-up window
            except Exception as e:  # noqa: BLE001 — IOS failure must not break listening
                log.debug("IOS routing failed: %s", e)

        latency_ms = (time.perf_counter() - t0) * 1000.0
        self.last_latency_ms = round(latency_ms, 2)
        self.metrics.record_command(latency_ms=latency_ms, confidence=conf.overall,
                                    speech_s=segment.duration_s, recognized=bool(text))

        result = {"text": text, "command": command, "routed": routed,
                  "wake": hit, "speaker": spk.label, "language": lang.language,
                  "emotion": emo.emotion, "confidence": conf.to_dict(),
                  "verdict": verdict.to_dict() if verdict is not None else None,
                  "latency_ms": self.last_latency_ms, "duration_s": segment.duration_s,
                  "response": response.to_dict() if response is not None and
                  hasattr(response, "to_dict") else None}
        self.bus.emit(AudioEvent.COMMAND_FINISHED, {k: result[k] for k in
                      ("text", "routed", "wake", "speaker", "language", "emotion",
                       "latency_ms")})
        self._set_state(ListeningState.IDLE)
        self.stage = "idle"
        return result

    # ── run loop (continuous, non-blocking) ─────────────────────────────────────
    def pump(self, max_frames: Optional[int] = None) -> int:
        """Drive the pipeline from the mic until it is exhausted (ArraySource) or
        `max_frames` / stop. Returns frames processed."""
        if not self.mic.is_open:
            self.mic.open()
        processed = 0
        while not self._stop.is_set():
            if max_frames is not None and processed >= max_frames:
                break
            frame = self.mic.read()
            if frame is None:
                break
            self.process_frame(frame)
            processed += 1
        return processed

    def start(self) -> None:
        """Start continuous listening in a daemon thread (never restarts the mic)."""
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        if not self.mic.is_open:
            self.mic.open()
        if self.async_segments and self._worker is None:
            self._segment_queue = queue.Queue(maxsize=4)
            self._worker = threading.Thread(target=self._segment_loop, daemon=True,
                                            name="friday-segments")
            self._worker.start()
        self._thread = threading.Thread(target=self._loop, daemon=True,
                                        name="friday-listener")
        self._thread.start()
        self._set_state(ListeningState.IDLE)

    def _segment_loop(self) -> None:  # pragma: no cover - thread loop
        while True:
            segment = self._segment_queue.get()
            if segment is None:          # shutdown sentinel
                return
            try:
                self._handle_segment(segment)
            except Exception:  # noqa: BLE001 — one bad segment never kills hearing
                log.debug("segment processing error", exc_info=True)

    def _loop(self) -> None:  # pragma: no cover - timing/thread loop
        idle_sleep = FRAME_SIZE / SAMPLE_RATE
        while not self._stop.is_set():
            frame = self.mic.read()
            if frame is None:
                time.sleep(idle_sleep)
                continue
            try:
                self.process_frame(frame)
            except Exception:  # noqa: BLE001
                log.debug("frame processing error", exc_info=True)

    def stop(self) -> None:
        self._stop.set()
        seg = self.segmenter.flush()
        if seg is not None:
            self._handle_segment(seg)    # finish what was being said, inline
        if self._thread:
            self._thread.join(timeout=1.0)
        if self._worker is not None and self._segment_queue is not None:
            self._segment_queue.put(None)            # sentinel: drain then exit
            self._worker.join(timeout=5.0)
            self._worker = None
            self._segment_queue = None

    # ── interruption passthrough ────────────────────────────────────────────────
    def interrupt(self, source: str = "user") -> bool:
        self.bus.emit(AudioEvent.INTERRUPT_REQUESTED, {"source": source})
        return self.interruption.request_interrupt(source)

    # ── diagnostics (Mission Control) ───────────────────────────────────────────
    def _set_state(self, state: ListeningState) -> None:
        if state != self.state:
            self.state = state
            self.bus.emit(AudioEvent.LISTENING_STATE_CHANGED, {"state": state.value})

    def status(self) -> dict:
        return {
            "microphone": self.mic.status(),
            "state": self.state.value,
            "stage": self.stage,
            "volume": self.volume,
            "noise_level": self.noise_level,
            "speech_detected": self.segmenter.collecting,
            "wake_words": self.wake.words(),
            "speaker": self.last_speaker,
            "language": self.last_language,
            "confidence": self.last_confidence,
            "latency_ms": self.last_latency_ms,
            "privacy": self.privacy,
            "buffer_seconds": self.buffer.seconds_held,
            "metrics": self.metrics.snapshot(),
        }

    def health(self) -> dict:
        return {"status": "ok" if not self.privacy else "privacy",
                "state": self.state.value, "transcriber": self.transcriber.name}
