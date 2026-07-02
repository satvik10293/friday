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
    logging.basicConfig(level=logging.INFO, format="%(levelname)s [%(name)s] %(message)s")
    log = logging.getLogger("friday.orb.app")

    from core.io.orb import OrbController, OrbView, OrbWindow

    # 1. runtime (event bus). Best-effort: the orb still opens if it can't start.
    runtime = None
    try:
        from core.runtime import get_runtime
        runtime = get_runtime()
        runtime.start(timeout=10)
    except Exception as e:  # noqa: BLE001
        log.warning("runtime did not start (%s); orb runs in a degraded, local-only mode", e)

    # 2. controller on the runtime bus
    controller = OrbController(bus=runtime)

    # 3. also reflect the live 3.0 global bus (where the running app emits expression signals)
    try:
        from core.infra.friday_signal import get_bus
        controller.add_source_bus(get_bus())
    except Exception as e:  # noqa: BLE001
        log.debug("global bus bridge skipped: %s", e)

    # 4. native window + view
    window = OrbWindow(controller, controller.settings)
    controller.attach_view(OrbView(window))
    controller.start()

    log.info("FRIDAY Orb ready (mode: %s). Opening the native window...", controller.mode)
    if not window.start():                    # blocks until the window closes
        return 1
    log.info("FRIDAY Orb closed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
