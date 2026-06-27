"""M12.1 — full listening pipeline: events, IOS routing, privacy, latency, stress."""

import numpy as np
import pytest

from core.audio.listener.events import AudioEvent
from core.audio.listener.microphone import ArraySource, FRAME_SIZE, noise, silence, tone
from core.audio.listener.pipeline import ListeningPipeline, ListeningState
from core.audio.listener.service import ListeningService
from core.audio.listener.transcription import FakeTranscriber


class FakeIOS:
    def __init__(self):
        self.calls = []
    def think(self, prompt, context=None):
        self.calls.append((prompt, context))
        class R:
            def to_dict(self_): return {"answer": "ok: " + prompt}
        return R()


def _command_wav(speech_s=0.5):
    return np.concatenate([silence(0.2), tone(speech_s, 300, 0.3), silence(1.0)])


def _pipe(script, ios=None, wake_required=True):
    mic = ArraySource(_command_wav())
    return ListeningPipeline(microphone=mic, transcriber=FakeTranscriber(script=script),
                             intelligence_os=ios, wake_required=wake_required)


# ── events + routing ───────────────────────────────────────────────────────────────
def test_pipeline_emits_event_sequence():
    p = _pipe(["friday hello"])
    seen = []
    p.bus.on_any(lambda e: seen.append(e.kind))
    p.pump()
    assert AudioEvent.SPEECH_DETECTED.value in seen
    assert AudioEvent.COMMAND_STARTED.value in seen
    assert AudioEvent.WAKE_WORD_DETECTED.value in seen
    assert AudioEvent.TRANSCRIPT_READY.value in seen
    assert AudioEvent.COMMAND_FINISHED.value in seen


def test_command_routed_to_ios_with_context():
    ios = FakeIOS()
    p = _pipe(["friday what is 2 plus 2"], ios=ios)
    p.pump()
    assert ios.calls
    prompt, ctx = ios.calls[0]
    assert prompt == "what is 2 plus 2"            # wake word stripped
    assert ctx["source"] == "voice" and "emotion" in ctx and "speaker" in ctx


def test_wake_gating_blocks_non_wake_speech():
    ios = FakeIOS()
    p = _pipe(["just thinking out loud"], ios=ios, wake_required=True)
    p.pump()
    assert ios.calls == []                          # no wake word → not routed


def test_no_wake_required_routes_everything():
    ios = FakeIOS()
    p = _pipe(["turn on the lights"], ios=ios, wake_required=False)
    p.pump()
    assert ios.calls and ios.calls[0][0] == "turn on the lights"


def test_command_result_shape():
    p = _pipe(["friday hello"], ios=FakeIOS())
    p.mic.open()
    result = None
    while True:
        f = p.mic.read()
        if f is None:
            break
        r = p.process_frame(f)
        if r:
            result = r
    assert result["wake"] and result["routed"]
    assert "confidence" in result and "latency_ms" in result
    assert result["response"]["answer"].startswith("ok:")


# ── privacy / security ─────────────────────────────────────────────────────────────
def test_privacy_mode_stops_processing():
    ios = FakeIOS()
    p = _pipe(["friday hello"], ios=ios)
    p.set_privacy(True)
    p.pump()
    assert ios.calls == []                          # nothing captured/processed
    assert p.state == ListeningState.DISABLED


def test_raw_audio_not_stored_by_default():
    p = _pipe(["friday hello"])
    p.pump()
    assert p._stored == []                           # privacy: no raw audio kept


def test_store_audio_when_enabled():
    mic = ArraySource(_command_wav())
    p = ListeningPipeline(microphone=mic, transcriber=FakeTranscriber(script=["friday hi"]),
                          store_audio=True)
    p.pump()
    assert len(p._stored) == 1


# ── continuous listening (never restarts mic) ──────────────────────────────────────
def test_returns_to_idle_after_command():
    p = _pipe(["friday hello"])
    p.pump()
    assert p.state == ListeningState.IDLE
    assert p.mic.is_open                             # mic stays open


def test_handles_multiple_commands_one_session():
    wav = np.concatenate([silence(0.2), tone(0.4, 300, 0.3), silence(1.0),
                          tone(0.4, 300, 0.3), silence(1.0)])
    mic = ArraySource(wav)
    ios = FakeIOS()
    p = ListeningPipeline(microphone=mic, intelligence_os=ios, wake_required=False,
                          transcriber=FakeTranscriber(script=["first command", "second command"]))
    p.pump()
    assert len(ios.calls) == 2


# ── latency + stress ───────────────────────────────────────────────────────────────
def test_per_frame_latency_low():
    import time
    p = _pipe(["friday hello"])
    p.mic.open()
    frame = tone(0.02, 300, 0.3)
    t0 = time.perf_counter()
    for _ in range(50):
        p.process_frame(frame)
    avg_ms = (time.perf_counter() - t0) * 1000 / 50
    assert avg_ms < 50                               # well under the 50ms budget


def test_stress_long_stream_stable():
    # ~30s of alternating speech/silence → memory bounded, no crash
    chunks = []
    for _ in range(15):
        chunks += [silence(0.3), tone(0.4, 300, 0.3), silence(1.0)]
    mic = ArraySource(np.concatenate(chunks))
    ios = FakeIOS()
    p = ListeningPipeline(microphone=mic, intelligence_os=ios, wake_required=False,
                          transcriber=FakeTranscriber(default="ping"))
    frames = p.pump()
    assert frames > 1000
    assert p.buffer.frames_held <= p.buffer.capacity_frames   # constant memory
    assert p.metrics.snapshot()["commands"] >= 10


# ── diagnostics + service ──────────────────────────────────────────────────────────
def test_status_diagnostics():
    p = _pipe(["friday hello"])
    p.pump()
    st = p.status()
    for k in ("microphone", "state", "stage", "volume", "noise_level",
              "speech_detected", "wake_words", "speaker", "language",
              "confidence", "latency_ms", "privacy", "metrics"):
        assert k in st


def test_service_dashboard():
    svc = ListeningService(intelligence_os=FakeIOS(),
                           microphone=ArraySource(_command_wav()))
    svc.pipeline.transcriber = FakeTranscriber(script=["friday hi"])
    svc.pipeline.pump()
    d = svc.dashboard()
    assert d["title"] == "Listening" and d["local"] is True
    assert "recent_events" in d and d["metrics"]["commands"] >= 1


def test_health():
    svc = ListeningService(microphone=ArraySource())
    assert svc.health()["status"] == "ok"
    svc.set_privacy(True)
    assert svc.health()["status"] == "privacy"
