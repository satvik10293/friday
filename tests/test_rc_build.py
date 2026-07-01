"""Tests for the RC1 packaging pipeline (deploy/rc.py, deploy/bootstrap.py, deploy/version)."""

from __future__ import annotations

import json
import zipfile

from deploy import bootstrap
from deploy.rc import KNOWN_ISSUES, TEST_CHECKLIST, build_rc, release_notes
from deploy.version import metadata, release_tag


def test_release_tag_is_rc():
    tag = release_tag()
    assert tag.startswith("0.20.0")
    assert "rc" in tag                          # RC channel
    assert metadata()["channel"] == "rc"
    assert metadata()["build"] == tag


def test_release_notes_contains_sections():
    notes = release_notes()
    for heading in ("## Install", "## Known issues", "## Please test", "First-run"):
        assert heading in notes
    assert release_tag() in notes


def test_known_issues_and_checklist_nonempty():
    assert len(KNOWN_ISSUES) >= 3
    assert len(TEST_CHECKLIST) >= 3


def test_build_rc_produces_verified_artifacts(tmp_path):
    result = build_rc(dest=tmp_path)
    assert result["ok"] is True
    assert result["verify"]["ok"] is True
    assert result["verify"].get("leaked_excludes") == []
    # deliverables exist
    assert (tmp_path / f"RELEASE_NOTES-{release_tag()}.md").exists()
    manifest_path = tmp_path / f"RC-{release_tag()}.manifest.json"
    assert manifest_path.exists()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["build_tag"] == release_tag()
    assert manifest["portable_package"]["verified"] is True


def test_portable_package_has_no_secrets_or_venv(tmp_path):
    result = build_rc(dest=tmp_path)
    with zipfile.ZipFile(result["archive"]) as zf:
        names = zf.namelist()
    assert not [n for n in names if n.endswith(".env")]
    assert not [n for n in names if ".venv" in n or n.endswith(".db")]
    # ships the installer + bootstrap + launchers
    for required in ("deploy/bootstrap.py", "deploy/windows/install.ps1",
                     "Install-FRIDAY.bat", "Launch-FRIDAY.bat"):
        assert required in names


def test_bootstrap_venv_python_path():
    from pathlib import Path
    p = bootstrap._venv_python(Path("X"))
    # resolves to a python executable under the venv layout
    assert p.name in ("python.exe", "python")
    assert "X" in str(p)


def test_bootstrap_entries_cover_known_launchers():
    assert set(bootstrap._ENTRIES) >= {"orb", "app", "launch", "spine"}
    for entry in bootstrap._ENTRIES.values():
        assert entry.endswith(".py")


def test_venv_ready_false_for_missing(tmp_path):
    assert bootstrap.venv_ready(tmp_path / "nope") is False
