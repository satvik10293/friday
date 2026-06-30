"""
core/spatial/queries.py — FRIDAY V3 (M16)
The spatial query engine — backend reasoning over the scene graph + spatial memory. It
answers the questions a spatial assistant must: where is my phone, where did I last
leave my wallet, what changed today, which room contains my laptop, what moved while I
was gone. Backend only (no GUI); returns structured dicts ready for the Brain/Executive
to verbalize.
"""

from __future__ import annotations

import time
from typing import Optional


class SpatialQueryEngine:
    def __init__(self, scene_graph, spatial_memory) -> None:
        self._scene = scene_graph
        self._memory = spatial_memory

    # ── "where is my phone?" ─────────────────────────────────────────────────────
    def where_is(self, label: str) -> dict:
        nodes = self._scene.find(label)
        if not nodes:
            last = self._memory.last_location(label=label)
            if last:
                return {"found": False, "known_last": True, "label": label,
                        "room": last["room"], "last_seen": last["ts"],
                        "answer": f"I last saw the {label} in the {last['room']}."}
            return {"found": False, "known_last": False, "label": label,
                    "answer": f"I haven't seen a {label}."}
        node = max(nodes, key=lambda n: n.last_seen)
        rels = [f"{r['relation'].replace('_', ' ')} the {r['target_label']}"
                for r in node.relationships if r["relation"] in ("on", "under", "inside",
                                                                 "beside", "near")]
        where = f"in the {node.room}"
        if rels:
            where += " (" + ", ".join(rels[:3]) + ")"
        return {"found": True, "label": node.label, "room": node.room,
                "persistent_id": node.persistent_id, "status": node.status,
                "position": node.position, "relationships": node.relationships,
                "confidence": round(node.confidence, 3), "last_seen": node.last_seen,
                "answer": f"The {node.label} is {where}."}

    # ── "where did I last leave my wallet?" ──────────────────────────────────────
    def last_seen(self, label: str) -> dict:
        last = self._memory.last_location(label=label)
        if not last:
            return {"found": False, "label": label, "answer": f"I have no record of a {label}."}
        return {"found": True, "label": label, "room": last["room"], "ts": last["ts"],
                "kind": last["kind"],
                "answer": f"You last left the {label} in the {last['room']}."}

    # ── "what changed today?" ────────────────────────────────────────────────────
    def what_changed(self, *, since: Optional[float] = None) -> dict:
        since = since if since is not None else _midnight()
        events = self._memory.moved_since(since)
        summary = [{"label": e["label"], "kind": e["kind"], "room": e["room"], "ts": e["ts"]}
                   for e in events]
        return {"since": since, "count": len(summary), "changes": summary,
                "answer": (f"{len(summary)} thing(s) changed." if summary
                           else "Nothing notable changed.")}

    # ── "which room contains my laptop?" ─────────────────────────────────────────
    def which_room(self, label: str) -> dict:
        nodes = self._scene.find(label)
        if not nodes:
            return {"found": False, "label": label, "answer": f"I don't know where the {label} is."}
        node = max(nodes, key=lambda n: n.last_seen)
        return {"found": True, "label": node.label, "room": node.room,
                "answer": f"The {node.label} is in the {node.room}."}

    # ── "what moved while I was gone?" ───────────────────────────────────────────
    def what_moved(self, *, since: float) -> dict:
        events = self._memory.moved_since(since)
        moved = [{"label": e["label"], "kind": e["kind"], "room": e["room"], "ts": e["ts"]}
                 for e in events if e["kind"] in ("moved", "lost", "returned", "removed")]
        return {"since": since, "count": len(moved), "moved": moved,
                "answer": (f"{len(moved)} object(s) moved while you were away." if moved
                           else "Nothing moved while you were away.")}

    # ── dispatch ─────────────────────────────────────────────────────────────────
    def query(self, intent: str, **params) -> dict:
        intent = (intent or "").strip().lower().replace(" ", "_")
        dispatch = {
            "where_is": lambda: self.where_is(params.get("label", "")),
            "last_seen": lambda: self.last_seen(params.get("label", "")),
            "what_changed": lambda: self.what_changed(since=params.get("since")),
            "which_room": lambda: self.which_room(params.get("label", "")),
            "what_moved": lambda: self.what_moved(since=params.get("since", _midnight())),
        }
        fn = dispatch.get(intent)
        if fn is None:
            return {"error": "unknown_intent", "intent": intent,
                    "supported": sorted(dispatch.keys())}
        return fn()


def _midnight() -> float:
    now = time.localtime()
    return time.mktime((now.tm_year, now.tm_mon, now.tm_mday, 0, 0, 0, 0, 0, -1))
