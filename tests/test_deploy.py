"""M20 — Deployment & release engineering: version metadata, installer (dry-run + secure
secret handling), build packaging (+ checksum + exclusion safety), release changelog +
manifest verification."""

import json
import zipfile
from pathlib import Path

import pytest

from deploy import (Installer, build_package, generate_changelog, metadata, python_ok,
                    release_manifest, verify_package, verify_release)


# ── version ──────────────────────────────────────────────────────────────────────────
def test_version_metadata():
    m = metadata()
    assert m["name"] == "FRIDAY" and m["private"] is True
    assert m["version"] and python_ok() is True


# ── installer ────────────────────────────────────────────────────────────────────────
def test_installer_dry_run_steps():
    rep = Installer(dry_run=True).run(groq_key=None)
    assert rep["dry_run"] and rep["steps"]["python"]["ok"]
    assert rep["steps"]["dependencies"].get("dry_run") and "command" in rep["steps"]["dependencies"]
    assert rep["steps"]["secret"]["configured"] is False         # no key → skipped


def test_installer_secret_is_secure(tmp_path):
    env = tmp_path / ".env"
    inst = Installer(dry_run=True)
    res = inst.configure_secret(groq_key="gsk_VERY_SECRET_123", env_path=env)
    assert res["ok"] and res["configured"]
    assert "GROQ_API_KEY=gsk_VERY_SECRET_123" in env.read_text()
    # the key must never appear in the returned report (no leakage)
    assert "gsk_VERY_SECRET_123" not in json.dumps(res)


def test_installer_validate_config():
    res = Installer(dry_run=True).validate_config()
    assert res["ok"] is True                                     # repo ships a valid config


def test_installer_full_dry_run_with_key(tmp_path):
    rep = Installer(dry_run=True).run(groq_key="gsk_abc", env_path=tmp_path / ".env")
    assert rep["installed"] is True
    assert "gsk_abc" not in json.dumps(rep)                      # never leaked


# ── build ────────────────────────────────────────────────────────────────────────────
def test_build_package_and_verify(tmp_path):
    out = build_package(dest=tmp_path / "dist")
    assert out["ok"] and out["manifest"]["files"] > 100
    archive = Path(out["archive"])
    assert archive.exists() and out["manifest"]["sha256"]
    v = verify_package(archive, expected_sha256=out["manifest"]["sha256"])
    assert v["ok"] and v["crc_ok"] and v["leaked_excludes"] == []


def test_build_excludes_secrets_and_weights(tmp_path):
    out = build_package(dest=tmp_path / "dist")
    with zipfile.ZipFile(out["archive"]) as zf:
        names = zf.namelist()
    # no secrets, databases, weights, venv, or git in the package
    assert not any(n == ".env" or n.endswith((".db", ".gguf", ".safetensors", ".pt"))
                   for n in names)
    assert not any(n.startswith((".venv/", ".git/", "data/", "dist/")) for n in names)
    assert any(n.startswith("core/") for n in names)            # source is included


def test_verify_detects_tampered_checksum(tmp_path):
    out = build_package(dest=tmp_path / "dist")
    v = verify_package(Path(out["archive"]), expected_sha256="deadbeef")
    assert v["ok"] is False                                     # checksum mismatch caught


# ── release ──────────────────────────────────────────────────────────────────────────
def test_changelog_generation():
    cl = generate_changelog()
    assert cl["count"] >= 10 and cl["milestones"][0].startswith("M1")


def test_release_manifest_and_verify(tmp_path):
    build_package(dest=tmp_path / "dist")
    manifest = release_manifest(dist=tmp_path / "dist")
    assert manifest["version"] and manifest["artifacts"]
    assert manifest["artifacts"][0]["verified"] is True
    assert verify_release(dist=tmp_path / "dist")["ok"] is True
