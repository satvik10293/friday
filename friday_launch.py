"""
friday_launch.py — FRIDAY production entry point (M20).

Thin wrapper over the production launcher. Detects the OS, loads configuration, validates
dependencies, runs the ordered startup sequence (Configuration → Kernel → Runtime →
Memory → Knowledge → Perception → Simulation → Coordinator → Executive → Plugins → Voice
→ UI → Ready), and reports health — then optionally hands off to the desktop UI.

    python friday_launch.py                 # headless boot + health report
    python friday_launch.py --json          # machine-readable startup report
    python friday_launch.py --profile development --start-runtime
"""

from __future__ import annotations

from core.launcher import main

if __name__ == "__main__":
    raise SystemExit(main())
