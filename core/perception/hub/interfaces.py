"""
core/perception/hub/interfaces.py — FRIDAY V3 (M17)
Internal strategy contracts of the Perception Hub. The pipeline stages (fusion,
confidence, reasoning) are dependency-injected behind these Protocols so each is
individually mockable/replaceable (e.g. a learned fuser or an LLM reasoner via the
PluginService) without changing the Hub.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class Fuser(Protocol):
    def fuse(self, modality_observations: list, *, session_id: str = "") -> list: ...


@runtime_checkable
class ConfidenceCombiner(Protocol):
    def combine(self, confidences: list, *, agreement: bool = False,
                conflict: bool = False) -> float: ...


@runtime_checkable
class Reasoner(Protocol):
    def reason(self, unified, context: dict) -> list: ...     # -> list[conclusion dicts]
