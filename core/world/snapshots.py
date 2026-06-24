"""
core/world/snapshots.py — FRIDAY 4.0 (M5)
Point-in-time captures of the world model + a structural diff. Snapshots let the
Executive Brain ask "what changed since I last looked?" — the seam future vision
modules will use to detect novelty.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field


@dataclass
class WorldSnapshot:
    snapshot_id: str
    ts: float
    label: str = ""
    entities: dict = field(default_factory=dict)        # entity_id -> entity dict
    relationships: list = field(default_factory=list)   # list of relationship dicts

    def to_dict(self) -> dict:
        return dict(self.__dict__)

    @staticmethod
    def from_dict(d: dict) -> "WorldSnapshot":
        return WorldSnapshot(
            snapshot_id=d["snapshot_id"], ts=d["ts"], label=d.get("label", ""),
            entities=dict(d.get("entities") or {}),
            relationships=list(d.get("relationships") or []),
        )


def new_snapshot(entities: dict, relationships: list, label: str = "") -> WorldSnapshot:
    return WorldSnapshot(
        snapshot_id=uuid.uuid4().hex[:12], ts=time.time(), label=label,
        entities={k: dict(v) for k, v in entities.items()},
        relationships=[dict(r) for r in relationships],
    )


def diff_snapshots(before: WorldSnapshot, after: WorldSnapshot) -> dict:
    """Structural diff of two snapshots.

    Returns {added, removed, changed} where `changed` maps entity_id -> the set of
    state/attribute keys whose values differ.
    """
    b, a = before.entities, after.entities
    added = [eid for eid in a if eid not in b]
    removed = [eid for eid in b if eid not in a]
    changed: dict[str, list[str]] = {}
    for eid in a:
        if eid not in b:
            continue
        keys = _changed_keys(b[eid], a[eid])
        if keys:
            changed[eid] = keys
    return {"added": added, "removed": removed, "changed": changed}


def _changed_keys(before: dict, after: dict) -> list[str]:
    diffs: list[str] = []
    for field_name in ("state", "attributes"):
        bf, af = before.get(field_name) or {}, after.get(field_name) or {}
        for key in set(bf) | set(af):
            if bf.get(key) != af.get(key):
                diffs.append(f"{field_name}.{key}")
    return sorted(diffs)
