"""
Output Module — On-Screen Signal Overlay.

A small always-on-top window that sits in the corner of your screen and
shows the latest recommendation in big color-coded text:

    BUY   -> green
    SELL  -> red
    HOLD  -> orange
    WAIT  -> gray

It also shows the live price each cycle, the confidence score, the top
reasons behind the call, and when it was last updated. On a fresh BUY or
SELL signal the panel flashes a few times to catch your eye.

Same safety rules as the rest of the project: this module only DISPLAYS
information. It never clicks, types, or touches the trading platform.

Uses tkinter (ships with Python on Windows — no extra install). All tkinter
calls happen inside one background thread; the main loop talks to it
through a thread-safe queue, so displaying never blocks the observe loop.

Drag the panel anywhere with the mouse. Double-click it to minimize to a
thin bar; double-click again to restore.
"""

from __future__ import annotations

import queue
import threading
import time
from dataclasses import dataclass
from typing import Optional

from recommend_recommendation_engine import Recommendation

# Panel color scheme (matches the Athena dashboard palette)
_BG = "#0b0f14"
_CARD = "#11161d"
_TEXT = "#d6dce3"
_MUTED = "#8894a3"

_ACTION_COLORS = {
    "BUY": "#22c55e",
    "SELL": "#ef4444",
    "HOLD": "#f59e0b",
    "WAIT": "#64748b",
}

_MAX_REASONS_SHOWN = 3


@dataclass
class _PriceUpdate:
    symbol: str
    price: float
    change_pct: Optional[float]


@dataclass
class _RecUpdate:
    rec: Recommendation
    price: Optional[float]


class ScreenAlert:
    """Always-on-top signal panel, driven from a background tkinter thread."""

    def __init__(self, width: int = 320):
        self._width = width
        self._queue: "queue.Queue" = queue.Queue()
        self._stop_event = threading.Event()
        self._last_action: Optional[str] = None
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    # ---- public API (safe to call from any thread) -----------------------

    def update_price(self, symbol: str, price: float, change_pct: Optional[float] = None) -> None:
        """Refresh the live price line (called every observe cycle)."""
        self._queue.put(_PriceUpdate(symbol, price, change_pct))

    def show(self, rec: Recommendation, price: Optional[float] = None) -> None:
        """Display a new recommendation on the panel."""
        self._queue.put(_RecUpdate(rec, price))

    def stop(self) -> None:
        self._stop_event.set()
        self._thread.join(timeout=5)

    # ---- tkinter thread ---------------------------------------------------

    def _run(self) -> None:
        import tkinter as tk

        root = tk.Tk()
        root.overrideredirect(True)          # frameless
        root.attributes("-topmost", True)    # always on top
        root.configure(bg=_BG)

        # Start in the top-right corner, just below the top edge
        full_height = 280
        screen_w = root.winfo_screenwidth()
        root.geometry(f"{self._width}x{full_height}+{screen_w - self._width - 20}+40")

        card = tk.Frame(root, bg=_CARD, highlightbackground=_ACTION_COLORS["WAIT"],
                        highlightthickness=2)
        card.pack(fill="both", expand=True, padx=2, pady=2)

        header = tk.Label(card, text="TRADING ASSISTANT", font=("Segoe UI", 8, "bold"),
                          fg=_MUTED, bg=_CARD, anchor="w")
        header.pack(fill="x", padx=10, pady=(8, 0))

        action_lbl = tk.Label(card, text="WAIT", font=("Segoe UI", 30, "bold"),
                              fg=_ACTION_COLORS["WAIT"], bg=_CARD)
        action_lbl.pack(pady=(0, 0))

        symbol_lbl = tk.Label(card, text="starting...", font=("Segoe UI", 11, "bold"),
                              fg=_TEXT, bg=_CARD)
        symbol_lbl.pack()

        conf_lbl = tk.Label(card, text="", font=("Segoe UI", 9),
                            fg=_MUTED, bg=_CARD)
        conf_lbl.pack()

        plan_lbl = tk.Label(card, text="", font=("Consolas", 9),
                            fg=_TEXT, bg=_CARD, justify="center")
        plan_lbl.pack(pady=(2, 0))

        reasons_lbl = tk.Label(card, text="waiting for first signal...",
                               font=("Segoe UI", 8), fg=_MUTED, bg=_CARD,
                               justify="left", wraplength=self._width - 30)
        reasons_lbl.pack(padx=10, pady=(4, 0))

        updated_lbl = tk.Label(card, text="", font=("Segoe UI", 7),
                               fg=_MUTED, bg=_CARD)
        updated_lbl.pack(side="bottom", pady=(0, 6))

        # ---- dragging -------------------------------------------------
        drag = {"x": 0, "y": 0}

        def on_press(event):
            drag["x"], drag["y"] = event.x, event.y

        def on_drag(event):
            root.geometry(f"+{event.x_root - drag['x']}+{event.y_root - drag['y']}")

        # ---- minimize/restore on double-click --------------------------
        minimized = {"on": False}

        def toggle_minimize(_event):
            minimized["on"] = not minimized["on"]
            geo = root.geometry().split("+")
            pos = f"+{geo[1]}+{geo[2]}"
            if minimized["on"]:
                root.geometry(f"{self._width}x28{pos}")
            else:
                root.geometry(f"{self._width}x{full_height}{pos}")

        for widget in (card, header, action_lbl, symbol_lbl, conf_lbl, plan_lbl, reasons_lbl):
            widget.bind("<ButtonPress-1>", on_press)
            widget.bind("<B1-Motion>", on_drag)
            widget.bind("<Double-Button-1>", toggle_minimize)

        # ---- flash effect for fresh BUY/SELL ---------------------------
        def flash(color: str, times: int = 6):
            def step(n):
                if n <= 0:
                    card.configure(highlightbackground=color)
                    return
                current = card.cget("highlightbackground")
                card.configure(highlightbackground=_CARD if current == color else color)
                root.after(250, step, n - 1)

            step(times)

        # ---- apply updates from the queue -------------------------------
        state = {"symbol": "", "price_text": ""}

        def apply_price(upd: _PriceUpdate):
            state["symbol"] = upd.symbol
            change = "" if upd.change_pct is None else f"  ({upd.change_pct:+.2f}%)"
            state["price_text"] = f"{upd.symbol}  {upd.price:.2f}{change}"
            symbol_lbl.configure(text=state["price_text"])

        def apply_rec(upd: _RecUpdate):
            rec = upd.rec
            color = _ACTION_COLORS.get(rec.action, _ACTION_COLORS["WAIT"])
            action_lbl.configure(text=rec.action, fg=color)
            conf_lbl.configure(text=f"Confidence: {rec.confidence:.0f}%")

            plan = getattr(rec, "plan", None)
            if plan is not None:
                plan_lines = [
                    f"SL {plan.stop_loss:.2f}   TGT {plan.target:.2f}",
                    f"risk {plan.risk_per_share:.2f} ({plan.risk_pct:.1f}%)   R:R 1:{plan.rr_ratio:.1f}",
                ]
                if plan.est_win_rate is not None:
                    plan_lines.append(
                        f"win rate {plan.est_win_rate * 100:.0f}%   "
                        f"exp {plan.expected_pnl_per_share:+.2f}/sh"
                    )
                plan_lbl.configure(text="\n".join(plan_lines))
            else:
                plan_lbl.configure(text="")

            shown = rec.reasons[:_MAX_REASONS_SHOWN]
            reasons_lbl.configure(text="\n".join(f"• {r}" for r in shown))
            updated_lbl.configure(text=time.strftime("signal @ %H:%M:%S"))

            if upd.price is not None:
                apply_price(_PriceUpdate(rec.symbol, upd.price, None))

            # Flash only when the call changes to an actionable BUY/SELL
            if rec.action in ("BUY", "SELL") and rec.action != self._last_action:
                flash(color)
            else:
                card.configure(highlightbackground=color)
            self._last_action = rec.action

        def poll():
            if self._stop_event.is_set():
                root.destroy()
                return
            try:
                while True:
                    item = self._queue.get_nowait()
                    if isinstance(item, _PriceUpdate):
                        apply_price(item)
                    elif isinstance(item, _RecUpdate):
                        apply_rec(item)
            except queue.Empty:
                pass
            root.after(200, poll)

        root.after(200, poll)
        try:
            root.mainloop()
        except Exception as exc:  # pragma: no cover - display/driver dependent
            print(f"[SCREEN ALERT] overlay stopped: {exc}")


# ---- quick manual test -----------------------------------------------------

if __name__ == "__main__":
    sample = Recommendation(
        symbol="RELIANCE.NS",
        action="BUY",
        confidence=81.0,
        reasons=[
            "Uptrend confirmed (price > SMA20 > SMA50)",
            "Volume increasing vs recent average",
            "Similar trend_continuation setup won 14 of last 20 times",
        ],
    )

    overlay = ScreenAlert()
    overlay.update_price("RELIANCE.NS", 2954.35, +1.24)
    time.sleep(2)
    overlay.show(sample, price=2954.35)
    time.sleep(8)

    sample_sell = Recommendation(
        symbol="RELIANCE.NS",
        action="SELL",
        confidence=66.0,
        reasons=["Downtrend confirmed (price < SMA20 < SMA50)",
                 "RSI overbought (74.2) — potential pullback"],
    )
    overlay.show(sample_sell, price=2941.10)
    time.sleep(8)
    overlay.stop()
