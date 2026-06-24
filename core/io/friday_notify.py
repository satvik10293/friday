"""
friday_notify.py — Friday 3.0
Notifications. Windows toast + system tray alerts.
Fallback to print if platform libs unavailable.
"""

import sys
import time
import logging
import platform
import threading
from pathlib import Path
from typing import Optional
from dataclasses import dataclass, field

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

log = logging.getLogger("friday.notify")

_IS_WIN = platform.system() == "Windows"


@dataclass
class Notification:
    title:    str
    message:  str
    duration: int   = 5       # seconds
    urgency:  str   = "normal"  # low / normal / critical
    icon:     Optional[str] = None
    callback: Optional[object] = None
    timestamp: float = field(default_factory=time.time)


class FridayNotify:

    def __init__(self):
        self._cap_toast   = False
        self._cap_plyer   = False
        self._cap_tray    = False
        self._queue:  list[Notification] = []
        self._lock    = threading.Lock()
        self._probe()
        log.info("Notify ready — toast=%s plyer=%s",
                 self._cap_toast, self._cap_plyer)

    def _probe(self) -> None:
        if _IS_WIN:
            try:
                from win10toast import ToastNotifier  # noqa
                self._cap_toast = True
            except ImportError:
                pass
        try:
            from plyer import notification  # noqa
            self._cap_plyer = True
        except ImportError:
            pass

    # ── Send ─────────────────────────────────────────────────────────────────

    def send(
        self,
        title:    str,
        message:  str,
        duration: int  = 5,
        urgency:  str  = "normal",
        icon:     Optional[str] = None,
    ) -> bool:
        """
        Send a desktop notification.
        Tries: win10toast → plyer → print fallback.
        Non-blocking — runs in background thread.
        """
        n = Notification(title=title, message=message,
                         duration=duration, urgency=urgency, icon=icon)
        threading.Thread(target=self._dispatch, args=(n,),
                         daemon=True, name="notify").start()
        return True

    def _dispatch(self, n: Notification) -> None:
        try:
            if _IS_WIN and self._cap_toast:
                self._send_toast(n)
            elif self._cap_plyer:
                self._send_plyer(n)
            else:
                self._send_print(n)
            with self._lock:
                self._queue.append(n)
                if len(self._queue) > 100:
                    self._queue = self._queue[-50:]
        except Exception as e:
            log.warning("Notification dispatch failed: %s", e)
            self._send_print(n)

    def _send_toast(self, n: Notification) -> None:
        from win10toast import ToastNotifier
        toaster = ToastNotifier()
        toaster.show_toast(
            n.title,
            n.message,
            duration   = n.duration,
            threaded   = True,
            icon_path  = n.icon,
        )

    def _send_plyer(self, n: Notification) -> None:
        from plyer import notification
        notification.notify(
            title       = n.title,
            message     = n.message,
            timeout     = n.duration,
            app_name    = "Friday",
        )

    def _send_print(self, n: Notification) -> None:
        urgency_prefix = {"critical": "🔴", "normal": "🔔", "low": "💬"}.get(n.urgency, "🔔")
        print(f"\n{urgency_prefix} [{n.title}] {n.message}")

    # ── Shortcuts ─────────────────────────────────────────────────────────────

    def alert(self, message: str) -> None:
        self.send("Friday", message, urgency="critical")

    def info(self, message: str) -> None:
        self.send("Friday", message, urgency="normal")

    def reminder(self, message: str, delay_seconds: int = 0) -> None:
        """Send a notification after a delay."""
        def _delayed():
            if delay_seconds > 0:
                time.sleep(delay_seconds)
            self.send("Reminder", message, urgency="normal", duration=10)
        threading.Thread(target=_delayed, daemon=True).start()

    def schedule(self, message: str, at_timestamp: float) -> None:
        """Send a notification at a specific Unix timestamp."""
        delay = max(0, at_timestamp - time.time())
        self.reminder(message, delay_seconds=int(delay))

    def recent(self, limit: int = 10) -> list:
        with self._lock:
            return list(self._queue[-limit:])

    def capabilities(self) -> dict:
        return {
            "win10toast": self._cap_toast,
            "plyer":      self._cap_plyer,
            "platform":   platform.system(),
        }


# ── Global singleton ──────────────────────────────────────────────────────────

_notify: Optional[FridayNotify] = None


def get_notify() -> FridayNotify:
    global _notify
    if _notify is None:
        _notify = FridayNotify()
    return _notify


# ── Self-test ─────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s [%(name)s] %(message)s")
    print("\n[friday_notify] Self-test...\n")

    n = FridayNotify()
    print(f"  Capabilities: {n.capabilities()}")

    n.info("Friday notify test — info")
    time.sleep(0.2)
    n.alert("Friday notify test — alert")
    time.sleep(0.2)
    n.reminder("Friday reminder test", delay_seconds=1)
    time.sleep(1.5)

    print(f"  ✓ Sent {len(n.recent())} notifications")
    print("\n[friday_notify] Done ✓\n")
