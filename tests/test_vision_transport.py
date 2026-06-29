"""M14 — Vision Transport Layer: Frame, queue, decoder, registry, adapters, manager,
health, metrics, events, recovery. The transport moves frames and performs zero
cognition."""

import time

import numpy as np
import pytest

from core.vision.transport.frame import Frame, PixelFormat, frame_from_array
from core.vision.transport.frame_queue import FrameQueue, OverflowPolicy
from core.vision.transport.decoder import FrameDecoder
from core.vision.transport.registry import CameraRegistry
from core.vision.transport.health import CameraHealth
from core.vision.transport.camera import CameraStatus
from core.vision.transport.adapters.array_adapter import ArrayAdapter, synthetic_frame
from core.vision.transport.service import VisionTransport


# ── Frame ───────────────────────────────────────────────────────────────────────────
def test_frame_from_array_fills_provenance():
    img = synthetic_frame(64, 48)
    f = frame_from_array("CAMERA_0001", img, frame_number=3,
                         capture_time=time.time() - 0.05)
    assert f.width == 64 and f.height == 48 and f.resolution == (64, 48)
    assert f.frame_number == 3 and f.camera_id == "CAMERA_0001"
    assert f.checksum and len(f.checksum) == 16
    assert f.latency_ms >= 0.0
    assert f.frame_id.startswith("FRM_")


def test_frame_to_dict_never_includes_pixels():
    f = frame_from_array("CAMERA_0001", synthetic_frame())
    d = f.to_dict()
    assert "data" not in d and d["shape"] == [48, 64, 3]
    assert d["nbytes"] > 0


# ── FrameQueue ──────────────────────────────────────────────────────────────────────
def test_queue_drop_oldest_keeps_freshest():
    q = FrameQueue(maxsize=2, policy=OverflowPolicy.DROP_OLDEST)
    for i in range(5):
        q.put(frame_from_array("c", synthetic_frame(), frame_number=i))
    assert q.depth == 2 and q.dropped == 3
    newest = q.peek()
    assert newest.frame_number == 4


def test_queue_drop_newest_keeps_backlog():
    q = FrameQueue(maxsize=2, policy=OverflowPolicy.DROP_NEWEST)
    stored = [q.put(frame_from_array("c", synthetic_frame(), frame_number=i)) for i in range(4)]
    assert stored[:2] == [True, True] and stored[2:] == [False, False]
    assert q.get().frame_number == 0


# ── Decoder ─────────────────────────────────────────────────────────────────────────
def test_decoder_roundtrip():
    dec = FrameDecoder()
    if dec.backend == "none":
        pytest.skip("no decode backend installed")
    img = synthetic_frame(32, 24, value=200)
    jpeg = dec.encode_jpeg(img)
    assert jpeg
    out = dec.decode(jpeg)
    assert out is not None and out.shape[0] == 24 and out.shape[1] == 32


def test_decoder_corrupt_returns_none_not_raise():
    dec = FrameDecoder()
    assert dec.decode(b"not-an-image") is None
    assert dec.decode("") is None


# ── Registry (permanent ids) ────────────────────────────────────────────────────────
def test_registry_stable_ids_and_persistence(tmp_path):
    path = tmp_path / "vision.db"
    reg = CameraRegistry(path, persistent=True)
    a = reg.allocate("token-A", kind="browser")
    b = reg.allocate("token-B", kind="browser")
    assert a == "CAMERA_0001" and b == "CAMERA_0002"
    assert reg.allocate("token-A") == a            # same key → same id
    reg.close()
    # survives restart
    reg2 = CameraRegistry(path, persistent=True)
    assert reg2.allocate("token-A") == "CAMERA_0001"
    assert reg2.allocate("token-C") == "CAMERA_0003"
    reg2.close()


# ── Health ──────────────────────────────────────────────────────────────────────────
def test_health_status_transitions():
    h = CameraHealth("CAMERA_0001", target_fps=10, degrade_after_s=2.0, disconnect_after_s=6.0)
    now = time.time()
    h.on_frame(latency_ms=20, nbytes=1000, ts=now)
    assert h.status(now) == CameraStatus.STREAMING.value
    assert h.status(now + 3) == CameraStatus.DEGRADED.value
    assert h.status(now + 7) == CameraStatus.DISCONNECTED.value
    assert 0 <= h.score(now) <= 100


# ── Manager / Transport ─────────────────────────────────────────────────────────────
def test_transport_array_camera_pump_consume():
    vt = VisionTransport()
    frames = [synthetic_frame(value=v) for v in (10, 120, 240)]
    cid = vt.add_array_camera("arr", frames)
    assert cid == "CAMERA_0001"
    n = vt.pump(cid)
    assert n == 3
    f = vt.consume(cid)
    assert isinstance(f, Frame) and f.data is not None
    vt.close()


def test_transport_reconnect_reuses_id_and_counts():
    vt = VisionTransport()
    cid = vt.connect_browser("tok-1", label="phone")
    again = vt.connect_browser("tok-1", label="phone")
    assert cid == again
    info = vt.manager.get(cid)
    assert info.reconnects == 1                     # browser refresh → reconnect, same id
    vt.close()


def test_transport_push_decode_off_socket(tmp_path):
    dec = FrameDecoder()
    if dec.backend == "none":
        pytest.skip("no decode backend")
    vt = VisionTransport()
    cid = vt.connect_browser("tok-2")
    jpeg = dec.encode_jpeg(synthetic_frame(40, 30, value=180))
    assert vt.submit_raw(cid, jpeg) is True
    assert vt.pump(cid) == 1                         # decode happens on pump (worker), not submit
    f = vt.consume(cid)
    assert f is not None and f.width == 40 and f.height == 30
    vt.close()


def test_corrupt_frame_flagged_not_crashing():
    vt = VisionTransport()
    cid = vt.connect_browser("tok-3")
    vt.submit_raw(cid, b"garbage")
    vt.pump(cid)                                     # corrupt → dropped, not enqueued
    assert vt.consume(cid) is None
    assert vt.metrics()["frames_corrupt"] >= 1
    vt.close()


def test_transport_events_on_runtime(runtime):
    from core.vision.transport.events import VisionEvent
    seen = []

    async def handler(ev):
        seen.append(ev)

    runtime.on(VisionEvent.CAMERA_REGISTERED, handler)
    vt = VisionTransport(runtime=runtime)
    vt.add_array_camera("arr", [synthetic_frame()])
    deadline = time.time() + 2.0
    while not seen and time.time() < deadline:
        time.sleep(0.02)
    assert seen, "expected a camera.registered event"
    vt.close()


def test_dashboard_and_health_shape():
    vt = VisionTransport()
    vt.add_array_camera("arr", [synthetic_frame()])
    d = vt.dashboard()
    assert d["title"] == "Vision Transport" and d["camera_count"] == 1
    assert vt.health()["status"] in ("ok", "degraded")
    vt.close()


def test_transport_manifest():
    vt = VisionTransport()
    m = vt.manifest()
    assert m["subsystem"] == "vision_transport" and m["milestone"] == "M14"
    vt.close()


def test_side_effect_free_import():
    import importlib
    importlib.import_module("core.vision")
    importlib.import_module("core.vision.transport")
