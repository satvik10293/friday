"""
predict.py — read a live chart with the trained ChartNet.

    from vision_model.predict import ChartPredictor
    p = ChartPredictor("out/chartnet.pt")
    p.predict_df(ohlcv_df)          # from candle data
    p.predict_image(screenshot)     # from a grayscale screenshot crop (numpy)

Returns {"class": "bullish", "confidence": 0.82, "probs": {...}}. Never raises
for an operational miss — a missing weights file yields available()==False and a
clear, empty read, so Athena degrades to her rule engine.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import numpy as np

from .model import CLASSES
from .render import image_from_array, render_candles


class ChartPredictor:
    def __init__(self, weights: str = "out/chartnet.pt", size: int = 64) -> None:
        self._path = Path(weights)
        self._size = size
        self._net = None

    def available(self) -> bool:
        return self._path.exists()

    def _load(self):
        if self._net is not None:
            return self._net
        import torch
        from .model import ChartNet
        net = ChartNet(n_classes=len(CLASSES), size=self._size)
        net.load_state_dict(torch.load(self._path, map_location="cpu"))
        net.eval()
        self._net = net
        return net

    def _infer(self, img: np.ndarray) -> dict:
        if not self.available():
            return {"class": "", "confidence": 0.0, "probs": {}, "error": "model not trained"}
        try:
            import torch
            net = self._load()
            x = torch.from_numpy(img.astype(np.float32))[None, None]
            with torch.no_grad():
                probs = torch.softmax(net(x), dim=1)[0].tolist()
            top = int(np.argmax(probs))
            return {"class": CLASSES[top], "confidence": round(probs[top], 3),
                    "probs": {c: round(p, 3) for c, p in zip(CLASSES, probs)}}
        except Exception as e:  # noqa: BLE001 — inference miss must not crash Athena
            return {"class": "", "confidence": 0.0, "probs": {}, "error": str(e)}

    def predict_df(self, df) -> dict:
        return self._infer(render_candles(df, self._size))

    def predict_image(self, arr: np.ndarray) -> dict:
        return self._infer(image_from_array(arr, self._size))
