"""
friday_app.py — Friday 3.0
The desktop app. Friday's cinematic HUD (WebGL neural core, mood-tinted rails,
conversation timeline, mini-brain roster, gesture control) in its OWN native
window — no browser, no tabs, no localhost URL to click.

How it works: the HUD backend (core.io.friday_face, a tiny local Flask server)
runs on 127.0.0.1 in a background thread; the cinematic interface is rendered in
a native OS window by an embedded webview (Edge WebView2 on Windows, which has
full WebGL support).

    python friday_app.py
"""

import sys
import time
import socket
import logging
import threading
from pathlib import Path

_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

HOST, PORT = "127.0.0.1", 7862
TITLE = "Friday 3.0"


def _wait_for_server(host: str, port: int, timeout: float = 30.0) -> bool:
    end = time.time() + timeout
    while time.time() < end:
        try:
            with socket.create_connection((host, port), timeout=1):
                return True
        except OSError:
            time.sleep(0.25)
    return False


def _free_port(host: str, start: int, tries: int = 12) -> int:
    """Return the first free port at/after `start` so a stale instance can't block us."""
    port = start
    for _ in range(tries):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex((host, port)) != 0:   # nothing listening → free
                return port
        port += 1
    return start


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s [%(name)s] %(message)s")

    try:
        import webview  # pywebview
    except ImportError:
        print("[FridayApp] pywebview is not installed.")
        print("            Install it with:  pip install pywebview")
        print("            (Windows also needs the Edge WebView2 runtime, which ships with Win 11.)")
        return

    from core.io import friday_face

    port = _free_port(HOST, PORT)
    print(f"[FridayApp] Booting Friday's HUD backend on http://{HOST}:{port} ...")
    friday_face.run_background(host=HOST, port=port)

    if not _wait_for_server(HOST, port):
        print("[FridayApp] Backend did not come up in time. Aborting.")
        return
    print("[FridayApp] Backend ready — opening the cinematic window.")

    # Warm the brain in the background so the first question is snappy.
    def _warm():
        try:
            from core.brain.friday_brain import get_brain
            get_brain()
        except Exception as e:
            logging.getLogger("friday.app").debug("Brain warm-up skipped: %s", e)
    threading.Thread(target=_warm, daemon=True, name="brain-warm").start()

    webview.create_window(
        TITLE,
        f"http://{HOST}:{port}/",
        width=1500,
        height=920,
        min_size=(960, 640),
        background_color="#030608",
        text_select=False,
        confirm_close=False,
    )
    # Blocks on the main thread until the window is closed.
    webview.start()
    print("[FridayApp] Window closed — Friday HUD shut down.")


if __name__ == "__main__":
    main()
