"""
deploy/setup/installer.py — the official FRIDAY launcher (M44).

One executable. Double-click it and FRIDAY installs and runs:

    1. identify the machine   OS, RAM, Python, GPU (graded best/good/average)
    2. recommend              the best FRIDAY edition + torch build for it
    3. install                extract the embedded payload, provision the venv
                              (CUDA torch when the GPU earns it), shortcuts
    4. launch                 FRIDAY starts; the M35 wizard measures the GPU
                              on first boot and writes the real device plan

The payload (the verified portable source package from deploy/build.py) is
embedded in the frozen binary by build_setup.py; running from the repo, the
installer builds the payload on the fly (dev convenience). Upgrades preserve
user data: `.env`, `friday_config.json`, and `data/` are never in the payload
and never touched by extraction.

    FRIDAY-Setup.exe                       # interactive install + launch
    FRIDAY-Setup.exe --yes                 # no questions
    FRIDAY-Setup.exe --detect              # show what would be recommended
    FRIDAY-Setup.exe --dry-run             # full plan, no changes
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
import zipfile
from pathlib import Path
from typing import Optional

from .detect import SystemReport, detect_system
from .recommend import InstallPlan, recommend

# frozen consoles on Windows default to cp1252; the installer prints ASCII
# only, but paths and GPU names may not be — never crash on a print
for stream in (sys.stdout, sys.stderr):
    try:
        stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass

_BANNER = r"""
  =====================================================
     F R I D A Y   —   O F F I C I A L   S E T U P
  =====================================================
"""


def _say(msg: str = "") -> None:
    print(msg, flush=True)


def _step(n: int, total: int, title: str) -> None:
    _say(f"\n  [{n}/{total}] {title}")
    _say("  " + "-" * 49)


# ── payload ───────────────────────────────────────────────────────────────────

def find_payload(source: Optional[str] = None) -> Optional[Path]:
    """The FRIDAY source package to install. Frozen: embedded next to the
    executable's unpacked data (sys._MEIPASS/payload). Dev: --source zip, or
    build one from the repo this module lives in."""
    if source:
        p = Path(source)
        return p if p.exists() else None
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        zips = sorted(Path(meipass, "payload").glob("friday-*.zip"))
        return zips[-1] if zips else None
    repo = Path(__file__).resolve().parents[2]
    if (repo / "friday_launch.py").exists():
        # running from a source tree (npx download or a dev checkout):
        # build the verified package from it on the fly
        _say("  (building the install package from the downloaded source)")
        from deploy.build import build_package
        return Path(build_package(root=repo)["archive"])
    return None


def payload_version(payload: Path) -> str:
    m = re.match(r"friday-(.+)\.zip", payload.name)
    return m.group(1) if m else "unknown"


def extract_payload(payload: Path, dest: Path) -> int:
    """Extract the package. User data (`.env`, config, `data/`, `.venv`) is
    never inside the payload, so extraction is upgrade-safe by construction."""
    dest.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(payload) as zf:
        names = zf.namelist()
        zf.extractall(dest)
    return len(names)


# ── provisioning + launch ─────────────────────────────────────────────────────

def provision(dest: Path, python_exe: str, torch_flavor: str,
              *, skip_deps: bool = False) -> bool:
    """Provision FRIDAY's venv with the bundled bootstrap, under the system
    Python we detected. The torch flavor is the GPU decision made here at
    install time — the M35 wizard measures with that torch on first boot."""
    cmd = [python_exe, str(dest / "deploy" / "bootstrap.py"),
           "--provision-only", "--torch", torch_flavor]
    if skip_deps:
        # dev/test path: venv only, no multi-GB dependency download
        cmd = [python_exe, "-c",
               "import sys; sys.path.insert(0, r'%s'); "
               "from deploy.bootstrap import create_venv; "
               "raise SystemExit(0 if create_venv() else 1)" % dest]
    proc = subprocess.run(cmd, cwd=str(dest))
    return proc.returncode == 0


def create_shortcuts(dest: Path) -> list[str]:
    """Desktop + Start Menu shortcuts (Windows); a .desktop entry (Linux).
    Best-effort — an install without shortcuts is still an install."""
    created: list[str] = []
    launcher = dest / "Launch-FRIDAY.bat"
    if sys.platform.startswith("win") and launcher.exists():
        script = (
            "$sh = New-Object -ComObject WScript.Shell; "
            "foreach ($dir in @([Environment]::GetFolderPath('Desktop'), "
            "[Environment]::GetFolderPath('Programs'))) { "
            "  $lnk = $sh.CreateShortcut((Join-Path $dir 'FRIDAY.lnk')); "
            f"  $lnk.TargetPath = '{launcher}'; "
            f"  $lnk.WorkingDirectory = '{dest}'; "
            "  $lnk.Description = 'Launch FRIDAY'; $lnk.Save(); "
            "  Write-Output (Join-Path $dir 'FRIDAY.lnk') }")
        try:
            out = subprocess.run(["powershell", "-NoProfile", "-Command", script],
                                 capture_output=True, text=True, timeout=30)
            created = [ln.strip() for ln in out.stdout.splitlines() if ln.strip()]
        except Exception:  # noqa: BLE001
            pass
    elif sys.platform.startswith("linux"):
        try:
            apps = Path.home() / ".local" / "share" / "applications"
            apps.mkdir(parents=True, exist_ok=True)
            entry = apps / "friday.desktop"
            entry.write_text(
                "[Desktop Entry]\nType=Application\nName=FRIDAY\n"
                f"Exec=python3 {dest / 'deploy' / 'bootstrap.py'}\n"
                f"Path={dest}\nTerminal=true\n", encoding="utf-8")
            created = [str(entry)]
        except Exception:  # noqa: BLE001
            pass
    return created


def create_cli_command(dest: Path) -> Optional[str]:
    """Register a `friday` terminal command so she starts from any shell.
    Windows: a shim in %LOCALAPPDATA%\\Microsoft\\WindowsApps (on every user's
    PATH by default). POSIX: ~/.local/bin/friday. Best-effort."""
    try:
        if sys.platform.startswith("win"):
            windows_apps = Path(os.environ.get("LOCALAPPDATA", "")) / \
                "Microsoft" / "WindowsApps"
            if not windows_apps.is_dir():
                return None
            shim = windows_apps / "friday.cmd"
            shim.write_text("@echo off\r\n"
                            f"\"{dest / 'Launch-FRIDAY.bat'}\" %*\r\n",
                            encoding="ascii")
            return str(shim)
        bin_dir = Path.home() / ".local" / "bin"
        bin_dir.mkdir(parents=True, exist_ok=True)
        shim = bin_dir / "friday"
        shim.write_text("#!/bin/sh\n"
                        f"exec python3 \"{dest / 'deploy' / 'bootstrap.py'}\" \"$@\"\n",
                        encoding="ascii")
        shim.chmod(0o755)
        return str(shim)
    except Exception:  # noqa: BLE001 — a missing CLI shim never fails the install
        return None


def launch(dest: Path, python_exe: str) -> bool:
    """Start FRIDAY detached — the installer's job ends when she's running."""
    cmd = [python_exe, str(dest / "deploy" / "bootstrap.py")]
    try:
        if sys.platform.startswith("win"):
            subprocess.Popen(cmd, cwd=str(dest),
                             creationflags=subprocess.CREATE_NEW_CONSOLE)
        else:
            subprocess.Popen(cmd, cwd=str(dest), start_new_session=True)
        return True
    except Exception as e:  # noqa: BLE001
        _say(f"  launch failed: {e}")
        return False


# ── the run ───────────────────────────────────────────────────────────────────

def _print_report(report: SystemReport, plan: InstallPlan) -> None:
    gpu = report.gpu
    _say(f"  OS         : {report.os_name} {report.os_version} ({report.arch})")
    _say(f"  Memory     : {report.ram_gb} GB")
    _say(f"  Python     : "
         + (f"{report.python['version']}  ({report.python['exe']})"
            if report.python else "NOT FOUND"))
    _say(f"  GPU        : {plan.gpu_summary}")
    _say("")
    _say(f"  Recommended: FRIDAY [{plan.edition}]")
    _say(f"               {plan.edition_note}")
    _say(f"  Torch build: {plan.torch_flavor}"
         + ("  (CUDA 12.4 wheel — the GPU earned it)"
            if plan.torch_flavor == "cuda" else ""))
    _say(f"  Install to : {plan.install_dir}")
    for w in plan.warnings:
        _say(f"  ! {w}")


def run(argv: Optional[list] = None) -> int:
    p = argparse.ArgumentParser(prog="FRIDAY-Setup",
                                description="The official FRIDAY installer")
    p.add_argument("--yes", "-y", action="store_true", help="no questions")
    p.add_argument("--detect", action="store_true",
                   help="show the machine report + recommendation, then exit")
    p.add_argument("--dry-run", action="store_true",
                   help="plan everything, change nothing")
    p.add_argument("--dir", default=None, help="override the install directory")
    p.add_argument("--source", default=None,
                   help="use this payload zip instead of the embedded one")
    p.add_argument("--torch", default=None, choices=["cpu", "cuda"],
                   help="override the GPU decision")
    p.add_argument("--no-launch", action="store_true")
    p.add_argument("--skip-deps", action="store_true",
                   help="(testing) provision the venv without dependencies")
    args = p.parse_args(argv)

    _say(_BANNER)
    total = 4

    _step(1, total, "Identifying this machine")
    report = detect_system()
    plan = recommend(report)
    if args.dir:
        plan.install_dir = Path(args.dir)
    if args.torch:
        plan.torch_flavor = args.torch
    _print_report(report, plan)

    if args.detect:
        _say("\n" + json.dumps({**report.to_dict(), "plan": plan.to_dict()},
                               indent=2))
        return 0
    if report.python is None:
        _say("\n  Cannot continue without Python >= 3.10. "
             "Install it, then run this setup again.")
        return 1

    _step(2, total, "Locating the FRIDAY package")
    payload = find_payload(args.source)
    if payload is None:
        _say("  No payload found — this binary was built without one.")
        return 1
    version = payload_version(payload)
    _say(f"  FRIDAY {version}  ({payload.name}, "
         f"{payload.stat().st_size // (1024 * 1024)} MB)")

    if args.dry_run:
        _say("\n  Dry run — nothing installed. The plan above is what "
             "--yes would execute.")
        return 0
    if not args.yes:
        answer = input(f"\n  Install FRIDAY {version} to "
                       f"{plan.install_dir}? [Y/n] ").strip().lower()
        if answer not in ("", "y", "yes"):
            _say("  Cancelled.")
            return 1

    _step(3, total, f"Installing to {plan.install_dir}")
    t0 = time.time()
    count = extract_payload(payload, plan.install_dir)
    _say(f"  {count} files extracted in {time.time() - t0:.1f}s")
    _say(f"  Provisioning the environment (torch: {plan.torch_flavor}) — "
         "first install downloads dependencies and can take several minutes ...")
    if not provision(plan.install_dir, report.python["exe"], plan.torch_flavor,
                     skip_deps=args.skip_deps):
        _say("  Provisioning reported errors — FRIDAY may run degraded. "
             "Re-run this setup to retry.")
    shortcuts = create_shortcuts(plan.install_dir)
    for s in shortcuts:
        _say(f"  shortcut: {s}")
    cli = create_cli_command(plan.install_dir)
    if cli:
        _say(f"  command : friday  ({cli})")

    _step(4, total, "Launching FRIDAY")
    if args.no_launch:
        _say("  Skipped (--no-launch). Start her any time with the FRIDAY "
             "shortcut or Launch-FRIDAY.bat.")
        return 0
    ok = launch(plan.install_dir, report.python["exe"])
    _say("  FRIDAY is starting — the first-run wizard will measure your "
         "hardware and finish setup." if ok else
         "  Could not start automatically; use the FRIDAY shortcut.")
    return 0 if ok else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(run())
