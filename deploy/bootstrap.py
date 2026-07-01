"""
deploy/bootstrap.py — FRIDAY V3 (RC1)
The self-provisioning launcher used by the installed / portable build. FRIDAY ships as its
own source tree plus this bootstrap; on first run it creates an isolated virtual
environment next to the app, installs the pinned dependencies into it, runs the first-run
wizard, and then launches FRIDAY using that venv's interpreter. Subsequent runs skip
straight to launch (the venv + first-run marker already exist).

This is the correct packaging model for a heavy, CPU-first ML application (mediapipe /
faster-whisper / faiss / torch): rather than freezing gigabytes into a brittle single
binary, we provision a clean, reproducible environment the user never has to touch.

    python deploy/bootstrap.py                 # provision (if needed) then launch the orb
    python deploy/bootstrap.py --provision-only
    python deploy/bootstrap.py --entry app     # launch friday_app.py instead of the orb

Only the *system* Python is needed to start this; everything else is provisioned here.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import venv
from pathlib import Path
from typing import Optional

_ROOT = Path(__file__).resolve().parents[1]
_VENV = _ROOT / ".venv"

_ENTRIES = {
    "orb": "friday_orb.py",
    "app": "friday_app.py",
    "launch": "friday_launch.py",
    "spine": "friday_spine.py",
}


def _venv_python(venv_dir: Path) -> Path:
    if sys.platform.startswith("win"):
        return venv_dir / "Scripts" / "python.exe"
    return venv_dir / "bin" / "python"


def venv_ready(venv_dir: Path = _VENV) -> bool:
    return _venv_python(venv_dir).exists()


def create_venv(venv_dir: Path = _VENV) -> bool:
    """Create the virtual environment (idempotent). Returns whether the interpreter exists
    afterwards."""
    if venv_ready(venv_dir):
        return True
    print(f"[bootstrap] creating virtual environment at {venv_dir} ...")
    try:
        venv.EnvBuilder(with_pip=True, clear=False).create(str(venv_dir))
    except Exception as e:  # noqa: BLE001
        print(f"[bootstrap] venv creation failed: {e}")
        return False
    return venv_ready(venv_dir)


def install_dependencies(venv_dir: Path = _VENV, *, root: Path = _ROOT) -> bool:
    """Install the pinned requirements into the venv. Returns success."""
    req = root / "requirements.txt"
    if not req.exists():
        print("[bootstrap] requirements.txt missing; skipping dependency install")
        return True
    py = _venv_python(venv_dir)
    print("[bootstrap] installing dependencies (first run can take several minutes) ...")
    try:
        subprocess.run([str(py), "-m", "pip", "install", "--upgrade", "pip"],
                       check=False)
        proc = subprocess.run([str(py), "-m", "pip", "install", "-r", str(req)])
        return proc.returncode == 0
    except Exception as e:  # noqa: BLE001
        print(f"[bootstrap] dependency install failed: {e}")
        return False


def run_first_run(venv_dir: Path = _VENV, *, root: Path = _ROOT) -> None:
    """Run the first-run wizard inside the provisioned venv (non-fatal)."""
    py = _venv_python(venv_dir)
    try:
        subprocess.run([str(py), "-m", "core.launcher.first_run"], cwd=str(root))
    except Exception as e:  # noqa: BLE001
        print(f"[bootstrap] first-run wizard skipped: {e}")


def launch(entry: str = "orb", venv_dir: Path = _VENV, *, root: Path = _ROOT) -> int:
    py = _venv_python(venv_dir)
    target = root / _ENTRIES.get(entry, _ENTRIES["orb"])
    if not target.exists():
        target = root / _ENTRIES["launch"]
    print(f"[bootstrap] launching {target.name} ...")
    try:
        return subprocess.call([str(py), str(target)], cwd=str(root))
    except Exception as e:  # noqa: BLE001
        print(f"[bootstrap] launch failed: {e}")
        return 1


def provision(venv_dir: Path = _VENV, *, root: Path = _ROOT) -> bool:
    """Ensure venv + dependencies + first-run are done. Returns whether the app is ready."""
    fresh = not venv_ready(venv_dir)
    if not create_venv(venv_dir):
        return False
    if fresh and not install_dependencies(venv_dir, root=root):
        print("[bootstrap] WARNING: some dependencies failed to install; "
              "FRIDAY will run degraded.")
    if fresh:
        run_first_run(venv_dir, root=root)
    return venv_ready(venv_dir)


def main(argv: Optional[list] = None) -> int:
    p = argparse.ArgumentParser(prog="friday-bootstrap",
                                description="Provision + launch FRIDAY")
    p.add_argument("--entry", default=os.environ.get("FRIDAY_ENTRY", "orb"),
                   choices=list(_ENTRIES))
    p.add_argument("--provision-only", action="store_true")
    p.add_argument("--venv", default=str(_VENV))
    args = p.parse_args(argv)
    venv_dir = Path(args.venv)

    if not provision(venv_dir):
        print("[bootstrap] provisioning failed — cannot start FRIDAY")
        return 1
    if args.provision_only:
        print("[bootstrap] environment ready.")
        return 0
    return launch(args.entry, venv_dir)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
