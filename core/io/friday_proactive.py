"""
friday_proactive.py — Friday 3.0
Proactive loop + screen watcher. Instead of only reacting, Friday keeps a light
eye on what you're doing and offers help at the right moment.

Built for SPEED (runs continuously without hogging the CPU):
  • Foreground WINDOW TITLE via Win32 — the highest-signal context, basically free.
  • A cheap downsampled SCREEN-CHANGE check (mss) — tells "actively working" from
    "stuck staring at it". No per-frame OCR (that's slow); OCR stays opt-in.
  • Heavy throttling: a nudge only fires when an error/stuck context PERSISTS and the
    screen is static, with a cooldown and de-dupe so she never nags.

Nudges go out as a non-intrusive notification (friday_notify) + signal-bus event.
"""

import os
import re
import sys
import time
import logging
import threading
from typing import Optional

log = logging.getLogger("friday.proactive")

_HERE = __import__("pathlib").Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

# ── config (env-tunable) ────────────────────────────────────────────────────────
INTERVAL      = int(os.environ.get("FRIDAY_PROACTIVE_INTERVAL", "25"))   # seconds/tick
STUCK_SECONDS = int(os.environ.get("FRIDAY_PROACTIVE_STUCK", "90"))      # persist before nudge
COOLDOWN      = int(os.environ.get("FRIDAY_PROACTIVE_COOLDOWN", "240"))  # min secs between nudges
USE_LLM       = os.environ.get("FRIDAY_PROACTIVE_LLM", "0") == "1"       # off = instant templated

# Window-title hints that suggest the user may be stuck / want help.
_ERROR_HINTS = ("error", "exception", "failed", "failure", "traceback",
                "cannot ", "undefined", "not found", "denied", "stack overflow",
                "bug", "warning", "fatal")


# ── fast context probes ─────────────────────────────────────────────────────────
def active_window_title() -> str:
    """Foreground window title (Win32). Near-instant. '' on failure / non-Windows."""
    try:
        import ctypes
        u = ctypes.windll.user32
        h = u.GetForegroundWindow()
        n = u.GetWindowTextLengthW(h)
        buf = ctypes.create_unicode_buffer(n + 1)
        u.GetWindowTextW(h, buf, n + 1)
        return buf.value or ""
    except Exception:
        return ""


def _screen_fingerprint() -> Optional[int]:
    """Cheap fingerprint of the screen to detect change. None if unavailable."""
    try:
        import mss
        import numpy as np
        with mss.mss() as sct:
            shot = sct.grab(sct.monitors[1])
        arr = np.frombuffer(shot.bgra, dtype=np.uint8)
        return hash(arr[::1000].tobytes())   # sparse sample = fast fingerprint
    except Exception:
        return None


# ── the watcher ─────────────────────────────────────────────────────────────────
class ProactiveWatcher:
    def __init__(self):
        self._title       = ""
        self._title_since = time.time()
        self._fp          = None
        self._screen_moved = True
        self._last_nudge  = 0.0
        self._last_sig    = ""

    def snapshot(self) -> dict:
        """Read current context (fast). Updates internal state."""
        now   = time.time()
        title = active_window_title()
        if title != self._title:
            self._title = title
            self._title_since = now

        fp = _screen_fingerprint()
        if fp is not None:
            self._screen_moved = (fp != self._fp)
            self._fp = fp

        return {
            "title":         title,
            "held_secs":     round(now - self._title_since),
            "screen_moved":  self._screen_moved,
            "looks_stuck":   self._looks_stuck(title),
        }

    @staticmethod
    def _looks_stuck(title: str) -> bool:
        t = (title or "").lower()
        return any(h in t for h in _ERROR_HINTS)

    def step(self) -> Optional[str]:
        """One proactive tick. Returns a nudge string if one was emitted."""
        snap = self.snapshot()
        now  = time.time()

        # Conditions for a nudge: an error/stuck context that has PERSISTED, the
        # screen is static (you're not actively typing), cooldown elapsed, and we
        # haven't already nudged about this exact context.
        if not snap["looks_stuck"]:
            return None
        if snap["held_secs"] < STUCK_SECONDS:
            return None
        if snap["screen_moved"]:
            return None
        if (now - self._last_nudge) < COOLDOWN:
            return None
        sig = re.sub(r"\s+", " ", snap["title"]).strip().lower()[:80]
        if sig == self._last_sig:
            return None

        msg = self._make_nudge(snap["title"])
        self._emit(msg)
        self._last_nudge = now
        self._last_sig   = sig
        return msg

    def _make_nudge(self, title: str) -> str:
        short = (title or "this").strip()[:60]
        if USE_LLM:
            try:
                from core.intelligence.service import think_text
                nudge = think_text(
                    f"The user has been on this window a while and may be stuck: "
                    f"'{title}'. In ONE short friendly sentence, proactively offer "
                    f"specific help. No preamble.",
                )
                if nudge:
                    return nudge[:200]
            except Exception as e:
                log.debug("nudge generation failed: %s", e)
        return f"You've been on “{short}” for a while — looks like an error. Want me to take a look or search it?"

    @staticmethod
    def _emit(msg: str) -> None:
        log.info("Proactive nudge: %s", msg)
        try:
            from core.io.friday_notify import FridayNotify
            FridayNotify().send(title="Friday", message=msg[:180])
        except Exception as e:
            log.debug("notify failed: %s", e)
        try:
            from core.infra.friday_signal import get_bus, Signal
            sig = getattr(Signal, "PROACTIVE", None) or getattr(Signal, "THINKING_DONE", None)
            if sig:
                get_bus().emit_sync(sig, data=msg, source="proactive")
        except Exception:
            pass


# ── background daemon ───────────────────────────────────────────────────────────
_watcher: Optional[ProactiveWatcher] = None
_stop    = threading.Event()
_thread: Optional[threading.Thread] = None


def _loop(interval: int):
    global _watcher
    _watcher = ProactiveWatcher()
    while not _stop.is_set():
        try:
            _watcher.step()
        except Exception as e:
            log.error("Proactive tick failed: %s", e)
        _stop.wait(timeout=interval)


def start(interval: int = INTERVAL) -> None:
    """Start the proactive watcher loop. Safe to call once."""
    global _thread
    if _thread and _thread.is_alive():
        return
    _stop.clear()
    _thread = threading.Thread(target=_loop, args=(interval,),
                               name="proactive", daemon=True)
    _thread.start()
    log.info("Proactive watcher started (interval=%ds, stuck=%ds, cooldown=%ds)",
             interval, STUCK_SECONDS, COOLDOWN)


def stop() -> None:
    _stop.set()
    if _thread:
        _thread.join(timeout=5)


# ── CLI ───────────────────────────────────────────────────────────────────────-
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s [%(name)s] %(message)s")
    import argparse
    ap = argparse.ArgumentParser(description="Friday proactive screen watcher")
    ap.add_argument("--once",  action="store_true", help="print one context snapshot")
    ap.add_argument("--watch", type=int, default=0, help="watch for N seconds, printing context")
    args = ap.parse_args()

    w = ProactiveWatcher()
    if args.watch:
        t0 = time.time()
        while time.time() - t0 < args.watch:
            s = w.snapshot()
            print(f"  title={s['title'][:60]!r:62} held={s['held_secs']:>4}s "
                  f"moved={s['screen_moved']} stuck={s['looks_stuck']}")
            nudge = w.step()
            if nudge:
                print("  >>> NUDGE:", nudge)
            time.sleep(3)
    else:
        s = w.snapshot()
        print("snapshot:", s)
