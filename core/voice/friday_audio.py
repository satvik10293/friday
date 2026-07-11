"""
core/voice/friday_audio.py — Friday 3.0
Temp audio file helpers. Audio artifacts live under the SYSTEM temp directory
— never the CWD, which may be a read-only install directory (Program Files)
where a write would kill the voice entirely. Paths are per-process so two
FRIDAY processes never fight over the same file.
"""

import os
import tempfile
from pathlib import Path

_TEMP_DIR = Path(tempfile.gettempdir()) / "friday_voice"


def get_temp_audio_file() -> str:
    _TEMP_DIR.mkdir(parents=True, exist_ok=True)
    return str(_TEMP_DIR / f"friday_reply_{os.getpid()}.mp3")


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
