"""
core/spatial/relationships.py — FRIDAY V3 (M16)
Spatial relationship inference. Given the current object nodes, derive the symbolic
relationships that make the scene graph *meaningful* — the phone is ON the desk, BESIDE
the keyboard, INSIDE the office. Relationships are recomputed each scene update and
diffed by the engine so only changes are published.

Geometry is normalized (0..1) image coordinates with optional bboxes; image-y grows
downward, so a smaller y is physically "above". Depth (front/behind) is inferred from
relative apparent size when bboxes are present. This is a deterministic, model-free
inferencer; a learned one can be injected via the PluginService (it only needs to satisfy
the `RelationshipInferencer` protocol).
"""

from __future__ import annotations

from typing import Optional

from .config import RelationshipConfig

# the full M16 relationship vocabulary
ON, UNDER, INSIDE, NEAR, BESIDE = "on", "under", "inside", "near", "beside"
LEFT_OF, RIGHT_OF, BEHIND, IN_FRONT_OF = "left_of", "right_of", "behind", "in_front_of"
TOUCHING, ATTACHED_TO, CONTAINED_BY = "touching", "attached_to", "contained_by"


class RelationshipEngine:
    def __init__(self, config: Optional[RelationshipConfig] = None) -> None:
        self.config = config or RelationshipConfig()

    def infer(self, nodes: list) -> list:
        """Return a flat list of relationship dicts for the given scene nodes.
        Each: {source, source_label, target, target_label, relation, weight}."""
        if not self.config.enabled:
            return []
        objs = [n for n in nodes if getattr(n, "object_class", "") != "room"]
        rels: list = []
        for i in range(len(objs)):
            for j in range(len(objs)):
                if i == j:
                    continue
                a, b = objs[i], objs[j]
                rels.extend(self._relate(a, b))
        return rels

    def _relate(self, a, b) -> list:
        ca, cb = _center(a), _center(b)
        dx, dy = cb[0] - ca[0], cb[1] - ca[1]
        dist = (dx * dx + dy * dy) ** 0.5
        ba, bb = _bbox(a), _bbox(b)
        out: list = []

        # containment (needs bboxes)
        if ba and bb:
            if _contains(bb, ba):
                out.append(_rel(a, b, INSIDE)); out.append(_rel(a, b, CONTAINED_BY))
                return out                              # containment dominates
            iou = _iou(ba, bb)
            if iou >= self.config.touch_iou:
                out.append(_rel(a, b, TOUCHING))
                if _small_on_large(ba, bb):
                    out.append(_rel(a, b, ATTACHED_TO))

        # proximity
        if dist <= self.config.near_fraction:
            out.append(_rel(a, b, NEAR, weight=round(1.0 - dist, 3)))
            if abs(dy) <= self.config.near_fraction * 0.6:
                out.append(_rel(a, b, BESIDE))

        # vertical: on / under (horizontal overlap + clear vertical separation)
        if ba and bb and _horizontal_overlap(ba, bb) >= self.config.on_overlap:
            if ca[1] < cb[1] - 0.02:                    # a physically above b
                out.append(_rel(a, b, ON))
            elif ca[1] > cb[1] + 0.02:
                out.append(_rel(a, b, UNDER))

        # dominant horizontal direction (a relative to b): if b is to the right
        # (dx > 0), then a is to the LEFT of b.
        if abs(dx) >= abs(dy) and dist > 1e-6:
            out.append(_rel(a, b, LEFT_OF if dx > 0 else RIGHT_OF, weight=round(abs(dx), 3)))

        # depth (behind / in_front_of) requires a real depth signal — inferring it from
        # apparent size across different object classes is unreliable, so we only emit it
        # when explicit z coordinates are present (e.g. a depth camera or future plugin).
        za, zb = _z(a), _z(b)
        if za is not None and zb is not None and abs(za - zb) > 1e-6:
            out.append(_rel(a, b, IN_FRONT_OF if za < zb else BEHIND))
        return out


# ── helpers ─────────────────────────────────────────────────────────────────────────
def _center(n) -> tuple:
    p = getattr(n, "position", {}) or {}
    return (float(p.get("x", 0.0)), float(p.get("y", 0.0)))


def _z(n):
    p = getattr(n, "position", {}) or {}
    return float(p["z"]) if "z" in p else None


def _bbox(n) -> Optional[dict]:
    b = (getattr(n, "attributes", {}) or {}).get("bbox")
    if b and all(k in b for k in ("x", "y", "w", "h")):
        return b
    return None


def _rel(a, b, relation: str, *, weight: float = 1.0) -> dict:
    return {"source": a.node_id, "source_label": a.label,
            "target": b.node_id, "target_label": b.label,
            "relation": relation, "weight": weight}


def _iou(a: dict, b: dict) -> float:
    ax2, ay2 = a["x"] + a["w"], a["y"] + a["h"]
    bx2, by2 = b["x"] + b["w"], b["y"] + b["h"]
    ix1, iy1 = max(a["x"], b["x"]), max(a["y"], b["y"])
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    iw, ih = max(0.0, ix2 - ix1), max(0.0, iy2 - iy1)
    inter = iw * ih
    union = a["w"] * a["h"] + b["w"] * b["h"] - inter
    return inter / union if union > 0 else 0.0


def _contains(outer: dict, inner: dict) -> bool:
    return (outer["x"] <= inner["x"] and outer["y"] <= inner["y"] and
            outer["x"] + outer["w"] >= inner["x"] + inner["w"] and
            outer["y"] + outer["h"] >= inner["y"] + inner["h"] and
            outer["w"] * outer["h"] > inner["w"] * inner["h"] * 1.1)


def _horizontal_overlap(a: dict, b: dict) -> float:
    left, right = max(a["x"], b["x"]), min(a["x"] + a["w"], b["x"] + b["w"])
    overlap = max(0.0, right - left)
    return overlap / min(a["w"], b["w"]) if min(a["w"], b["w"]) > 0 else 0.0


def _small_on_large(a: dict, b: dict) -> bool:
    return a["w"] * a["h"] <= b["w"] * b["h"] * 0.5
