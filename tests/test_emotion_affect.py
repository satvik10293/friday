"""
The Emotion Brain's affect model (completed): named emotions + event appraisal.
Proves the mood reflects what happened (by meaning), names the feeling, decays
toward neutral, and reports real (non-placeholder) health.
"""

from __future__ import annotations

from core.brains.emotion.brain import EmotionBrain, _emotion_label


def test_named_emotions_cover_the_quadrants():
    assert _emotion_label(0.0, 0.0) == "neutral"
    assert _emotion_label(0.5, 0.7) == "energized"      # pleasant + activated
    assert _emotion_label(-0.5, 0.7) == "alarmed"       # unpleasant + activated
    assert _emotion_label(0.5, 0.1) == "content"        # pleasant + calm
    assert _emotion_label(-0.4, 0.2) == "concerned"     # unpleasant, low arousal
    assert _emotion_label(0.0, 0.3) == "calm"           # flat valence, mild arousal


def test_appraise_emergency_makes_her_alarmed():
    b = EmotionBrain()
    b.appraise("emergency", priority=1.0)
    mood = b.local.get("mood")
    assert mood["valence"] < 0 and mood["arousal"] > 0.4
    assert b.emotion() == "alarmed"


def test_appraise_success_makes_her_content():
    b = EmotionBrain()
    b.appraise("success", priority=1.0)
    assert b.local.get("mood")["valence"] > 0.2
    assert b.emotion() in ("content", "energized")


def test_unknown_category_is_affectively_neutral():
    b = EmotionBrain()
    b.appraise("weather_report", priority=1.0)
    assert b.emotion() == "neutral"


def test_mood_decays_toward_neutral_over_ticks():
    b = EmotionBrain()
    b.appraise("emergency", priority=1.0)
    hot = abs(b.local.get("mood")["arousal"])
    for _ in range(10):
        b.tick()                                        # reason() decays each tick
    cooled = abs(b.local.get("mood")["arousal"])
    assert cooled < hot, "arousal did not decay"


def test_situation_report_names_the_emotion():
    b = EmotionBrain()
    assert b.tick() is None                             # neutral → nothing to report
    b.appraise("emergency", priority=1.0)
    report = b.tick()
    assert report is not None and report.data["label"] == b.emotion()


def test_health_is_real_not_placeholder():
    b = EmotionBrain()
    h = b.health()
    assert h["status"] == "ok"
    assert h["emotion"] == "neutral" and "mood" in h
