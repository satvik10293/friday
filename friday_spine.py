"""
friday_spine.py — FRIDAY 5.x entry point.

The 3.0 spine is retired and its modules have been removed. This entry point
delegates to the production launcher (`friday_launch.py` / `core.launcher`),
which boots the full cognitive stack: Runtime → Brains → Coordinator →
Executive → Intelligence OS → Voice.

    python friday_spine.py              # full voice-mode boot (production launcher)
"""

from __future__ import annotations

import sys


def main(argv: list | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    from core.launcher import main as launcher_main
    # voice mode: not headless, so the launcher starts the runtime + listening
    return launcher_main(args)


if __name__ == "__main__":
    raise SystemExit(main())
