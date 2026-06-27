"""M12.1 — speech segmenter + transcription + speaker + emotion."""

import numpy as np

from core.audio.listener.emotion import EmotionEstimator
from core.audio.listener.microphone import FRAME_SIZE, SAMPLE_RATE, silence, tone
from core.audio.listener.speaker import SpeakerRecognizer, fingerprint
from core.audio.listener.speech_segmenter import SpeechSegmenter
from core.audio.listener.transcription import FakeTranscriber, get_transcriber


def _frames(wav):
    n = len(wav) // FRAME_SIZE
    return [wav[i * FRAME_SIZE:(i + 1) * FRAME_SIZE] for i in range(n)]


# ── segmentation ───────────────────────────────────────────────────────────────────
def test_segments_speech_between_silence():
    seg = SpeechSegmenter()
    wav = np.concatenate([silence(0.2), tone(0.5, 300, 0.3), silence(1.0)])
    out = None
    for f in _frames(wav):
        s = seg.process(f)
        if s is not None:
            out = s
            break
    assert out is not None
    assert out.duration_s > 0.3      # captured the speech (plus pre-roll)


def test_no_segment_for_pure_silence():
    seg = SpeechSegmenter()
    for f in _frames(silence(1.5)):
        assert seg.process(f) is None


def test_preroll_included():
    seg = SpeechSegmenter(preroll_frames=8)
    wav = np.concatenate([silence(0.3), tone(0.4, 300, 0.3), silence(1.0)])
    out = next((s for f in _frames(wav) if (s := seg.process(f)) is not None), None)
    assert out is not None
    # duration exceeds the 0.4s of speech because pre-roll frames were prepended
    assert out.duration_s >= 0.4


def test_multiple_commands():
    seg = SpeechSegmenter()
    wav = np.concatenate([silence(0.2), tone(0.4, 300, 0.3), silence(1.0),
                          tone(0.4, 300, 0.3), silence(1.0)])
    segs = [s for f in _frames(wav) if (s := seg.process(f)) is not None]
    assert len(segs) == 2            # two back-to-back commands


def test_flush_closes_open_segment():
    seg = SpeechSegmenter()
    wav = np.concatenate([silence(0.2), tone(0.4, 300, 0.3)])   # no closing silence
    for f in _frames(wav):
        seg.process(f)
    assert seg.flush() is not None


# ── transcription ──────────────────────────────────────────────────────────────────
def test_fake_transcriber_script():
    t = FakeTranscriber(script=["hello world"])
    r = t.transcribe(tone(0.1))
    assert r.text == "hello world" and r.confidence > 0 and r.engine == "fake"


def test_get_transcriber_returns_local():
    t = get_transcriber()
    assert hasattr(t, "transcribe")


# ── speaker ────────────────────────────────────────────────────────────────────────
def test_fingerprint_deterministic():
    a = tone(0.3, 300, 0.3)
    assert np.allclose(fingerprint(a), fingerprint(a))


def test_speaker_enroll_and_identify():
    sr = SpeakerRecognizer(threshold=0.8)
    voice = tone(0.4, 220, 0.3)
    sr.enroll("satvik", voice)
    res = sr.identify(voice)
    assert res.label == "satvik" and res.known


def test_unknown_speaker():
    sr = SpeakerRecognizer(threshold=0.99)
    sr.enroll("satvik", tone(0.4, 220, 0.3))
    res = sr.identify(tone(0.4, 900, 0.3))     # very different voice
    assert res.label == "unknown" and not res.known


def test_no_enrollment_unknown():
    assert SpeakerRecognizer().identify(tone(0.3)).label == "unknown"


# ── emotion ────────────────────────────────────────────────────────────────────────
def test_emotion_calm_for_quiet():
    r = EmotionEstimator().estimate(tone(0.4, 200, 0.005))
    assert r.emotion == "calm"


def test_emotion_returns_known_label():
    r = EmotionEstimator().estimate(tone(0.4, 300, 0.2))
    assert r.emotion in EmotionEstimator().emotions()
    assert "level" in r.features
