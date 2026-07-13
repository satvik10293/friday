"""
deploy/ — FRIDAY V3 (M20) Deployment & Release Engineering.

Installer framework + build/release scripts for packaging FRIDAY as a private,
cross-platform application. One Python codebase; per-OS specifics stay in
core/launcher/platform_adapter. Secrets are never embedded, printed, or committed. These
scripts prepare verifiable artifacts and metadata — they never publish or push.
"""

from __future__ import annotations

from importlib import import_module

# Lazy re-exports (PEP 562). Eager imports here once dragged core/ (and with
# it torch + transformers) into anything importing the deploy package — the
# one-file installer ballooned to 367 MB because deploy.install imports
# core.launcher. deploy/setup must stay stdlib-only; heavy modules now load
# only when their symbol is actually used.
_EXPORTS = {
    "build_package": ".build", "verify_package": ".build",
    "Installer": ".install",
    "build_rc": ".rc", "release_notes": ".rc",
    "generate_changelog": ".release", "release_manifest": ".release",
    "verify_release": ".release",
    "VERSION": ".version", "metadata": ".version", "python_ok": ".version",
    "release_tag": ".version",
}

__all__ = list(_EXPORTS)


def __getattr__(name: str):
    if name in _EXPORTS:
        return getattr(import_module(_EXPORTS[name], __name__), name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
