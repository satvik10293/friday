"""
find_region.py — one-off utility to help you pick --region LEFT,TOP,WIDTH,HEIGHT
for main.py.

Run this with your trading platform window visible on screen. It saves
region_finder.png: your screen with a green coordinate grid drawn every
100px so you can read off the top-left corner and size of the window you
want main.py to watch.

This only reads pixels (same as vision_screen_capture.py) — it never
clicks or sends input anywhere.
"""

from __future__ import annotations

import cv2
import mss
import numpy as np


def grab_full_screen() -> tuple[np.ndarray, list[dict]]:
    with mss.mss() as sct:
        monitors = sct.monitors
        print("Detected monitors:")
        for i, m in enumerate(monitors):
            print(f"  [{i}] {m}")

        # monitors[0] is the "all monitors combined" virtual screen; grab that
        # so the grid covers everything, including secondary monitors.
        raw = sct.grab(monitors[0])
        img = np.array(raw)[:, :, :3]  # drop alpha
        return img, monitors


def draw_grid(img: np.ndarray, step: int = 100) -> np.ndarray:
    out = img.copy()
    h, w = out.shape[:2]
    color = (0, 255, 0)  # green, BGR
    thickness = 1
    font = cv2.FONT_HERSHEY_SIMPLEX
    font_scale = 0.4

    for x in range(0, w, step):
        cv2.line(out, (x, 0), (x, h), color, thickness)
        cv2.putText(out, str(x), (x + 3, 15), font, font_scale, color, 1, cv2.LINE_AA)

    for y in range(0, h, step):
        cv2.line(out, (0, y), (w, y), color, thickness)
        cv2.putText(out, str(y), (3, y + 12), font, font_scale, color, 1, cv2.LINE_AA)

    return out


def main() -> None:
    img, _monitors = grab_full_screen()
    gridded = draw_grid(img)

    out_path = "region_finder.png"
    cv2.imwrite(out_path, gridded)

    print(f"Saved {out_path} — open it, find your trading platform window,")
    print("and read off left/top (top-left corner) and width/height from the grid.")
    print("Then run:  python main.py --symbol AAPL --region LEFT,TOP,WIDTH,HEIGHT")


if __name__ == "__main__":
    main()
