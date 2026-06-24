"""
friday_senses.py — Friday 3.0
Microphone front-end. Provides TWO logical listeners over ONE shared mic stream:

  • listen_for_command()  — the MAIN listener. Energy-based VAD: waits for you to
    start talking, records until you go quiet, then transcribes the whole utterance
    (no more fixed 5-second windows).
  • listen_for_stopword() — the STOP-WORD listener. Runs while Friday is speaking,
    transcribing short rolling windows and returning True the moment it hears the
    stop word ("friday") so the spine can cut her off mid-sentence.

Both consume the same `sd.InputStream` queue, but never at the same time (the main
listener runs while idle; the stop-word listener runs only while speaking), and a
lock guards the device so they can't fight over it.

faster-whisper transcribes numpy audio directly, so nothing is written to disk
(fixes the old test.wav-in-CWD gotcha).
"""

import queue
import logging
import threading

import numpy as np
import sounddevice as sd

from core.voice.friday_stt import FridaySTT

log = logging.getLogger("friday.senses")


class FridaySenses:

    def __init__(
        self,
        sample_rate=16000,
        block_ms=30,
        silence_threshold=0.012,   # RMS below this counts as silence
        silence_ms=800,            # trailing silence that ends an utterance
        max_utterance_s=15,        # hard cap on a single utterance
        min_utterance_ms=300,      # ignore blips shorter than this
    ):
        self.sample_rate = sample_rate
        self.block_size = int(sample_rate * block_ms / 1000)
        self.silence_threshold = silence_threshold
        self._silence_blocks = max(1, int(silence_ms / block_ms))
        self._max_blocks = int(max_utterance_s * 1000 / block_ms)
        self._min_blocks = max(1, int(min_utterance_ms / block_ms))

        print("[FridaySenses] Initializing STT...")
        self.stt = FridaySTT()

        self._q: "queue.Queue[np.ndarray]" = queue.Queue()
        self._stream = None
        self._lock = threading.Lock()
        print("[FridaySenses] Ready")

    # ── shared mic stream ───────────────────────────────────────────────────────

    def _callback(self, indata, frames, time_info, status):
        if status:
            log.debug("mic status: %s", status)
        self._q.put(indata[:, 0].copy())

    def start(self):
        """Open the shared input stream. Safe to call repeatedly."""
        if self._stream is None:
            self._stream = sd.InputStream(
                samplerate=self.sample_rate,
                channels=1,
                dtype="float32",
                blocksize=self.block_size,
                callback=self._callback,
            )
            self._stream.start()

    def stop(self):
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:
                pass
            self._stream = None

    def _drain(self):
        try:
            while True:
                self._q.get_nowait()
        except queue.Empty:
            pass

    @staticmethod
    def _rms(block) -> float:
        return float(np.sqrt(np.mean(np.square(block)) + 1e-12))

    def _transcribe(self, audio, beam_size=5) -> str:
        audio = np.asarray(audio, dtype=np.float32)
        segments, _ = self.stt.model.transcribe(
            audio, language="en", beam_size=beam_size
        )
        return " ".join(s.text for s in segments).strip()

    # ── MAIN listener: VAD utterance capture ────────────────────────────────────

    def listen_for_command(self, should_run=None) -> str:
        """Block until a full spoken utterance is captured, then transcribe it.
        `should_run` is an optional predicate; when it returns False we bail out."""
        with self._lock:
            self.start()
            self._drain()
            print("[Friday] Listening...")

            frames = []
            triggered = False
            silence = 0
            while should_run is None or should_run():
                try:
                    block = self._q.get(timeout=0.5)
                except queue.Empty:
                    continue

                if self._rms(block) >= self.silence_threshold:
                    triggered = True
                    silence = 0
                    frames.append(block)
                elif triggered:
                    silence += 1
                    frames.append(block)
                    if silence >= self._silence_blocks:
                        break

                if len(frames) >= self._max_blocks:
                    break

            if not triggered or len(frames) < self._min_blocks:
                return ""
            print("[Friday] Transcribing...")
            return self._transcribe(np.concatenate(frames))

    # ── STOP-WORD listener ──────────────────────────────────────────────────────

    def listen_for_stopword(self, stop_words, should_run, window_s=1.0) -> bool:
        """While `should_run()` is True, transcribe short rolling windows and
        return True as soon as one of `stop_words` is heard. Returns False if
        `should_run()` goes False first (Friday finished speaking normally)."""
        words = [w.lower() for w in stop_words]
        with self._lock:
            self.start()
            self._drain()
            window_blocks = max(1, int(window_s * self.sample_rate / self.block_size))
            while should_run():
                frames = []
                while len(frames) < window_blocks and should_run():
                    try:
                        frames.append(self._q.get(timeout=0.2))
                    except queue.Empty:
                        continue
                if not frames or not should_run():
                    break
                window = np.concatenate(frames)
                if self._rms(window) < self.silence_threshold:
                    continue
                text = self._transcribe(window, beam_size=1).lower()
                if text and any(w in text for w in words):
                    log.info("Stop word heard: %r", text)
                    return True
            return False
