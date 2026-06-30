"""M20 — Production launcher: platform adapter, structured logging, health diagnostics,
ordered startup sequence (with graceful recovery), and the Launcher orchestration."""

import importlib

import pytest

from core.launcher.health import HealthMonitor
from core.launcher.launcher import Launcher
from core.launcher.logging_config import configure_logging
from core.launcher.platform_adapter import PlatformAdapter, detect_os
from core.launcher.startup import STARTUP_STAGES, StartupSequence


# ── platform adapter ─────────────────────────────────────────────────────────────────
def test_detect_os():
    assert detect_os() in ("windows", "macos", "linux")


def test_platform_dirs_resolve(tmp_path, monkeypatch):
    monkeypatch.setenv("FRIDAY_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("FRIDAY_LOG_DIR", str(tmp_path / "logs"))
    pa = PlatformAdapter()
    assert pa.data_dir() == tmp_path / "data" and pa.log_dir() == tmp_path / "logs"
    pa.ensure_dirs()
    assert pa.log_dir().exists()
    info = pa.info()
    assert info["os"] in ("windows", "macos", "linux") and "python" in info


# ── logging ──────────────────────────────────────────────────────────────────────────
def test_logging_configures_rotation(tmp_path):
    report = configure_logging(log_dir=tmp_path, level="INFO", console=False)
    assert any("friday.log" in h for h in report["handlers"]) or report.get("already_configured")
    # idempotent
    assert configure_logging(log_dir=tmp_path).get("already_configured")


# ── startup sequence ─────────────────────────────────────────────────────────────────
def test_startup_runs_all_stages_in_order():
    report = StartupSequence(headless=True).run()
    assert [s.stage for s in report.stages] == list(STARTUP_STAGES)
    assert report.ready and report.ok()
    # the cognitive kernel + coordinator + executive came up
    assert report.components.get("coordinator") is not None
    assert report.components.get("executive") is not None
    assert report.components.get("memory") is not None


def test_startup_graceful_recovery_on_stage_failure():
    class BadStartup(StartupSequence):
        def _stage_simulation(self):
            raise RuntimeError("simulation init blew up")

    report = BadStartup(headless=True).run()
    sim = next(s for s in report.stages if s.stage == "simulation")
    assert sim.status == "failed"                          # recorded, not raised
    # later stages still ran and FRIDAY still reached ready
    assert any(s.stage == "coordinator" and s.status == "ok" for s in report.stages)
    assert report.ready


def test_startup_voice_ui_skipped_headless():
    report = StartupSequence(headless=True).run()
    for stage in ("voice", "ui"):
        assert next(s for s in report.stages if s.stage == stage).status == "skipped"


# ── health monitor ───────────────────────────────────────────────────────────────────
def test_health_diagnostics():
    seq = StartupSequence(headless=True).run()
    hm = HealthMonitor(container=seq.components.get("kernel"),
                       coordinator=seq.components.get("coordinator"),
                       simulation=seq.components.get("simulation"))
    diag = hm.diagnostics()
    assert "system" in diag and "threads" in diag["system"]
    assert diag["status"] in ("ok", "degraded")


# ── launcher ─────────────────────────────────────────────────────────────────────────
def test_launcher_boots_ready(tmp_path, monkeypatch):
    monkeypatch.setenv("FRIDAY_LOG_DIR", str(tmp_path / "logs"))
    monkeypatch.setenv("FRIDAY_DATA_DIR", str(tmp_path / "data"))
    report = Launcher(profile="testing", headless=True).run()
    assert report["friday"] == "ready"
    assert report["startup"]["ok"] and report["health"]["status"] in ("ok", "degraded")
    assert "dependencies" in report and "platform" in report


def test_launcher_validates_dependencies():
    deps = Launcher(profile="testing", headless=True).validate_dependencies()
    assert "python" in deps and "available" in deps and "missing" in deps


def test_side_effect_free_import():
    import threading
    before = threading.active_count()
    importlib.import_module("core.launcher")
    assert threading.active_count() == before
