"""M16 — Spatial relationship inference: on/under, left/right (correct direction),
near/beside, inside/contained, touching, depth (behind/in_front via z)."""

from dataclasses import dataclass

from core.spatial.config import RelationshipConfig
from core.spatial.relationships import RelationshipEngine


@dataclass
class _Node:
    node_id: str
    label: str
    position: dict
    attributes: dict
    object_class: str = "object"


def _n(nid, x, y, w=0.1, h=0.1, z=None):
    pos = {"x": x + w / 2, "y": y + h / 2}
    if z is not None:
        pos["z"] = z
    return _Node(nid, nid, pos, {"bbox": {"x": x, "y": y, "w": w, "h": h}})


def _rels(nodes):
    eng = RelationshipEngine(RelationshipConfig())
    out = {}
    for r in eng.infer(nodes):
        out.setdefault((r["source_label"], r["target_label"]), set()).add(r["relation"])
    return out


def test_on_and_under():
    desk = _n("desk", 0.2, 0.6, 0.5, 0.2)
    laptop = _n("laptop", 0.3, 0.5, 0.15, 0.1)        # above desk + horizontal overlap
    r = _rels([desk, laptop])
    assert "on" in r[("laptop", "desk")]
    assert "under" in r[("desk", "laptop")]


def test_left_right_direction_is_correct():
    a = _n("a", 0.1, 0.5)                              # left object
    b = _n("b", 0.7, 0.5)                              # right object
    r = _rels([a, b])
    assert "left_of" in r[("a", "b")]                 # a is left of b
    assert "right_of" in r[("b", "a")]                # b is right of a


def test_near_and_beside():
    a = _n("a", 0.40, 0.5, 0.05, 0.05)
    b = _n("b", 0.46, 0.5, 0.05, 0.05)                # very close, same height
    r = _rels([a, b])
    assert "near" in r[("a", "b")] and "beside" in r[("a", "b")]


def test_inside_containment():
    box = _n("box", 0.2, 0.2, 0.6, 0.6)
    coin = _n("coin", 0.4, 0.4, 0.05, 0.05)           # fully inside box
    r = _rels([box, coin])
    assert "inside" in r[("coin", "box")] and "contained_by" in r[("coin", "box")]


def test_touching():
    a = _n("a", 0.30, 0.5, 0.12, 0.12)
    b = _n("b", 0.38, 0.5, 0.12, 0.12)                # overlapping boxes
    r = _rels([a, b])
    assert "touching" in r[("a", "b")]


def test_depth_requires_z():
    near = _n("near", 0.4, 0.5, 0.1, 0.1, z=0.2)
    far = _n("far", 0.5, 0.5, 0.1, 0.1, z=0.8)
    r = _rels([near, far])
    assert "in_front_of" in r[("near", "far")]
    assert "behind" in r[("far", "near")]
    # without z, no behind/in_front noise
    r2 = _rels([_n("a", 0.4, 0.5), _n("b", 0.6, 0.5)])
    assert all("behind" not in v and "in_front_of" not in v for v in r2.values())


def test_disabled_returns_nothing():
    eng = RelationshipEngine(RelationshipConfig(enabled=False))
    assert eng.infer([_n("a", 0.1, 0.1), _n("b", 0.2, 0.2)]) == []
