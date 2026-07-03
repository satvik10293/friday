"""
friday_orb_app.py -- FRIDAY V3 (M20 revision)

The primary FRIDAY interface: the floating Orb, in its own native window (NOT a browser).

Boot sequence:
  1. start the Runtime (its event bus is the orb's only control channel),
  2. build the Orb Controller on the runtime bus,
  3. also reflect FRIDAY's live 3.0 nervous system (core.infra.friday_signal.get_bus),
     so real SPEAK_* / THINKING_* / WAKE_WORD / MOOD_UPDATED reach the orb,
  4. open the native frameless/transparent/always-on-top orb window and run it.

The orb contains no AI logic; it visualises signals and forwards user interactions back onto
the bus. The dashboard (cinematic HUD, friday_app.py) is now a secondary interface the orb
opens on request; closing it never shuts FRIDAY down.

    python friday_orb_app.py
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


def main() -> int:
    logging.basicConfig(level=logging.ERROR, format="%(levelname)s [%(name)s] %(message)s")
    log = logging.getLogger("friday.orb.app")

    from core.io.orb import OrbController, OrbView, OrbWindow
    from core.launcher import Launcher

    # 1. production startup: runtime, brains, memory, executive, voice, wake word, orb.
    launcher = Launcher(profile="production", headless=False, start_runtime=True)
    report = launcher.run()
    runtime = launcher.components.get("runtime")
    controller = launcher.components.get("orb")

    # 2. controller on the runtime bus. If startup degraded before the orb stage, keep the
    # native orb available as the recovery surface.
    if controller is None:
        controller = OrbController(bus=runtime)
        controller.start()

    # 3. also reflect the live 3.0 global bus (where the running app emits expression
    # signals). StartupSequence already does this for the normal path; this is harmless.
    try:
        from core.infra.friday_signal import get_bus
        controller.add_source_bus(get_bus())
    except Exception as e:  # noqa: BLE001
        log.debug("global bus bridge skipped: %s", e)

    # 4. native window + view
    window = OrbWindow(controller, controller.settings)
    controller.attach_view(OrbView(window))
    if not window.start():                    # blocks until the window closes
        return 1
    return 0 if report.get("friday") == "ready" else 1


if __name__ == "__main__":
    raise SystemExit(main())
