"""
deploy/release.py — FRIDAY V3 (M20)
Release engineering helpers: generate a changelog from the milestone history, assemble a
release manifest (version + artifacts + checksums), and verify the release is internally
consistent. Produces metadata only — it never publishes or pushes (that stays a manual,
confirmed step).

    python -m deploy.release --changelog
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Optional

from .build import _sha256, verify_package
from .version import metadata

_ROOT = Path(__file__).resolve().parents[1]


def generate_changelog(*, root: Optional[Path] = None) -> dict:
    """Extract the milestone section headers from FRIDAY_4.0_CHANGES.md into a concise
    release changelog."""
    root = Path(root) if root else _ROOT
    src = root / "FRIDAY_4.0_CHANGES.md"
    entries = []
    if src.exists():
        for line in src.read_text(encoding="utf-8").splitlines():
            m = re.match(r"^## (M[0-9].*?)$", line.strip())
            if m and "delivery summary" not in m.group(1).lower():
                entries.append(m.group(1).strip())
    return {"version": metadata()["version"], "generated_at": time.time(),
            "milestones": entries, "count": len(entries)}


def release_manifest(*, root: Optional[Path] = None, dist: Optional[Path] = None) -> dict:
    """Build the release manifest from whatever artifacts are present in dist/."""
    root = Path(root) if root else _ROOT
    dist = Path(dist) if dist else (root / "dist")
    artifacts = []
    if dist.exists():
        for art in sorted(dist.glob("friday-*.zip")):
            v = verify_package(art)
            artifacts.append({"name": art.name, "sha256": _sha256(art),
                              "size_bytes": art.stat().st_size, "verified": v["ok"]})
    return {**metadata(), "released_at": time.time(), "artifacts": artifacts,
            "changelog": generate_changelog(root=root), "private": True}


def verify_release(*, root: Optional[Path] = None, dist: Optional[Path] = None) -> dict:
    manifest = release_manifest(root=root, dist=dist)
    ok = all(a["verified"] for a in manifest["artifacts"]) if manifest["artifacts"] else False
    return {"ok": ok, "artifacts": len(manifest["artifacts"]),
            "milestones": manifest["changelog"]["count"]}


def main(argv: Optional[list] = None) -> int:
    import argparse
    p = argparse.ArgumentParser(prog="friday-release")
    p.add_argument("--changelog", action="store_true")
    p.add_argument("--manifest", action="store_true")
    args = p.parse_args(argv)
    if args.changelog:
        print(json.dumps(generate_changelog(), indent=2))
    elif args.manifest:
        print(json.dumps(release_manifest(), indent=2, default=str))
    else:
        print(json.dumps(verify_release(), indent=2))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
