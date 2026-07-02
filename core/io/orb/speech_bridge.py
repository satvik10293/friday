"""
core/io/orb/speech_bridge.py -- FRIDAY V3 (M20 revision: Orb UI)

The Speech Service bridge. When FRIDAY speaks, this publishes the speech text and the REAL
audio amplitude envelope onto the Runtime Event Bus so the Orb can visualise it -- the orb
never runs any speech synthesis itself (browser TTS is removed). Amplitude is computed as an
RMS envelope of the actual synthesized audio, paced to its true duration on a background
thread, so the orb "vibrates" in sync with FRIDAY's voice.

All optional imports (soundfile / numpy / wave / friday_tts) are guarded; every method is
best-effort and never raises.
"""

from __future__ import annotations

import logging
import math
import threading
import time
import wave
from typing import Optional

from . import events as E

log = logging.getLogger("friday.orb.speech_bridge")

_WINDOW_MS = 60                              # amplitude frame size (~60 ms)


class SpeechBridge:
    def __init__(self, bus) -> None:
        self._bus = bus

    # -- bus emit (sync Runtime, async EventBus via emit_sync, or coroutine) ---------
    def _emit(self, signal, data=None) -> None:
        bus = self._bus
        if bus is None:
            return
        try:
            emit_sync = getattr(bus, "emit_sync", None)
            if callable(emit_sync):
                emit_sync(signal, data, "speech")
                return
            emit = getattr(bus, "emit", None)
            if emit is None:
                return
            import asyncio
            if asyncio.iscoroutinefunction(emit):
                coro = emit(signal, data=data, source="speech")
                try:
                    asyncio.get_running_loop().create_task(coro)
                except RuntimeError:
                    coro.close()
            else:
                emit(signal, data=data, source="speech")
        except Exception:  # noqa: BLE001
            log.debug("[Orb] speech emit failed", exc_info=True)

    # -- public API -----------------------------------------------------------------
    def emit_speech(self, text: str, audio_path: Optional[str] = None,
                    *, block: bool = False) -> None:
        """Announce a spoken utterance: show text + speaking state, stream a real amplitude
        envelope for the audio's duration, then hide + return to idle."""
        self._emit(E.ORB_SPEECH_SHOW, text)
        self._emit(E.ORB_STATE, "speaking")
        env, duration = self._envelope(audio_path)
        runner = lambda: self._stream(env, duration)  # noqa: E731
        if block:
            runner()
        else:
            threading.Thread(target=runner, daemon=True, name="orb-amplitude").start()

    def speak(self, text: str) -> None:
        """Synthesize `text` with FRIDAY's TTS to a temp file, then visualise it."""
        path = None
        try:
            import os
            import tempfile
            fd, path = tempfile.mkstemp(suffix=".mp3", prefix="friday_orb_")
            os.close(fd)
            from core.voice import friday_tts
            import asyncio
            asyncio.run(friday_tts.speak_to_file(text, path))
        except Exception:  # noqa: BLE001
            log.debug("[Orb] TTS synth failed; visualising without audio", exc_info=True)
            path = None
        self.emit_speech(text, path, block=True)
        if path:
            try:
                import os
                os.remove(path)
            except OSError:
                pass

    # -- amplitude envelope ---------------------------------------------------------
    def _stream(self, envelope, duration: float) -> None:
        try:
            n = len(envelope)
            if n == 0:
                self._finish()
                return
            frame = max(duration / n, 0.02)
            for amp in envelope:
                self._emit(E.ORB_AMPLITUDE, float(amp))
                time.sleep(frame)
        except Exception:  # noqa: BLE001
            log.debug("[Orb] amplitude stream failed", exc_info=True)
        finally:
            self._finish()

    def _finish(self) -> None:
        self._emit(E.ORB_AMPLITUDE, 0.0)
        self._emit(E.ORB_SPEECH_HIDE)
        self._emit(E.ORB_STATE, "idle")

    def _envelope(self, audio_path: Optional[str]):
        """Return (envelope[0..1], duration_seconds). Real RMS if the audio decodes, else a
        short synthetic envelope so the orb still animates."""
        if audio_path:
            env = self._rms_from_soundfile(audio_path) or self._rms_from_wave(audio_path)
            if env:
                return env
        return self._synthetic(), 1.6

    def _rms_from_soundfile(self, path: str):
        try:
            import numpy as np
            import soundfile as sf
        except Exception:  # noqa: BLE001
            return None
        try:
            data, rate = sf.read(path, always_2d=True)
            mono = data.mean(axis=1)
            return self._rms_windows(mono, rate, np)
        except Exception:  # noqa: BLE001
            return None

    def _rms_from_wave(self, path: str):
        try:
            with wave.open(path, "rb") as w:
                rate = w.getframerate()
                n = w.getnframes()
                raw = w.readframes(n)
                width = w.getsampwidth()
        except Exception:  # noqa: BLE001
            return None
        try:
            import numpy as np
            dtype = {1: np.int8, 2: np.int16, 4: np.int32}.get(width)
            if dtype is None:
                return None
            arr = np.frombuffer(raw, dtype=dtype).astype("float64")
            peak = float(np.iinfo(dtype).max) or 1.0
            return self._rms_windows(arr / peak, rate, np)
        except Exception:  # noqa: BLE001
            return None

    def _rms_windows(self, mono, rate, np):
        step = max(int(rate * _WINDOW_MS / 1000), 1)
        frames = []
        for i in range(0, len(mono), step):
            chunk = mono[i:i + step]
            if len(chunk):
                frames.append(float(np.sqrt(np.mean(chunk * chunk))))
        if not frames:
            return None
        peak = max(frames) or 1.0
        env = [max(0.0, min(1.0, f / peak)) for f in frames]
        duration = len(mono) / float(rate or 1)
        return env, max(duration, 0.1)

    @staticmethod
    def _synthetic():
        return [abs(math.sin(i * 0.4)) * 0.6 + 0.2 for i in range(24)]
