"""
core/io/orb/window.py -- FRIDAY V3 (M20 revision: Orb UI)

The native Orb window and its view adapter. The orb runs LOCALLY (not in a browser): a tiny
threaded HTTP server serves the self-contained ui/ assets to an embedded webview window
(Edge WebView2 on Windows, WebKitGTK/Cocoa elsewhere) -- frameless, transparent, always on
top, draggable.

  * OrbView   implements the controller's view protocol by JSON-encoding each call and
              pushing it into the page as `window.FRIDAY.<method>(...)` via evaluate_js.
  * Api       is the pywebview JS API: the page calls `window.pywebview.api.<method>()`
              for user interactions, which forward to the controller.
  * OrbWindow  wires them together and owns the webview lifecycle.

Import is side-effect free: pywebview/webview is imported lazily inside start(), so this
module (and the package) import cleanly on headless machines with no display.
"""

from __future__ import annotations

import functools
import json
import logging
import socket
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Optional

log = logging.getLogger("friday.orb.window")

_UI_DIR = Path(__file__).resolve().parent / "ui"


def _free_port(host: str = "127.0.0.1", start: int = 7870, tries: int = 24) -> int:
    port = start
    for _ in range(tries):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex((host, port)) != 0:
                return port
        port += 1
    return start


class _QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *_a) -> None:      # keep the console clean
        pass


class OrbView:
    """Reactive sink: forwards controller calls to `window.FRIDAY.*` in the page. Every
    call is guarded -- a dead/loading window can never break the controller."""

    def __init__(self, window_holder) -> None:
        self._holder = window_holder          # exposes .evaluate(js: str)

    def _call(self, method: str, *args) -> None:
        try:
            payload = ",".join(json.dumps(a) for a in args)
            self._holder.evaluate(f"window.FRIDAY && window.FRIDAY.{method}({payload});")
        except Exception:  # noqa: BLE001
            log.debug("[Orb] evaluate %s failed", method, exc_info=True)

    def set_state(self, state: str) -> None:        self._call("setState", state)
    def set_emotion(self, emotion: str) -> None:    self._call("setEmotion", emotion)
    def show_speech(self, text: str) -> None:       self._call("showSpeech", text)
    def hide_speech(self) -> None:                  self._call("hideSpeech")
    def set_amplitude(self, value: float) -> None:  self._call("setAmplitude", float(value))
    def set_mode(self, mode: str) -> None:          self._call("setMode", mode)
    def notify(self, kind: str, glow: str) -> None: self._call("notify", kind, glow)
    def open_dashboard(self) -> None:               self._call("openDashboard")
    def close_dashboard(self) -> None:              self._call("closeDashboard")
    def bootstrap(self, snapshot: dict) -> None:    self._call("bootstrap", snapshot)


class Api:
    """pywebview JS API -- user interactions travel page -> here -> controller."""

    def __init__(self, controller) -> None:
        self._c = controller

    def wake(self):                 self._c.wake();              return True
    def toggle_dashboard(self):     self._c.toggle_dashboard();  return self._c.dashboard_open
    def command(self, action):      self._c.command(action);     return True
    def set_mode(self, mode):       return self._c.set_mode(mode)
    def move(self, x, y):           self._c.on_move(x, y);        return True
    def resize(self, w, h):         self._c.on_resize(w, h);      return True
    def ready(self):                return self._c.snapshot()


class OrbWindow:
    def __init__(self, controller, settings=None, *, title: str = "FRIDAY") -> None:
        self._controller = controller
        self._settings = settings if settings is not None else getattr(controller, "settings", None)
        self._title = title
        self._server: Optional[ThreadingHTTPServer] = None
        self._port: Optional[int] = None
        self._window = None                    # the pywebview Window (after start())

    # -- local asset server --------------------------------------------------------
    def _serve(self) -> int:
        port = _free_port()
        handler = functools.partial(_QuietHandler, directory=str(_UI_DIR))
        self._server = ThreadingHTTPServer(("127.0.0.1", port), handler)
        threading.Thread(target=self._server.serve_forever, daemon=True,
                         name="orb-http").start()
        self._port = port
        return port

    # -- view push -----------------------------------------------------------------
    def evaluate(self, js: str) -> None:
        win = self._window
        if win is None:
            return
        try:
            win.evaluate_js(js)
        except Exception:  # noqa: BLE001
            log.debug("[Orb] evaluate_js failed", exc_info=True)

    # -- lifecycle -----------------------------------------------------------------
    def start(self) -> bool:
        """Create + run the native window (blocks until closed). Returns False if pywebview
        is unavailable, so callers can degrade gracefully."""
        try:
            import webview
        except ImportError:
            print("[FRIDAY Orb] pywebview is not installed. Install with: pip install pywebview")
            print("             (Windows also needs the Edge WebView2 runtime, bundled with Win 11.)")
            return False

        port = self._serve()
        s = self._settings
        opts = dict(
            frameless=True, easy_drag=False,
            on_top=bool(getattr(s, "always_on_top", True)),
            width=int(getattr(s, "width", 340)), height=int(getattr(s, "height", 340)),
            background_color="#05070d", resizable=True,
        )
        # optional geometry (only pass when known; pywebview centres otherwise)
        if getattr(s, "x", None) is not None and getattr(s, "y", None) is not None:
            opts["x"], opts["y"] = int(s.x), int(s.y)
        try:
            opts["transparent"] = True
            self._window = webview.create_window(
                self._title, f"http://127.0.0.1:{port}/orb.html",
                js_api=Api(self._controller), **opts)
        except Exception:  # noqa: BLE001 -- some platforms reject transparent; retry opaque
            opts.pop("transparent", None)
            self._window = webview.create_window(
                self._title, f"http://127.0.0.1:{port}/orb.html",
                js_api=Api(self._controller), **opts)
        try:
            webview.start()
        finally:
            self.shutdown()
        return True

    def shutdown(self) -> None:
        if self._server is not None:
            try:
                self._server.shutdown()
            except Exception:  # noqa: BLE001
                pass
            self._server = None
