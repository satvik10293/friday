"""
core/perception/hub/fusion.py — FRIDAY V3 (M17)
Multimodal fusion. Takes one cycle's per-sensor `ModalityObservation`s and merges the
co-occurring ones into `UnifiedObservation`s — one coherent cognitive event per location.
Vision contributes objects/people, audio contributes the sound context, spatial
contributes the room + user state; the confidence engine fuses their certainties. The
result is a single understanding instead of three disconnected facts.

Extensible: the grouping key and the per-modality extractors are simple and overridable;
a learned fuser can replace this (it only needs to satisfy the `Fuser` protocol).
"""

from __future__ import annotations

from typing import Optional

from .config import FusionConfig
from .confidence import ConfidenceEngine
from .observations import ModalityObservation, UnifiedObservation

# base importance by event category (reasoning may raise it)
_CATEGORY_IMPORTANCE = {"emergency": 1.0, "alert": 0.8, "user_state": 0.5,
                        "object": 0.4, "sound": 0.45, "scene": 0.3}


class MultimodalFusion:
    def __init__(self, config: Optional[FusionConfig] = None,
                 confidence_engine: Optional[ConfidenceEngine] = None) -> None:
        self.config = config or FusionConfig()
        self._confidence = confidence_engine or ConfidenceEngine()

    def fuse(self, modality_observations: list, *, session_id: str = "") -> list:
        """Group observations by location and fuse each group into a UnifiedObservation."""
        obs = [o if isinstance(o, ModalityObservation) else ModalityObservation.from_dict(o)
               for o in modality_observations]
        if not obs:
            return []
        groups: dict[str, list] = {}
        for o in obs:
            key = o.location if self.config.by_location else "*"
            groups.setdefault(key or "unknown", []).append(o)
        return [self._fuse_group(loc, group, session_id) for loc, group in groups.items()]

    def _fuse_group(self, location: str, group: list, session_id: str) -> UnifiedObservation:
        group = group[: self.config.max_sources_per_event]
        sources = sorted({o.source for o in group})
        objects, people, sounds = [], [], []
        spatial_ctx, audio_ctx = {}, {}
        category = "scene"

        for o in group:
            for x in o.objects:
                if x not in objects:
                    objects.append(x)
            if o.category == "object" and o.label and o.label not in objects:
                objects.append(o.label)
            for p in o.people:
                if p not in people:
                    people.append(p)
            if o.source == "audio" or o.category == "sound":
                if o.label and o.label not in sounds:
                    sounds.append(o.label)
                audio_ctx.setdefault("categories", [])
                cat = o.data.get("category")
                if cat and cat not in audio_ctx["categories"]:
                    audio_ctx["categories"].append(cat)
            if o.source == "spatial":
                if o.data.get("user_state"):
                    spatial_ctx["user_state"] = o.data["user_state"]
                if o.data.get("relationships"):
                    spatial_ctx["relationships"] = o.data["relationships"]
            if o.category in ("emergency", "alert"):
                category = o.category

        if sounds:
            audio_ctx["sounds"] = sounds
        spatial_ctx.setdefault("room", location)

        conf = self._confidence.unify(group)
        importance = _CATEGORY_IMPORTANCE.get(category, 0.3)
        ts = max(o.timestamp for o in group)
        return UnifiedObservation(
            timestamp=ts, session_id=session_id, source_modules=sources,
            confidence=conf["confidence"], location=location, related_objects=objects,
            related_people=people, audio_context=audio_ctx, spatial_context=spatial_ctx,
            importance=importance, event_category=category,
            sources=[o.to_dict() for o in group])
