"""M12.1 — wake-word engine + language detector."""

import numpy as np

from core.audio.listener.language_detector import LanguageDetector
from core.audio.listener.wake_word import WakeWordEngine


# ── wake word ──────────────────────────────────────────────────────────────────────
def test_default_words():
    we = WakeWordEngine()
    assert "friday" in we.words() and "athena" in we.words()


def test_detect_hit():
    we = WakeWordEngine()
    hit, word, conf = we.detect("friday what time is it")
    assert hit and word == "friday" and conf >= 0.8


def test_detect_miss():
    we = WakeWordEngine()
    hit, _, _ = we.detect("just talking to myself")
    assert not hit


def test_near_miss_matches():
    we = WakeWordEngine(threshold=0.4)
    hit, word, _ = we.detect("fryday turn on the lights")   # slight misspelling
    assert hit and word == "friday"


def test_hot_swap_vocabulary():
    we = WakeWordEngine()
    we.add_word("jarvis")
    assert "jarvis" in we.words()
    assert we.detect("jarvis hello")[0]
    assert we.remove_word("athena")
    assert "athena" not in we.words()
    we.set_words(["computer"])
    assert we.words() == ["computer"]


def test_strip_wake_word():
    we = WakeWordEngine()
    assert we.strip_wake_word("friday what is 2 plus 2") == "what is 2 plus 2"
    assert we.strip_wake_word("what is 2 plus 2") == "what is 2 plus 2"


def test_independent_from_transcription():
    import core.audio.listener.wake_word as ww
    import types
    imported = {v.__name__ for v in vars(ww).values() if isinstance(v, types.ModuleType)}
    assert not any("transcription" in m for m in imported)


def test_detect_audio_seam():
    we = WakeWordEngine()
    hit, _, conf = we.detect_audio(np.zeros(320, dtype=np.float32))
    assert hit is False and conf == 0.0       # seam for a real KWS model


# ── language detector ──────────────────────────────────────────────────────────────
def test_english():
    r = LanguageDetector().detect("what is the weather today")
    assert r.language == "en"


def test_telugu():
    r = LanguageDetector().detect("నమస్కారం ఎలా ఉన్నారు")
    assert r.language == "te" and r.confidence > 0


def test_hindi():
    r = LanguageDetector().detect("नमस्ते आप कैसे हैं")
    assert r.language == "hi" and r.confidence > 0


def test_empty_defaults_english():
    assert LanguageDetector().detect("").language == "en"


def test_supported_languages():
    assert set(LanguageDetector().supported()) >= {"en", "te", "hi"}
