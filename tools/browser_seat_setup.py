"""
tools/browser_seat_setup.py — one-time login for a browser chat seat.

Plan-but-no-key users can let FRIDAY use a chat SEAT they already pay for
(ChatGPT / Claude / Gemini). This opens that site in a persistent browser
profile so you can log in BY HAND once; the session is saved and FRIDAY reuses
it. After logging in, enable the seat in friday_config.json under
`harness.browser_seats.<vendor>.enabled = true`.

Usage:
    python tools/browser_seat_setup.py chatgpt            # uses installed Chrome
    python tools/browser_seat_setup.py claude msedge      # or Edge
    python tools/browser_seat_setup.py gemini chromium    # or bundled Chromium

Requires Playwright:  pip install playwright  (and, for `chromium`, `playwright install chromium`)
This drives your OWN logged-in seat; it does not evade detection. Automating
these apps is generally against each vendor's Terms of Service.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.harness.browser_provider import SITES  # noqa: E402
from core.harness.browser_drivers import playwright_driver  # noqa: E402


def main() -> int:
    if len(sys.argv) < 2 or sys.argv[1] not in SITES:
        print(f"usage: python tools/browser_seat_setup.py <{'|'.join(SITES)}> [chrome|msedge|chromium]")
        return 1
    vendor = sys.argv[1]
    channel = sys.argv[2] if len(sys.argv) > 2 else "chrome"
    if channel == "chromium":
        channel = None                      # bundled Chromium (needs `playwright install`)

    user_data_dir = os.path.join("data", "seats", vendor)
    os.makedirs(user_data_dir, exist_ok=True)
    print(f"Opening {vendor} ({SITES[vendor].url}) in a persistent profile at {user_data_dir} …")

    driver = playwright_driver(vendor, user_data_dir=user_data_dir,
                               channel=channel, headless=False)
    try:
        driver._ensure_page()               # opens the browser at the site
        input("\nLog in in the window that opened, then press Enter here to save the session… ")
        ok = driver.is_ready()
        print(f"seat ready: {ok}")
        if ok:
            print(f"Now set harness.browser_seats.{vendor}.enabled = true in friday_config.json")
        return 0 if ok else 2
    finally:
        driver.close()


if __name__ == "__main__":
    raise SystemExit(main())
