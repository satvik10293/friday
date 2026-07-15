"""
core/io/tray.py — FRIDAY V3 (M48)
The proper desktop app: a system-tray presence instead of the heavy cinematic
HUD (Flask dev server + Edge WebView2 + WebGL). FRIDAY is a voice-first
assistant; her "window" is a tray icon that shows she's resident, lets you
mute the mic and quit, and raises desktop notifications when she speaks or
acts. No browser, no localhost, no console.

Everything here is guarded and OPTIONAL: if pystray / Pillow are missing the
app degrades to console-resident (exactly the pre-M48 behaviour), never
failing the boot. The tray runs on its own daemon thread; the cognitive stack
is untouched by it.
"""

from __future__ import annotations

import logging
import threading
from typing import Callable, Optional

log = logging.getLogger("friday.io.tray")

# tray state → icon tint (a glance tells you what she's doing)
_COLORS = {
    "idle": (90, 120, 200),          # calm blue
    "listening": (60, 190, 120),     # green
    "thinking": (230, 170, 40),      # amber
    "muted": (120, 120, 120),        # grey
    "error": (210, 70, 70),          # red
}


def _make_icon(color, size: int = 64):
    """A simple filled-circle icon in FRIDAY's current-state colour."""
    from PIL import Image, ImageDraw
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    pad = 6
    d.ellipse([pad, pad, size - pad, size - pad], fill=color + (255,))
    # a small inner ring so it reads as an "eye"/core, not just a dot
    inner = size // 4
    d.ellipse([inner, inner, size - inner, size - inner],
              fill=(255, 255, 255, 210))
    return img


def notify(title: str, message: str) -> bool:
    """Best-effort desktop notification (plyer → win10toast → nothing)."""
    try:
        from plyer import notification
        notification.notify(title=title, message=message[:240],
                            app_name="FRIDAY", timeout=5)
        return True
    except Exception:  # noqa: BLE001
        pass
    try:
        from win10toast import ToastNotifier
        ToastNotifier().show_toast(title, message[:240], duration=5, threaded=True)
        return True
    except Exception:  # noqa: BLE001
        return False


def available() -> bool:
    """True if a real system tray can be shown on this machine."""
    try:
        import PIL  # noqa: F401
        import pystray  # noqa: F401
        return True
    except Exception:  # noqa: BLE001
        return False


class TrayApp:
    """FRIDAY's tray presence. Holds a reference to the listening service (to
    mute/unmute the mic) and the launcher (to shut down cleanly)."""

    def __init__(self, *, listening=None, on_quit: Optional[Callable[[], None]] = None,
                 open_logs: Optional[Callable[[], None]] = None) -> None:
        self._listening = listening
        self._on_quit = on_quit
        self._open_logs = open_logs
        self._icon = None
        self._thread: Optional[threading.Thread] = None
        self._muted = False
        self._state = "idle"

    # ── state → icon ─────────────────────────────────────────────────────────────
    def set_state(self, state: str) -> None:
        """Reflect what she's doing in the tray icon colour (idle/listening/
        thinking/muted/error). Best-effort — never raises."""
        self._state = state
        icon = self._icon
        if icon is None:
            return
        try:
            icon.icon = _make_icon(_COLORS.get(state, _COLORS["idle"]))
        except Exception:  # noqa: BLE001
            log.debug("tray icon update failed", exc_info=True)

    # ── menu actions ─────────────────────────────────────────────────────────────
    def _toggle_mute(self, icon=None, item=None) -> None:
        self._muted = not self._muted
        try:
            if self._listening is not None:
                self._listening.set_privacy(self._muted)   # privacy = mic off
        except Exception:  # noqa: BLE001
            log.debug("tray mute toggle failed", exc_info=True)
        self.set_state("muted" if self._muted else "idle")
        notify("FRIDAY", "Microphone muted." if self._muted else "Listening again.")

    def _logs(self, icon=None, item=None) -> None:
        if self._open_logs is not None:
            try:
                self._open_logs()
            except Exception:  # noqa: BLE001
                log.debug("open logs failed", exc_info=True)

    def _quit(self, icon=None, item=None) -> None:
        try:
            if self._icon is not None:
                self._icon.stop()
        except Exception:  # noqa: BLE001
            pass
        if self._on_quit is not None:
            try:
                self._on_quit()
            except Exception:  # noqa: BLE001
                log.debug("quit callback failed", exc_info=True)

    def _build_menu(self):
        import pystray
        return pystray.Menu(
            pystray.MenuItem(lambda item: "Muted" if self._muted else "Listening",
                             None, enabled=False),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(lambda item: "Unmute mic" if self._muted else "Mute mic",
                             self._toggle_mute),
            pystray.MenuItem("Open logs", self._logs,
                             visible=self._open_logs is not None),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quit FRIDAY", self._quit),
        )

    # ── lifecycle ────────────────────────────────────────────────────────────────
    def start(self, *, blocking: bool = False) -> bool:
        """Show the tray icon. Non-blocking by default (own daemon thread).
        Returns whether the tray actually started."""
        if not available():
            log.info("tray unavailable (pystray/Pillow missing) — console-resident")
            return False
        try:
            import pystray
            self._icon = pystray.Icon("friday", icon=_make_icon(_COLORS["idle"]),
                                      title="FRIDAY", menu=self._build_menu())
        except Exception:  # noqa: BLE001
            log.debug("tray construction failed", exc_info=True)
            return False
        if blocking:
            self._icon.run()
            return True
        self._thread = threading.Thread(target=self._icon.run, name="friday-tray",
                                        daemon=True)
        self._thread.start()
        return True

    def stop(self) -> None:
        try:
            if self._icon is not None:
                self._icon.stop()
        except Exception:  # noqa: BLE001
            pass
