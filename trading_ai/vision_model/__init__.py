"""
trading_ai/vision_model — Athena's chart-vision model (Track B).

A small (~4-5M param) CNN that READS a chart from pixels — so Athena can
understand a chart on screen even when she has no underlying OHLCV (a broker UI,
a screenshot, someone else's terminal). It is trained by auto-labelling rendered
charts with signals_catalog.read_chart(), so the rule engine teaches the eye.

    model.py    — ChartNet (the ~4-5M param CNN)
    render.py   — OHLCV window -> grayscale chart image (pure numpy)
    dataset.py  — build labelled (image, class) data; synthetic generator
    train.py    — train on the data (local or Hugging Face GPU)
    predict.py  — load weights, read a live chart image

Honest scope: it learns to SEE the catalog's read from a picture. It sharpens
screen understanding; it does not predict the future or replace the rule engine.
"""
