"""
Eye 2, Stage 1 — Screen Capture.

Captures the screen (or a specific monitor/region) on an interval and hands
frames to downstream modules (OCR, chart detection, UI detection).

Uses `mss` (fast, cross-platform, no GUI deps) rather than pyautogui's
screenshot, which is slower for repeated capture.

Safety note: this module ONLY reads pixels. It never sends input
(no click/keyboard) — see vision/ui_detector.py and the project safety
rules: this app observes, it does not act on the screen.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

import mss
import numpy as np


@dataclass
class Frame:
    image: np.ndarray  # BGR, shape (H, W, 3)
    timestamp: datetime
    monitor_index: int


class ScreenCapture:
    def __init__(self, monitor_index: int = 1, region: Optional[dict] = None):
        """
        monitor_index: which monitor to capture (1 = primary in mss's numbering;
                        0 means "all monitors combined", which we avoid by default).
        region: optional dict {"top":..,"left":..,"width":..,"height":..} to
                 capture only the trading-platform window area instead of the
                 full screen. Narrowing this improves OCR speed/accuracy.
        """
        self.monitor_index = monitor_index
        self.region = region

    def capture_once(self) -> Frame:
        with mss.mss() as sct:
            target = self.region or sct.monitors[self.monitor_index]
            raw = sct.grab(target)
            img = np.array(raw)[:, :, :3]  # drop alpha, keep BGR-ish order
            return Frame(image=img, timestamp=datetime.now(), monitor_index=self.monitor_index)

    def stream(
        self,
        interval_seconds: float = 2.0,
        on_frame: Optional[Callable[[Frame], None]] = None,
        max_frames: Optional[int] = None,
    ):
        """Generator yielding Frame objects every `interval_seconds`.

        interval_seconds: keep within the spec's 1-5s range. Lower values cost
        more CPU (OCR + CV downstream); 2-3s is a reasonable default for a
        trading dashboard that isn't scalping tick-by-tick.
        """
        count = 0
        while max_frames is None or count < max_frames:
            frame = self.capture_once()
            if on_frame:
                on_frame(frame)
            yield frame
            count += 1
            time.sleep(interval_seconds)

    @staticmethod
    def save_frame(frame: Frame, out_dir: Path) -> Path:
        import cv2

        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / f"screen_{frame.timestamp.strftime('%Y%m%d_%H%M%S_%f')}.png"
        cv2.imwrite(str(path), frame.image)
        return path
