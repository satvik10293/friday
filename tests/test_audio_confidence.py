"""M12.1 — audio confidence analyzer + listening metrics + interruption."""

from core.audio.listener.confidence import ConfidenceAnalyzer
from core.audio.listener.interruption import InterruptionController
from core.audio.listener.metrics import ListeningMetrics


# ── confidence ─────────────────────────────────────────────────────────────────────
def test_confidence_range():
    c = ConfidenceAnalyzer().analyze(signal_rms=0.1, noise_floor=0.001,
                                     language_confidence=0.9, wake_confidence=1.0,
                                     transcription_confidence=0.9)
    assert 0.0 <= c.overall <= 1.0 and c.percent == int(round(c.overall * 100))


def test_confidence_rises_with_snr():
    a = ConfidenceAnalyzer()
    low = a.analyze(signal_rms=0.002, noise_floor=0.001, transcription_confidence=0.5)
    high = a.analyze(signal_rms=0.5, noise_floor=0.001, transcription_confidence=0.5)
    assert high.signal_quality > low.signal_quality


def test_confidence_components_present():
    c = ConfidenceAnalyzer().analyze(signal_rms=0.1, noise_floor=0.001,
                                     language_confidence=0.5, wake_confidence=0.5,
                                     transcription_confidence=0.5)
    d = c.to_dict()
    for k in ("signal_quality", "noise_estimate", "language_confidence",
              "wake_confidence", "transcription_confidence", "percent"):
        assert k in d


# ── metrics ────────────────────────────────────────────────────────────────────────
def test_metrics_record_command():
    m = ListeningMetrics()
    m.record_command(latency_ms=120, confidence=0.8, speech_s=1.0, recognized=True)
    m.record_command(latency_ms=80, confidence=0.6, speech_s=0.5, recognized=False)
    s = m.snapshot()
    assert s["commands"] == 2 and s["recognition_failures"] == 1
    assert s["avg_latency_ms"] == 100.0 and s["speech_seconds"] == 1.5


def test_metrics_wake_tracking():
    m = ListeningMetrics()
    m.record_wake()
    m.record_wake(false_positive=True)
    m.record_missed_wake()
    s = m.snapshot()
    assert s["wake_activations"] == 2 and s["false_activations"] == 1
    assert s["missed_activations"] == 1


# ── interruption ───────────────────────────────────────────────────────────────────
def test_interrupt_while_speaking():
    ic = InterruptionController()
    ic.begin_speaking()
    assert ic.user_interrupt() is True
    assert ic.should_stop()
    ic.end_speaking()


def test_interrupt_when_idle():
    ic = InterruptionController()
    assert ic.request_interrupt() is False     # nothing to interrupt


def test_self_interrupt():
    ic = InterruptionController()
    ic.begin_speaking()
    assert ic.self_interrupt() and ic.last_source == "self"


def test_cancel_and_resume():
    ic = InterruptionController()
    ic.begin_speaking(); ic.cancel()
    assert ic.should_stop() and not ic.speaking
    ic.resume()
    assert not ic.should_stop()


def test_nested_conversations():
    ic = InterruptionController()
    ic.push_context("weather"); ic.push_context("follow-up")
    assert ic.depth == 2
    assert ic.pop_context().topic == "follow-up"
    assert ic.depth == 1
