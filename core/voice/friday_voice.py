"""
core/voice/friday_voice.py — Friday 3.0
Friday's spoken voice. edge-tts (neural voice, needs network) synthesizes to a
per-process temp file; pygame plays it on a PERSISTENT mixer — initialized
once, never quit between sentences, so there is no per-sentence device churn
and barge-in's `pygame.mixer.music.stop()` always finds a live mixer.

She never goes silent just because the internet is down: when edge-tts fails,
Windows SAPI (built into the OS, no dependencies) speaks the sentence instead.

Imports of edge_tts / pygame are lazy — this module is cheap to import and
testable without audio hardware.
"""

from __future__ import annotations

import asyncio
import json
import logging
import subprocess
import sys
import time
from pathlib import Path

from core.voice.friday_audio import new_temp_audio_file, prune_temp_audio

log = logging.getLogger("friday.voice")


def _degraded(subsystem: str, detail: str, *, failed: bool = False) -> None:
    """Record a voice degradation on the process-wide ledger so a fallback (or
    total silence) is visible in status()/diagnostics, not just a log line."""
    try:
        from core.observability import note_degraded, FAILED, DEGRADED
        note_degraded(subsystem, detail, severity=FAILED if failed else DEGRADED)
    except Exception:  # noqa: BLE001 — self-reporting is never load-bearing
        pass


DEFAULT_VOICE = "en-US-AriaNeural"
_CONFIG_PATH = Path(__file__).resolve().parents[2] / "friday_config.json"


def _config_voice():
    try:
        cfg = json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))
        return (cfg.get("voice") or {}).get("voice_id") or cfg.get("voice_id")
    except (OSError, ValueError):
        return None


class FridayVoice:

    def __init__(self, voice=None):
        self.voice = voice or _config_voice() or DEFAULT_VOICE
        # a fresh file is chosen per utterance (see say); clear any leftovers a
        # prior run left locked so the temp dir doesn't grow without bound
        self.temp_file = None
        prune_temp_audio()

    # ── synthesis (cloud neural voice) ────────────────────────────────────────
    def _generate(self, text: str) -> bool:
        """Synthesize to the temp file. False (never raises) on any failure —
        offline, DNS, service down — so say() can fall back."""
        try:
            import edge_tts

            async def _run():
                await edge_tts.Communicate(text, self.voice).save(self.temp_file)

            asyncio.run(_run())
            return Path(self.temp_file).exists() and audio_nonempty(self.temp_file)
        except Exception:  # noqa: BLE001 — synthesis failure means fallback, not crash
            log.warning("edge-tts synthesis failed (offline?)", exc_info=True)
            return False

    # ── playback (persistent mixer) ───────────────────────────────────────────
    @staticmethod
    def _ensure_mixer():
        import pygame
        if not pygame.mixer.get_init():
            pygame.mixer.init()
        return pygame

    def _play(self, path: str) -> None:
        pygame = self._ensure_mixer()
        pygame.mixer.music.load(path)
        pygame.mixer.music.play()
        try:
            while pygame.mixer.music.get_busy():
                time.sleep(0.05)
        finally:
            # ALWAYS release the file handle (Windows), even if a barge-in
            # stop() or an exception ends playback early — otherwise the file
            # stays locked and can't be cleaned up.
            pygame.mixer.music.unload()

    # ── offline fallback (OS-native TTS — built in, no dependencies) ──────────
    # Windows → SAPI (System.Speech); macOS → the `say` command. Both ship with
    # the OS, so she keeps her voice when edge-tts (network) is unavailable.
    @staticmethod
    def _speak_offline(text: str) -> bool:
        if sys.platform == "win32":
            try:
                subprocess.run(
                    ["powershell", "-NoProfile", "-Command",
                     "Add-Type -AssemblyName System.Speech; "
                     "(New-Object System.Speech.Synthesis.SpeechSynthesizer)"
                     ".Speak([Console]::In.ReadToEnd())"],
                    input=text, text=True, timeout=60, check=True,
                    capture_output=True)
                return True
            except Exception:  # noqa: BLE001
                log.debug("SAPI fallback failed", exc_info=True)
                return False
        if sys.platform == "darwin":
            try:
                subprocess.run(["say", text], timeout=60, check=True,
                               capture_output=True)
                return True
            except Exception:  # noqa: BLE001
                log.debug("macOS `say` fallback failed", exc_info=True)
                return False
        return False

    # ── the public voice ──────────────────────────────────────────────────────
    def say(self, text):
        text = (text or "").strip()
        if not text:
            return
        print(f"\n[Friday] {text}")
        # a FRESH file per utterance: never overwrite one that may still be
        # locked (mid-play or left by a barge-in) — that collision is what made
        # her repeat the previous line instead of speaking the new one.
        self.temp_file = new_temp_audio_file()
        played = False
        try:
            if self._generate(text):
                try:
                    self._play(self.temp_file)
                    played = True
                except Exception:  # noqa: BLE001 — audio device trouble → fallback
                    log.warning("playback failed", exc_info=True)
                    _degraded("voice.playback",
                              "audio playback failed — using offline voice")
            else:
                _degraded("voice.tts",
                          "edge-tts unavailable (offline?) — using offline voice")
        finally:
            self._cleanup(self.temp_file)
        if played:
            return
        if not self._speak_offline(text):
            log.error("all speech paths failed for %r — staying silent", text[:60])
            _degraded("voice", "all speech paths failed — staying silent",
                      failed=True)

    @staticmethod
    def _cleanup(path) -> None:
        """Delete an utterance's temp file once it's played. Best-effort: a file
        still held is left for prune_temp_audio() on the next start."""
        if not path:
            return
        try:
            Path(path).unlink(missing_ok=True)
        except OSError:
            pass


def audio_nonempty(path: str) -> bool:
    try:
        return Path(path).stat().st_size > 0
    except OSError:
        return False


if __name__ == "__main__":
    voice = FridayVoice()
    voice.say("Hello Satvik. Voice systems are online.")
    voice.say("Phase one brain modules are operational.")
