"""Offline tests for vision_chart_detector using synthetic screenshots."""

import numpy as np
import pytest

from vision_chart_detector import find_chart_region


def _draw_candles(image, x_start, x_end, y_start, y_end, n=30):
    """Paints alternating green/red candlestick-like bars (BGR)."""
    width = x_end - x_start
    step = max(4, width // n)
    body_w = max(2, step // 2)
    rng = np.random.default_rng(7)
    for i in range(n):
        x = x_start + i * step
        if x + body_w >= x_end:
            break
        top = int(rng.integers(y_start, (y_start + y_end) // 2))
        bottom = int(rng.integers((y_start + y_end) // 2, y_end))
        color = (96, 169, 38) if i % 2 == 0 else (80, 83, 239)  # green / red, BGR
        image[top:bottom, x:x + body_w] = color


def _split_screen(chart_on: str) -> np.ndarray:
    """1000x600 dark screenshot: candles on one half, white 'text' on the other."""
    img = np.full((600, 1000, 3), 20, dtype=np.uint8)
    if chart_on == "left":
        _draw_candles(img, 60, 440, 80, 520)
        text_x = 560
    else:
        _draw_candles(img, 560, 940, 80, 520)
        text_x = 60
    # fake text lines on the other half (white — must not look like a chart)
    for y in range(100, 500, 30):
        img[y:y + 12, text_x:text_x + 380] = 230
    return img


def test_finds_chart_on_left_half():
    region = find_chart_region(_split_screen("left"))
    assert region is not None
    assert region.side == "left"
    assert region.chart_type == "candles"
    # The box must stay on the left half, not swallow the text side
    assert region.left + region.width <= 520


def test_finds_chart_on_right_half():
    region = find_chart_region(_split_screen("right"))
    assert region is not None
    assert region.side == "right"
    assert region.left >= 480


def test_blank_screen_returns_none():
    blank = np.full((600, 1000, 3), 20, dtype=np.uint8)
    assert find_chart_region(blank) is None


def test_small_colored_badge_is_not_a_chart():
    img = np.full((600, 1000, 3), 20, dtype=np.uint8)
    img[10:30, 950:990] = (80, 83, 239)  # tiny red notification badge
    assert find_chart_region(img) is None


def test_crop_matches_region():
    img = _split_screen("left")
    region = find_chart_region(img)
    crop = region.crop(img)
    assert crop.shape[0] == region.height
    assert crop.shape[1] == region.width
