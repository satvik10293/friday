"""
Athena's chart-vision model (Track B): the ~4-5M param CNN, the renderer, the
auto-labelled dataset, and a tiny end-to-end train + predict. No network, no
pretrained weights — everything is generated.
"""

from __future__ import annotations

import numpy as np

from vision_model.dataset import (build_synthetic_dataset, label_for, synth_ohlcv)
from vision_model.model import CLASSES, ChartNet, param_count
from vision_model.predict import ChartPredictor
from vision_model.render import image_from_array, render_candles


# ── the model is the right size and shape ─────────────────────────────────────

def test_chartnet_is_four_to_five_million_params():
    n = param_count(ChartNet())
    assert 4_000_000 <= n <= 5_000_000, f"expected ~4-5M params, got {n:,}"


def test_chartnet_forward_shape():
    import torch
    net = ChartNet()
    out = net(torch.zeros(3, 1, net.size, net.size))
    assert tuple(out.shape) == (3, len(CLASSES))


# ── rendering ─────────────────────────────────────────────────────────────────

def test_render_shape_and_range():
    df = synth_ohlcv(bars=64, drift=0.3, seed=1)
    img = render_candles(df, size=64)
    assert img.shape == (64, 64)
    assert img.min() >= 0.0 and img.max() <= 1.0 and img.max() > 0.0


def test_image_from_array_resizes_to_square():
    arr = np.random.default_rng(0).random((120, 200)) * 255
    out = image_from_array(arr, size=64)
    assert out.shape == (64, 64) and out.max() <= 1.0


# ── auto-labelled dataset ─────────────────────────────────────────────────────

def test_label_for_returns_a_valid_class():
    assert label_for(synth_ohlcv(bars=64, drift=0.9, seed=2)) in range(len(CLASSES))


def test_build_synthetic_dataset_shapes_and_labels():
    X, y = build_synthetic_dataset(n=40, size=64, seed=3)
    assert X.shape == (40, 1, 64, 64) and y.shape == (40,)
    assert set(np.unique(y)).issubset(set(range(len(CLASSES))))


# ── end-to-end: train tiny, then read a chart ─────────────────────────────────

def test_train_then_predict(tmp_path):
    from vision_model.train import main as train_main
    out = tmp_path / "chartnet.pt"
    rc = train_main(["--synthetic-n", "120", "--epochs", "1", "--out", str(out), "--seed", "4"])
    assert rc == 0 and out.exists() and out.with_suffix(".json").exists()

    p = ChartPredictor(str(out))
    assert p.available()
    res = p.predict_df(synth_ohlcv(bars=64, drift=0.9, seed=5))
    assert res["class"] in CLASSES and 0.0 <= res["confidence"] <= 1.0


def test_predictor_degrades_without_weights(tmp_path):
    p = ChartPredictor(str(tmp_path / "missing.pt"))
    assert p.available() is False
    res = p.predict_df(synth_ohlcv(bars=64, seed=6))
    assert res["class"] == "" and "error" in res            # honest miss, no raise
