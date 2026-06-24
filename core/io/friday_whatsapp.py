"""
friday_whatsapp.py — Friday 3.0
WhatsApp Assistant. Send messages, reply, read incoming.
Two backends:
  1. pywhatkit  — web.whatsapp.com via browser (PC)
  2. ADB        — WhatsApp on connected Android device
"""

import sys
import time
import logging
import threading
from pathlib import Path
from typing import Optional

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

log = logging.getLogger("friday.whatsapp")


class FridayWhatsApp:

    def __init__(self):
        self._cap_pywhatkit = False
        self._cap_adb       = False
        self._phone         = None
        self._probe()

    def _probe(self) -> None:
        try:
            import pywhatkit  # noqa
            self._cap_pywhatkit = True
            log.info("pywhatkit available")
        except ImportError:
            pass

        try:
            from core.io.friday_phone import get_phone
            p = get_phone()
            if p.is_connected():
                self._phone     = p
                self._cap_adb   = True
                log.info("ADB phone connected for WhatsApp")
        except Exception:
            pass

    # ── Send ─────────────────────────────────────────────────────────────────

    def send_message(
        self,
        number:  str,
        message: str,
        method:  str = "auto",   # auto / web / adb
    ) -> dict:
        """
        Send a WhatsApp message.
        number: E.164 format e.g. +919876543210
        """
        number = self._clean_number(number)

        if method == "auto":
            method = "adb" if self._cap_adb else "web"

        if method == "web" and self._cap_pywhatkit:
            return self._send_web(number, message)
        elif method == "adb" and self._cap_adb:
            return self._send_adb(number, message)
        else:
            return {"ok": False, "error": "No WhatsApp backend available. Install pywhatkit or connect a phone via ADB."}

    def _send_web(self, number: str, message: str) -> dict:
        """Send via web.whatsapp.com using pywhatkit."""
        try:
            import pywhatkit as pwk
            now       = time.localtime()
            send_hour = now.tm_hour
            send_min  = now.tm_min + 1
            if send_min >= 60:
                send_hour = (send_hour + 1) % 24
                send_min  = send_min - 60
            pwk.sendwhatmsg(
                number,
                message,
                send_hour,
                send_min,
                wait_time         = 15,
                tab_close         = True,
                close_time        = 3,
            )
            return {"ok": True, "result": f"Message queued for {number} via WhatsApp Web"}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def _send_adb(self, number: str, message: str) -> dict:
        """Open WhatsApp on phone via ADB and compose message."""
        if not self._phone:
            return {"ok": False, "error": "No phone connected"}
        # Open WhatsApp chat via deep link
        result = self._phone.open_app("com.whatsapp")
        time.sleep(2)
        # Use Android intent to open specific chat
        ok, out = self._phone._shell(
            f"am start -a android.intent.action.VIEW "
            f"-d 'https://api.whatsapp.com/send?phone={number}&text={message}'"
        )
        return {
            "ok":     ok,
            "result": f"WhatsApp opened for {number}" if ok else out
        }

    # ── Scheduled send ────────────────────────────────────────────────────────

    def send_at(
        self,
        number:    str,
        message:   str,
        hour:      int,
        minute:    int,
    ) -> dict:
        """Schedule a WhatsApp message."""
        try:
            import pywhatkit as pwk
            number = self._clean_number(number)
            pwk.sendwhatmsg(
                number, message, hour, minute,
                wait_time=15, tab_close=True, close_time=3
            )
            return {"ok": True, "result": f"Scheduled for {hour:02d}:{minute:02d}"}
        except ImportError:
            return {"ok": False, "error": "pywhatkit not installed"}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    # ── Group message ─────────────────────────────────────────────────────────

    def send_to_group(self, group_name: str, message: str) -> dict:
        try:
            import pywhatkit as pwk
            pwk.sendwhatmsg_to_group(
                group_name, message,
                time.localtime().tm_hour,
                time.localtime().tm_min + 1,
                wait_time=15, tab_close=True
            )
            return {"ok": True, "result": f"Message sent to group: {group_name}"}
        except ImportError:
            return {"ok": False, "error": "pywhatkit not installed"}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    # ── Read notifications (ADB) ──────────────────────────────────────────────

    def get_messages(self) -> dict:
        """Read WhatsApp notifications from connected phone."""
        if not self._phone:
            return {"ok": False, "messages": [], "error": "No phone connected"}
        result = self._phone.get_notifications()
        if not result["ok"]:
            return {"ok": False, "messages": []}
        # Filter WhatsApp notifications
        wa_msgs = [n for n in result["notifications"]
                   if any(w in n.lower() for w in ("whatsapp", "wa", "message"))]
        return {"ok": True, "messages": wa_msgs}

    # ── Utility ───────────────────────────────────────────────────────────────

    def _clean_number(self, number: str) -> str:
        """Ensure number starts with + and has no spaces."""
        number = number.replace(" ", "").replace("-", "")
        if not number.startswith("+"):
            number = "+" + number
        return number

    def is_available(self) -> bool:
        return self._cap_pywhatkit or self._cap_adb

    def status(self) -> dict:
        return {
            "pywhatkit":  self._cap_pywhatkit,
            "adb":        self._cap_adb,
            "available":  self.is_available(),
        }


# ── Global singleton ──────────────────────────────────────────────────────────

_wa: Optional[FridayWhatsApp] = None


def get_whatsapp() -> FridayWhatsApp:
    global _wa
    if _wa is None:
        _wa = FridayWhatsApp()
    return _wa


# ── Self-test ─────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s [%(name)s] %(message)s")
    print("\n[friday_whatsapp] Self-test...\n")
    wa = FridayWhatsApp()
    print(f"  Status: {wa.status()}")
    if not wa.is_available():
        print("  ○ No WhatsApp backend available")
        print("  Install pywhatkit: pip install pywhatkit")
        print("  Or connect an Android phone via ADB")
    else:
        print("  ✓ WhatsApp backend ready")
    print("\n[friday_whatsapp] Done ✓\n")
