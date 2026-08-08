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
import threading
from typing import Optional

from .first_run import FirstRunWizard
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
                 headless: bool = True, start_runtime: bool = False,
                 account_ui: bool = False) -> None:
        self.profile = profile
        self.headless = headless
        self.start_runtime = start_runtime
        self.account_ui = account_ui
        self.platform = PlatformAdapter()
        self.config = self._load_config(config)
        self.report: Optional[dict] = None
        self.components: dict = {}
        self._tray = None
        self._overlay = None
        self._shutdown = threading.Event()

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

    # ── first run (idempotent; runs the wizard only once) ────────────────────────
    def first_run(self, *, force: bool = False, groq_key: Optional[str] = None) -> dict:
        wizard = FirstRunWizard(platform=self.platform)
        return wizard.run(force=force, groq_key=groq_key).to_dict()

    # ── AI-account onboarding (first GUI launch only; never blocks headless) ─────
    def account_onboarding(self) -> dict:
        """Prompt once for the user's AI accounts (API key or linked browser seat)
        so the harness council has real subscriptions to reach. Gated to a real
        GUI launch; a marker makes it a no-op after the first time. Never raises."""
        if not self.account_ui or self.headless:
            return {"shown": False, "reason": "disabled"}
        try:
            from .account_setup import maybe_prompt
            return maybe_prompt(headless=self.headless)
        except Exception:  # noqa: BLE001 — onboarding must never take the boot down
            log.debug("account onboarding failed", exc_info=True)
            return {"shown": False, "reason": "error"}

    # ── boot ─────────────────────────────────────────────────────────────────────
    def run(self) -> dict:
        import sys
        self.platform.ensure_dirs()
        # windowless launch (pythonw) has no console — sys.stdout is None, so a
        # console log handler would crash. Log to file only in that case.
        has_console = sys.stdout is not None and sys.stderr is not None
        log_report = configure_logging(log_dir=self.platform.log_dir(),
                                       console=has_console,
                                       debug=(self.profile == "development"))
        first_run = self.first_run()               # idempotent: no-op after the first boot
        accounts = self.account_onboarding()       # first GUI launch only; keys go live now
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
            "first_run": first_run, "accounts": accounts,
            "dependencies": deps, "startup": startup.to_dict(),
            "health": health.diagnostics(),
        }
        return self.report

    # ── diagnostics (operator view of the live components) ───────────────────────
    def diagnostics(self) -> dict:
        from .diagnostics import Diagnostics
        return Diagnostics(components=self.components).report()

    # ── the app surface (guarded; never required) ────────────────────────────────
    def start_ui(self) -> str:
        """Bring up FRIDAY's app surface. `ui.mode` config picks it:
          tray  (default) — a system-tray presence (icon + mute + quit +
                            notifications); voice-first, no browser, no console
          hud             — the legacy cinematic HUD (Flask + Edge WebView2)
          none            — headless-resident (voice only)
        Returns the surface actually started ("tray" | "hud" | "none")."""
        if self.headless:
            return "none"
        ui = self.config.get("ui") or {}
        # the private overlay (M51) is an ADDITIONAL layer — it runs alongside
        # whatever surface, so you always see her state + answers on-screen
        # (and it's excluded from screen shares). Default on.
        self._start_overlay(ui.get("overlay"))
        mode = str(ui.get("mode", "tray")).lower()
        if mode == "tray" and self._start_tray():
            return "tray"
        if mode == "hud" and self._start_hud():
            return "hud"
        if mode == "tray":                       # tray asked but unavailable → HUD
            return "hud" if self._start_hud() else "none"
        return "none"

    def _start_overlay(self, cfg) -> bool:
        cfg = cfg if isinstance(cfg, dict) else {}
        if cfg.get("enabled", True) is False:
            return False
        try:
            from core.io.overlay import Overlay, available
            if not available():
                return False
            overlay = Overlay(
                corner=cfg.get("corner", "top-right"),
                opacity=float(cfg.get("opacity", 0.9)),
                exclude_capture=bool(cfg.get("exclude_capture", True)),
                click_through=bool(cfg.get("click_through", True)))
            if not overlay.start():
                return False
            self._overlay = overlay
            bridge = self.components.get("conversation")
            if bridge is not None:
                bridge.overlay = overlay         # her answers flow onto the layer
            overlay.set_state("idle")
            overlay.notice("FRIDAY is online.")
            return True
        except Exception:  # noqa: BLE001 — the overlay never blocks the app
            log.debug("overlay start failed", exc_info=True)
            return False

    def _start_tray(self) -> bool:
        try:
            from core.io.tray import TrayApp, available, notify
            if not available():
                return False
            listening = self.components.get("listening")
            self._tray = TrayApp(
                listening=listening,
                on_quit=self._request_shutdown,
                open_logs=self._open_log_dir)
            if self._tray.start():
                notify("FRIDAY", "I'm online and listening.")
                return True
        except Exception:  # noqa: BLE001
            log.debug("tray start failed", exc_info=True)
        return False

    def _start_hud(self) -> bool:
        try:
            import subprocess
            import sys
            entry = self.platform.config_dir() / "friday_app.py"
            if entry.exists():
                subprocess.Popen([sys.executable, str(entry)],
                                 cwd=str(self.platform.config_dir()))
                return True
        except Exception:  # noqa: BLE001
            log.debug("HUD start failed", exc_info=True)
        return False

    def _open_log_dir(self) -> None:
        import os
        import subprocess
        import sys
        log_dir = self.platform.data_dir() / "logs"
        try:
            if sys.platform.startswith("win"):
                os.startfile(str(log_dir))       # noqa: S606 — user-initiated
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(log_dir)])
            else:
                subprocess.Popen(["xdg-open", str(log_dir)])
        except Exception:  # noqa: BLE001
            log.debug("open log dir failed", exc_info=True)

    def _request_shutdown(self) -> None:
        """Tray 'Quit' → end the process cleanly."""
        self._shutdown.set()


def main(argv: Optional[list] = None) -> int:
    parser = argparse.ArgumentParser(prog="friday", description="FRIDAY production launcher")
    parser.add_argument("--profile", default="production",
                        choices=["development", "testing", "production"])
    parser.add_argument("--headless", action="store_true", help="do not start UI/voice")
    parser.add_argument("--start-runtime", action="store_true", help="start the async runtime loop")
    parser.add_argument("--json", action="store_true", help="print the startup report as JSON")
    parser.add_argument("--diagnostics", action="store_true",
                        help="boot, then print the diagnostics screen and exit")
    parser.add_argument("--first-run", action="store_true",
                        help="run the first-run wizard interactively and exit")
    args = parser.parse_args(argv)

    if args.first_run:
        from .first_run import main as first_run_main
        return first_run_main([])            # interactive wizard, then exit

    # the account-setup window belongs only to a real resident launch — never in
    # --json/--diagnostics (machine-readable) or --headless boots
    account_ui = not (args.headless or args.json or args.diagnostics)
    launcher = Launcher(profile=args.profile, headless=args.headless,
                        start_runtime=args.start_runtime or not args.headless,
                        account_ui=account_ui)
    report = launcher.run()
    if args.diagnostics:
        print(launcher.diagnostics() if args.json else "")
        from .diagnostics import Diagnostics
        print(Diagnostics(components=launcher.components).render())
        return 0 if report["friday"] == "ready" else 1
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

    ready = report["friday"] == "ready"
    # non-headless boots stay resident: the voice loop, runtime scheduler and
    # background cognition live on daemon threads and die with the process,
    # so exiting after the report would silently take FRIDAY down with it
    if ready and not args.headless:
        surface = launcher.start_ui()
        print(f"  app surface: {surface}")
        print("  FRIDAY is running — quit from the tray, or Ctrl+C here.", flush=True)
        try:
            launcher._shutdown.wait()             # tray 'Quit' sets this
        except KeyboardInterrupt:
            print("shutting down.")
        finally:
            if launcher._tray is not None:
                launcher._tray.stop()
            if launcher._overlay is not None:
                launcher._overlay.stop()
    return 0 if ready else 1
