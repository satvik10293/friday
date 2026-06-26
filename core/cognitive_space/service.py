"""
core/cognitive_space/service.py — FRIDAY 4.0 (M11)
The cognitive-space facade: build the universe at any zoom level, search globally,
expose the visual language. Composes the injected subsystems; Mission Control wraps
it for the interactive UI.
"""

from __future__ import annotations

from typing import Optional

from .models import VISUAL_LANGUAGE, ZoomLevel
from .search import GlobalSearch
from .space import CognitiveSpaceBuilder
from .zoom import LEVEL_BUDGETS


class CognitiveSpace:
    def __init__(self, *, knowledge_service=None, goal_service=None, society=None,
                 simulation_service=None, user_model=None) -> None:
        services = dict(knowledge_service=knowledge_service, goal_service=goal_service,
                        society=society, simulation_service=simulation_service,
                        user_model=user_model)
        self._builder = CognitiveSpaceBuilder(**services)
        self._search = GlobalSearch(**services)

    def build(self, level: int = 1, focus: Optional[str] = None) -> dict:
        return self._builder.build(level, focus)

    def universe(self) -> dict:
        return self.build(ZoomLevel.UNIVERSE.value)

    def search(self, query: str, *, limit: int = 30) -> dict:
        return self._search.search(query, limit=limit)

    def zoom_levels(self) -> list[dict]:
        return [{"level": z.value, "name": z.name, "budget": LEVEL_BUDGETS[z.value]}
                for z in ZoomLevel]

    def visual_language(self) -> dict:
        return VISUAL_LANGUAGE

    def health(self) -> dict:
        uni = self.build(ZoomLevel.UNIVERSE.value)
        return {"status": "ok", "levels": len(list(ZoomLevel)),
                "universe_nodes": uni["counts"]["nodes"]}


_space: Optional[CognitiveSpace] = None


def get_cognitive_space(**kw) -> CognitiveSpace:
    global _space
    if _space is None:
        _space = CognitiveSpace(**kw)
    return _space
