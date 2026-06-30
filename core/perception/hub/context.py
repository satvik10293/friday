"""
core/perception/hub/context.py — FRIDAY V3 (M17)
The context engine — FRIDAY's continuously-updated picture of "right now": current room,
task/activity, conversation, user activity, present objects and devices, and the overall
situation. Each unified observation updates the context; when something material changes,
the engine reports it so the Hub can publish ContextChanged / SituationChanged. The prior
context is retained so incomplete observations can be enriched rather than rejected.
"""

from __future__ import annotations

import threading
import time


class ContextEngine:
    def __init__(self) -> None:
        self._ctx: dict = {"room": "", "activity": "", "situation": "", "objects": [],
                          "people": [], "devices": [], "conversation": "", "updated_at": 0.0}
        self._prev: dict = dict(self._ctx)
        self._lock = threading.Lock()
        self._changes = 0

    def snapshot(self) -> dict:
        with self._lock:
            return dict(self._ctx)

    def previous(self) -> dict:
        with self._lock:
            return dict(self._prev)

    def update(self, unified) -> dict:
        """Fold a unified observation into the active context. Returns
        {changed, situation_changed, context}."""
        with self._lock:
            before = dict(self._ctx)
            ctx = dict(self._ctx)
            if unified.location:
                ctx["room"] = unified.location
            state = unified.spatial_context.get("user_state")
            if state:
                ctx["activity"] = state
            if unified.related_objects:
                ctx["objects"] = sorted(set(unified.related_objects))[:20]
            if unified.related_people:
                ctx["people"] = sorted(set(unified.related_people))[:10]
            situation = unified.conclusions[0]["situation"] if unified.conclusions else ctx["situation"]
            ctx["situation"] = situation
            ctx["updated_at"] = time.time()

            changed = any(ctx.get(k) != before.get(k)
                          for k in ("room", "activity", "objects", "people"))
            situation_changed = ctx["situation"] != before.get("situation")
            if changed or situation_changed:
                self._prev = before
                self._ctx = ctx
                self._changes += 1
            return {"changed": changed, "situation_changed": situation_changed,
                    "context": dict(self._ctx)}

    def set_conversation(self, text: str) -> None:
        with self._lock:
            self._ctx["conversation"] = text
            self._ctx["updated_at"] = time.time()

    def metrics(self) -> dict:
        return {"changes": self._changes}

    def health(self) -> dict:
        return {"status": "ok", "room": self._ctx["room"], "situation": self._ctx["situation"]}
