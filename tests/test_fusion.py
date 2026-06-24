"""
tests/test_fusion.py — FRIDAY 4.0 M6
Sensor fusion: corroborating observations from multiple sensors combine into a
single higher-confidence observation.
"""

import pytest

from core.perception import (
    FusionRule, ObservationType, SensorFusion, new_observation, noisy_or,
)


def _screen(window):
    return new_observation(ObservationType.SCREEN, "screen", {"window": window}, confidence=0.6)


def _process(proc):
    return new_observation(ObservationType.APPLICATION, "process", {"process": proc},
                           confidence=0.7)


# ── math ─────────────────────────────────────────────────────────────────────
def test_noisy_or_increases_with_corroboration():
    assert noisy_or([0.6]) == pytest.approx(0.6)
    assert noisy_or([0.6, 0.7]) == pytest.approx(1 - 0.4 * 0.3)   # 0.88
    assert noisy_or([0.6, 0.7]) > 0.7


def test_noisy_or_empty():
    assert noisy_or([]) == 0.0


# ── application detection ────────────────────────────────────────────────────
def test_fuses_chrome_from_screen_and_process():
    fused = SensorFusion().fuse([_screen("Chrome"), _process("chrome.exe")])
    assert len(fused) == 1
    app = fused[0]
    assert app.type == ObservationType.APPLICATION
    assert app.payload["name"].lower() == "chrome"
    assert app.confidence > 0.7                       # boosted above either source
    assert set(app.payload["corroborated_by"]) == {"screen", "process"}


def test_single_source_not_fused():
    fused = SensorFusion().fuse([_screen("Chrome")])
    assert fused == []                                 # needs >= 2 corroborating sources


def test_fused_observation_carries_entity_metadata():
    fused = SensorFusion().fuse([_screen("Chrome"), _process("chrome.exe")])[0]
    assert fused.metadata["fused"] is True
    assert fused.metadata["entity_name"].lower() == "chrome"
    assert fused.metadata["entity_kind"] == "application"


def test_fuse_and_merge_keeps_raw():
    obs = [_screen("Chrome"), _process("chrome.exe")]
    merged = SensorFusion().fuse_and_merge(obs)
    assert len(merged) == 3                            # 2 raw + 1 fused


def test_distinct_apps_not_merged():
    fused = SensorFusion().fuse([_screen("Chrome"), _process("code.exe")])
    assert fused == []                                 # different subjects, no corroboration


def test_custom_rule_registration():
    fusion = SensorFusion(rules=[])
    fusion.register_rule(FusionRule(
        name="by_tag", key_fn=lambda o: o.payload.get("tag"),
        out_type=ObservationType.CUSTOM, min_sources=2))
    a = new_observation(ObservationType.CUSTOM, "s1", {"tag": "z"}, confidence=0.5)
    b = new_observation(ObservationType.CUSTOM, "s2", {"tag": "z"}, confidence=0.5)
    fused = fusion.fuse([a, b])
    assert len(fused) == 1 and fused[0].metadata["rule"] == "by_tag"


def test_fusion_metrics():
    fusion = SensorFusion()
    fusion.fuse([_screen("Chrome"), _process("chrome.exe")])
    assert fusion.metrics()["fused"] == 1


def test_app_name_normalized_across_sources():
    # "Chrome" (window) and "CHROME.EXE" (process) must resolve to the same app
    fused = SensorFusion().fuse([_screen("Chrome"), _process("CHROME.EXE")])
    assert len(fused) == 1 and fused[0].payload["name"].lower() == "chrome"
