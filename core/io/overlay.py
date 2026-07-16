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
            root.attributes("-alpha", self.opacity)
            root.configure(bg=_TRANSPARENT_KEY)
            try:
                root.attributes("-transparentcolor", _TRANSPARENT_KEY)
            except tk.TclError:
                pass                                     # non-Windows: solid bg
            self._build_widgets(tk, root)
            self._place(root)
            self._apply_win32(root)
            root.after(120, self._drain)
            root.mainloop()
        except Exception:  # noqa: BLE001 — the overlay must never crash the app
            log.debug("overlay thread failed", exc_info=True)

    def _build_widgets(self, tk, root) -> None:
        card = tk.Frame(root, bg="#0e1524", bd=0, highlightthickness=0)
        card.pack(fill="both", expand=True, padx=2, pady=2)
        dot = tk.Label(card, text="●", fg=_STATE_COLORS["idle"], bg="#0e1524",
                       font=("Segoe UI", 11))
        dot.grid(row=0, column=0, sticky="w", padx=(8, 4), pady=(6, 0))
        name = tk.Label(card, text="FRIDAY", fg="#cdd6ff", bg="#0e1524",
                        font=("Segoe UI Semibold", 10))
        name.grid(row=0, column=1, sticky="w", pady=(6, 0))
        heard = tk.Label(card, text="", fg="#8fa0c8", bg="#0e1524",
                         font=("Segoe UI", 9), wraplength=self.width - 30,
                         justify="left", anchor="w")
        heard.grid(row=1, column=0, columnspan=2, sticky="we", padx=8, pady=(2, 0))
        answer = tk.Label(card, text="", fg="#eef2ff", bg="#0e1524",
                          font=("Segoe UI", 10), wraplength=self.width - 30,
                          justify="left", anchor="w")
        answer.grid(row=2, column=0, columnspan=2, sticky="we", padx=8, pady=(2, 8))
        card.grid_columnconfigure(1, weight=1)
        self._widgets = {"card": card, "dot": dot, "heard": heard, "answer": answer}
        self._answer_hide_at = None

    def _place(self, root) -> None:
        root.update_idletasks()
        sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
        w = self.width
        h = max(90, root.winfo_reqheight())
        margin = 24
        x = sw - w - margin if "right" in self.corner else margin
        y = margin if "top" in self.corner else sh - h - margin - 48
        root.geometry(f"{w}x{h}+{x}+{y}")

    def _apply_win32(self, root) -> None:
        import sys
        if not sys.platform.startswith("win"):
            return
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

    def _drain(self) -> None:  # pragma: no cover - GUI thread
        import time
        try:
            while True:
                event = self._q.get_nowait()
                self._apply(event, now=time.time())
        except queue.Empty:
            pass
        # fade the answer once its time is up
        if self._answer_hide_at is not None and time.time() > self._answer_hide_at:
            self._widgets["answer"].config(text="")
            self._answer_hide_at = None
        if not self._stop.is_set() and self._root is not None:
            self._root.after(150, self._drain)

    def _apply(self, event: dict, *, now: float) -> None:  # pragma: no cover
        kind = event.get("kind")
        w = self._widgets
        if kind == "state":
            color = _STATE_COLORS.get(event.get("state", "idle"), _STATE_COLORS["idle"])
            w["dot"].config(fg=color)
        elif kind == "heard":
            w["heard"].config(text="“" + event.get("text", "") + "”")
        elif kind == "answer":
            w["answer"].config(text=event.get("text", ""))
            self._answer_hide_at = now + self.answer_ttl_s
        elif kind == "notice":
            w["answer"].config(text=event.get("text", ""))
            self._answer_hide_at = now + 6.0
        self._place(self._root)

    def status(self) -> dict:
        return {"started": self._started, "excluded_from_capture": self.captured_excluded,
                "corner": self.corner}
