"""
ChartNet — the ~4-5M parameter chart-reading CNN.

Input : 1 x SIZE x SIZE grayscale chart image (SIZE=64 by default)
Output: logits over CLASSES (bearish / neutral / bullish by default)

The parameter budget lives almost entirely in the first fully-connected layer
(128*8*8 -> 512 ≈ 4.19M), which lands the whole net at ~4.3M — the "4-5 million"
target. Pure torch; no external weights, nothing downloaded.
"""

from __future__ import annotations

import torch
import torch.nn as nn

CLASSES = ["bearish", "neutral", "bullish"]


class ChartNet(nn.Module):
    def __init__(self, n_classes: int = len(CLASSES), size: int = 64) -> None:
        super().__init__()
        self.size = size
        self.n_classes = n_classes
        self.features = nn.Sequential(
            nn.Conv2d(1, 32, 3, padding=1), nn.BatchNorm2d(32), nn.ReLU(inplace=True),
            nn.MaxPool2d(2),                                        # -> 32 x S/2
            nn.Conv2d(32, 64, 3, padding=1), nn.BatchNorm2d(64), nn.ReLU(inplace=True),
            nn.MaxPool2d(2),                                        # -> 64 x S/4
            nn.Conv2d(64, 128, 3, padding=1), nn.BatchNorm2d(128), nn.ReLU(inplace=True),
            nn.MaxPool2d(2),                                        # -> 128 x S/8
        )
        feat = size // 8
        self.classifier = nn.Sequential(
            nn.Flatten(),
            nn.Dropout(0.3),
            nn.Linear(128 * feat * feat, 512), nn.ReLU(inplace=True),
            nn.Dropout(0.3),
            nn.Linear(512, n_classes),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.classifier(self.features(x))


def param_count(model: nn.Module) -> int:
    return sum(p.numel() for p in model.parameters())


if __name__ == "__main__":
    net = ChartNet()
    print(f"ChartNet params: {param_count(net):,}")
    dummy = torch.zeros(2, 1, net.size, net.size)
    print("forward output shape:", tuple(net(dummy).shape))
