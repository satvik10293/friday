"""
core/vision/processing/scene_stats.py — FRIDAY 6.1 (M14)
Always-available scene statistics: brightness, contrast, colourfulness, sharpness, and
a coarse dominant colour. Pure numpy (no backend), so the pipeline always produces real
structured output. These feed scene-change detection in Visual Memory and give the
Observation Builder a frame-level summary even when no objects are detected.
"""

from __future__ import annotations

import numpy as np

from .base import VisionProcessor, to_gray


class SceneStatsProcessor(VisionProcessor):
    name = "scene_stats"
    kind = "scene"
    requires = ()                             # numpy only — always available

    def analyze(self, frame):
        arr = np.asarray(frame.data)
        gray = to_gray(arr)
        brightness = float(gray.mean()) / 255.0
        contrast = float(gray.std()) / 128.0
        # sharpness: variance of a cheap Laplacian (numpy gradient), normalized
        gy, gx = np.gradient(gray)
        sharpness = float((gx ** 2 + gy ** 2).mean()) / 1000.0
        data = {
            "brightness": round(brightness, 4),
            "contrast": round(min(1.0, contrast), 4),
            "sharpness": round(min(1.0, sharpness), 4),
        }
        if arr.ndim == 3 and arr.shape[2] >= 3:
            mean_bgr = arr[:, :, :3].astype(np.float32).reshape(-1, 3).mean(axis=0)
            # frames are BGR by convention (see decoder); report RGB for humans
            data["mean_rgb"] = [int(mean_bgr[2]), int(mean_bgr[1]), int(mean_bgr[0])]
            data["dominant_channel"] = ["blue", "green", "red"][int(np.argmax(mean_bgr))]
        # a stable scene signature for cheap change detection (coarse 4x4 luminance grid)
        data["signature"] = self._signature(gray)
        return [], data

    @staticmethod
    def _signature(gray: np.ndarray) -> list:
        h, w = gray.shape[:2]
        if h == 0 or w == 0:
            return []
        ys = np.linspace(0, h, 5).astype(int)
        xs = np.linspace(0, w, 5).astype(int)
        sig = []
        for i in range(4):
            for j in range(4):
                cell = gray[ys[i]:ys[i + 1], xs[j]:xs[j + 1]]
                sig.append(int(cell.mean()) if cell.size else 0)
        return sig
