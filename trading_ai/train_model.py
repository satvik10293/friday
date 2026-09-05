"""
trading_ai/train_model.py — train Athena on HISTORY, then test her HONESTLY.

Training a model to predict the market is the oldest trap in trading: it will ace
the data it studied and then fail on data it never saw (overfitting). So this
pipeline judges every trained model the only way that means anything — a
TIME-ORDERED out-of-sample split: fit on the older bars, score on the newer bars
the model never touched, and report whether it actually beats a naive baseline
AND makes money after costs on those unseen bars. If it doesn't, that's the
honest answer, and the model is not wired into her decisions.

    python train_model.py --symbols AAPL,MSFT,NVDA --period 2y --interval 1d --horizon 5

Not financial advice. A model that passes here is evidence, not a guarantee —
paper-trade it before risking money you can afford to lose.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

import numpy as np
import pandas as pd

from signals_catalog import indicators

# The features she learns from — all from indicators she already computes.
FEATURES = ["rsi14", "macd_hist", "bb_width", "stoch_k", "adx14", "cci",
            "williams_r", "ret1", "ret5", "atr_pct"]

_ROOT = Path(__file__).resolve().parent
_DEFAULT_MODEL = _ROOT.parent / "data" / "athena_model.joblib"


def build_features(df: pd.DataFrame, *, horizon: int = 5):
    """(X, y, forward_return, cols) from a candle frame. Label = 1 if price is
    higher `horizon` bars later. Rows without full indicators/label are dropped."""
    d = indicators(df).copy()
    c = d["close"]
    d["ret1"] = c.pct_change()
    d["ret5"] = c.pct_change(5)
    d["atr_pct"] = d["atr14"] / c.replace(0.0, np.nan)
    d["fwd"] = c.shift(-horizon) / c - 1.0
    d = d.replace([np.inf, -np.inf], np.nan).dropna(subset=FEATURES + ["fwd"])
    X = d[FEATURES].to_numpy(float)
    fwd = d["fwd"].to_numpy(float)
    y = (fwd > 0).astype(int)
    return X, y, fwd, list(FEATURES)


@dataclass
class TrainResult:
    ok: bool = True
    reason: str = ""
    rows: int = 0
    oos_accuracy: float = 0.0
    baseline: float = 0.0                 # always-guess-majority-class accuracy
    oos_return_pct: float = 0.0           # compounded, trading the predictions, after cost
    edge: bool = False
    features: List[str] = field(default_factory=list)
    model: object = None
    scaler: object = None

    def verdict(self) -> str:
        if not self.ok:
            return f"NO MODEL — {self.reason}"
        beats = self.oos_accuracy - self.baseline
        head = "REAL EDGE (on unseen data)" if self.edge else "NO EDGE — overfit or noise"
        return (f"{head}: out-of-sample accuracy {self.oos_accuracy:.1%} vs "
                f"baseline {self.baseline:.1%} ({beats:+.1%}), "
                f"traded return {self.oos_return_pct:+.2f}% after costs")


def train_and_validate(df: pd.DataFrame, *, horizon: int = 5, test_frac: float = 0.3,
                       cost: float = 0.0005, min_rows: int = 150) -> TrainResult:
    """Fit on the older bars, score on the newer bars the model never saw."""
    X, y, fwd, cols = build_features(df, horizon=horizon)
    n = len(y)
    if n < min_rows:
        return TrainResult(ok=False, reason=f"not enough data ({n} rows, need {min_rows})")
    if len(set(y.tolist())) < 2:
        return TrainResult(ok=False, reason="only one outcome class in this data")

    k = int(n * (1 - test_frac))
    Xtr, Xte, ytr, yte, fwdte = X[:k], X[k:], y[:k], y[k:], fwd[k:]
    if len(yte) < 20 or len(set(ytr.tolist())) < 2:
        return TrainResult(ok=False, reason="split too small or single-class train set")

    from sklearn.ensemble import GradientBoostingClassifier
    from sklearn.preprocessing import StandardScaler

    scaler = StandardScaler().fit(Xtr)
    clf = GradientBoostingClassifier(random_state=0, n_estimators=150, max_depth=3)
    clf.fit(scaler.transform(Xtr), ytr)

    pred = clf.predict(scaler.transform(Xte))
    oos_acc = float((pred == yte).mean())
    baseline = float(max(yte.mean(), 1 - yte.mean()))     # majority-class guess
    # trade the prediction: go long the next `horizon` bars when it says "up"
    trade_ret = np.where(pred == 1, fwdte, 0.0) - cost * (pred == 1)
    oos_return = float((np.prod(1.0 + trade_ret) - 1.0) * 100.0)
    # honest bar: must beat baseline by a real margin AND make money after costs
    edge = (oos_acc >= baseline + 0.02) and (oos_return > 0.0)

    return TrainResult(ok=True, rows=n, oos_accuracy=oos_acc, baseline=baseline,
                       oos_return_pct=oos_return, edge=edge, features=cols,
                       model=clf, scaler=scaler)


def save_model(result: TrainResult, path: Path = _DEFAULT_MODEL) -> Optional[str]:
    """Persist a trained model — ONLY if it earned it (real out-of-sample edge)."""
    if not result.ok or not result.edge:
        return None
    import joblib
    path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump({"model": result.model, "scaler": result.scaler,
                 "features": result.features}, path)
    return str(path)


def load_model(path: Path = _DEFAULT_MODEL):
    if not Path(path).exists():
        return None
    import joblib
    try:
        return joblib.load(path)
    except Exception:  # noqa: BLE001
        return None


def latest_features(df: pd.DataFrame):
    """Feature row for the CURRENT last bar (no forward label needed), or None."""
    d = indicators(df).copy()
    c = d["close"]
    d["ret1"] = c.pct_change()
    d["ret5"] = c.pct_change(5)
    d["atr_pct"] = d["atr14"] / c.replace(0.0, np.nan)
    d = d.replace([np.inf, -np.inf], np.nan).dropna(subset=FEATURES)
    if d.empty:
        return None
    return d[FEATURES].to_numpy(float)[-1:]


def predict_up_prob(df: pd.DataFrame, bundle=None) -> Optional[float]:
    """P(price up next horizon) from a saved model, or None if there's no model
    (there only IS one if it passed the honest out-of-sample edge test)."""
    bundle = bundle or load_model()
    if bundle is None:
        return None
    x = latest_features(df)
    if x is None:
        return None
    try:
        xs = bundle["scaler"].transform(x)
        return float(bundle["model"].predict_proba(xs)[0][1])
    except Exception:  # noqa: BLE001
        return None


def main(argv=None) -> int:
    import sys
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass
    ap = argparse.ArgumentParser(description="Train Athena on history, test her honestly")
    ap.add_argument("--symbols", default="AAPL,MSFT,NVDA,AMZN,GOOGL")
    ap.add_argument("--period", default="2y")
    ap.add_argument("--interval", default="1d")
    ap.add_argument("--horizon", type=int, default=5, help="bars ahead to predict")
    ap.add_argument("--save", action="store_true", help="save the model IF it has a real edge")
    args = ap.parse_args(argv)

    from data_market_api import MarketDataClient, MarketAPIError
    market = MarketDataClient()
    frames = []
    for sym in [s.strip() for s in args.symbols.split(",") if s.strip()]:
        try:
            frames.append(market.get_candles(sym, period=args.period, interval=args.interval))
            print(f"  fetched {sym}")
        except (MarketAPIError, Exception) as e:  # noqa: BLE001
            print(f"  [{sym}] skipped: {e}")
    if not frames:
        print("No data fetched.")
        return 2

    df = pd.concat(frames, ignore_index=True)
    print(f"\nTraining on {len(df)} bars, predicting {args.horizon} bars ahead ...\n")
    result = train_and_validate(df, horizon=args.horizon)
    print("  " + result.verdict())
    if args.save:
        saved = save_model(result)
        print("  saved to " + saved if saved else
              "  NOT saved — a model with no out-of-sample edge is not wired in.")
    print("\n  (Honest test. Even a pass is evidence, not a promise — paper-trade first.)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
