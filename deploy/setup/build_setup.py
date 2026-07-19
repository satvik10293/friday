"""
deploy/setup/build_setup.py — build the official one-file installer (M44).

Produces a single self-contained binary for the CURRENT OS:

    dist/FRIDAY-Setup-<version>-<os>-<arch>[.exe]

containing the installer (detect → recommend → install → launch) plus the
verified portable source package as an embedded payload. Cross-OS by
construction: the same script builds a native binary on whichever OS it runs
on (PyInstaller cannot cross-compile — build on Windows for the .exe, on
macOS/Linux for theirs).

    python -m deploy.setup.build_setup            # payload + binary
    python -m deploy.setup.build_setup --skip-payload   # reuse dist/friday-*.zip
"""

from __future__ import annotations

import argparse
import os
import platform
import subprocess
import sys
from pathlib import Path
from typing import Optional

_ROOT = Path(__file__).resolve().parents[2]
_DIST = _ROOT / "dist"
_WORK = _ROOT / "build" / "friday-setup"

# a stdlib-only installer freezes to ~10-15 MB; anything far beyond payload +
# this margin means a heavy package leaked into the dependency graph
_MAX_OVERHEAD_MB = 60

_ENTRY_SOURCE = """\
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from deploy.setup.installer import run
raise SystemExit(run())
"""


def _os_label() -> str:
    return {"Windows": "windows", "Darwin": "macos"}.get(platform.system(),
                                                         "linux")


def _arch_label() -> str:
    m = platform.machine().lower()
    return {"amd64": "x64", "x86_64": "x64", "arm64": "arm64",
            "aarch64": "arm64"}.get(m, m)


def ensure_pyinstaller() -> bool:
    try:
        import PyInstaller  # noqa: F401
        return True
    except ImportError:
        print("[build-setup] installing PyInstaller ...")
        proc = subprocess.run([sys.executable, "-m", "pip", "install",
                               "pyinstaller"])
        return proc.returncode == 0


def build_payload() -> Path:
    from deploy.build import build_package, verify_package
    build = build_package(root=_ROOT, dest=_DIST)
    archive = Path(build["archive"])
    verify = verify_package(archive,
                            expected_sha256=build["manifest"]["sha256"])
    if not verify["ok"] or verify.get("leaked_excludes"):
        raise SystemExit(f"[build-setup] payload failed verification: {verify}")
    return archive


def latest_payload() -> Optional[Path]:
    # strict match: source packages are friday-<version>.zip. Windows globs
    # are case-insensitive, so a loose pattern also caught
    # FRIDAY-Windows-Portable-Installer-*.zip — the wrong artifact.
    import re
    zips = sorted(p for p in _DIST.glob("friday-*.zip")
                  if re.match(r"^friday-\d[\w.\-]*\.zip$", p.name))
    return zips[-1] if zips else None


def build_binary(payload: Path) -> Path:
    from deploy.version import release_tag
    name = f"FRIDAY-Setup-{release_tag()}-{_os_label()}-{_arch_label()}"

    _WORK.mkdir(parents=True, exist_ok=True)
    entry = _WORK / "friday_setup_entry.py"
    entry.write_text(_ENTRY_SOURCE, encoding="utf-8")

    cmd = [sys.executable, "-m", "PyInstaller", "--onefile", "--console",
           "--noconfirm", "--clean",
           "--name", name,
           "--distpath", str(_DIST),
           "--workpath", str(_WORK / "work"),
           "--specpath", str(_WORK),
           "--paths", str(_ROOT),
           "--add-data", f"{payload}{os.pathsep}payload",
           # deploy/__init__ lazy-exports via importlib (PEP 562) so eager
           # imports can't drag core/torch into the freeze — but that same
           # laziness hides these modules from PyInstaller's static analysis.
           # Declare every deploy module the installer touches at runtime
           # explicitly (all stdlib-only; the size tripwire below still
           # guards against anything heavy leaking in).
           "--hidden-import", "deploy.build",
           "--hidden-import", "deploy.version",
           "--hidden-import", "deploy.setup.detect",
           "--hidden-import", "deploy.setup.recommend",
           "--hidden-import", "deploy.setup.installer",
           str(entry)]
    print(f"[build-setup] freezing {name} ...")
    proc = subprocess.run(cmd, cwd=str(_ROOT))
    if proc.returncode != 0:
        raise SystemExit("[build-setup] PyInstaller failed")

    suffix = ".exe" if platform.system() == "Windows" else ""
    binary = _DIST / f"{name}{suffix}"
    if not binary.exists():
        raise SystemExit(f"[build-setup] expected artifact missing: {binary}")
    size_mb = binary.stat().st_size / (1024 * 1024)
    payload_mb = payload.stat().st_size / (1024 * 1024)
    if size_mb > payload_mb + _MAX_OVERHEAD_MB:
        raise SystemExit(
            f"[build-setup] binary is {size_mb:.0f} MB for a {payload_mb:.0f} MB "
            f"payload — a heavy package (core/torch?) leaked into the freeze. "
            f"The installer must stay stdlib-only; check what deploy imports.")
    return binary


def main(argv: Optional[list] = None) -> int:
    p = argparse.ArgumentParser(prog="friday-build-setup")
    p.add_argument("--skip-payload", action="store_true",
                   help="reuse the newest dist/friday-*.zip")
    args = p.parse_args(argv)

    if not ensure_pyinstaller():
        print("[build-setup] PyInstaller unavailable")
        return 1
    payload = latest_payload() if args.skip_payload else build_payload()
    if payload is None:
        print("[build-setup] no payload; run without --skip-payload")
        return 1
    print(f"[build-setup] payload: {payload.name} "
          f"({payload.stat().st_size // (1024 * 1024)} MB)")
    binary = build_binary(payload)
    print(f"[build-setup] OK: {binary}  "
          f"({binary.stat().st_size // (1024 * 1024)} MB)")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
