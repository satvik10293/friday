"""
The expert brain wired into the live recommendation engine: every recommendation
now carries the full catalog read + playbook (why + entry/stop), additively,
without changing the BUY/SELL/WAIT decision.
"""

from __future__ import annotations

from recommend_recommendation_engine import Recommendation, RecommendationEngine
from vision_model.dataset import synth_ohlcv


def test_enrich_attaches_expert_read_and_playbook():
    engine = RecommendationEngine()                       # no market/db needed for enrich
    rec = Recommendation("TEST", "WAIT", 0.0, ["base reason"])
    df = synth_ohlcv(bars=80, drift=0.8, vol=0.7, seed=3)  # clear uptrend
    engine._enrich(rec, df)

    text = "\n".join(rec.reasons)
    assert "Expert read" in text                          # the catalog summary line
    assert any("•" in r for r in rec.reasons)             # at least one named signal
    assert "base reason" in rec.reasons                   # additive — original kept


def test_enrich_never_changes_the_action_or_raises():
    engine = RecommendationEngine()
    rec = Recommendation("TEST", "BUY", 72.0, [])
    # even with a degenerate frame it must not raise or alter the decision
    df = synth_ohlcv(bars=45, drift=0.0, vol=0.2, seed=9)
    engine._enrich(rec, df)
    assert rec.action == "BUY" and rec.confidence == 72.0


def test_enrich_includes_the_why_behind_signals():
    engine = RecommendationEngine()
    rec = Recommendation("TEST", "WAIT", 0.0, [])
    df = synth_ohlcv(bars=80, drift=-0.8, vol=0.7, seed=5)  # clear downtrend
    engine._enrich(rec, df)
    # a signal line should carry an explanation (the 'why'), not just a name
    assert any(": " in r and len(r) > 30 for r in rec.reasons if "•" in r)
