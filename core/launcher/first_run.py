"""
core/launcher/first_run.py — FRIDAY V3 (RC1)
The first-run wizard. On the very first launch (no first-run marker present) it verifies
the environment the user just installed into — operating system, Python runtime, and the
audio/vision devices FRIDAY can use — captures the (temporary) Groq reasoning key SECURELY
into a gitignored `.env`, writes the initial configuration, and records that first-run
completed so it never blocks subsequent launches.

Design rules (same as the rest of the launcher):
  * side-effect-free to import (no device probing, no I/O at import time),
  * never-raises: every probe is guarded and degrades to an "unknown"/"absent" result,
  * secrets are never printed, logged, embedded, or committed — only written to `.env`,
  * fully headless-capable: `run()` accepts an injected key + non-interactive mode so it
    is deterministic and testable.

CLI:  python -m core.launcher.first_run          (interactive)
      python -m core.launcher.first_run --json    (report only, non-interactive)
"""

from __future__ import annotations

import importlib.util
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from .platform_adapter import PlatformAdapter, detect_os

log = logging.getLogger("friday.launcher.first_run")

_MARKER_NAME = "first_run.json"          # written under the data dir once first-run completes


@dataclass
class CheckResult:
    name: str
    status: str                          # ok | warn | absent | unknown | failed
    detail: str = ""

    def to_dict(self) -> dict:
        return {"name": self.name, "status": self.status, "detail": self.detail}


@dataclass
class FirstRunReport:
    completed: bool = False
    already_done: bool = False
    checks: list = field(default_factory=list)
    secret_configured: bool = False
    config_written: bool = False
    marker: str = ""

    def ok(self) -> bool:
        # first-run "succeeds" as long as the runtime is usable; devices are advisory only
        runtime = next((c for c in self.checks if c.name == "runtime"), None)
        return runtime is not None and runtime.status == "ok"

    def to_dict(self) -> dict:
        return {"completed": self.completed, "already_done": self.already_done,
                "ok": self.ok(), "secret_configured": self.secret_configured,
                "config_written": self.config_written, "marker": self.marker,
                "checks": [c.to_dict() for c in self.checks]}


class FirstRunWizard:
    """Runs the one-time environment verification + secure key capture. Reuses the
    PlatformAdapter for all path/OS conventions so it behaves identically to the launcher."""

    def __init__(self, *, root: Optional[Path] = None,
                 platform: Optional[PlatformAdapter] = None) -> None:
        self.platform = platform or PlatformAdapter()
        self.root = Path(root) if root else self.platform.config_dir()

    # ── marker (idempotency) ─────────────────────────────────────────────────────
    def marker_path(self) -> Path:
        return self.platform.data_dir() / _MARKER_NAME

    def is_first_run(self) -> bool:
        return not self.marker_path().exists()

    # ── environment checks (all best-effort, never raise) ────────────────────────
    def check_os(self) -> CheckResult:
        return CheckResult("os", "ok", detect_os())

    def check_runtime(self) -> CheckResult:
        import sys
        v = sys.version_info
        ok = (v.major, v.minor) >= (3, 10)
        return CheckResult("runtime", "ok" if ok else "failed",
                           f"Python {v.major}.{v.minor}.{v.micro}"
                           + ("" if ok else " (3.10+ required)"))

    def check_microphone(self) -> CheckResult:
        return self._probe_audio(kind="input", name="microphone")

    def check_speakers(self) -> CheckResult:
        return self._probe_audio(kind="output", name="speakers")

    def check_camera(self) -> CheckResult:
        """Camera is optional; absence is not a failure (headless / no webcam)."""
        if importlib.util.find_spec("cv2") is None:
            return CheckResult("camera", "absent", "opencv not installed (vision optional)")
        try:
            import cv2  # type: ignore
            cap = cv2.VideoCapture(0)
            try:
                opened = bool(cap.isOpened())
            finally:
                cap.release()
            return CheckResult("camera", "ok" if opened else "absent",
                               "camera detected" if opened else "no camera device")
        except Exception as e:  # noqa: BLE001
            return CheckResult("camera", "unknown", f"probe error: {type(e).__name__}")

    def _probe_audio(self, *, kind: str, name: str) -> CheckResult:
        if importlib.util.find_spec("sounddevice") is None:
            return CheckResult(name, "absent", "sounddevice not installed (voice optional)")
        try:
            import sounddevice as sd  # type: ignore
            devices = sd.query_devices()
            key = "max_input_channels" if kind == "input" else "max_output_channels"
            count = sum(1 for d in devices if int(d.get(key, 0)) > 0)
            return CheckResult(name, "ok" if count else "warn",
                               f"{count} {kind} device(s)" if count
                               else f"no {kind} device found")
        except Exception as e:  # noqa: BLE001
            return CheckResult(name, "unknown", f"probe error: {type(e).__name__}")

    def run_checks(self) -> list:
        return [self.check_os(), self.check_runtime(), self.check_microphone(),
                self.check_speakers(), self.check_camera()]

    # ── secure key capture + config ──────────────────────────────────────────────
    def configure_secret(self, groq_key: Optional[str], *,
                         env_path: Optional[Path] = None) -> bool:
        """Persist the Groq key to a gitignored `.env`. Returns whether a key was written.
        The key value is never returned, printed, or logged."""
        if not groq_key or not groq_key.strip():
            return False
        env = Path(env_path) if env_path else (self.root / ".env")
        try:
            lines = []
            if env.exists():
                lines = [ln for ln in env.read_text(encoding="utf-8").splitlines()
                         if not ln.startswith("GROQ_API_KEY=")]
            lines.append(f"GROQ_API_KEY={groq_key.strip()}")
            env.write_text("\n".join(lines) + "\n", encoding="utf-8")
            try:
                env.chmod(0o600)
            except OSError:
                pass
            log.info("[FirstRun] reasoning key stored securely in .env")
            return True
        except OSError as e:
            log.warning("[FirstRun] could not write .env: %s", e)
            return False

    def write_config(self) -> bool:
        """Ensure a friday_config.json exists so the app has non-secret settings. Never
        overwrites an existing config; never stores secrets here."""
        cfg = self.root / "friday_config.json"
        if cfg.exists():
            return True
        try:
            cfg.write_text(json.dumps({"owner_name": "Satvik", "environment": "production"},
                                      indent=2), encoding="utf-8")
            return True
        except OSError:
            return False

    def _write_marker(self, report: FirstRunReport) -> str:
        path = self.marker_path()
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            payload = {"completed": True, "os": detect_os(),
                       "checks": [c.to_dict() for c in report.checks]}
            path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
            return str(path)
        except OSError as e:
            log.warning("[FirstRun] could not write marker: %s", e)
            return ""

    # ── orchestration ────────────────────────────────────────────────────────────
    def run(self, *, groq_key: Optional[str] = None, force: bool = False,
            key_prompt: Optional[Callable[[], Optional[str]]] = None) -> FirstRunReport:
        """Run the wizard. `groq_key` injects the key non-interactively (tests / installer);
        `key_prompt` supplies an interactive callback; `force` re-runs even if the marker
        exists. Always returns a report; never raises."""
        if not force and not self.is_first_run():
            return FirstRunReport(completed=True, already_done=True,
                                  marker=str(self.marker_path()))
        self.platform.ensure_dirs()
        report = FirstRunReport(checks=self.run_checks())
        report.config_written = self.write_config()
        if groq_key is None and key_prompt is not None:
            try:
                groq_key = key_prompt()
            except Exception:  # noqa: BLE001
                groq_key = None
        report.secret_configured = self.configure_secret(groq_key)
        report.marker = self._write_marker(report)
        report.completed = report.ok()
        return report


def _render(report: FirstRunReport) -> str:
    if report.already_done:
        return "FRIDAY first-run already completed."
    icon = {"ok": "+", "warn": "~", "absent": "-", "unknown": "?", "failed": "!"}
    lines = ["FRIDAY — First Run", "-" * 32]
    for c in report.checks:
        lines.append(f"  [{icon.get(c.status, '?')}] {c.name:<11} {c.detail}")
    lines.append("-" * 32)
    lines.append(f"  reasoning key: {'configured' if report.secret_configured else 'skipped'}")
    lines.append("FRIDAY Ready." if report.ok() else "FRIDAY needs Python 3.10+ to run.")
    return "\n".join(lines)


def main(argv: Optional[list] = None) -> int:
    import argparse
    import getpass
    p = argparse.ArgumentParser(prog="friday-first-run",
                                description="FRIDAY first-run wizard")
    p.add_argument("--json", action="store_true", help="print report as JSON, no prompt")
    p.add_argument("--force", action="store_true", help="re-run even if already completed")
    p.add_argument("--no-key", action="store_true", help="skip the reasoning-key prompt")
    args = p.parse_args(argv)

    wizard = FirstRunWizard()
    prompt = None
    if not args.json and not args.no_key:
        def prompt() -> Optional[str]:  # noqa: E306
            try:
                return getpass.getpass(
                    "Groq API key (temporary reasoning provider, blank to skip): ")
            except Exception:  # noqa: BLE001
                return None
    report = wizard.run(force=args.force, key_prompt=prompt)
    if args.json:
        print(json.dumps(report.to_dict(), indent=2))
    else:
        print(_render(report))
    return 0 if report.ok() or report.already_done else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
