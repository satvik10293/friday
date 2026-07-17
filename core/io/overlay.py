"""
core/io/overlay.py — FRIDAY V3 (M51)
The private overlay: a small, transparent, always-on-top panel in a screen
corner that shows FRIDAY's state and her latest answer — so you always know
she's alive and see what she said, while the tray + voice run in the
background. It is NOT the removed cinematic HUD (no Flask, no WebView2, no
WebGL): just text drawn on a transparent tkinter window, cheap on a CPU box.

The point: it's visible to YOU but not to a screen share. On Windows 10 2004+
`SetWindowDisplayAffinity(hwnd, WDA_EXCLUDEFROMCAPTURE)` makes the window
render normally on your monitor yet appear blank in captures / Teams / Zoom /
OBS / PrintScreen — the same mechanism password managers use.

Everything is guarded: no tkinter, an old Windows, or no display → the overlay
quietly does nothing (the tray + voice are unaffected). tkinter is single-
threaded, so the window lives on its own thread and all updates are marshalled
onto it through a queue.
"""

from __future__ import annotations

import logging
import queue
import threading
from typing import Optional

log = logging.getLogger("friday.io.overlay")

# Win32 constants
_WDA_EXCLUDEFROMCAPTURE = 0x00000011      # Win10 2004+: excluded from capture
_WDA_MONITOR = 0x00000001                 # older fallback: black in capture
_GWL_EXSTYLE = -20
_WS_EX_LAYERED = 0x00080000
_WS_EX_TRANSPARENT = 0x00000020           # click-through
_WS_EX_TOOLWINDOW = 0x00000080            # no taskbar button

_STATE_COLORS = {
    "idle": "#5a78c8", "listening": "#3cbe78", "thinking": "#e6aa28",
    "speaking": "#7cc0ff", "muted": "#808080", "error": "#d24646",
}
_TRANSPARENT_KEY = "#010203"              # this bg colour renders fully clear


def available() -> bool:
    try:
        import tkinter  # noqa: F401
        return True
    except Exception:  # noqa: BLE001
        return False


class Overlay:
    """A capture-excluded, click-through status panel. Feed it with
    set_state()/heard()/answer(); it fades her answer after a while."""

    def __init__(self, *, corner: str = "top-right", opacity: float = 0.9,
                 exclude_capture: bool = True, click_through: bool = True,
                 width: int = 380, answer_ttl_s: float = 20.0) -> None:
        self.corner = corner
        self.opacity = max(0.2, min(1.0, opacity))
        self.exclude_capture = exclude_capture
        self.click_through = click_through
        self.width = width
        self.answer_ttl_s = answer_ttl_s
        self._q: "queue.Queue[dict]" = queue.Queue(maxsize=64)
        self._thread: Optional[threading.Thread] = None
        self._root = None
        self._widgets: dict = {}
        self._content: dict = {"state": "idle", "heard": "", "answer": ""}
        self._answer_hide_at: Optional[float] = None
        self._transparent = False
        self._canvas_bg = _TRANSPARENT_KEY
        self._stop = threading.Event()
        self._started = False
        self.captured_excluded = False    # set True once affinity is applied

    # ── thread-safe feed (call from anywhere) ────────────────────────────────────
    def post(self, **event) -> None:
        try:
            self._q.put_nowait(event)
        except queue.Full:
            pass                          # UI is best-effort; drop if backed up

    def set_state(self, state: str) -> None:
        self.post(kind="state", state=state)

    def heard(self, text: str) -> None:
        self.post(kind="heard", text=(text or "")[:160])

    def answer(self, text: str) -> None:
        self.post(kind="answer", text=(text or "")[:400])

    def notice(self, text: str) -> None:
        self.post(kind="notice", text=(text or "")[:160])

    # ── lifecycle ────────────────────────────────────────────────────────────────
    def start(self) -> bool:
        if not available():
            log.info("overlay unavailable (no tkinter) — running without it")
            return False
        if self._started:
            return True
        self._started = True
        self._thread = threading.Thread(target=self._run, name="friday-overlay",
                                        daemon=True)
        self._thread.start()
        return True

    def stop(self) -> None:
        self._stop.set()
        root = self._root
        if root is not None:
            try:
                root.after(0, root.destroy)      # destroy ON the tk thread
            except Exception:  # noqa: BLE001
                pass
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=2.0)             # let tk tear down cleanly first

    # ── the tk thread ────────────────────────────────────────────────────────────
    def _run(self) -> None:  # pragma: no cover - GUI thread, verified live
        try:
            import tkinter as tk
        except Exception:  # noqa: BLE001
            return
        try:
            root = tk.Tk()
            self._root = root
            root.overrideredirect(True)                 # borderless
            root.attributes("-topmost", True)           # always on top
            # fully opaque text; the SEE-THROUGH comes from a transparent
            # window, not from dimming alpha (which would fade the text too).
            import sys
            root.attributes("-alpha", 1.0)
            self._transparent = False
            if sys.platform == "darwin":
                # macOS: no transparentcolor key — use the native transparent
                # window attribute (Tk 8.6 on Aqua). UNVERIFIED (built on
                # Windows); the canvas bg becomes systemTransparent so only the
                # outlined text shows.
                try:
                    root.attributes("-transparent", True)
                    root.configure(bg="systemTransparent")
                    self._canvas_bg = "systemTransparent"
                    self._transparent = True
                except tk.TclError:
                    root.configure(bg=_TRANSPARENT_KEY)
                    self._canvas_bg = _TRANSPARENT_KEY
                    root.attributes("-alpha", self.opacity)
            else:
                root.configure(bg=_TRANSPARENT_KEY)
                self._canvas_bg = _TRANSPARENT_KEY
                try:
                    root.attributes("-transparentcolor", _TRANSPARENT_KEY)
                    self._transparent = True             # Windows: real blend
                except tk.TclError:
                    root.attributes("-alpha", self.opacity)   # e.g. Linux: dim
            self._build_widgets(tk, root)
            self._apply_platform(root)
            self._redraw()
            root.after(120, self._drain)
            root.mainloop()
        except Exception:  # noqa: BLE001 — the overlay must never crash the app
            log.debug("overlay thread failed", exc_info=True)

    def _build_widgets(self, tk, root) -> None:
        # a transparent canvas: its background is the colour key, so it renders
        # fully clear. Text is drawn directly onto it (outlined for readability
        # on any wallpaper), so the words float on your screen — no box.
        canvas = tk.Canvas(root, bg=getattr(self, "_canvas_bg", _TRANSPARENT_KEY),
                           highlightthickness=0, bd=0)
        canvas.pack(fill="both", expand=True)
        self._widgets = {"canvas": canvas}
        self._content = {"state": "idle", "heard": "", "answer": ""}
        self._answer_hide_at = None

    _OUTLINE_OFFSETS = ((-1, -1), (-1, 1), (1, -1), (1, 1),
                        (-1, 0), (1, 0), (0, -1), (0, 1), (2, 2))

    def _text(self, canvas, x: int, y: int, text: str, fill: str, font,
              width: Optional[int] = None) -> int:
        """Draw outlined text (dark halo + drop shadow behind bright glyphs) so
        it reads on light OR dark backgrounds. Returns the bottom y."""
        kw = {"anchor": "nw", "font": font, "justify": "left"}
        if width:
            kw["width"] = width
        for dx, dy in self._OUTLINE_OFFSETS:
            canvas.create_text(x + dx, y + dy, text=text, fill="#000000", **kw)
        item = canvas.create_text(x, y, text=text, fill=fill, **kw)
        box = canvas.bbox(item)
        return box[3] if box else y + 16

    def _redraw(self) -> None:  # pragma: no cover - GUI thread
        canvas = self._widgets.get("canvas")
        if canvas is None:
            return
        canvas.delete("all")
        pad, x = 10, 10
        y = 8
        wrap = self.width - 2 * pad
        color = _STATE_COLORS.get(self._content["state"], _STATE_COLORS["idle"])
        canvas.create_oval(x, y + 4, x + 11, y + 15, fill=color, outline="#000000")
        y = self._text(canvas, x + 20, y, "FRIDAY", "#e8eeff",
                       ("Segoe UI Semibold", 11)) + 5
        if self._content["heard"]:
            y = self._text(canvas, x, y, "you:  " + self._content["heard"],
                           "#cdd8f0", ("Segoe UI", 10), width=wrap) + 4
        if self._content["answer"]:
            y = self._text(canvas, x, y, self._content["answer"], "#ffffff",
                           ("Segoe UI Semibold", 11), width=wrap) + 6
        box = canvas.bbox("all")
        self._resize(int(box[3] + 8) if box else 56)

    def _resize(self, h: int) -> None:  # pragma: no cover - GUI thread
        root = self._root
        if root is None:
            return
        sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
        w, h, margin = self.width, max(48, h), 24
        x = sw - w - margin if "right" in self.corner else margin
        y = margin if "top" in self.corner else sh - h - margin - 48
        root.geometry(f"{w}x{h}+{x}+{y}")

    def _apply_platform(self, root) -> None:
        """Apply the OS-specific window magic: exclude from screen capture and
        make it click-through. Windows and macOS have different APIs; Linux has
        neither (the overlay is simply visible)."""
        import sys
        if sys.platform.startswith("win"):
            self._apply_win32(root)
        elif sys.platform == "darwin":
            self._apply_macos(root)

    def _apply_win32(self, root) -> None:
        try:
            import ctypes
            u = ctypes.windll.user32
            hwnd = u.GetParent(root.winfo_id()) or root.winfo_id()
            # exclude from screen capture / sharing (the whole point)
            if self.exclude_capture:
                ok = u.SetWindowDisplayAffinity(hwnd, _WDA_EXCLUDEFROMCAPTURE)
                if not ok:
                    u.SetWindowDisplayAffinity(hwnd, _WDA_MONITOR)   # older fallback
                self.captured_excluded = bool(ok)
            # click-through + no taskbar button
            ex = u.GetWindowLongW(hwnd, _GWL_EXSTYLE)
            ex |= _WS_EX_LAYERED | _WS_EX_TOOLWINDOW
            if self.click_through:
                ex |= _WS_EX_TRANSPARENT
            u.SetWindowLongW(hwnd, _GWL_EXSTYLE, ex)
        except Exception:  # noqa: BLE001
            log.debug("overlay win32 setup failed", exc_info=True)

    def _apply_macos(self, root) -> None:
        """macOS equivalent of the Win32 setup — UNVERIFIED (written on Windows;
        needs a real Mac). Screen-capture exclusion via NSWindow.sharingType =
        NSWindowSharingNone; click-through via ignoresMouseEvents. The NSWindow
        is located by a unique title we stamp on the Tk window."""
        try:
            token = "friday-overlay-%d" % id(self)
            root.title(token)               # a handle to find the NSWindow by
            root.update_idletasks()
            from AppKit import NSApp        # pyobjc; ships in the macOS edition
            _NSWindowSharingNone = 0
            for win in (NSApp.windows() or []):
                try:
                    if win.title() == token:
                        if self.exclude_capture:
                            win.setSharingType_(_NSWindowSharingNone)
                            self.captured_excluded = True
                        if self.click_through:
                            win.setIgnoresMouseEvents_(True)
                        win.setLevel_(3)     # NSFloatingWindowLevel ~ always on top
                        break
                except Exception:  # noqa: BLE001
                    continue
        except Exception:  # noqa: BLE001 — mac window magic is best-effort
            log.debug("overlay macOS setup failed", exc_info=True)

    def _drain(self) -> None:  # pragma: no cover - GUI thread
        import time
        dirty = False
        try:
            while True:
                self._apply(self._q.get_nowait(), now=time.time())
                dirty = True
        except queue.Empty:
            pass
        # fade the answer once its time is up
        if self._answer_hide_at is not None and time.time() > self._answer_hide_at:
            self._content["answer"] = ""
            self._answer_hide_at = None
            dirty = True
        if dirty:
            self._redraw()
        if not self._stop.is_set() and self._root is not None:
            self._root.after(150, self._drain)

    def _apply(self, event: dict, *, now: float) -> None:  # pragma: no cover
        kind = event.get("kind")
        if kind == "state":
            self._content["state"] = event.get("state", "idle")
        elif kind == "heard":
            self._content["heard"] = event.get("text", "")
        elif kind == "answer":
            self._content["answer"] = event.get("text", "")
            self._answer_hide_at = now + self.answer_ttl_s
        elif kind == "notice":
            self._content["answer"] = event.get("text", "")
            self._answer_hide_at = now + 6.0

    def status(self) -> dict:
        return {"started": self._started, "excluded_from_capture": self.captured_excluded,
                "transparent": getattr(self, "_transparent", False),
                "corner": self.corner}
