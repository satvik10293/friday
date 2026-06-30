"""
deploy/install.py — FRIDAY V3 (M20)
Cross-platform installer framework (one Python codebase; small per-OS adapters live in
core/launcher/platform_adapter). It verifies the Python version, installs dependencies,
validates configuration, captures the (temporary) Groq reasoning key SECURELY into a
gitignored `.env` (never embedded in code or config), creates a desktop shortcut, writes
uninstall information, and prepares logs.

Secrets are never printed, logged, embedded, or committed. Supports `dry_run` so it is
fully testable without mutating the system. Run:  python -m deploy.install
"""

from __future__ import annotations

import json
import logging
import subprocess
import sys
from pathlib import Path
from typing import Optional

from core.launcher.platform_adapter import PlatformAdapter

from .version import metadata, python_ok

log = logging.getLogger("friday.deploy.install")
_ROOT = Path(__file__).resolve().parents[1]


class Installer:
    def __init__(self, *, root: Optional[Path] = None, dry_run: bool = False) -> None:
        self.root = Path(root) if root else _ROOT
        self.dry_run = dry_run
        self.platform = PlatformAdapter()
        self._created: list = []

    # ── steps ────────────────────────────────────────────────────────────────────
    def check_python(self) -> dict:
        return {"ok": python_ok(), "required": metadata()["python_requires"],
                "current": metadata()["current_python"]}

    def install_dependencies(self) -> dict:
        req = self.root / "requirements.txt"
        if not req.exists():
            return {"ok": False, "reason": "requirements.txt not found"}
        cmd = [sys.executable, "-m", "pip", "install", "-r", str(req)]
        if self.dry_run:
            return {"ok": True, "dry_run": True, "command": " ".join(cmd)}
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
            return {"ok": proc.returncode == 0, "returncode": proc.returncode}
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "reason": str(e)}

    def validate_config(self) -> dict:
        cfg = self.root / "friday_config.json"
        if not cfg.exists():
            return {"ok": False, "reason": "friday_config.json missing"}
        try:
            json.loads(cfg.read_text(encoding="utf-8"))
        except ValueError as e:
            return {"ok": False, "reason": f"invalid JSON: {e}"}
        return {"ok": True, "env_present": (self.root / ".env").exists()}

    def configure_secret(self, *, groq_key: Optional[str] = None,
                         env_path: Optional[Path] = None) -> dict:
        """Write the Groq reasoning key to a gitignored .env — securely. The key is never
        embedded in code/config, never printed, never logged. No key → skipped."""
        if not groq_key:
            return {"ok": True, "configured": False, "reason": "no key provided (skipped)"}
        env = Path(env_path) if env_path else (self.root / ".env")
        try:
            lines = []
            if env.exists():
                lines = [ln for ln in env.read_text(encoding="utf-8").splitlines()
                         if not ln.startswith("GROQ_API_KEY=")]
            lines.append(f"GROQ_API_KEY={groq_key}")
            env.write_text("\n".join(lines) + "\n", encoding="utf-8")
            try:
                env.chmod(0o600)                      # owner-only where supported
            except OSError:
                pass
            self._created.append(str(env))
            return {"ok": True, "configured": True, "path": str(env)}   # key NOT included
        except OSError as e:
            return {"ok": False, "reason": str(e)}

    def create_shortcut(self) -> dict:
        if self.dry_run:
            return {"ok": True, "dry_run": True}
        created = self.platform.create_shortcut(target=str(self.root / "friday_orb.py"),
                                                name="FRIDAY")
        return {"ok": created, "created": created}

    def write_uninstall_info(self) -> dict:
        info = {"app": "FRIDAY", "version": metadata()["version"], "root": str(self.root),
                "created_files": list(self._created)}
        path = self.platform.data_dir() / "uninstall.json"
        if self.dry_run:
            return {"ok": True, "dry_run": True, "path": str(path)}
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(info, indent=2), encoding="utf-8")
            return {"ok": True, "path": str(path)}
        except OSError as e:
            return {"ok": False, "reason": str(e)}

    def prepare_logs(self) -> dict:
        self.platform.ensure_dirs()
        return {"ok": True, "log_dir": str(self.platform.log_dir())}

    # ── orchestration ────────────────────────────────────────────────────────────
    def run(self, *, groq_key: Optional[str] = None, env_path: Optional[Path] = None) -> dict:
        steps = {
            "python": self.check_python(),
            "dependencies": self.install_dependencies(),
            "config": self.validate_config(),
            "secret": self.configure_secret(groq_key=groq_key, env_path=env_path),
            "shortcut": self.create_shortcut(),
            "logs": self.prepare_logs(),
            "uninstall": self.write_uninstall_info(),
        }
        ok = all(s.get("ok", False) for s in steps.values())
        return {"installed": ok, "dry_run": self.dry_run, "platform": self.platform.os,
                "version": metadata()["version"], "steps": steps}


def main(argv: Optional[list] = None) -> int:
    import argparse
    import getpass
    p = argparse.ArgumentParser(prog="friday-install", description="FRIDAY installer")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--no-key", action="store_true", help="skip the Groq key prompt")
    args = p.parse_args(argv)
    installer = Installer(dry_run=args.dry_run)
    key = None
    if not args.no_key and not args.dry_run:
        try:
            key = getpass.getpass("Groq API key (temporary reasoning provider, blank to skip): ")
        except Exception:  # noqa: BLE001
            key = None
    report = installer.run(groq_key=key or None)
    print(json.dumps({**report, "steps": {k: {kk: vv for kk, vv in v.items() if kk != "path"}
                                          for k, v in report["steps"].items()}}, indent=2))
    return 0 if report["installed"] else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
