"""
The learning loop must actually close: the setup tag she FILES a closed paper
trade under must equal the tag she READS back when sizing the next call. A real
bug filed outcomes under "paper" but read history under "trend_continuation", so
everything she "learned" was invisible to her decisions. These pin the contract.
"""

from __future__ import annotations

from data_db import Database
from recommend_recommendation_engine import Recommendation


def test_recommendation_carries_a_setup_tag():
    rec = Recommendation("AAPL", "BUY", 60.0)
    assert rec.setup_tag == "trend_continuation"      # the tag evaluate reads under


def test_learning_round_trips_under_the_recommendation_tag(tmp_path):
    db = Database(path=tmp_path / "athena.db")
    tag = Recommendation("AAPL", "BUY", 60.0).setup_tag   # what run_live now files under
    for _ in range(3):
        db.update_strategy_score(tag, won=True)
    db.update_strategy_score(tag, won=False)
    row = db.get_strategy_score(tag)                      # what evaluate reads back
    assert row is not None
    assert row["wins"] == 3 and row["losses"] == 1


def test_a_mismatched_tag_sees_nothing(tmp_path):
    # documents the old bug: writing under one tag, reading another → no learning
    db = Database(path=tmp_path / "athena.db")
    db.update_strategy_score("paper", won=True)
    assert db.get_strategy_score("trend_continuation") is None
