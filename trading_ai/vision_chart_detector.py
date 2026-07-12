"""
Eye 2, Stage 3 — Chart Region Detector.

Finds WHERE the price chart is on the screen, so OCR and analysis can focus
on just that area and ignore everything else (browser tabs, YouTube videos,
chat windows, the other half of a split screen...).

How it works: candlestick charts are visually loud — lots of saturated
green/red (or teal/red) pixels clustered in one rectangular area. We:
  1. mask pixels in candle-green and candle-red color ranges (HSV)
  2. dilate the mask so individual candles merge into one blob
  3. take the largest connected blob and its bounding box
  4. report which side of the screen it sits on: left / right / center

If no candle colors are found (line chart instead of candles), a second
pass looks for the classic blue line-chart color.

Pixels in, rectangle out — this module never clicks or types anything.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import cv2
import numpy as np


@dataclass
class ChartRegion:
    left: int
    top: int
    width: int
    height: int
    side: str        # "left" | "right" | "center"
    chart_type: str  # "candles" | "line"
    density: float   # fraction of chart-colored pixels inside the box (quality hint)

    def crop(self, image: np.ndarray) -> np.ndarray:
        return image[self.top: self.top + self.height,
                     self.left: self.left + self.width]

    def as_mss_region(self) -> dict:
        return {"left": self.left, "top": self.top,
                "width": self.width, "height": self.height}


def _candle_mask(bgr: np.ndarray) -> np.ndarray:
    """Pixels colored like bullish (green/teal) or bearish (red) candles."""
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    green = cv2.inRange(hsv, (40, 60, 60), (95, 255, 255))
    red_lo = cv2.inRange(hsv, (0, 60, 60), (10, 255, 255))
    red_hi = cv2.inRange(hsv, (170, 60, 60), (180, 255, 255))
    return green | red_lo | red_hi


def _line_mask(bgr: np.ndarray) -> np.ndarray:
    """Fallback: the saturated blue used by most line/area charts."""
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    return cv2.inRange(hsv, (100, 120, 120), (130, 255, 255))


def _largest_blob_bbox(mask: np.ndarray) -> Optional[tuple]:
    """Merges nearby mask pixels and returns (x, y, w, h, filled_area) of the
    biggest cluster, or None if the mask is essentially empty."""
    h, w = mask.shape
    kernel_w = max(15, w // 40)
    kernel_h = max(15, h // 40)
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (kernel_w, kernel_h))
    merged = cv2.dilate(mask, kernel)

    n_labels, labels, stats, _ = cv2.connectedComponentsWithStats(merged)
    if n_labels < 2:  # label 0 is background
        return None

    # Largest component by area, skipping the background
    idx = int(np.argmax(stats[1:, cv2.CC_STAT_AREA])) + 1
    x = int(stats[idx, cv2.CC_STAT_LEFT])
    y = int(stats[idx, cv2.CC_STAT_TOP])
    bw = int(stats[idx, cv2.CC_STAT_WIDTH])
    bh = int(stats[idx, cv2.CC_STAT_HEIGHT])
    area = int(stats[idx, cv2.CC_STAT_AREA])
    return x, y, bw, bh, area


def find_chart_region(
    image: np.ndarray,
    min_width_frac: float = 0.15,
    min_height_frac: float = 0.15,
) -> Optional[ChartRegion]:
    """
    Locates the price chart in a screenshot. Returns None when nothing on
    screen looks like a chart (so callers can fall back to full-frame OCR).

    min_width_frac / min_height_frac: reject blobs smaller than this fraction
    of the screen — a stray green icon or a red notification badge is not a
    chart.
    """
    h, w = image.shape[:2]

    for mask_fn, chart_type in ((_candle_mask, "candles"), (_line_mask, "line")):
        mask = mask_fn(image)
        blob = _largest_blob_bbox(mask)
        if blob is None:
            continue

        x, y, bw, bh, _ = blob
        if bw < w * min_width_frac or bh < h * min_height_frac:
            continue

        # Pad the box a little: the symbol name / legend usually sits just
        # above or at the top-left of the plotted candles, and we want OCR
        # to read it.
        pad_x, pad_y = int(w * 0.03), int(h * 0.05)
        x0 = max(0, x - pad_x)
        y0 = max(0, y - pad_y)
        x1 = min(w, x + bw + pad_x)
        y1 = min(h, y + bh + pad_y)

        center_x = (x0 + x1) / 2
        if center_x < w * 0.4:
            side = "left"
        elif center_x > w * 0.6:
            side = "right"
        else:
            side = "center"

        box_mask = mask[y0:y1, x0:x1]
        density = float(np.count_nonzero(box_mask)) / max(1, box_mask.size)

        return ChartRegion(
            left=x0, top=y0, width=x1 - x0, height=y1 - y0,
            side=side, chart_type=chart_type, density=density,
        )

    return None


# ---- quick manual test -----------------------------------------------------

if __name__ == "__main__":
    from vision_screen_capture import ScreenCapture

    frame = ScreenCapture().capture_once()
    region = find_chart_region(frame.image)
    if region is None:
        print("No chart found on screen.")
    else:
        print(f"Chart found on the {region.side.upper()} side "
              f"({region.chart_type}, {region.width}x{region.height} px "
              f"at {region.left},{region.top}, density {region.density:.1%})")
        cv2.imwrite("chart_region_debug.png", region.crop(frame.image))
        print("Cropped chart saved to chart_region_debug.png")
