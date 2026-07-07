"""
friday_spine.py — FRIDAY 5.x compatibility shim (Phase A cutover).

The 3.0 spine is retired. This entry point now delegates to the production
launcher (`friday_launch.py` / `core.launcher`), which boots the full cognitive
stack: Runtime → Brains → Coordinator → Executive → Intelligence OS → Voice.
No 3.0 brain modules are imported on this path.

    python friday_spine.py              # full voice-mode boot (production launcher)
    python friday_spine.py --legacy     # emergency fallback: the retired 3.0 spine

The retired orchestrator lives at legacy/friday_spine_v3.py for reference.
"""

from __future__ import annotations

import sys


def _run_legacy() -> int:
    import logging
    logging.basicConfig(level=logging.INFO, format="%(levelname)s [%(name)s] %(message)s")
    print("[Spine] WARNING: running the retired 3.0 orchestrator (legacy fallback)")
    from legacy.friday_spine_v3 import FridaySpine
    spine = FridaySpine()
    if not spine.boot():
        print("[Spine] Boot failed — check config and API keys")
        return 1
    spine.run_voice_loop()
    return 0


def main(argv: list | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if "--legacy" in args:
        return _run_legacy()
    from core.launcher import main as launcher_main
    # voice mode: not headless, so the launcher starts the runtime + listening
    return launcher_main(args)


if __name__ == "__main__":
    raise SystemExit(main())
