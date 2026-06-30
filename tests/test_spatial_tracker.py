"""M16 — Object tracking: persistent identity (new/tracked/moved/lost/returned/removed),
no duplicate identities, stable-id fast path, confidence gating, long sessions."""

import pytest

from core.spatial.config import TrackerConfig
from core.spatial.interfaces import SpatialObservation
from core.spatial.tracker import ObjectTracker, TrackState


def _obs(cls, x, y, conf=0.9, stable_id=None, room="office"):
    return SpatialObservation(object_class=cls, label=cls, confidence=conf,
                              position={"x": x, "y": y}, room=room, stable_id=stable_id)


def test_new_then_tracked_keeps_identity():
    tr = ObjectTracker(TrackerConfig(min_confidence=0.5))
    u1, _ = tr.update([_obs("phone", 0.5, 0.5)], now=100.0)
    assert u1[0].state == TrackState.NEW
    pid = u1[0].persistent_id
    u2, _ = tr.update([_obs("phone", 0.51, 0.5)], now=100.5)   # tiny move → tracked
    assert u2[0].state == TrackState.TRACKED and u2[0].persistent_id == pid


def test_moved_detected_on_significant_shift():
    tr = ObjectTracker(TrackerConfig(min_confidence=0.5))
    tr.update([_obs("phone", 0.5, 0.5)], now=100.0)
    u2, _ = tr.update([_obs("phone", 0.58, 0.5)], now=100.5)   # > move eps, < match dist
    assert u2[0].state == TrackState.MOVED


def test_lost_then_returned():
    tr = ObjectTracker(TrackerConfig(min_confidence=0.5, lost_after_s=2.0, forget_after_s=100.0))
    u1, _ = tr.update([_obs("phone", 0.5, 0.5)], now=0.0)
    pid = u1[0].persistent_id
    _, life = tr.update([], now=3.0)                            # unseen 3s → lost
    assert any(e["state"] == TrackState.LOST and e["persistent_id"] == pid for e in life)
    u3, _ = tr.update([_obs("phone", 0.5, 0.5)], now=4.0)       # reappears
    assert u3[0].state == TrackState.RETURNED and u3[0].persistent_id == pid


def test_removed_after_forget_timeout():
    tr = ObjectTracker(TrackerConfig(min_confidence=0.5, lost_after_s=2.0, forget_after_s=10.0))
    tr.update([_obs("cup", 0.5, 0.5)], now=0.0)
    _, life = tr.update([], now=20.0)
    assert any(e["state"] == TrackState.REMOVED for e in life)
    assert tr.metrics()["tracks"] == 0


def test_no_duplicate_identities():
    tr = ObjectTracker(TrackerConfig(min_confidence=0.5))
    # two phones in one frame → two distinct ids; next frame keeps both (no extra ids)
    u1, _ = tr.update([_obs("phone", 0.2, 0.5), _obs("phone", 0.8, 0.5)], now=0.0)
    ids = {u.persistent_id for u in u1}
    assert len(ids) == 2
    u2, _ = tr.update([_obs("phone", 0.21, 0.5), _obs("phone", 0.79, 0.5)], now=0.5)
    assert {u.persistent_id for u in u2} == ids
    assert tr.metrics()["tracks"] == 2


def test_stable_id_fast_path_matches_across_distance():
    tr = ObjectTracker(TrackerConfig(min_confidence=0.5, match_distance=0.1))
    u1, _ = tr.update([_obs("phone", 0.1, 0.1, stable_id="ENT_1")], now=0.0)
    pid = u1[0].persistent_id
    assert pid == "ENT_1"
    # big jump but same stable id → still the same identity
    u2, _ = tr.update([_obs("phone", 0.9, 0.9, stable_id="ENT_1")], now=0.5)
    assert u2[0].persistent_id == "ENT_1"


def test_low_confidence_ignored():
    tr = ObjectTracker(TrackerConfig(min_confidence=0.7))
    u, _ = tr.update([_obs("phone", 0.5, 0.5, conf=0.3)], now=0.0)
    assert u == [] and tr.metrics()["tracks"] == 0
