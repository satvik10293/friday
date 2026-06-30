"""
deploy/build.py — FRIDAY V3 (M20)
Release packaging. Builds a clean, verifiable source distribution of FRIDAY (a single
Python codebase that runs on Windows/macOS/Linux) — excluding the virtualenv, git, runtime
data, caches, model weights, and secrets. Writes a build manifest with a SHA-256 checksum
and verifies the archive. Native installers (PyInstaller .exe / .app / Linux package) are
produced by the platform CI using this same source tree; this script prepares the
verifiable payload and metadata.

    python -m deploy.build            # build into dist/
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
import zipfile
from pathlib import Path
from typing import Optional

from .version import metadata

log = logging.getLogger("friday.deploy.build")
_ROOT = Path(__file__).resolve().parents[1]

# directory names + file suffixes never shipped (secrets, data, weights, caches, vcs)
_EXCLUDE_DIRS = {".git", ".venv", "venv", "__pycache__", ".pytest_cache", "data",
                 "dist", "build", ".idea", ".vscode", "migration_backups"}
_EXCLUDE_SUFFIXES = {".db", ".db-wal", ".db-shm", ".pyc", ".env", ".gguf", ".safetensors",
                     ".pt", ".pth", ".onnx", ".h5", ".ckpt", ".bin", ".log"}
_EXCLUDE_NAMES = {".env", "friday_config.local.json"}


def _included(path: Path) -> bool:
    parts = set(path.parts)
    if parts & _EXCLUDE_DIRS:
        return False
    if path.name in _EXCLUDE_NAMES or path.suffix in _EXCLUDE_SUFFIXES:
        return False
    return True


def _iter_source(root: Path):
    for p in sorted(root.rglob("*")):
        if p.is_file() and _included(p.relative_to(root)):
            yield p


def build_package(*, root: Optional[Path] = None, dest: Optional[Path] = None) -> dict:
    """Create a source zip + manifest in `dest` (default: <root>/dist). Returns build info
    including the archive path, file count, and SHA-256 checksum."""
    root = Path(root) if root else _ROOT
    dest = Path(dest) if dest else (root / "dist")
    dest.mkdir(parents=True, exist_ok=True)
    version = metadata()["version"]
    archive = dest / f"friday-{version}.zip"

    files = list(_iter_source(root))
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in files:
            zf.write(f, f.relative_to(root).as_posix())

    checksum = _sha256(archive)
    manifest = {**metadata(), "built_at": time.time(), "files": len(files),
                "archive": archive.name, "sha256": checksum,
                "size_bytes": archive.stat().st_size}
    (dest / f"friday-{version}.manifest.json").write_text(json.dumps(manifest, indent=2),
                                                          encoding="utf-8")
    log.info("[Build] %s (%d files, %s)", archive.name, len(files), checksum[:12])
    return {"ok": True, "archive": str(archive), "manifest": manifest}


def verify_package(archive: Path, *, expected_sha256: Optional[str] = None) -> dict:
    """Verify a built archive: it opens, passes its CRC test, and (optionally) matches the
    expected checksum."""
    archive = Path(archive)
    if not archive.exists():
        return {"ok": False, "reason": "archive missing"}
    try:
        with zipfile.ZipFile(archive) as zf:
            bad = zf.testzip()
            count = len(zf.namelist())
            # safety: the archive must not contain secrets/weights
            leaked = [n for n in zf.namelist()
                      if n.endswith(tuple(_EXCLUDE_SUFFIXES)) or Path(n).name in _EXCLUDE_NAMES]
    except zipfile.BadZipFile as e:
        return {"ok": False, "reason": f"bad zip: {e}"}
    checksum = _sha256(archive)
    ok = bad is None and not leaked and (expected_sha256 is None or checksum == expected_sha256)
    return {"ok": ok, "files": count, "sha256": checksum, "crc_ok": bad is None,
            "leaked_excludes": leaked}


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def main(argv: Optional[list] = None) -> int:
    result = build_package()
    verify = verify_package(Path(result["archive"]),
                            expected_sha256=result["manifest"]["sha256"])
    print(json.dumps({"build": result["manifest"], "verify": verify}, indent=2))
    return 0 if verify["ok"] else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
