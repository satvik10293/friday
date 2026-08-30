"""
Athena's trading playbook: every indicator / trend / candle / chart pattern with
what it is, WHY it happens, and how to enter, take profit, and stop the loss.
"""

from __future__ import annotations

from trading_knowledge import (ALL_LESSONS, by_category, catalog, counts,
                               explain, explain_chart, teach)
from vision_model.dataset import synth_ohlcv   # reuse the synthetic OHLCV helper


def test_coverage_is_comprehensive():
    c = counts()
    assert c["indicator"] >= 14
    assert c["trend"] >= 6
    assert c["candlestick"] >= 15
    assert c["chart_pattern"] >= 10
    assert c["risk"] >= 6
    assert len(ALL_LESSONS) >= 55


def test_every_lesson_explains_what_and_why():
    for lesson in ALL_LESSONS:
        assert lesson.what.strip(), f"{lesson.name} missing 'what'"
        assert lesson.why.strip(), f"{lesson.name} missing 'why'"


def test_tradeable_lessons_say_how_to_profit_and_stop():
    # every candlestick / trend / chart pattern should carry entry+stop guidance
    for lesson in by_category("candlestick") + by_category("chart_pattern"):
        assert lesson.entry.strip(), f"{lesson.name} missing entry"
        assert lesson.stop.strip(), f"{lesson.name} missing stop"


def test_risk_section_covers_the_essentials():
    names = {l.name for l in by_category("risk")}
    for essential in ("stop-loss", "take-profit", "risk-reward ratio",
                      "position sizing", "cutting losses"):
        assert essential in names


def test_explain_by_name_and_alias():
    assert explain("RSI").category == "indicator"
    assert explain("SMA").name == "moving average"        # alias resolves
    assert explain("hammer").bias == 1
    assert explain("head and shoulders").bias == -1


def test_teach_includes_why_and_how():
    lesson = teach("hammer")
    assert "Why:" in lesson and "Entry:" in lesson and "Stop-loss:" in lesson


def test_catalog_groups_by_category():
    cats = set(catalog())
    assert {"indicator", "trend", "candlestick", "chart_pattern", "risk"} <= cats


def test_explain_chart_attaches_playbook_to_detected_signals():
    df = synth_ohlcv(bars=64, drift=0.9, vol=0.7, seed=11)   # clear uptrend
    read = explain_chart(df)
    assert read["count"] >= 1
    # at least one detected signal should carry the why + how-to-trade
    enriched = [s for s in read["signals"] if s.get("why")]
    assert enriched, "no signal got its playbook attached"
    s = enriched[0]
    assert "why" in s and ("stop_loss" in s or "take_profit" in s)
