"""Tests for the degradation ledger — FRIDAY's honest record of what isn't
working. Covers the ledger itself, boot feeding it, and status() surfacing it."""

import pytest

from core.observability import (get_degradation_ledger, note_degraded,
                                DegradationLedger, FAILED, DEGRADED, SKIPPED)


@pytest.fixture(autouse=True)
def _clean_ledger():
    get_degradation_ledger().clear()
    yield
    get_degradation_ledger().clear()


def test_fresh_ledger_is_healthy():
    r = get_degradation_ledger().report()
    assert r["healthy"] is True
    assert r["failed"] == r["degraded"] == r["skipped"] == 0
    assert r["subsystems"] == {}
    assert r["recent"] == []


def test_degraded_flips_health_and_is_counted():
    note_degraded("vision", "camera not found")
    r = get_degradation_ledger().report()
    assert r["healthy"] is False
    assert r["degraded"] == 1
    assert "vision" in r["subsystems"]
    assert r["subsystems"]["vision"]["last_detail"] == "camera not found"


def test_failed_flips_health():
    note_degraded("voice.tts", severity=FAILED)
    assert get_degradation_ledger().healthy() is False
    assert get_degradation_ledger().report()["failed"] == 1


def test_skipped_alone_stays_healthy_but_visible():
    """An opt-out subsystem is legitimately skipped: surfaced, not counted
    against health."""
    note_degraded("knowledge", "no memory brain", severity=SKIPPED)
    r = get_degradation_ledger().report()
    assert r["healthy"] is True          # skipped-only is still healthy
    assert r["skipped"] == 1
    assert "knowledge" in r["subsystems"]  # ...but it IS visible


def test_exception_is_captured_without_detail():
    try:
        raise ValueError("boom")
    except ValueError as e:
        note_degraded("audio", exc=e)
    s = get_degradation_ledger().report()["subsystems"]["audio"]
    assert s["last_exc"] == "ValueError"
    assert "boom" in s["last_detail"]


def test_repeated_records_accumulate():
    for _ in range(3):
        note_degraded("net", "timeout")
    s = get_degradation_ledger().report()["subsystems"]["net"]
    assert s["count"] == 3
    assert s["by_severity"][DEGRADED] == 3


def test_record_never_raises_on_bad_input():
    # observability must never break its caller, even with junk input
    get_degradation_ledger().record(None, None, severity="not-a-severity")
    assert isinstance(get_degradation_ledger().report(), dict)


def test_recent_is_bounded():
    led = DegradationLedger(recent_max=4)
    for i in range(10):
        led.record("x", f"event {i}")
    recent = led.report()["recent"]
    assert len(recent) == 4
    assert recent[0]["detail"] == "event 9"      # newest first


def test_summary_line():
    led = get_degradation_ledger()
    assert led.summary_line() == "all subsystems nominal"
    led.record("a", severity=FAILED)
    led.record("b", severity=SKIPPED)
    assert "1 failed" in led.summary_line()
    assert "1 skipped" in led.summary_line()


def test_boot_feeds_ledger():
    """A headless boot records its skipped/failed stages into the ledger, so a
    'ready' verdict no longer hides subsystems that didn't come up."""
    from core.launcher.startup import StartupSequence
    get_degradation_ledger().clear()
    StartupSequence(headless=True).run()
    r = get_degradation_ledger().report()
    # every recorded boot subsystem is namespaced boot.* and carries a reason
    boot_events = {k: v for k, v in r["subsystems"].items()
                   if k.startswith("boot.")}
    for name, s in boot_events.items():
        assert s["last_severity"] in (FAILED, SKIPPED)
        assert s["last_detail"]           # never a silent skip
