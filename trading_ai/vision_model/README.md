# Athena chart-vision model (Track B)

A small (~4.3M param) CNN — **ChartNet** — that reads a chart from **pixels**, so
Athena can understand a chart on screen even with no underlying OHLCV (a broker
UI, a screenshot, someone else's terminal). It complements the rule engine
(`signals_catalog.py`): rules read the numbers, the net reads the picture.

## How it learns (no manual labelling)

Charts are auto-labelled by the rule engine: render an OHLCV window to an image,
then label it with `signals_catalog.read_chart()`'s bias (bearish / neutral /
bullish). The rules teach the eye — so we get unlimited training data for free.

```
OHLCV window ──render_candles──> 64x64 image ──read_chart──> label
                                     └────────── (image, label) pair
```

## Files

| File | What |
|---|---|
| `model.py` | ChartNet — the ~4-5M param CNN (`param_count` prints it) |
| `render.py` | OHLCV → grayscale image (pure numpy); `image_from_array` for live screenshots |
| `dataset.py` | `build_synthetic_dataset` (network-free) + `build_dataset_from_ohlcv` (real market windows) |
| `train.py` | training loop — CPU locally or GPU on Hugging Face |
| `predict.py` | `ChartPredictor` — read a live chart df or screenshot; degrades cleanly with no weights |

## Pipeline (train on Hugging Face, run locally)

Same shape as the persona kit: HF is the gym, this machine is the home.

1. **Smoke-test locally (CPU):**
   ```bash
   cd trading_ai
   python -m vision_model.train --synthetic-n 400 --epochs 3 --out out/chartnet.pt
   ```
2. **Build a real dataset (stronger model):** feed real windows from Athena's
   market API into `build_dataset_from_ohlcv`, save as an `.npz` (`X`, `y`), and
   upload it — or just raise `--synthetic-n` a lot.
3. **Train on a Hugging Face GPU:**
   ```bash
   python -m vision_model.train --data charts.npz --epochs 20 --out out/chartnet.pt
   ```
   (CUDA is used automatically when present.)
4. **Bring it home:** download `out/chartnet.pt` (+ the `.json` meta), drop it in
   `trading_ai/out/`, and Athena reads charts:
   ```python
   from vision_model.predict import ChartPredictor
   ChartPredictor("out/chartnet.pt").predict_image(screenshot_crop)
   ```

## Honest scope

ChartNet learns to reproduce the rule engine's *read* from a picture — that's
**screen understanding**, its real job. It does **not** predict the future or
replace `signals_catalog`; the edge stays probabilistic. On synthetic data it
learns the mapping quickly; real-market images make it robust to real chart
styling. Wiring its output into the recommendation engine is a deliberate
follow-up so Athena's tested BUY/SELL logic stays intact.
```
