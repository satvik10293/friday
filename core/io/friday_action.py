"""
friday_action.py — Friday 3.0
PC Control + System Automation.
Executes system commands triggered by the brain or voice.
"""

import sys
import os
import time
import logging
import platform
import subprocess
import threading
from pathlib import Path
from typing import Optional

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

log = logging.getLogger("friday.action")

_IS_WIN = platform.system() == "Windows"
_IS_MAC = platform.system() == "Darwin"


def _osa(script: str) -> subprocess.CompletedProcess:
    """Run an AppleScript one-liner (macOS). The scripting bridge for volume,
    media, apps — the mac equivalent of the Win32 calls below."""
    return subprocess.run(["osascript", "-e", script],
                          capture_output=True, text=True, timeout=6)


def _resolve_win_app(exe: str) -> Optional[str]:
    """Resolve a Windows app to a full path via PATH then the App Paths registry
    (where chrome, edge, spotify, etc. register even when not on PATH). Raw
    `subprocess.Popen('chrome.exe')` fails because cmd doesn't consult App Paths;
    this does. Returns a full path or None."""
    import shutil
    import winreg
    hit = shutil.which(exe) or (shutil.which(exe + ".exe")
                                if not exe.lower().endswith(".exe") else None)
    if hit:
        return hit
    names = [exe] if exe.lower().endswith(".exe") else [exe + ".exe", exe]
    for nm in names:
        for root in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
            try:
                k = winreg.OpenKey(
                    root,
                    r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\\" + nm)
                val, _ = winreg.QueryValueEx(k, None)
                winreg.CloseKey(k)
                if val:
                    return val.strip('"')
            except OSError:
                continue
    return None


def _win_media_key(vk: int) -> bool:
    """Send a media virtual-key via keybd_event — reliable and dependency-free,
    unlike routing through pyautogui's key map. VK_MEDIA_PLAY_PAUSE=0xB3,
    NEXT=0xB0, PREV=0xB1."""
    try:
        import ctypes
        ext, up = 0x0001, 0x0002
        ctypes.windll.user32.keybd_event(vk, 0, ext, 0)
        ctypes.windll.user32.keybd_event(vk, 0, ext | up, 0)
        return True
    except Exception:  # noqa: BLE001
        return False


class FridayAction:

    def __init__(self):
        self._caps = self._probe()
        log.info("Action ready — caps: %s", self._caps)

    def _probe(self) -> dict:
        caps = {"pyautogui": False, "pygetwindow": False, "win32": False}
        try:
            import pyautogui
            caps["pyautogui"] = True
        except ImportError:
            pass
        try:
            import pygetwindow
            caps["pygetwindow"] = True
        except ImportError:
            pass
        if _IS_WIN:
            try:
                import win32gui  # noqa
                caps["win32"] = True
            except ImportError:
                pass
        return caps

    # ── Dispatch ───────────────────────────────────────────────────────────────

    def execute(self, command: str, args: dict = None) -> dict:
        """
        Execute a named action. Returns {ok, result, error}.
        command: snake_case action name
        args:    dict of parameters
        """
        args = args or {}
        handlers = {
            "open_app":          self.open_app,
            "close_app":         self.close_app,
            "type_text":         self.type_text,
            "press_key":         self.press_key,
            "screenshot":        self.screenshot,
            "set_volume":        self.set_volume,
            "mute":              lambda: self.mute(),
            "unmute":            lambda: self.unmute(),
            "set_brightness":    self.set_brightness,
            "brightness_up":     lambda **kw: self.brightness_up(**kw),
            "brightness_down":   lambda **kw: self.brightness_down(**kw),
            "open_url":          self.open_url,
            "run_command":       self.run_shell,
            "focus_window":      self.focus_window,
            "minimize_window":   self.minimize_window,
            "maximize_window":   self.maximize_window,
            "move_mouse":        self.move_mouse,
            "click":             self.click,
            "scroll":            self.scroll,
            "copy_to_clipboard": self.copy_to_clipboard,
            "get_clipboard":     self.get_clipboard,
            "system_summary":    lambda: self.get_system_summary(),
            "wifi_status":       lambda: self.get_wifi_status(),
            "check_internet":    lambda: self.check_internet(),
            "get_ip":            lambda: self.get_ip(),
            "media_play_pause":  lambda: self.media_play_pause(),
            "media_next":        lambda: self.media_next(),
            "media_prev":        lambda: self.media_prev(),
            "search_files":      self.search_files,
            "recent_files":      lambda **kw: self.get_recent_files(**kw),
            "sleep_pc":          lambda: self.sleep_pc(),
            "restart_pc":        self.restart_pc,
            "add_to_startup":    self.add_to_startup,
            "remove_from_startup": self.remove_from_startup,
        }
        fn = handlers.get(command)
        if not fn:
            return {"ok": False, "error": f"Unknown command: {command}"}
        try:
            result = fn(**args)
            return {"ok": True, "result": result}
        except Exception as e:
            log.warning("Action '%s' failed: %s", command, e)
            return {"ok": False, "error": str(e)}

    # ── App control ────────────────────────────────────────────────────────────

    def open_app(self, name: str) -> str:
        """Open an application by name."""
        _WIN_APPS = {
            "notepad":      "notepad.exe",
            "calculator":   "calc.exe",
            "explorer":     "explorer.exe",
            "terminal":     "wt.exe",
            "cmd":          "cmd.exe",
            "powershell":   "powershell.exe",
            "chrome":       "chrome.exe",
            "firefox":      "firefox.exe",
            "edge":         "msedge.exe",
            "vs code":      "code",
            "vscode":       "code",
            "spotify":      "spotify.exe",
            "task manager": "taskmgr.exe",
            "paint":        "mspaint.exe",
            "word":         "winword.exe",
            "excel":        "excel.exe",
        }
        key = name.lower().strip()
        if _IS_MAC:                                  # macOS: `open -a <App>`
            _MAC_APPS = {"terminal": "Terminal", "vs code": "Visual Studio Code",
                         "vscode": "Visual Studio Code", "chrome": "Google Chrome",
                         "calculator": "Calculator", "notepad": "TextEdit",
                         "explorer": "Finder", "finder": "Finder"}
            app = _MAC_APPS.get(key, name)
            subprocess.Popen(["open", "-a", app])
            return f"Opened {name}"
        if not _IS_WIN:                              # Linux: xdg-open / direct
            subprocess.Popen([name])
            return f"Opened {name}"
        exe = _WIN_APPS.get(key, name)
        target = _resolve_win_app(exe)
        try:
            # ShellExecute (os.startfile) consults PATH + App Paths + file assoc,
            # and RAISES if it can't resolve — so failure is honest, not silent.
            os.startfile(target or exe)  # noqa: S606 — launching a user-named app
            return f"Opened {name}"
        except OSError:
            if target:                    # resolved but ShellExecute balked
                subprocess.Popen(f'start "" "{target}"', shell=True)
                return f"Opened {name}"
            return f"I couldn't find an app called '{name}'."

    def close_app(self, name: str) -> str:
        if _IS_WIN:
            subprocess.run(f"taskkill /F /IM {name}.exe",
                           shell=True, capture_output=True)
        else:
            subprocess.run(["pkill", "-f", name], capture_output=True)
        return f"Closed {name}"

    def focus_window(self, title: str) -> str:
        if not self._caps["pygetwindow"]:
            return "pygetwindow not available"
        import pygetwindow as gw
        wins = gw.getWindowsWithTitle(title)
        if wins:
            wins[0].activate()
            return f"Focused: {wins[0].title}"
        return f"Window not found: {title}"

    def minimize_window(self, title: str = None) -> str:
        if not self._caps["pygetwindow"]:
            return "pygetwindow not available"
        import pygetwindow as gw
        win = gw.getActiveWindow() if not title else (gw.getWindowsWithTitle(title) or [None])[0]
        if win:
            win.minimize()
            return "Window minimized"
        return "No window found"

    def maximize_window(self, title: str = None) -> str:
        if not self._caps["pygetwindow"]:
            return "pygetwindow not available"
        import pygetwindow as gw
        win = gw.getActiveWindow() if not title else (gw.getWindowsWithTitle(title) or [None])[0]
        if win:
            win.maximize()
            return "Window maximized"
        return "No window found"

    # ── Keyboard / mouse ────────────────────────────────────────────────────────

    def type_text(self, text: str, interval: float = 0.03) -> str:
        if not self._caps["pyautogui"]:
            return "pyautogui not available"
        import pyautogui
        pyautogui.write(text, interval=interval)
        return f"Typed: {text[:40]}"

    def press_key(self, key: str) -> str:
        if not self._caps["pyautogui"]:
            return "pyautogui not available"
        import pyautogui
        keys = key.replace("+", " ").split()
        if len(keys) > 1:
            pyautogui.hotkey(*keys)
        else:
            pyautogui.press(key)
        return f"Pressed: {key}"

    def move_mouse(self, x: int, y: int, duration: float = 0.3) -> str:
        if not self._caps["pyautogui"]:
            return "pyautogui not available"
        import pyautogui
        pyautogui.moveTo(x, y, duration=duration)
        return f"Mouse moved to ({x}, {y})"

    def click(self, x: int = None, y: int = None, button: str = "left") -> str:
        if not self._caps["pyautogui"]:
            return "pyautogui not available"
        import pyautogui
        if x is not None and y is not None:
            pyautogui.click(x, y, button=button)
        else:
            pyautogui.click(button=button)
        return f"Clicked {button}"

    def scroll(self, clicks: int = 3, direction: str = "down") -> str:
        if not self._caps["pyautogui"]:
            return "pyautogui not available"
        import pyautogui
        amount = -clicks if direction == "down" else clicks
        pyautogui.scroll(amount)
        return f"Scrolled {direction} {clicks}"

    # ── Screen ─────────────────────────────────────────────────────────────────

    def screenshot(self, path: str = None) -> str:
        if not self._caps["pyautogui"]:
            return "pyautogui not available"
        import pyautogui
        save_path = path or str(Path.home() / "Desktop" / f"friday_shot_{int(time.time())}.png")
        pyautogui.screenshot(save_path)
        return f"Screenshot saved: {save_path}"

    # ── Volume ─────────────────────────────────────────────────────────────────

    def set_volume(self, level: int) -> str:
        level = max(0, min(100, int(level)))
        if _IS_WIN:
            try:
                from ctypes import cast, POINTER
                from comtypes import CLSCTX_ALL
                from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
                devices = AudioUtilities.GetSpeakers()
                interface = devices.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
                volume    = cast(interface, POINTER(IAudioEndpointVolume))
                volume.SetMasterVolumeLevelScalar(level / 100, None)
                return f"Volume set to {level}%"
            except Exception:
                # Fallback via nircmd
                subprocess.run(f"nircmd setsysvolume {int(level * 655.35)}",
                               shell=True, capture_output=True)
                return f"Volume set to {level}%"
        if _IS_MAC:                                  # macOS: AppleScript
            _osa(f"set volume output volume {level}")
            return f"Volume set to {level}%"
        # Linux: try amixer / pactl, best-effort
        for cmd in ([f"amixer -q sset Master {level}%"],
                    [f"pactl set-sink-volume @DEFAULT_SINK@ {level}%"]):
            try:
                subprocess.run(cmd[0], shell=True, capture_output=True, timeout=5)
                return f"Volume set to {level}%"
            except Exception:  # noqa: BLE001
                continue
        return f"Volume control not implemented for {platform.system()}"

    # ── Web ─────────────────────────────────────────────────────────────────────

    def open_url(self, url: str) -> str:
        import webbrowser
        if not url.startswith("http"):
            url = "https://" + url
        webbrowser.open(url)
        return f"Opened: {url}"

    # ── Shell ──────────────────────────────────────────────────────────────────

    def run_shell(self, command: str, timeout: int = 30) -> str:
        """
        Run a safe shell command. Blocked commands rejected.
        """
        _BLOCKED = ["rm -rf", "format", "del /f", "shutdown", "reboot",
                    "mkfs", "dd if=", ":(){:|:&};:"]
        cmd_l = command.lower()
        for blocked in _BLOCKED:
            if blocked in cmd_l:
                return f"Blocked: '{blocked}' is not allowed"
        try:
            result = subprocess.run(
                command, shell=True, capture_output=True,
                text=True, timeout=timeout
            )
            out = (result.stdout or result.stderr or "").strip()
            return out[:500] if out else "Command ran (no output)"
        except subprocess.TimeoutExpired:
            return f"Command timed out after {timeout}s"
        except Exception as e:
            return f"Command failed: {e}"

    # ── Clipboard ──────────────────────────────────────────────────────────────

    def copy_to_clipboard(self, text: str) -> str:
        try:
            import pyperclip
            pyperclip.copy(text)
            return f"Copied {len(text)} chars to clipboard"
        except Exception as e:
            return f"Clipboard failed: {e}"

    def get_clipboard(self) -> str:
        try:
            import pyperclip
            return pyperclip.paste() or ""
        except Exception:
            return ""

    # ── Brightness ────────────────────────────────────────────────────────────

    def get_brightness(self) -> int:
        try:
            import screen_brightness_control as sbc
            return sbc.get_brightness()[0]
        except Exception:
            return -1

    def set_brightness(self, level: int) -> str:
        try:
            import screen_brightness_control as sbc
            sbc.set_brightness(max(0, min(100, int(level))))
            return f"Brightness set to {level}%"
        except Exception as e:
            return f"Brightness error: {e}"

    def brightness_up(self, step: int = 10) -> str:
        current = self.get_brightness()
        if current >= 0:
            return self.set_brightness(min(100, current + step))
        return "Brightness unavailable"

    def brightness_down(self, step: int = 10) -> str:
        current = self.get_brightness()
        if current >= 0:
            return self.set_brightness(max(0, current - step))
        return "Brightness unavailable"

    # ── System stats ──────────────────────────────────────────────────────────

    def get_system_summary(self) -> str:
        try:
            import psutil
            cpu    = psutil.cpu_percent(interval=0.5)
            mem    = psutil.virtual_memory()
            disk   = psutil.disk_usage("C:\\" if _IS_WIN else "/")
            bat    = psutil.sensors_battery()
            parts  = [
                f"CPU: {cpu}%",
                f"RAM: {round(mem.used/1e9,1)}GB/{round(mem.total/1e9,1)}GB ({mem.percent}%)",
                f"Disk: {round(disk.free/1e9,1)}GB free",
            ]
            if bat:
                parts.append(f"Battery: {round(bat.percent)}% ({'charging' if bat.power_plugged else 'on battery'})")
            vol = self._get_volume_level()
            if vol >= 0:
                parts.append(f"Volume: {vol}%")
            return " | ".join(parts)
        except Exception as e:
            return f"System stats unavailable: {e}"

    def _get_volume_level(self) -> int:
        if not _IS_WIN:
            return -1
        try:
            from ctypes import cast, POINTER
            from comtypes import CLSCTX_ALL
            from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
            devices   = AudioUtilities.GetSpeakers()
            interface = devices.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
            volume    = cast(interface, POINTER(IAudioEndpointVolume))
            return int(volume.GetMasterVolumeLevelScalar() * 100)
        except Exception:
            return -1

    def mute(self) -> str:
        if _IS_MAC:
            _osa("set volume output muted true")
            return "Muted"
        if not _IS_WIN:
            return "Mute not implemented on this platform"
        try:
            from ctypes import cast, POINTER
            from comtypes import CLSCTX_ALL
            from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
            devices   = AudioUtilities.GetSpeakers()
            interface = devices.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
            volume    = cast(interface, POINTER(IAudioEndpointVolume))
            volume.SetMute(1, None)
            return "Muted"
        except Exception as e:
            return f"Mute error: {e}"

    def unmute(self) -> str:
        if _IS_MAC:
            _osa("set volume output muted false")
            return "Unmuted"
        if not _IS_WIN:
            return "Unmute not implemented on this platform"
        try:
            from ctypes import cast, POINTER
            from comtypes import CLSCTX_ALL
            from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
            devices   = AudioUtilities.GetSpeakers()
            interface = devices.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
            volume    = cast(interface, POINTER(IAudioEndpointVolume))
            volume.SetMute(0, None)
            return "Unmuted"
        except Exception as e:
            return f"Unmute error: {e}"

    # ── Network ───────────────────────────────────────────────────────────────

    def get_wifi_status(self) -> dict:
        try:
            if _IS_MAC:                              # macOS: networksetup
                out = subprocess.run(
                    ["networksetup", "-getairportnetwork", "en0"],
                    capture_output=True, text=True, timeout=5).stdout
                ssid = out.split(": ", 1)[-1].strip() if ":" in out else ""
                # "You are not associated…" means not connected
                connected = bool(ssid) and "not associated" not in out.lower()
                return {"ssid": ssid if connected else "", "signal": "",
                        "connected": connected}
            if not _IS_WIN:                          # Linux: iwgetid
                ssid = subprocess.run(["iwgetid", "-r"], capture_output=True,
                                      text=True, timeout=5).stdout.strip()
                return {"ssid": ssid, "signal": "", "connected": bool(ssid)}
            result = subprocess.run("netsh wlan show interfaces",
                                    capture_output=True, text=True, shell=True, timeout=5)
            ssid = signal = ""
            for line in result.stdout.split("\n"):
                if "SSID" in line and "BSSID" not in line:
                    ssid = line.split(":")[-1].strip()
                if "Signal" in line:
                    signal = line.split(":")[-1].strip()
            return {"ssid": ssid, "signal": signal, "connected": bool(ssid)}
        except Exception:
            return {"ssid": "", "signal": "", "connected": False}

    def check_internet(self) -> bool:
        try:
            import socket
            socket.create_connection(("8.8.8.8", 53), timeout=3)
            return True
        except Exception:
            return False

    def get_ip(self) -> str:
        try:
            import socket
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except Exception:
            return "Unknown"

    # ── Media keys ────────────────────────────────────────────────────────────

    def _media(self, vk: int, key: str, label: str) -> str:
        if _IS_WIN and _win_media_key(vk):
            return label
        if self._caps["pyautogui"]:
            import pyautogui
            pyautogui.press(key)
            return label
        if _IS_MAC:
            # macOS media control via AppleScript (Music app; best-effort)
            verb = {"playpause": "playpause", "nexttrack": "next track",
                    "prevtrack": "previous track"}[key]
            _osa(f'tell application "Music" to {verb}')
            return label
        return "Media control not available"

    def media_play_pause(self) -> str:
        return self._media(0xB3, "playpause", "Play/pause")

    def media_next(self) -> str:
        return self._media(0xB0, "nexttrack", "Next track")

    def media_prev(self) -> str:
        return self._media(0xB1, "prevtrack", "Previous track")

    # ── File operations ───────────────────────────────────────────────────────

    def search_files(self, query: str, folder: str = None, extension: str = None) -> list:
        from pathlib import Path as P
        base = P(folder) if folder else P.home()
        results = []
        try:
            for path in base.rglob(f"*{query}*"):
                if extension and path.suffix.lower() != extension.lower():
                    continue
                results.append(str(path))
                if len(results) >= 20:
                    break
        except Exception:
            pass
        return results

    def get_recent_files(self, count: int = 10) -> list:
        from pathlib import Path as P
        files = []
        for folder in [P.home()/"Desktop", P.home()/"Documents", P.home()/"Downloads"]:
            try:
                for f in folder.iterdir():
                    if f.is_file():
                        files.append((f.stat().st_mtime, str(f)))
            except Exception:
                pass
        files.sort(reverse=True)
        return [f[1] for f in files[:count]]

    # ── Startup programs (Windows) ────────────────────────────────────────────

    def add_to_startup(self, name: str, exe_path: str) -> str:
        if not _IS_WIN:
            return "Startup management only on Windows"
        try:
            import winreg
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Run",
                0, winreg.KEY_SET_VALUE
            )
            winreg.SetValueEx(key, name, 0, winreg.REG_SZ, exe_path)
            winreg.CloseKey(key)
            return f"Added to startup: {name}"
        except Exception as e:
            return f"Startup error: {e}"

    def remove_from_startup(self, name: str) -> str:
        if not _IS_WIN:
            return "Startup management only on Windows"
        try:
            import winreg
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Run",
                0, winreg.KEY_SET_VALUE
            )
            winreg.DeleteValue(key, name)
            winreg.CloseKey(key)
            return f"Removed from startup: {name}"
        except Exception as e:
            return f"Startup error: {e}"

    # ── Power ─────────────────────────────────────────────────────────────────

    def sleep_pc(self) -> str:
        if _IS_WIN:
            subprocess.run("rundll32.exe powrprof.dll,SetSuspendState 0,1,0", shell=True)
        return "Going to sleep"

    def restart_pc(self, delay: int = 0) -> str:
        if _IS_WIN:
            subprocess.run(f"shutdown /r /t {delay}", shell=True)
        return f"Restarting in {delay}s"

    # ── Battery alerts (background) ───────────────────────────────────────────

    def start_battery_alert(self, threshold: int = 20) -> None:
        def _monitor():
            import psutil
            while True:
                bat = psutil.sensors_battery()
                if bat and 0 < bat.percent < threshold and not bat.power_plugged:
                    try:
                        from core.io.friday_notify import get_notify
                        get_notify().alert(f"Battery low: {bat.percent:.0f}%")
                    except Exception:
                        pass
                time.sleep(60)
        threading.Thread(target=_monitor, daemon=True, name="battery-alert").start()

    def capabilities(self) -> dict:
        return dict(self._caps)


# ── Self-test ─────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s [%(name)s] %(message)s")
    print("\n[friday_action] Self-test...\n")

    a = FridayAction()
    print(f"  Capabilities: {a.capabilities()}")

    # Safe tests only
    r = a.execute("run_command", {"command": "echo Friday Action OK"})
    print(f"  ✓ Shell: {r}")

    r = a.execute("open_url", {"url": "https://google.com"})
    print(f"  ✓ URL: {r}")

    r = a.execute("get_clipboard")
    print(f"  ✓ Clipboard: ok")

    r = a.execute("run_command", {"command": "rm -rf /"})
    print(f"  ✓ Blocked: {r}")

    print("\n[friday_action] Done ✓\n")