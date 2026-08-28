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


_START_APPS_CACHE = None


def _win_start_apps(*, tries: int = 2, timeout: int = 15) -> tuple:
    """(name_lower, display_name, AppID) for every launchable app on the Start
    menu — Store/UWP apps AND desktop apps — via `Get-StartApps`. This is how
    Windows itself enumerates what you can launch, so it finds Store apps
    (Spotify, WhatsApp, Discord) and Chrome PWAs that never register on PATH or
    under App Paths, which is exactly why raw `os.startfile('spotify.exe')` fails
    for them.

    Cached for the process (a NON-EMPTY result only — a transient PowerShell
    failure never poisons the cache). A cold PowerShell spawn during boot can be
    slow or get starved, so we give it a generous timeout and one retry: an
    empty enumeration is why 'open spotify' used to fail with 'couldn't find it'
    even though the app was installed. Empty tuple only when it truly can't run."""
    global _START_APPS_CACHE
    if _START_APPS_CACHE is not None:
        return _START_APPS_CACHE
    if not _IS_WIN:
        return ()
    import json
    for attempt in range(max(1, tries)):
        try:
            out = subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command",
                 "Get-StartApps | ConvertTo-Json -Compress"],
                capture_output=True, text=True, timeout=timeout)
            data = json.loads(out.stdout or "[]")
            if isinstance(data, dict):                   # single app → one object
                data = [data]
            apps = tuple((nm.lower(), nm, aid) for d in data
                         for nm in [(d.get("Name") or "").strip()]
                         for aid in [(d.get("AppID") or "").strip()]
                         if nm and aid)
            if apps:
                _START_APPS_CACHE = apps
                return apps
        except Exception:  # noqa: BLE001 — Start-menu enumeration is best-effort
            log.debug("Get-StartApps attempt %d failed", attempt + 1, exc_info=True)
    return ()


def warm_start_apps() -> None:
    """Pre-fetch the Start-app list in the background so it's ready BEFORE the
    owner asks to open something. Without warming, the first 'open <store app>'
    pays the cold PowerShell spawn on the turn itself and could time out."""
    if not _IS_WIN or _START_APPS_CACHE is not None:
        return
    threading.Thread(target=_win_start_apps, name="friday-warm-startapps",
                     daemon=True).start()


def _match_start_app(name: str):
    """Best Start-menu match for a spoken app name. Prefers exact name, then a
    prefix match ("spotify" → "Spotify"), then the shortest substring match
    (so "Spotify" wins over "Spotify Web Helper"). Returns (display, AppID) or
    None."""
    q = (name or "").lower().strip()
    apps = _win_start_apps()
    if not q or not apps:
        return None
    for low, disp, aid in apps:
        if low == q:
            return (disp, aid)
    hits = [(disp, aid) for low, disp, aid in apps if low.startswith(q)]
    if hits:
        return min(hits, key=lambda t: len(t[0]))
    hits = [(disp, aid) for low, disp, aid in apps if q in low]
    if hits:
        return min(hits, key=lambda t: len(t[0]))
    return None


# Process names FRIDAY must NEVER terminate on a fuzzy 'close X'. Killing any of
# these can take the desktop, the session, or FRIDAY herself down — this is the
# guard that stops a vague or MIS-HEARD close command from wrecking the machine.
_PROTECTED_PROCS = {
    "system", "system idle process", "registry", "smss", "csrss", "wininit",
    "winlogon", "services", "lsass", "svchost", "dwm", "fontdrvhost", "sihost",
    "ctfmon", "explorer", "taskmgr", "runtimebroker", "conhost", "audiodg",
    "python", "pythonw", "shellexperiencehost", "searchhost", "spoolsv",
    "startmenuexperiencehost", "textinputhost", "lockapp", "dllhost",
}

# a window whose title ends like this is a BROWSER's own window (a tab), not a
# standalone app — closing "Instagram" must not kill the whole browser and every
# other tab, so these are skipped in the title match (real PWAs are titled just
# "Instagram"/"Spotify"). Closing the browser itself still works by exe name.
_BROWSER_WINDOWS = ("google chrome", "mozilla firefox", "microsoft edge",
                    "brave", "opera", "chromium")


class FridayAction:

    def __init__(self):
        self._caps = self._probe()
        warm_start_apps()          # ready the Store/PWA app list before she's asked
        log.info("Action ready — caps: %s", self._caps)

    def _probe(self) -> dict:
        caps = {"pyautogui": False, "pygetwindow": False, "win32": False}
        try:
            caps["pyautogui"] = True
        except ImportError:
            pass
        try:
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
            "play_music":        lambda **kw: self.play_music(**kw),
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
            r = subprocess.run(["open", "-a", app], capture_output=True, text=True)
            if r.returncode != 0:                    # `open` reports a missing app
                raise FileNotFoundError(f"I couldn't find an app called '{name}'.")
            return f"Opened {name}"
        if not _IS_WIN:                              # Linux: xdg-open / direct
            subprocess.Popen([name])
            return f"Opened {name}"

        # 1) a real executable — on PATH or in the App Paths registry
        exe = _WIN_APPS.get(key, name)
        target = _resolve_win_app(exe)
        if target:
            try:
                os.startfile(target)  # noqa: S606 — launching a user-named app
            except OSError:
                subprocess.Popen(f'start "" "{target}"', shell=True)
            return f"Opened {name}"

        # 2) a Start-menu app — Store/UWP OR desktop — invisible to PATH and App
        # Paths (this is why `spotify.exe`/`discord.exe` resolve to None). Windows
        # itself launches these via the AppsFolder shell namespace by AppID.
        match = _match_start_app(name) or _match_start_app(key)
        if match:
            disp, appid = match
            subprocess.Popen(["explorer.exe", f"shell:AppsFolder\\{appid}"])
            return f"Opened {disp}"

        # 3) last resort: let ShellExecute try a file association / protocol.
        # If even that can't resolve it, FAIL HONESTLY — never claim to have
        # opened an app that isn't there (the old code returned a success string
        # here, so she'd cheerfully say "opening it" while nothing happened).
        try:
            os.startfile(exe)  # noqa: S606
            return f"Opened {name}"
        except OSError:
            raise FileNotFoundError(f"I couldn't find an app called '{name}'.")

    def play_music(self, query: str = None) -> str:
        """Actually START music, not just toggle a media key. Launches Spotify
        (the Store build or the desktop build — see open_app) and starts
        playback; with a `query` it opens that search in Spotify first. Honest:
        raises when Spotify can't be found, so she never claims to be playing
        music that never started. (The bare media key toggles nothing when no
        player has a queue — which is why 'play music' used to do nothing.)"""
        if _IS_MAC:
            r = _osa('tell application "Spotify" to play')
            if r.returncode != 0:
                raise FileNotFoundError(
                    "I couldn't find Spotify to play music.")
            return f"Playing {query} on Spotify." if query else "Playing music on Spotify."

        launched = False
        if query:                                    # spotify:search:<q> opens results
            from urllib.parse import quote
            try:
                os.startfile("spotify:search:" + quote(query))
                launched = True
            except OSError:
                launched = False
        if not launched:                             # open Spotify itself (exe/Store)
            try:
                self.open_app("spotify")
                launched = True
            except Exception:  # noqa: BLE001 — fall through to the protocol probe
                launched = False
        if not launched:                             # bare spotify: protocol
            try:
                os.startfile("spotify:")
                launched = True
            except OSError:
                launched = False
        if not launched:
            raise FileNotFoundError(
                "I couldn't find Spotify to play music. Install Spotify, or tell "
                "me which music app to use.")
        # let the app come up, then press play so sound actually starts (a
        # no-op if it's already playing; instant when Spotify was already open)
        time.sleep(2.5)
        if _IS_WIN:
            _win_media_key(0xB3)
        return f"Playing {query} on Spotify." if query else "Playing music on Spotify."

    def close_app(self, name: str) -> str:
        """Close a running app by name — the programmatic 'End task'. Finds the
        matching running processes (by executable name AND by window title, so a
        Store/PWA app like a Chrome-wrapped Spotify is caught even though there is
        no spotify.exe) and terminates them by PID with taskkill. Refuses to touch
        critical system processes, so a vague or misheard 'close ...' can never
        take the machine down. Honest: says so when nothing matched — never a fake
        'Closed'."""
        q = (name or "").strip().lower()
        if len(q) < 2:
            return "Tell me which app to close."
        if not _IS_WIN:
            r = subprocess.run(["pkill", "-f", q], capture_output=True)
            return (f"Closed {name}." if r.returncode == 0
                    else f"I couldn't find a running app called '{name}'.")
        pids, label = self._find_app_processes(q)
        if not pids:
            return f"I couldn't find a running app called '{name}'."
        killed = 0
        for pid in pids:
            # /F force, /T also ends the process tree (a PWA's renderer children);
            # argv (no shell) so a spoken name can't inject a second command
            r = subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)],
                               capture_output=True, text=True)
            if r.returncode == 0:
                killed += 1
        if killed:
            return f"Closed {label}."
        return f"I found '{name}' but couldn't close it — it may need admin rights."

    @staticmethod
    def _window_pids_matching(q: str) -> dict:
        """{pid: window_title} for every visible window whose title contains q.
        Catches Store/PWA apps that run under a generic host exe (a PWA 'Spotify'
        is a chrome.exe whose window title is just 'Spotify'). Browser windows
        (tabs) are skipped so closing an app never kills the whole browser."""
        found: dict = {}
        try:
            import ctypes
            import pygetwindow as gw
            get_pid = ctypes.windll.user32.GetWindowThreadProcessId
            for w in gw.getAllWindows():
                title = (getattr(w, "title", "") or "").strip()
                hwnd = getattr(w, "_hWnd", 0)
                low = title.lower()
                if not title or not hwnd:
                    continue
                # a standalone app/PWA window title IS the app name, optionally
                # with a suffix after a boundary ("Spotify", "Spotify - Playlist").
                # Require that boundary so "PythonProject1 - editor" does NOT match
                # "python" — that over-match once caught the IDE.
                if not (low == q or (low.startswith(q)
                                     and not low[len(q):len(q) + 1].isalnum())):
                    continue
                if any(low.endswith(b) for b in _BROWSER_WINDOWS):
                    continue                       # a browser tab, not an app
                pid = ctypes.c_ulong()
                get_pid(int(hwnd), ctypes.byref(pid))
                if pid.value:
                    found[pid.value] = title
        except Exception:  # noqa: BLE001 — window enumeration is best-effort
            log.debug("window pid match failed", exc_info=True)
        return found

    def _find_app_processes(self, q: str):
        """([pid, ...], label) for running processes matching q by exe name or
        window title, excluding protected system processes."""
        import psutil
        title_pids = self._window_pids_matching(q)
        pids: list = []
        label = ""
        for proc in psutil.process_iter(["pid", "name"]):
            try:
                pid = proc.info["pid"]
                pname = proc.info["name"] or ""
                base = pname[:-4].lower() if pname.lower().endswith(".exe") \
                    else pname.lower()
                if not base or base in _PROTECTED_PROCS or base.startswith("python"):
                    continue                       # never kill FRIDAY's own runtime
                by_name = (len(q) >= 2 and q in base) or (len(base) >= 3 and base in q)
                if by_name or pid in title_pids:
                    pids.append(pid)
                    if not label:
                        label = title_pids.get(pid) or pname
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        return pids, (label or q)

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
            log.debug("suppressed exception", exc_info=True)
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
                log.debug("suppressed exception", exc_info=True)
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
                        log.debug("suppressed exception", exc_info=True)
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