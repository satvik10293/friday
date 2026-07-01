"""
deploy/rc.py — FRIDAY V3 (RC1)
Release-Candidate orchestrator. Produces the first *installable* build for real-world
testing: a verifiable portable package (the clean source tree + self-provisioning
bootstrap + installer assets), a release-notes document, a curated known-issues list, and
a signed-by-checksum RC manifest. It does not publish or push — it assembles and verifies
the artifacts under `dist/` so they can be installed and tested.

    python -m deploy.rc                 # build + verify the RC into dist/
    python -m deploy.rc --notes-only    # regenerate release notes only

Native OS installers (a compiled .exe via Inno Setup / a .app / a .deb) are produced from
this same tree by `deploy/windows/friday.iss` (and the per-OS CI); the portable package
here already installs and runs on any machine with a system Python, via the bootstrap.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Optional

from .build import build_package, verify_package
from .release import generate_changelog
from .version import metadata, release_tag

_ROOT = Path(__file__).resolve().parents[1]

# Curated, honest list of what is NOT yet validated in RC1 — surfaced to the tester so they
# know what to expect. Keep this truthful; it is part of the deliverable.
KNOWN_ISSUES = [
    "No compiled single-file .exe: FRIDAY ships as source + a self-provisioning bootstrap "
    "(creates its own .venv on first run). A native installer is generated from "
    "deploy/windows/friday.iss when Inno Setup is available.",
    "First launch is slow: the bootstrap installs ~50 pinned dependencies (mediapipe, "
    "faster-whisper, faiss, torch CPU) into the venv — this can take several minutes and "
    "requires network access.",
    "Cloud reasoning needs a key: without a Groq/Gemini/OpenAI key in .env, FRIDAY runs "
    "local-only (flan-t5) and will not use cloud fallback.",
    "Voice, gesture and vision require optional hardware/backends (microphone, webcam, "
    "sounddevice, opencv, mediapipe); each degrades gracefully if absent.",
    "Windows-first: macOS/Linux share the same core and bootstrap, but desktop-integration "
    "(shortcuts, HUD native window) is validated on Windows only.",
    "docs/PRODUCTION_AUDIT.md predates M18–M20 and is scheduled for refresh.",
]

TEST_CHECKLIST = [
    "Clean install: run the installer into an empty directory; confirm the venv provisions "
    "and FRIDAY reaches 'Ready'.",
    "First-run wizard: verify OS/mic/speaker/camera detection and (optional) key capture.",
    "Startup: python friday_launch.py --json → all stages ok/skipped, health 'ok'.",
    "Diagnostics: python -m core.launcher.diagnostics → brains, provider, vitals shown.",
    "Shutdown: close the app/orb; confirm no orphaned processes.",
    "Upgrade: install over an existing install; confirm config + .env are preserved.",
]


def release_notes(*, root: Optional[Path] = None) -> str:
    root = Path(root) if root else _ROOT
    meta = metadata()
    changelog = generate_changelog(root=root)
    milestone_lines = [f"- {m}" for m in changelog["milestones"]] or \
        ["- (see FRIDAY_4.0_CHANGES.md)"]
    lines = [
        f"# FRIDAY {release_tag()} — Release Candidate {_rc_number()}",
        "",
        f"**Version:** {meta['version']}  ·  **Channel:** {meta['channel']}  ·  "
        f"**Codename:** {meta['codename']}",
        f"**Requires:** Python {meta['python_requires']} (CPU-first; Windows validated)",
        "",
        "First installable build for real-world testing. This is a packaging and "
        "validation release — no new cognitive features.",
        "",
        "## Install",
        "",
        "**Windows (recommended):** run `Install-FRIDAY.bat` (or "
        "`deploy/windows/install.ps1`). It copies FRIDAY, provisions an isolated `.venv`, "
        "creates Desktop + Start-Menu shortcuts, registers an uninstall entry, verifies, "
        "and offers to launch.",
        "",
        "**Portable / any OS:** unzip the package and run `python deploy/bootstrap.py` — it "
        "provisions the venv, runs the first-run wizard, and launches the floating orb.",
        "",
        "## What's included (milestones)",
        "",
        *milestone_lines,
        "",
        "## First-run wizard",
        "",
        "Detects OS, verifies the Python runtime, probes microphone / speakers / camera, "
        "captures the (optional) Groq key into a gitignored `.env`, writes config, and "
        "reports **FRIDAY Ready**.",
        "",
        "## Known issues / limitations",
        "",
        *[f"- {k}" for k in KNOWN_ISSUES],
        "",
        "## Please test",
        "",
        *[f"- [ ] {t}" for t in TEST_CHECKLIST],
        "",
        "## Logs & diagnostics",
        "",
        "Verbose logs: `data/logs/friday.log` (+ `friday-error.log`), rotating. "
        "Diagnostics: `python -m core.launcher.diagnostics --gui`.",
        "",
        "_Report bugs with the FRIDAY version, your OS, and the tail of `friday-error.log`._",
        "",
    ]
    return "\n".join(lines)


def _rc_number() -> int:
    from .version import RC
    return RC


def build_rc(*, root: Optional[Path] = None, dest: Optional[Path] = None) -> dict:
    """Build the RC: portable package + release notes + known issues + RC manifest, all
    verified. Returns the deliverables map."""
    root = Path(root) if root else _ROOT
    dest = Path(dest) if dest else (root / "dist")
    dest.mkdir(parents=True, exist_ok=True)

    build = build_package(root=root, dest=dest)
    archive = Path(build["archive"])
    verify = verify_package(archive, expected_sha256=build["manifest"]["sha256"])

    notes = release_notes(root=root)
    notes_path = dest / f"RELEASE_NOTES-{release_tag()}.md"
    notes_path.write_text(notes, encoding="utf-8")

    manifest = {
        **metadata(),
        "build_tag": release_tag(),
        "built_at": time.time(),
        "portable_package": {
            "archive": archive.name,
            "sha256": build["manifest"]["sha256"],
            "size_bytes": build["manifest"]["size_bytes"],
            "files": build["manifest"]["files"],
            "verified": verify["ok"],
            "leaked_excludes": verify.get("leaked_excludes", []),
        },
        "release_notes": notes_path.name,
        "known_issues": KNOWN_ISSUES,
        "test_checklist": TEST_CHECKLIST,
        "installer": "deploy/windows/install.ps1 (+ friday.iss for a native .exe)",
        "entry_points": ["Install-FRIDAY.bat", "Launch-FRIDAY.bat", "deploy/bootstrap.py"],
    }
    manifest_path = dest / f"RC-{release_tag()}.manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    ok = verify["ok"] and not verify.get("leaked_excludes")
    return {"ok": ok, "dest": str(dest), "archive": str(archive),
            "release_notes": str(notes_path), "manifest": str(manifest_path),
            "verify": verify}


def main(argv: Optional[list] = None) -> int:
    import argparse
    p = argparse.ArgumentParser(prog="friday-rc", description="FRIDAY Release-Candidate build")
    p.add_argument("--notes-only", action="store_true")
    args = p.parse_args(argv)
    if args.notes_only:
        print(release_notes())
        return 0
    result = build_rc()
    summary = {"ok": result["ok"], "archive": Path(result["archive"]).name,
               "release_notes": Path(result["release_notes"]).name,
               "manifest": Path(result["manifest"]).name,
               "verified": result["verify"]["ok"],
               "leaked": result["verify"].get("leaked_excludes", [])}
    print(json.dumps(summary, indent=2))
    return 0 if result["ok"] else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
