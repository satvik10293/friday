"""
The voice output layer (core/voice) — the repaired weakest part:

  · audio artifacts live under the SYSTEM temp dir, never the CWD (which may
    be a read-only install dir under Program Files)
  · edge-tts failure (offline) falls back to Windows SAPI — never silent,
    never a crash on the speech worker
  · every module is side-effect-free to import (friday_mic_test used to
    START RECORDING at import; friday_voice_loop was an accidental setup.py
    copy that ran pip installs and a blocking input() at import)

No audio hardware, network, or pygame device is touched by these tests.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from core.voice.friday_audio import get_temp_audio_file
from core.voice.friday_voice import FridayVoice


# ── temp paths: never the CWD ─────────────────────────────────────────────────

def test_temp_audio_lives_under_the_system_temp_dir():
    p = Path(get_temp_audio_file())
    assert Path(tempfile.gettempdir()) in p.parents
    assert Path.cwd() not in p.parents
    assert p.parent.exists()          # created on demand


def test_temp_audio_is_per_process():
    import os
    assert str(os.getpid()) in Path(get_temp_audio_file()).name


# ── say(): synthesis → playback → offline fallback ───────────────────────────

class _Probe(FridayVoice):
    """FridayVoice with the three effects recorded instead of executed."""

    def __init__(self, generate_ok=True, play_ok=True):
        super().__init__(voice="en-US-AriaNeural")
        self.calls = []
        self._generate_ok = generate_ok
        self._play_ok = play_ok

    def _generate(self, text):
        self.calls.append("generate")
        return self._generate_ok

    def _play(self, path):
        self.calls.append("play")
        if not self._play_ok:
            raise RuntimeError("audio device gone")

    @staticmethod
    def _speak_offline(text):
        return True

    def _speak_offline_probe(self, text):  # bound in tests that need counting
        self.calls.append("offline")
        return True


def test_say_plays_the_synthesized_audio():
    v = _Probe()
    v._speak_offline = v._speak_offline_probe
    v.say("Hello there.")
    assert v.calls == ["generate", "play"]


def test_say_falls_back_to_offline_when_synthesis_fails():
    v = _Probe(generate_ok=False)
    v._speak_offline = v._speak_offline_probe
    v.say("Hello there.")
    assert v.calls == ["generate", "offline"]     # no playback attempt


def test_say_falls_back_to_offline_when_playback_fails():
    v = _Probe(play_ok=False)
    v._speak_offline = v._speak_offline_probe
    v.say("Hello there.")
    assert v.calls == ["generate", "play", "offline"]


def test_say_never_raises_when_every_path_fails():
    v = _Probe(generate_ok=False)
    v._speak_offline = lambda text: False
    v.say("Hello there.")                         # silent, but alive


def test_say_ignores_empty_text():
    v = _Probe()
    v.say("   ")
    assert v.calls == []


# ── import safety ─────────────────────────────────────────────────────────────

def test_mic_test_is_side_effect_free_to_import():
    import core.voice.friday_mic_test as mod
    assert callable(mod.main)
    # 3.0 built the whisper model AND recorded 5 s of audio at module level
    assert not hasattr(mod, "model")
    assert not hasattr(mod, "audio")


def test_voice_loop_is_side_effect_free_to_import():
    import core.voice.friday_voice_loop as mod
    assert callable(mod.main)


def test_no_voice_module_writes_to_the_cwd():
    import inspect

    import core.voice.friday_audio as audio
    import core.voice.friday_tts as tts
    import core.voice.friday_voice as voice
    for mod in (audio, tts, voice):
        source = inspect.getsource(mod)
        assert "friday_reply.mp3\"" not in source.replace("'", '"'), \
            f"{mod.__name__} hardcodes a CWD-relative audio path"
