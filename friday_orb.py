"""
friday_orb.py — FRIDAY's minimal cross-platform launcher (floating orb).

A tiny, always-on-top, frameless glowing orb you can drag anywhere on screen. Click it to
launch FRIDAY; right-click for a menu. Pure standard-library Tkinter — no extra
dependencies — and it degrades gracefully across Windows, macOS, and Linux (true circular
transparency on Windows; soft-alpha elsewhere). It is a *launcher only*: it spawns the
existing entry points (`friday_app.py` → `friday_spine.py`) in a subprocess and never
imports `core`, so it cannot affect the architecture and starts instantly.

Run:   python friday_orb.py
Config (optional env):
    FRIDAY_LAUNCH_CMD   shell command to launch FRIDAY (default: python friday_app.py)
    FRIDAY_ORB_SIZE     orb diameter in px (default: 110)
"""

from __future__ import annotations

import os
import shlex
import subprocess
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent
_KEY = "#000001"                      # near-black chroma key for Windows transparency

# status → orb colours (core, glow)
_PALETTE = {
    "idle": ("#19d3ff", "#0a6f88"),
    "launching": ("#ffc14d", "#8a6311"),
    "running": ("#36e27b", "#147a40"),
    "error": ("#ff5468", "#7a1622"),
}


def _default_cmd() -> list:
    env = os.environ.get("FRIDAY_LAUNCH_CMD")
    if env:
        return shlex.split(env)
    entry = "friday_app.py" if (_ROOT / "friday_app.py").exists() else "friday_spine.py"
    return [sys.executable, str(_ROOT / entry)]


class FridayOrb:
    def __init__(self, root) -> None:
        import tkinter as tk
        self.tk = tk
        self.root = root
        self.size = int(os.environ.get("FRIDAY_ORB_SIZE", "110"))
        self.status = "idle"
        self.process: "subprocess.Popen | None" = None
        self._pulse = 0.0
        self._pulse_dir = 1.0
        self._drag = (0, 0)
        self._press = (0, 0)

        root.title("FRIDAY")
        root.overrideredirect(True)                  # frameless
        root.attributes("-topmost", True)            # always on top
        self._enable_transparency()
        # place near the bottom-right by default
        sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
        root.geometry(f"{self.size}x{self.size}+{sw - self.size - 40}+{sh - self.size - 80}")

        self.canvas = tk.Canvas(root, width=self.size, height=self.size,
                                highlightthickness=0, bg=self._bg)
        self.canvas.pack()
        self._bind()
        self._menu = self._build_menu()
        self._animate()

    # ── platform transparency (graceful per OS) ──────────────────────────────────
    def _enable_transparency(self) -> None:
        self._bg = _KEY
        try:
            if sys.platform.startswith("win"):
                self.root.attributes("-transparentcolor", _KEY)   # true round orb
            elif sys.platform == "darwin":
                self.root.attributes("-transparent", True)
                self._bg = "systemTransparent"
                self.root.config(bg=self._bg)
            else:                                                  # Linux: soft alpha
                self.root.attributes("-alpha", 0.92)
                self._bg = "#0b0f14"
        except Exception:                                          # noqa: BLE001
            self._bg = "#0b0f14"                                   # opaque fallback

    # ── drawing + animation ──────────────────────────────────────────────────────
    def _animate(self) -> None:
        self._pulse += 0.06 * self._pulse_dir
        if self._pulse >= 1.0 or self._pulse <= 0.0:
            self._pulse_dir *= -1.0
        self._draw()
        self.root.after(40, self._animate)

    def _draw(self) -> None:
        c = self.canvas
        c.delete("all")
        cx = cy = self.size / 2
        core, glow = _PALETTE.get(self.status, _PALETTE["idle"])
        # outer glow rings (fade out), pulsing
        rings = 5
        for i in range(rings, 0, -1):
            r = (self.size / 2) * (i / rings) * (0.78 + 0.18 * self._pulse)
            shade = _blend(glow, self._bg if self._bg.startswith("#") else "#0b0f14",
                           i / (rings + 1))
            c.create_oval(cx - r, cy - r, cx + r, cy + r, fill=shade, outline="")
        # core orb + highlight
        r = self.size * 0.26
        c.create_oval(cx - r, cy - r, cx + r, cy + r, fill=core, outline="")
        hr = r * 0.4
        c.create_oval(cx - r * 0.45 - hr, cy - r * 0.45 - hr,
                      cx - r * 0.45 + hr, cy - r * 0.45 + hr, fill="#ffffff", outline="")

    # ── interaction ──────────────────────────────────────────────────────────────
    def _bind(self) -> None:
        self.canvas.bind("<ButtonPress-1>", self._on_press)
        self.canvas.bind("<B1-Motion>", self._on_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_release)
        self.canvas.bind("<Double-Button-1>", lambda e: self.launch())
        self.canvas.bind("<Button-3>", self._on_menu)
        self.root.bind("<Escape>", lambda e: self.quit())

    def _on_press(self, e) -> None:
        self._drag = (e.x, e.y)
        self._press = (e.x_root, e.y_root)

    def _on_drag(self, e) -> None:
        x = self.root.winfo_x() + (e.x - self._drag[0])
        y = self.root.winfo_y() + (e.y - self._drag[1])
        self.root.geometry(f"+{x}+{y}")

    def _on_release(self, e) -> None:
        moved = abs(e.x_root - self._press[0]) + abs(e.y_root - self._press[1])
        if moved < 5:                                # a tap, not a drag → launch/toggle
            self.launch()

    def _build_menu(self):
        m = self.tk.Menu(self.root, tearoff=0)
        m.add_command(label="Launch FRIDAY", command=self.launch)
        m.add_command(label="Open HUD (browser backend)", command=self.open_hud)
        m.add_separator()
        m.add_command(label="Quit", command=self.quit)
        return m

    def _on_menu(self, e) -> None:
        try:
            self._menu.tk_popup(e.x_root, e.y_root)
        finally:
            self._menu.grab_release()

    # ── actions (launcher only — spawns existing entry points) ───────────────────
    def launch(self) -> None:
        if self.process is not None and self.process.poll() is None:
            self._set_status("running")             # already running
            return
        self._set_status("launching")
        try:
            self.process = subprocess.Popen(_default_cmd(), cwd=str(_ROOT))
            self.root.after(1500, self._check_process)
        except Exception:                            # noqa: BLE001
            self._set_status("error")

    def open_hud(self) -> None:
        try:
            subprocess.Popen([sys.executable, "-m", "core.io.friday_face"], cwd=str(_ROOT))
        except Exception:                            # noqa: BLE001
            self._set_status("error")

    def _check_process(self) -> None:
        if self.process is None:
            return
        code = self.process.poll()
        self._set_status("error" if (code is not None and code != 0) else
                         "idle" if code == 0 else "running")

    def _set_status(self, status: str) -> None:
        self.status = status

    def quit(self) -> None:
        try:
            self.root.destroy()
        except Exception:                            # noqa: BLE001
            pass


def _blend(a: str, b: str, t: float) -> str:
    ar, ag, ab = _rgb(a)
    br, bg, bb = _rgb(b)
    return "#%02x%02x%02x" % (int(ar + (br - ar) * t), int(ag + (bg - ag) * t),
                              int(ab + (bb - ab) * t))


def _rgb(h: str):
    h = h.lstrip("#")
    if len(h) != 6:
        return (11, 15, 20)
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def main() -> int:
    try:
        import tkinter as tk
    except Exception as e:                           # noqa: BLE001 — headless / no Tk
        print(f"[FRIDAY orb] Tkinter unavailable ({e}). On Linux install python3-tk.")
        print("Launch FRIDAY directly:", " ".join(_default_cmd()))
        return 1
    root = tk.Tk()
    FridayOrb(root)
    try:
        root.mainloop()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
