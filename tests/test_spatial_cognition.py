"""M16 — Rooms, user localization, spatial memory, and the query engine (units)."""

import time

import pytest

from core.spatial.config import LocalizationConfig, RoomConfig
from core.spatial.interfaces import SpatialObservation
from core.spatial.localization import UserLocalizer, UserState
from core.spatial.memory import SpatialMemory
from core.spatial.queries import SpatialQueryEngine
from core.spatial.rooms import RoomModel
from core.spatial.scene_graph import SceneGraph


def _o(cls, x, y, room="office"):
    return SpatialObservation(object_class=cls, label=cls, confidence=0.9,
                              position={"x": x, "y": y}, room=room)


# ── rooms (never hardcoded; extensible) ─────────────────────────────────────────────
def test_room_resolution_precedence():
    rm = RoomModel(RoomConfig(default_room="unknown", camera_rooms={"cam1": "kitchen"}))
    assert rm.room_for(camera_id="cam1") == "kitchen"          # camera map
    assert rm.room_for(camera_id="camX") == "unknown"          # default
    assert rm.room_for(observation=_o("phone", 0.5, 0.5, room="bedroom")) == "bedroom"  # explicit


def test_room_registration_and_classifier():
    rm = RoomModel(RoomConfig())
    rm.set_camera_room("cam2", "garage")
    assert "garage" in rm.known_rooms()

    class Classifier:
        def room_for(self, *, camera_id="", observation=None):
            return "living room"
    rm.set_classifier(Classifier())
    assert rm.room_for(camera_id="cam9") == "living room"


# ── localization ────────────────────────────────────────────────────────────────────
def test_localizer_entering_present_leaving_idle():
    loc = UserLocalizer(LocalizationConfig(idle_after_s=10, away_after_s=100))
    r1 = loc.estimate(observations=[_o("person", 0.5, 0.7)], audio_events=[], now=0.0)
    assert r1["state"] == UserState.ENTERING_ROOM and r1["present"]
    r2 = loc.estimate(observations=[_o("person", 0.5, 0.7)], audio_events=[], now=1.0)
    assert r2["present"] and r2["state"] in (UserState.PRESENT, UserState.AT_DESK)
    r3 = loc.estimate(observations=[], audio_events=[], now=2.0)
    assert r3["state"] == UserState.LEAVING_ROOM and not r3["present"]
    r4 = loc.estimate(observations=[], audio_events=[], now=20.0)
    assert r4["state"] == UserState.IDLE


def test_localizer_working_at_desk_from_audio():
    loc = UserLocalizer(LocalizationConfig())
    obs = [_o("person", 0.5, 0.5), _o("keyboard", 0.5, 0.52)]
    loc.estimate(observations=obs, audio_events=[], now=0.0)        # prime presence (entering)
    r = loc.estimate(observations=obs, audio_events=[{"sound": "keyboard_typing"}], now=1.0)
    assert r["state"] == UserState.WORKING


def test_localizer_audio_only_presence():
    loc = UserLocalizer(LocalizationConfig())
    r = loc.estimate(observations=[], audio_events=[{"sound": "keyboard_typing"}], now=0.0)
    assert r["present"] and r["state"] == UserState.WORKING


def test_localizer_walking_on_motion():
    loc = UserLocalizer(LocalizationConfig())
    loc.estimate(observations=[_o("person", 0.2, 0.5)], audio_events=[], now=0.0)
    loc.estimate(observations=[_o("person", 0.2, 0.5)], audio_events=[], now=1.0)
    r = loc.estimate(observations=[_o("person", 0.6, 0.5)], audio_events=[], now=2.0)
    assert r["state"] == UserState.WALKING and r["moved"]


# ── spatial memory ──────────────────────────────────────────────────────────────────
def test_spatial_memory_dedup_and_movement():
    m = SpatialMemory(persistent=False, dedup_window_s=10.0)
    assert m.record_event(kind="detected", persistent_id="p1", label="phone", room="office",
                          confidence=0.9, ts=0.0) is True
    assert m.record_event(kind="detected", persistent_id="p1", label="phone", room="office",
                          confidence=0.9, ts=1.0) is False        # redundant within window
    m.record_movement(persistent_id="p1", label="phone", room="office", center=(0.5, 0.5))
    assert m.movement_history("p1")
    m.close()


def test_spatial_memory_last_location_and_moved():
    m = SpatialMemory(persistent=False, dedup_window_s=0.0)
    m.record_event(kind="detected", persistent_id="p1", label="phone", room="office",
                   confidence=0.9, ts=10.0)
    m.record_event(kind="moved", persistent_id="p1", label="phone", room="kitchen",
                   confidence=0.9, ts=20.0)
    last = m.last_location(label="phone")
    assert last["room"] == "kitchen"
    assert len(m.moved_since(0.0)) == 1
    m.close()


def test_spatial_memory_chronicle_forward():
    forwarded = []

    class MemSvc:
        def remember(self, content, *, kind="event", metadata=None):
            forwarded.append(content)

    m = SpatialMemory(persistent=False, memory_service=MemSvc(), significance_threshold=0.5)
    m.record_event(kind="moved", persistent_id="p1", label="wallet", room="office",
                   confidence=0.9, ts=0.0, significant=True)
    assert forwarded and "wallet" in forwarded[0]
    m.close()


# ── query engine ────────────────────────────────────────────────────────────────────
def test_queries_where_is_and_which_room():
    sg = SceneGraph()
    sg.upsert_object(persistent_id="p1", object_class="phone", label="phone",
                     position={"x": 0.5, "y": 0.5}, room="office", confidence=0.9)
    mem = SpatialMemory(persistent=False)
    q = SpatialQueryEngine(sg, mem)
    assert q.where_is("phone")["found"] and q.where_is("phone")["room"] == "office"
    assert q.which_room("phone")["room"] == "office"
    assert q.where_is("wallet")["found"] is False
    mem.close()


def test_queries_last_seen_and_what_moved():
    sg = SceneGraph()
    mem = SpatialMemory(persistent=False, dedup_window_s=0.0)
    mem.record_event(kind="moved", persistent_id="p1", label="wallet", room="bedroom",
                     confidence=0.9, ts=time.time())
    q = SpatialQueryEngine(sg, mem)
    assert q.last_seen("wallet")["room"] == "bedroom"
    assert q.what_moved(since=0.0)["count"] == 1
    assert q.query("what_changed", since=0.0)["count"] >= 1
    assert q.query("bogus_intent")["error"] == "unknown_intent"
    mem.close()
