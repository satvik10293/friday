"""
friday_secrets.py — Friday 3.0
Loads secrets from a gitignored `.env` at the project root into the process
environment, so API keys live in environment variables instead of in any tracked
file. Zero dependencies.

Precedence: a real environment variable always wins over the `.env` file, so you
can override keys per-shell without editing anything.
"""

import os
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_ENV_FILE = _ROOT / ".env"


def load_env(path: Path = _ENV_FILE) -> int:
    """Load KEY=VALUE lines from `.env` into os.environ (without overriding
    variables already set in the environment). Returns how many were applied."""
    path = Path(path)
    if not path.exists():
        return 0
    applied = 0
    try:
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, val = line.split("=", 1)
            key = key.strip()
            val = val.strip().strip('"').strip("'")
            if key and key not in os.environ:   # real env wins
                os.environ[key] = val
                applied += 1
    except OSError:
        return applied
    return applied


# Load on import so simply importing this module wires up the secrets.
load_env()
