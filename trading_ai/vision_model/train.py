"""
train.py — train ChartNet on labelled chart images.

Runs locally on CPU (slow but works) or on a Hugging Face GPU (fast). With no
dataset it generates synthetic data on the fly, so you can smoke-test the whole
loop before committing GPU time.

    # local smoke test (small, CPU)
    python -m vision_model.train --synthetic-n 400 --epochs 3 --out out/chartnet.pt

    # real run (on HF GPU): make a big set, more epochs
    python -m vision_model.train --synthetic-n 20000 --epochs 20 --out out/chartnet.pt

Saves the weights (.pt) plus a sidecar .json with size / classes / accuracy.
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import numpy as np


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Train Athena's chart-vision model")
    ap.add_argument("--data", default="", help="npz with X,y (else synthetic)")
    ap.add_argument("--synthetic-n", type=int, default=2000)
    ap.add_argument("--size", type=int, default=64)
    ap.add_argument("--epochs", type=int, default=10)
    ap.add_argument("--batch", type=int, default=64)
    ap.add_argument("--lr", type=float, default=1e-3)
    ap.add_argument("--out", default="out/chartnet.pt")
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args(argv)

    import torch
    from torch.utils.data import DataLoader

    from .dataset import ChartDataset, build_synthetic_dataset
    from .model import CLASSES, ChartNet, param_count

    if args.data:
        d = np.load(args.data)
        X, y = d["X"].astype(np.float32), d["y"].astype(np.int64)
    else:
        print(f"generating {args.synthetic_n} synthetic charts ...")
        X, y = build_synthetic_dataset(n=args.synthetic_n, size=args.size, seed=args.seed)
    print(f"dataset: {X.shape[0]} images, class counts = {np.bincount(y, minlength=len(CLASSES)).tolist()}")

    # split
    rng = np.random.default_rng(args.seed)
    idx = rng.permutation(len(y))
    cut = int(len(y) * 0.9)
    tr, va = idx[:cut], idx[cut:]
    train_dl = DataLoader(ChartDataset(X[tr], y[tr]), batch_size=args.batch, shuffle=True)
    val_dl = DataLoader(ChartDataset(X[va], y[va]), batch_size=args.batch)

    device = "cuda" if torch.cuda.is_available() else "cpu"
    net = ChartNet(n_classes=len(CLASSES), size=args.size).to(device)
    print(f"ChartNet params: {param_count(net):,} | device: {device}")
    opt = torch.optim.Adam(net.parameters(), lr=args.lr)
    loss_fn = torch.nn.CrossEntropyLoss()

    best_acc = 0.0
    for epoch in range(1, args.epochs + 1):
        net.train()
        t0 = time.time()
        for xb, yb in train_dl:
            xb, yb = xb.to(device), yb.to(device)
            opt.zero_grad()
            loss = loss_fn(net(xb), yb)
            loss.backward()
            opt.step()
        acc = _accuracy(net, val_dl, device)
        best_acc = max(best_acc, acc)
        print(f"epoch {epoch:2d}/{args.epochs} | val acc {acc:.3f} | {time.time()-t0:.1f}s")

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    torch.save(net.state_dict(), out)
    meta = {"classes": CLASSES, "size": args.size, "params": param_count(net),
            "val_accuracy": round(best_acc, 4), "trained_on": X.shape[0]}
    out.with_suffix(".json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    print(f"saved {out} (val acc {best_acc:.3f}); meta -> {out.with_suffix('.json')}")
    return 0


def _accuracy(net, dl, device) -> float:
    import torch
    net.eval()
    correct = total = 0
    with torch.no_grad():
        for xb, yb in dl:
            pred = net(xb.to(device)).argmax(1).cpu()
            correct += int((pred == yb).sum())
            total += len(yb)
    return correct / max(1, total)


if __name__ == "__main__":
    raise SystemExit(main())
