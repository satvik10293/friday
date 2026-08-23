"""
core/voice/friday_audio.py — Friday 3.0
Temp audio file helpers. Audio artifacts live under the SYSTEM temp directory
— never the CWD, which may be a read-only install directory (Program Files)
where a write would kill the voice entirely. Paths are per-process so two
FRIDAY processes never fight over the same file.
"""

import os
import tempfile
import uuid
from pathlib import Path

_TEMP_DIR = Path(tempfile.gettempdir()) / "friday_voice"


def get_temp_audio_file() -> str:
    _TEMP_DIR.mkdir(parents=True, exist_ok=True)
    return str(_TEMP_DIR / f"friday_reply_{os.getpid()}.mp3")


def new_temp_audio_file() -> str:
    """A UNIQUE temp mp3 path for a SINGLE utterance. The per-process name from
    get_temp_audio_file() meant every reply wrote the SAME file; if a prior
    clip's handle was still held — mid-play, or left locked by a barge-in
    `stop()` — the next synthesis hit `PermissionError`, synthesis failed, and
    the stale clip replayed. That is Friday 'repeating herself'. A fresh name
    per reply removes the collision entirely."""
    _TEMP_DIR.mkdir(parents=True, exist_ok=True)
    return str(_TEMP_DIR / f"friday_reply_{os.getpid()}_{uuid.uuid4().hex[:8]}.mp3")


def prune_temp_audio() -> None:
    """Best-effort delete of leftover reply files (from a prior crash or a still
    -held handle). Never raises; a file another process is using simply skips."""
    try:
        for f in _TEMP_DIR.glob("friday_reply_*.mp3"):
            try:
                f.unlink()
            except OSError:
                pass                      # locked/in use — leave it, harmless
    except OSError:
        pass


def audio_exists() -> bool:
    return Path(get_temp_audio_file()).exists()


def audio_size() -> int:
    p = Path(get_temp_audio_file())
    return p.stat().st_size if p.exists() else 0


def clear_audio() -> None:
    p = Path(get_temp_audio_file())
    if p.exists():
        p.unlink()


if __name__ == "__main__":
    print("Path:", get_temp_audio_file())
    print("Exists:", audio_exists())
    print("Size:", audio_size(), "bytes")
