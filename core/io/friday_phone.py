"""
friday_phone.py — Friday 3.0
Phone Control. Android via ADB. iOS via shortcuts bridge.
Send messages, make calls, read notifications, control media.
"""

import sys
import time
import logging
import subprocess
import threading
from pathlib import Path
from typing import Optional

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

log = logging.getLogger("friday.phone")


class FridayPhone:

    def __init__(self):
        self._adb_ok      = False
        self._device_id   = None
        self._pending_cmds: list = []
        self._probe()

    def _probe(self) -> None:
        try:
            result = subprocess.run(
                ["adb", "devices"],
                capture_output=True, text=True, timeout=5
            )
            lines = result.stdout.strip().splitlines()
            devices = [l for l in lines[1:] if "device" in l and "offline" not in l]
            if devices:
                self._device_id = devices[0].split()[0]
                self._adb_ok    = True
                log.info("ADB device: %s", self._device_id)
            else:
                log.info("ADB: no devices connected")
        except FileNotFoundError:
            log.info("ADB not installed")
        except Exception as e:
            log.warning("ADB probe failed: %s", e)

    # ── ADB core ───────────────────────────────────────────────────────────────

    def _adb(self, *args, timeout: int = 10) -> tuple[bool, str]:
        """Run an adb command. Returns (success, output)."""
        if not self._adb_ok:
            return False, "ADB not available"
        cmd = ["adb"]
        if self._device_id:
            cmd += ["-s", self._device_id]
        cmd += list(args)
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
            out = (r.stdout or r.stderr or "").strip()
            return r.returncode == 0, out[:500]
        except subprocess.TimeoutExpired:
            return False, "ADB timeout"
        except Exception as e:
            return False, str(e)

    def _shell(self, command: str, timeout: int = 10) -> tuple[bool, str]:
        return self._adb("shell", command, timeout=timeout)

    # ── Calls ──────────────────────────────────────────────────────────────────

    def make_call(self, number: str) -> dict:
        """Initiate a phone call."""
        number = number.replace(" ", "").replace("-", "")
        ok, out = self._shell(f"am start -a android.intent.action.CALL -d tel:{number}")
        return {"ok": ok, "result": f"Calling {number}" if ok else out}

    def end_call(self) -> dict:
        ok, out = self._shell("input keyevent KEYCODE_ENDCALL")
        return {"ok": ok, "result": "Call ended" if ok else out}

    def answer_call(self) -> dict:
        ok, out = self._shell("input keyevent KEYCODE_CALL")
        return {"ok": ok, "result": "Call answered" if ok else out}

    # ── SMS ────────────────────────────────────────────────────────────────────

    def send_sms(self, number: str, message: str) -> dict:
        """Open SMS composer (ADB cannot send directly without root)."""
        number = number.replace(" ", "")
        msg    = message.replace("'", "\\'").replace('"', '\\"')
        ok, out = self._shell(
            f"am start -a android.intent.action.SENDTO "
            f"-d sms:{number} "
            f"--es sms_body '{msg}' "
            f"--ez exit_on_sent false"
        )
        return {"ok": ok, "result": f"SMS composer opened for {number}" if ok else out}

    # ── Media ──────────────────────────────────────────────────────────────────

    def play_pause(self) -> dict:
        ok, out = self._shell("input keyevent KEYCODE_MEDIA_PLAY_PAUSE")
        return {"ok": ok, "result": "Play/pause toggled" if ok else out}

    def next_track(self) -> dict:
        ok, out = self._shell("input keyevent KEYCODE_MEDIA_NEXT")
        return {"ok": ok, "result": "Next track" if ok else out}

    def prev_track(self) -> dict:
        ok, out = self._shell("input keyevent KEYCODE_MEDIA_PREVIOUS")
        return {"ok": ok, "result": "Previous track" if ok else out}

    def set_volume(self, level: int) -> dict:
        """Set media volume 0-15 (Android stream steps)."""
        level = max(0, min(15, int(level)))
        ok, out = self._shell(f"media volume --stream 3 --set {level}")
        return {"ok": ok, "result": f"Volume set to {level}/15" if ok else out}

    # ── Notifications ──────────────────────────────────────────────────────────

    def get_notifications(self) -> dict:
        """Read active notifications via dumpsys."""
        ok, out = self._shell("dumpsys notification --noredact")
        if not ok:
            return {"ok": False, "notifications": [], "error": out}
        # Parse notification titles
        notifications = []
        for line in out.splitlines():
            if "android.title=" in line:
                title = line.split("android.title=")[-1].strip().strip('"')
                if title and len(title) > 1:
                    notifications.append(title)
        return {"ok": True, "notifications": notifications[:10]}

    # ── Screen ─────────────────────────────────────────────────────────────────

    def lock_screen(self) -> dict:
        ok, out = self._shell("input keyevent KEYCODE_POWER")
        return {"ok": ok, "result": "Screen locked" if ok else out}

    def unlock_screen(self) -> dict:
        ok, _ = self._shell("input keyevent KEYCODE_WAKEUP")
        ok2, _ = self._shell("input keyevent KEYCODE_MENU")
        return {"ok": ok, "result": "Screen unlocked"}

    def screenshot(self, save_path: str = None) -> dict:
        save_path = save_path or str(Path.home() / "Desktop" / f"phone_{int(time.time())}.png")
        ok1, _ = self._shell("screencap -p /sdcard/friday_shot.png")
        if not ok1:
            return {"ok": False, "error": "screencap failed"}
        ok2, out = self._adb("pull", "/sdcard/friday_shot.png", save_path)
        return {"ok": ok2, "path": save_path if ok2 else None, "error": out if not ok2 else None}

    # ── Apps ───────────────────────────────────────────────────────────────────

    def open_app(self, package: str) -> dict:
        ok, out = self._shell(
            f"monkey -p {package} -c android.intent.category.LAUNCHER 1"
        )
        return {"ok": ok, "result": f"Opened {package}" if ok else out}

    def install_apk(self, apk_path: str) -> dict:
        ok, out = self._adb("install", "-r", apk_path, timeout=120)
        return {"ok": ok, "result": out}

    # ── Device info ────────────────────────────────────────────────────────────

    def get_battery(self) -> dict:
        ok, out = self._shell("dumpsys battery")
        if not ok:
            return {"ok": False}
        level = None
        charging = None
        for line in out.splitlines():
            if "level:" in line:
                try:
                    level = int(line.split(":")[-1].strip())
                except Exception:
                    log.debug("suppressed exception", exc_info=True)
            if "status:" in line:
                charging = "2" in line   # 2 = charging
        return {"ok": True, "level": level, "charging": charging}

    def is_connected(self) -> bool:
        return self._adb_ok

    def status(self) -> dict:
        return {
            "adb_available": self._adb_ok,
            "device_id":     self._device_id,
            "connected":     self.is_connected(),
        }


# ── Global singleton ──────────────────────────────────────────────────────────

_phone: Optional[FridayPhone] = None


def get_phone() -> FridayPhone:
    global _phone
    if _phone is None:
        _phone = FridayPhone()
    return _phone


# ── Self-test ─────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s [%(name)s] %(message)s")
    print("\n[friday_phone] Self-test...\n")
    p = FridayPhone()
    print(f"  Status: {p.status()}")
    if p.is_connected():
        print(f"  Battery: {p.get_battery()}")
        print(f"  Notifications: {p.get_notifications()}")
    else:
        print("  ○ No Android device connected via ADB")
        print("  ✓ Module loaded correctly — connect a device to test")
    print("\n[friday_phone] Done ✓\n")
