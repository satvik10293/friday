from unittest.mock import MagicMock, patch

import numpy as np

from vision_screen_capture import ScreenCapture


def _fake_mss(monitor_shape=(100, 200, 4)):
    """Builds a mock mss.mss() context manager returning a fake screenshot."""
    fake_sct = MagicMock()
    fake_sct.monitors = [
        {"top": 0, "left": 0, "width": 1, "height": 1},  # index 0: "all"
        {"top": 0, "left": 0, "width": 200, "height": 100},  # index 1: primary
    ]
    fake_sct.grab.return_value = np.zeros(monitor_shape, dtype=np.uint8)
    cm = MagicMock()
    cm.__enter__.return_value = fake_sct
    cm.__exit__.return_value = False
    return cm


def test_capture_once_returns_frame_with_correct_shape():
    with patch("vision_screen_capture.mss.mss", return_value=_fake_mss()):
        cap = ScreenCapture(monitor_index=1)
        frame = cap.capture_once()
    assert frame.image.shape == (100, 200, 3)  # alpha channel dropped
    assert frame.monitor_index == 1


def test_capture_once_uses_custom_region():
    region = {"top": 10, "left": 10, "width": 50, "height": 50}
    with patch(
        "vision_screen_capture.mss.mss", return_value=_fake_mss((50, 50, 4))
    ) as mock_mss:
        cap = ScreenCapture(region=region)
        cap.capture_once()
    grabbed_arg = mock_mss.return_value.__enter__.return_value.grab.call_args[0][0]
    assert grabbed_arg == region


def test_stream_yields_max_frames_and_calls_callback():
    received = []
    with patch("vision_screen_capture.mss.mss", return_value=_fake_mss()):
        with patch("vision_screen_capture.time.sleep", return_value=None):
            cap = ScreenCapture(monitor_index=1)
            frames = list(
                cap.stream(interval_seconds=0, on_frame=received.append, max_frames=3)
            )
    assert len(frames) == 3
    assert len(received) == 3
