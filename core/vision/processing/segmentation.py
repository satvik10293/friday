"""
core/vision/processing/segmentation.py — FRIDAY 6.1 (M14)
Lightweight scene segmentation. Always-available (pure numpy): it tiles the frame into
a GxG grid of mean-colour cells and merges adjacent cells with similar colour via
union-find, yielding a small set of coarse colour segments with bounding boxes and
dominant colours. This is a real, dependency-free segmenter — a deterministic
stand-in/companion for a learned semantic segmenter, which can be added later as
another plugin without changing the pipeline.
"""

from __future__ import annotations

import numpy as np

from .base import BoundingBox, Detection, VisionProcessor


class _UnionFind:
    def __init__(self, n: int) -> None:
        self._p = list(range(n))

    def find(self, a: int) -> int:
        while self._p[a] != a:
            self._p[a] = self._p[self._p[a]]
            a = self._p[a]
        return a

    def union(self, a: int, b: int) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self._p[ra] = rb


class SegmentationProcessor(VisionProcessor):
    name = "segmentation"
    kind = "segmentation"
    requires = ()

    def __init__(self, config=None) -> None:
        super().__init__()
        self._grid = max(2, int(getattr(config, "segmentation_grid", 8)))
        self._tol = float(getattr(config, "segmentation_merge_tol", 18.0))

    def analyze(self, frame):
        arr = np.asarray(frame.data)
        if arr.ndim == 2:
            arr = np.stack([arr] * 3, axis=-1)
        h, w = arr.shape[:2]
        g = self._grid
        ys = np.linspace(0, h, g + 1).astype(int)
        xs = np.linspace(0, w, g + 1).astype(int)

        # mean colour per cell
        cell_mean = np.zeros((g, g, 3), dtype=np.float32)
        for i in range(g):
            for j in range(g):
                block = arr[ys[i]:ys[i + 1], xs[j]:xs[j + 1], :3]
                cell_mean[i, j] = block.reshape(-1, 3).mean(axis=0) if block.size else 0.0

        uf = _UnionFind(g * g)
        for i in range(g):
            for j in range(g):
                idx = i * g + j
                if j + 1 < g and self._close(cell_mean[i, j], cell_mean[i, j + 1]):
                    uf.union(idx, idx + 1)
                if i + 1 < g and self._close(cell_mean[i, j], cell_mean[i + 1, j]):
                    uf.union(idx, (i + 1) * g + j)

        # gather segments → bbox + mean colour
        segs: dict[int, dict] = {}
        for i in range(g):
            for j in range(g):
                root = uf.find(i * g + j)
                s = segs.setdefault(root, {"x1": xs[j], "y1": ys[i], "x2": xs[j + 1],
                                           "y2": ys[i + 1], "cells": 0,
                                           "color": np.zeros(3, dtype=np.float32)})
                s["x1"] = min(s["x1"], xs[j]); s["y1"] = min(s["y1"], ys[i])
                s["x2"] = max(s["x2"], xs[j + 1]); s["y2"] = max(s["y2"], ys[i + 1])
                s["cells"] += 1
                s["color"] += cell_mean[i, j]

        detections: list = []
        for s in sorted(segs.values(), key=lambda d: d["cells"], reverse=True):
            color = (s["color"] / s["cells"]).astype(int)   # BGR mean
            x, y = int(s["x1"]), int(s["y1"])
            bw, bh = int(s["x2"] - s["x1"]), int(s["y2"] - s["y1"])
            coverage = (s["cells"] / (g * g))
            detections.append(Detection(
                label="segment", confidence=round(coverage, 3), kind="region",
                bbox=BoundingBox(x, y, bw, bh),
                attributes={"coverage": round(coverage, 3),
                            "rgb": [int(color[2]), int(color[1]), int(color[0])]}))
        return detections, {"segments": len(detections), "grid": g}

    def _close(self, a: np.ndarray, b: np.ndarray) -> bool:
        return float(np.abs(a - b).sum()) <= self._tol
