"""
core/launcher/launcher.py — FRIDAY V3 (M20)
The production launcher. It detects the OS, loads configuration, validates dependencies,
runs the ordered startup sequence, reports health, and recovers gracefully from startup
failures. It contains NO cognitive logic — it only brings the cognitive machinery up and
keeps it observable.

Usage:  python friday_launch.py [--profile production] [--headless] [--start-runtime]
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import logging
from typing import Optional

from .health import HealthMonitor
from .logging_config import configure_logging
from .platform_adapter import PlatformAdapter
from .startup import StartupSequence

log = logging.getLogger("friday.launcher")

# optional dependency groups checked at startup (missing → graceful degradation)
_OPTIONAL_DEPS = {
    "vision": ("cv2", "numpy"), "audio": ("numpy",), "voice": ("sounddevice",),
    "transcription": ("faster_whisper",), "ui": ("webview",), "metrics": ("psutil",),
}


class Launcher:
    def __init__(self, *, config: Optional[dict] = None, profile: str = "production",
                 headless: bool = True, start_runtime: bool = False) -> None:
        self.profile = profile
        self.headless = headless
        self.start_runtime = start_runtime
        self.platform = PlatformAdapter()
        self.config = self._load_config(config)
        self.report: Optional[dict] = None
        self.components: dict = {}

    # ── configuration ────────────────────────────────────────────────────────────
    def _load_config(self, override: Optional[dict]) -> dict:
        cfg: dict = {}
        path = self.platform.config_dir() / "friday_config.json"
        if path.exists():
            try:
                cfg = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                log.warning("could not read %s; using defaults", path)
        cfg.setdefault("environment", self.profile)
        if override:
            cfg.update(override)
        return cfg

    # ── dependency validation ────────────────────────────────────────────────────
    def validate_dependencies(self) -> dict:
        report = {"python": self.platform.info()["python"], "available": {}, "missing": {}}
        for group, mods in _OPTIONAL_DEPS.items():
            missing = [m for m in mods if importlib.util.find_spec(m) is None]
            (report["missing"] if missing else report["available"])[group] = missing or list(mods)
        return report

    # ── boot ─────────────────────────────────────────────────────────────────────
    def run(self) -> dict:
        self.platform.ensure_dirs()
        log_report = configure_logging(log_dir=self.platform.log_dir(),
                                       debug=(self.profile == "development"))
        deps = self.validate_dependencies()
        sequence = StartupSequence(config=self.config, headless=self.headless,
                                   start_runtime=self.start_runtime)
        startup = sequence.run()
        self.components = startup.components
        health = HealthMonitor(container=startup.components.get("kernel"),
                               runtime=startup.components.get("runtime"),
                               coordinator=startup.components.get("coordinator"),
                               simulation=startup.components.get("simulation"))
        self.report = {
            "friday": "ready" if startup.ready else "degraded",
            "profile": self.profile, "headless": self.headless,
            "platform": self.platform.info(), "logging": log_report,
            "dependencies": deps, "startup": startup.to_dict(),
            "health": health.diagnostics(),
        }
        return self.report

    # ── optional UI (guarded; never required) ────────────────────────────────────
    def start_ui(self) -> bool:
        if self.headless:
            return False
        try:
            import subprocess
            import sys
            entry = self.platform.config_dir() / "friday_app.py"
            if entry.exists():
                subprocess.Popen([sys.executable, str(entry)], cwd=str(self.platform.config_dir()))
                return True
        except Exception:  # noqa: BLE001
            log.debug("UI start failed", exc_info=True)
        return False


def main(argv: Optional[list] = None) -> int:
    parser = argparse.ArgumentParser(prog="friday", description="FRIDAY production launcher")
    parser.add_argument("--profile", default="production",
                        choices=["development", "testing", "production"])
    parser.add_argument("--headless", action="store_true", help="do not start UI/voice")
    parser.add_argument("--start-runtime", action="store_true", help="start the async runtime loop")
    parser.add_argument("--json", action="store_true", help="print the startup report as JSON")
    args = parser.parse_args(argv)

    launcher = Launcher(profile=args.profile, headless=args.headless or True,
                        start_runtime=args.start_runtime)
    report = launcher.run()
    if args.json:
        print(json.dumps(report, indent=2, default=str))
    else:
        s = report["startup"]
        print(f"FRIDAY {report['friday'].upper()} ({report['profile']}, "
              f"{report['platform']['os']}, {s['total_ms']:.0f} ms)")
        for stage in s["stages"]:
            mark = {"ok": "+", "skipped": "-", "failed": "!"}.get(stage["status"], "?")
            print(f"  [{mark}] {stage['stage']:<14} {stage['status']:<8} {stage['detail']}")
        print(f"  health: {report['health']['status']}")
    return 0 if report["friday"] == "ready" else 1
