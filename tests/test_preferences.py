"""M9 — PreferenceEngine: automatic preference learning."""

from core.user_model.models import PreferenceCategory
from core.user_model.preferences import PreferenceEngine


def test_first_observation_starts_above_neutral(user_model_store):
    pe = PreferenceEngine(user_model_store)
    pref = pe.observe("learning.detail", positive=True,
                      category=PreferenceCategory.LEARNING.value)
    assert pref.score > 0.5
    assert pref.evidence_count == 1


def test_repeated_positive_raises_score(user_model_store):
    pe = PreferenceEngine(user_model_store)
    for _ in range(5):
        pe.observe("learning.detail", positive=True)
    assert pe.score("learning.detail") > 0.8


def test_negative_lowers_score(user_model_store):
    pe = PreferenceEngine(user_model_store)
    for _ in range(4):
        pe.observe("ui.dark_mode", positive=False)
    assert pe.score("ui.dark_mode") < 0.5


def test_score_clamped(user_model_store):
    pe = PreferenceEngine(user_model_store)
    for _ in range(50):
        pe.observe("x", positive=True)
    assert pe.score("x") <= 1.0


def test_set_explicit_preference(user_model_store):
    pe = PreferenceEngine(user_model_store)
    pref = pe.set("ui.theme", "dark", category=PreferenceCategory.UI.value)
    assert pref.value == "dark" and pref.score >= 0.9


def test_list_by_category(user_model_store):
    pe = PreferenceEngine(user_model_store)
    pe.set("ui.theme", "dark", category=PreferenceCategory.UI.value)
    pe.set("coding.style", "pep8", category=PreferenceCategory.CODING.value)
    ui = pe.list(category=PreferenceCategory.UI.value)
    assert len(ui) == 1 and ui[0].category == PreferenceCategory.UI.value


def test_strong_preferences(user_model_store):
    pe = PreferenceEngine(user_model_store)
    for _ in range(5):
        pe.observe("strong.one", positive=True)
    pe.observe("weak.one", positive=True)
    strong = {p.key for p in pe.strong()}
    assert "strong.one" in strong


def test_default_score_when_absent(user_model_store):
    pe = PreferenceEngine(user_model_store)
    assert pe.score("never.seen", default=0.42) == 0.42
