"""
tests/test_io_hardening.py — M32.5 base perfection.

Pins the io-layer repairs: friday_action's missing threading import (calling
start_battery_alert raised NameError since 3.0), the Face's per-process
SECRET_KEY (was a hardcoded constant), and _jobs eviction (grew unbounded).
"""

import time

import pytest

import core.io.friday_action as action_mod
import core.io.friday_face as face


def test_action_threading_import_present():
    assert hasattr(action_mod, "threading"), \
        "start_battery_alert references threading but the module never imported it"


def test_start_battery_alert_no_longer_raises():
    act = action_mod.FridayAction()
    act.start_battery_alert(threshold=0)   # NameError before the fix


def test_secret_key_is_per_process_not_constant():
    pytest.importorskip("flask")
    app1 = face.create_app()
    app2 = face.create_app()
    assert app1.config["SECRET_KEY"] != "friday-face-secret"
    assert app1.config["SECRET_KEY"] != app2.config["SECRET_KEY"]
    assert len(app1.config["SECRET_KEY"]) >= 64


def test_job_eviction_drops_stale_completed_jobs(monkeypatch):
    monkeypatch.setattr(face, "_jobs", {
        "old-done":  {"status": "done",    "done_at": time.time() - 10_000},
        "new-done":  {"status": "done",    "done_at": time.time()},
        "running":   {"status": "running"},
    })
    face._evict_jobs()
    assert "old-done" not in face._jobs, "stale completed job survived TTL"
    assert "new-done" in face._jobs
    assert "running" in face._jobs, "running job must never be evicted"


def test_job_eviction_enforces_cap(monkeypatch):
    now = time.time()
    jobs = {f"j{i}": {"status": "done", "done_at": now + i} for i in range(300)}
    jobs["live"] = {"status": "running"}
    monkeypatch.setattr(face, "_jobs", jobs)
    face._evict_jobs()
    assert len(face._jobs) <= face._JOBS_MAX + 1
    assert "live" in face._jobs
    assert "j299" in face._jobs, "newest completed jobs should be kept"
