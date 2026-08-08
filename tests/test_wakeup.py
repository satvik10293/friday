"""Tests for FRIDAY's honest wake-up narration — the spoken line is derived
from the degradation ledger, so it tells the truth about what came up."""

from datetime import datetime

import pytest

from core.launcher.wakeup import wakeup_line, announce, _friendly, _greeting
from core.observability import get_degradation_ledger, FAILED, DEGRADED, SKIPPED


@pytest.fixture(autouse=True)
def _clean_ledger():
    get_degradation_ledger().clear()
    yield
    get_degradation_ledger().clear()


def _report():
    return get_degradation_ledger().report()


def test_healthy_is_all_nominal():
    line = wakeup_line([], _report(), owner="Satvik",
                       now=datetime(2026, 8, 8, 20, 0))
    assert "Good evening, Satvik." in line
    assert "All systems nominal" in line
    assert "I'm ready" in line


def test_greeting_tracks_time_of_day():
    assert _greeting(datetime(2026, 1, 1, 8)) == "Good morning"
    assert _greeting(datetime(2026, 1, 1, 14)) == "Good afternoon"
    assert _greeting(datetime(2026, 1, 1, 22)) == "Good evening"


def test_no_owner_omits_name():
    line = wakeup_line([], _report(), now=datetime(2026, 8, 8, 9, 0))
    assert line.startswith("Good morning.")


def test_single_degraded_faculty_is_named_with_reason():
    get_degradation_ledger().record(
        "audio.stt", "faster-whisper not installed — hearing disabled",
        severity=FAILED)
    line = wakeup_line([], _report(), owner="Satvik")
    assert "hearing" in line                       # friendly name, not "audio.stt"
    assert "degraded" in line
    assert "faster-whisper not installed" in line  # the real reason, spoken
    assert "running degraded" in line


def test_multiple_degraded_faculties_are_listed():
    led = get_degradation_ledger()
    led.record("audio.stt", "no whisper", severity=FAILED)
    led.record("vision.live", "camera not found", severity=DEGRADED)
    line = wakeup_line([], led.report(), owner="Satvik")
    assert "hearing" in line and "vision" in line
    assert "are degraded" in line                  # plural verb


def test_skipped_only_stays_nominal():
    # intentional opt-outs (skipped) must NOT make her announce degradation
    get_degradation_ledger().record("boot.knowledge", "no memory brain",
                                     severity=SKIPPED)
    line = wakeup_line([], _report())
    assert "All systems nominal" in line


def test_duplicate_faculties_collapse():
    led = get_degradation_ledger()
    led.record("voice.tts", "edge-tts down", severity=DEGRADED)
    led.record("voice.playback", "device busy", severity=DEGRADED)
    line = wakeup_line([], led.report())
    # both map to "voice" — it should be named once, not twice
    assert line.count("voice") == 1


def test_friendly_names():
    assert _friendly("audio.stt") == "hearing"
    assert _friendly("vision.live") == "vision"
    assert _friendly("boot.memory") == "memory"
    assert _friendly("boot.some_new_stage") == "some new stage"


def test_announce_respects_disabled_narration():
    """With ui.wake_narration off, announce returns the line WITHOUT touching
    the voice stack — so it's safe on a box with no audio."""
    get_degradation_ledger().record("audio.stt", "no whisper", severity=FAILED)

    class _FakeLauncher:
        config = {"owner_name": "Satvik", "ui": {"wake_narration": False}}
        report = {"startup": {"stages": []}}

    line = announce(_FakeLauncher(), now=datetime(2026, 8, 8, 20, 0))
    assert "hearing" in line
    assert "Good evening, Satvik" in line
