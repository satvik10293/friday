"""
Compatibility shim — the real engine lives in recommend_recommendation_engine.py.

This file previously held a stale copy of the voice-alert module, which was
misleading. Import from here and you get the real thing:

    from recommendation_engine import RecommendationEngine, Recommendation, TradePlan
"""

from recommend_recommendation_engine import (  # noqa: F401
    Recommendation,
    RecommendationEngine,
    TradePlan,
)
