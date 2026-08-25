"""
Mobile camera end-to-end (M64).

Proves the phone-camera path works without needing a phone: a base64 JPEG
data-URL (exactly what the browser client emits over SocketIO) is submitted to
the Camera Manager, decoded off the socket thread, and surfaces as a decoded
Frame the next pipeline stage can consume — and the camera's health reports the
live stream. Also pins the LAN-URL helper the launcher prints.
"""

from __future__ import annotations

import base64

import cv2
import numpy as np

from core.vision.transport.service import VisionTransport


def _jpeg_data_url(w=64, h=48) -> str:
    """A real JPEG data-URL, identical in shape to the browser client's payload."""
    img = np.zeros((h, w, 3), np.uint8)
    img[:, : w // 2] = (0, 0, 255)          # left half red (BGR)
    ok, buf = cv2.imencode(".jpg", img)
    assert ok
    return "data:image/jpeg;base64," + base64.b64encode(buf.tobytes()).decode()


def test_phone_frame_flows_through_to_a_decoded_frame():
    transport = VisionTransport()
    cid = transport.connect_browser("phone-token-abc", label="Pixel test")
    assert cid.startswith("CAMERA_")

    # the SocketIO 'frame' handler does exactly this: submit_raw with the data-URL
    ok = transport.submit_raw(cid, _jpeg_data_url(), capture_time=1.0, recv_time=1.02)
    assert ok

    ingested = transport.pump(cid)          # worker drains + decodes (sync here)
    assert ingested == 1

    frame = transport.consume(cid)
    assert frame is not None
    assert frame.data is not None
    assert frame.data.shape == (48, 64, 3)   # decoded back to the right size
    assert (frame.width, frame.height) == (64, 48)


def test_registration_is_stable_by_token():
    transport = VisionTransport()
    a = transport.connect_browser("same-token", label="phone")
    b = transport.connect_browser("same-token", label="phone")
    assert a == b                            # same phone → same permanent camera id


def test_health_reports_the_camera_after_frames():
    transport = VisionTransport()
    cid = transport.connect_browser("phone-2")
    for _ in range(3):
        transport.submit_raw(cid, _jpeg_data_url(), capture_time=1.0, recv_time=1.0)
    transport.pump(cid)
    health = transport.health()
    assert health["cameras"] >= 1


def test_local_ip_is_a_dotted_quad():
    from tools.mobile_camera import local_ip
    ip = local_ip()
    parts = ip.split(".")
    assert len(parts) == 4 and all(p.isdigit() for p in parts)
