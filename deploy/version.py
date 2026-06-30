"""
deploy/version.py — FRIDAY V3 (M20)
Single source of truth for the release version + metadata. Read by the build/release
scripts and the installer. Keep this the only place the version number lives.
"""

from __future__ import annotations

import sys

VERSION = "0.20.0"               # pre-1.0; M20 productization
RELEASE = "M20"
CODENAME = "Productization & Release Engineering"
PYTHON_REQUIRES = (3, 10)


def metadata() -> dict:
    return {
        "name": "FRIDAY",
        "version": VERSION,
        "release": RELEASE,
        "codename": CODENAME,
        "python_requires": ">=%d.%d" % PYTHON_REQUIRES,
        "current_python": "%d.%d.%d" % sys.version_info[:3],
        "private": True,
    }


def python_ok() -> bool:
    return sys.version_info[:2] >= PYTHON_REQUIRES
