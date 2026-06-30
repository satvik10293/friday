"""
core/launcher/platform_adapter.py — FRIDAY V3 (M20)
The small, single place that knows about operating-system differences. The rest of FRIDAY
stays one Python codebase; only path conventions, shortcut creation, and the like live
here. Everything is resolved at runtime (never hardcoded) and overridable via environment
variables, so the same code runs on Windows, macOS, and Linux.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]


def detect_os() -> str:
    if sys.platform.startswith("win"):
        return "windows"
    if sys.platform == "darwin":
        return "macos"
    return "linux"


class PlatformAdapter:
    """Per-OS paths + integration helpers. Defaults favour a self-contained project-local
    layout (dev); production installs can point the dirs elsewhere via env vars."""

    def __init__(self, *, app_name: str = "FRIDAY") -> None:
        self.os = detect_os()
        self.app_name = app_name

    # ── directories (env-overridable; OS conventions; no hardcoded absolute paths) ─
    def data_dir(self) -> Path:
        env = os.environ.get("FRIDAY_DATA_DIR")
        if env:
            return Path(env)
        if self.os == "windows":
            base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        elif self.os == "macos":
            base = str(Path.home() / "Library" / "Application Support")
        else:
            base = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
        # in development, prefer the repo's data/ so nothing leaks outside the project
        if os.environ.get("FRIDAY_ENV", "development") == "development":
            return _ROOT / "data"
        return Path(base) / self.app_name

    def config_dir(self) -> Path:
        env = os.environ.get("FRIDAY_CONFIG_DIR")
        return Path(env) if env else _ROOT

    def log_dir(self) -> Path:
        env = os.environ.get("FRIDAY_LOG_DIR")
        return Path(env) if env else (self.data_dir() / "logs")

    def ensure_dirs(self) -> None:
        for d in (self.data_dir(), self.log_dir()):
            try:
                d.mkdir(parents=True, exist_ok=True)
            except OSError:
                pass

    # ── desktop integration (best-effort; never fatal) ───────────────────────────
    def create_shortcut(self, *, target: str, name: str, args: str = "") -> bool:
        """Create a desktop shortcut to launch FRIDAY. Best-effort per OS; returns
        whether it was created. Never raises."""
        try:
            desktop = Path.home() / "Desktop"
            if not desktop.exists():
                return False
            if self.os == "windows":
                lnk = desktop / f"{name}.lnk"
                ps = (f"$s=(New-Object -ComObject WScript.Shell).CreateShortcut('{lnk}');"
                      f"$s.TargetPath='{sys.executable}';$s.Arguments='{target} {args}';"
                      f"$s.WorkingDirectory='{_ROOT}';$s.Save()")
                import subprocess
                subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                               capture_output=True, timeout=15)
                return lnk.exists()
            # macOS / Linux: a simple shell launcher on the Desktop
            script = desktop / f"{name}.command" if self.os == "macos" else desktop / f"{name}.sh"
            script.write_text(f"#!/bin/sh\ncd '{_ROOT}'\nexec '{sys.executable}' {target} {args}\n",
                              encoding="utf-8")
            os.chmod(script, 0o755)
            return True
        except Exception:  # noqa: BLE001 — desktop integration is optional
            return False

    def info(self) -> dict:
        return {"os": self.os, "python": sys.version.split()[0], "executable": sys.executable,
                "data_dir": str(self.data_dir()), "log_dir": str(self.log_dir()),
                "config_dir": str(self.config_dir())}
