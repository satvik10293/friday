"""
deploy/ — FRIDAY V3 (M20) Deployment & Release Engineering.

Installer framework + build/release scripts for packaging FRIDAY as a private,
cross-platform application. One Python codebase; per-OS specifics stay in
core/launcher/platform_adapter. Secrets are never embedded, printed, or committed. These
scripts prepare verifiable artifacts and metadata — they never publish or push.
"""

from __future__ import annotations

from .build import build_package, verify_package
from .install import Installer
from .rc import build_rc, release_notes
from .release import generate_changelog, release_manifest, verify_release
from .version import VERSION, metadata, python_ok, release_tag

__all__ = ["VERSION", "metadata", "python_ok", "release_tag", "Installer", "build_package",
           "verify_package", "generate_changelog", "release_manifest", "verify_release",
           "build_rc", "release_notes"]
