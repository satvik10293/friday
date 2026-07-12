"""
market_simulator.py
Drop-in market data simulator for testing the trading_ai pipeline when real
markets are closed. Mimics a MarketAPI.get_quote()-style interface and adds
rolling technical indicators computed purely from the simulated price/volume
stream (no external data needed).

CLI:
    python market_simulator.py --symbol AAPL --scenario breakout --ticks 60 --interval 1 --seed 42

Scenarios: uptrend, downtrend, choppy, breakout, reversal, crash, volatile
"""

import argparse
import math
import random
import time
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Deque, Dict, List, Optional, Tuple


# --------------------------------------------------------------------------- #
# Quote
# --------------------------------------------------------------------------- #

@dataclass
class Quote:
    symbol: str
    price: float
    change_pct: float
    volume: int
    high: float
    low: float
    timestamp: str


# --------------------------------------------------------------------------- #
# Technical indicators - pure functions, operate on plain lists
# --------------------------------------------------------------------------- #

def sma(values: List[float], period: int) -> Optional[float]:
    if len(values) < period:
        return None
    return sum(values[-period:]) / period


def ema_series(values: List[float], period: int) -> List[float]:
    if not values:
        return []
    k = 2 / (period + 1)
    out = [values[0]]
    for v in values[1:]:
        out.append(v * k + out[-1] * (1 - k))
    return out


def ema(values: List[float], period: int) -> Optional[float]:
    if len(values) < period:
        return None
    return ema_series(values, period)[-1]


def rsi(values: List[float], period: int = 14) -> Optional[float]:
    if len(values) < period + 1:
        return None
    window = values[-(period + 1):]
    gains, losses = 0.0, 0.0
    for i in range(1, len(window)):
        delta = window[i] - window[i - 1]
        if delta >= 0:
            gains += delta
        else:
            losses -= delta
    avg_gain = gains / period
    avg_loss = losses / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def macd(
    values: List[float], fast: int = 12, slow: int = 26, signal: int = 9
) -> Tuple[Optional[float], Optional[float], Optional[float]]:
    if len(values) < slow + signal:
        return None, None, None
    fast_e = ema_series(values, fast)
    slow_e = ema_series(values, slow)
    n = min(len(fast_e), len(slow_e))
    macd_line = [fast_e[-n:][i] - slow_e[-n:][i] for i in range(n)]
    signal_line = ema_series(macd_line, signal)
    macd_val = macd_line[-1]
    signal_val = signal_line[-1]
    return macd_val, signal_val, macd_val - signal_val


def bollinger_bands(
    values: List[float], period: int = 20, num_std: float = 2.0
) -> Tuple[Optional[float], Optional[float], Optional[float]]:
    if len(values) < period:
        return None, None, None
    window = values[-period:]
    mid = sum(window) / period
    variance = sum((v - mid) ** 2 for v in window) / period
    std = math.sqrt(variance)
    return mid + num_std * std, mid, mid - num_std * std


def atr(
    highs: List[float], lows: List[float], closes: List[float], period: int = 14
) -> Optional[float]:
    if len(closes) < period + 1:
        return None
    trs = []
    for i in range(1, len(closes)):
        tr = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1]),
        )
        trs.append(tr)
    return sum(trs[-period:]) / period


def stochastic_oscillator(
    highs: List[float], lows: List[float], closes: List[float], period: int = 14
) -> Tuple[Optional[float], None]:
    if len(closes) < period:
        return None, None
    window_high = max(highs[-period:])
    window_low = min(lows[-period:])
    if window_high == window_low:
        k = 50.0
    else:
        k = (closes[-1] - window_low) / (window_high - window_low) * 100
    return k, None  # %D left to caller (rolling avg of %K) if needed


def vwap(closes: List[float], volumes: List[float]) -> Optional[float]:
    if not closes or not volumes or len(closes) != len(volumes):
        return None
    total_vol = sum(volumes)
    if total_vol == 0:
        return None
    return sum(c * v for c, v in zip(closes, volumes)) / total_vol


# --------------------------------------------------------------------------- #
# Full-history "series" variants - same math as above, but return one value
# per tick (None where there isn't enough history yet) for charting.
# --------------------------------------------------------------------------- #

def sma_series(values: List[float], period: int) -> List[Optional[float]]:
    out: List[Optional[float]] = []
    for i in range(len(values)):
        if i + 1 < period:
            out.append(None)
        else:
            out.append(sum(values[i + 1 - period: i + 1]) / period)
    return out


def rsi_series(values: List[float], period: int = 14) -> List[Optional[float]]:
    out: List[Optional[float]] = []
    for i in range(len(values)):
        out.append(rsi(values[: i + 1], period))
    return out


def bollinger_series(
    values: List[float], period: int = 20, num_std: float = 2.0
) -> Dict[str, List[Optional[float]]]:
    upper: List[Optional[float]] = []
    mid: List[Optional[float]] = []
    lower: List[Optional[float]] = []
    for i in range(len(values)):
        u, m, l = bollinger_bands(values[: i + 1], period, num_std)
        upper.append(u)
        mid.append(m)
        lower.append(l)
    return {"upper": upper, "mid": mid, "lower": lower}


# --------------------------------------------------------------------------- #
# Scenario engine
# --------------------------------------------------------------------------- #

SCENARIOS = ("uptrend", "downtrend", "choppy", "breakout", "reversal", "crash", "volatile")


class MarketSimulator:
    """
    Generates a synthetic tick-by-tick price/volume stream and tracks rolling
    technical indicators. get_quote() mirrors a MarketAPI.get_quote(symbol)
    style interface so it can stand in for data_market_api.py when markets
    are closed.
    """

    def __init__(
        self,
        symbol: str = "SIM",
        scenario: str = "choppy",
        start_price: float = 100.0,
        seed: Optional[int] = None,
        history_len: int = 200,
    ):
        if scenario not in SCENARIOS:
            raise ValueError(f"scenario must be one of {SCENARIOS}")
        self.symbol = symbol
        self.scenario = scenario
        self.price = start_price
        self.prev_close = start_price
        self.tick = 0
        self.rng = random.Random(seed)

        self.closes: Deque[float] = deque(maxlen=history_len)
        self.highs: Deque[float] = deque(maxlen=history_len)
        self.lows: Deque[float] = deque(maxlen=history_len)
        self.volumes: Deque[float] = deque(maxlen=history_len)

        self.closes.append(self.price)
        self.highs.append(self.price)
        self.lows.append(self.price)
        self.volumes.append(self._base_volume())

        # trigger tick for breakout / reversal / crash scenarios
        self._event_tick = self.rng.randint(15, 30)
        self._event_fired = False

    # ----- internal helpers -----

    def _base_volume(self) -> int:
        return max(0, int(self.rng.gauss(5000, 1500)))

    def _drift_and_noise(self) -> Tuple[float, float]:
        """Return (drift, noise_std) for the current scenario at this tick."""
        s = self.scenario
        if s == "uptrend":
            return 0.0009, 0.0025
        if s == "downtrend":
            return -0.0009, 0.0025
        if s == "choppy":
            return 0.0, 0.0020
        if s == "volatile":
            return 0.0, 0.0080
        if s == "breakout":
            if not self._event_fired and self.tick >= self._event_tick:
                self._event_fired = True
            if self._event_fired and self.tick < self._event_tick + 8:
                return 0.012, 0.0040
            return 0.0001, 0.0018
        if s == "reversal":
            if not self._event_fired and self.tick >= self._event_tick:
                self._event_fired = True
            if self._event_fired:
                return -0.010, 0.0035
            return 0.0009, 0.0020
        if s == "crash":
            if self.tick == self._event_tick:
                return -0.045, 0.0060
            return 0.0001, 0.0022
        return 0.0, 0.0020

    # ----- public API -----

    def get_quote(self, symbol: Optional[str] = None) -> Quote:
        """Advance the simulation by one tick and return a Quote."""
        self.tick += 1
        drift, noise_std = self._drift_and_noise()
        shock = self.rng.gauss(drift, noise_std)
        self.prev_close = self.price
        self.price = max(0.01, self.price * (1 + shock))

        wick = abs(self.rng.gauss(0, noise_std)) * self.price
        high = max(self.price, self.prev_close) + wick
        low = max(0.01, min(self.price, self.prev_close) - wick)
        volume = int(self._base_volume() * (1 + abs(shock) * 40))

        self.closes.append(self.price)
        self.highs.append(high)
        self.lows.append(low)
        self.volumes.append(volume)

        change_pct = ((self.price - self.prev_close) / self.prev_close) * 100

        return Quote(
            symbol=symbol or self.symbol,
            price=self.price,
            change_pct=change_pct,
            volume=volume,
            high=high,
            low=low,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )

    def get_indicators(self) -> Dict[str, Optional[float]]:
        """Compute the current set of technical indicators from history so far."""
        closes = list(self.closes)
        highs = list(self.highs)
        lows = list(self.lows)
        volumes = list(self.volumes)

        macd_val, macd_signal, macd_hist = macd(closes)
        bb_upper, bb_mid, bb_lower = bollinger_bands(closes)
        stoch_k, _ = stochastic_oscillator(highs, lows, closes)

        return {
            "sma20": sma(closes, 20),
            "sma50": sma(closes, 50),
            "ema12": ema(closes, 12),
            "ema26": ema(closes, 26),
            "rsi14": rsi(closes, 14),
            "macd": macd_val,
            "macd_signal": macd_signal,
            "macd_hist": macd_hist,
            "bb_upper": bb_upper,
            "bb_mid": bb_mid,
            "bb_lower": bb_lower,
            "atr14": atr(highs, lows, closes, 14),
            "stoch_k": stoch_k,
            "vol_sma20": sma(volumes, 20),
            "vwap": vwap(closes, volumes),
        }

    def reset(self, start_price: Optional[float] = None) -> None:
        self.__init__(
            symbol=self.symbol,
            scenario=self.scenario,
            start_price=start_price or self.price,
            seed=None,
            history_len=self.closes.maxlen,
        )


# --------------------------------------------------------------------------- #
# Plotting
# --------------------------------------------------------------------------- #

def plot_simulation(
    symbol: str,
    scenario: str,
    ticks: int,
    start_price: float = 100.0,
    seed: Optional[int] = None,
    save_path: Optional[str] = None,
    show: bool = False,
) -> str:
    """Run a simulation and render price+SMA20+Bollinger, RSI, and volume panels."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    sim = MarketSimulator(symbol=symbol, scenario=scenario, start_price=start_price, seed=seed)
    for _ in range(ticks):
        sim.get_quote()

    closes = list(sim.closes)
    volumes = list(sim.volumes)
    x = list(range(len(closes)))

    nan = float("nan")
    sma20 = [v if v is not None else nan for v in sma_series(closes, 20)]
    bb_raw = bollinger_series(closes, 20, 2.0)
    bb_upper = [v if v is not None else nan for v in bb_raw["upper"]]
    bb_lower = [v if v is not None else nan for v in bb_raw["lower"]]
    rsi_vals = [v if v is not None else nan for v in rsi_series(closes, 14)]

    fig, (ax_price, ax_rsi, ax_vol) = plt.subplots(
        3, 1, figsize=(10, 8), sharex=True, gridspec_kw={"height_ratios": [3, 1, 1]}
    )

    ax_price.plot(x, closes, color="#0F6E56", linewidth=1.5, label="Close")
    ax_price.plot(x, sma20, color="#854F0B", linewidth=1.2, linestyle="--", label="SMA20")
    ax_price.fill_between(
        x, bb_lower, bb_upper, color="#378ADD", alpha=0.12, label="Bollinger band"
    )
    ax_price.set_title(f"{symbol} - {scenario} scenario simulation")
    ax_price.set_ylabel("Price")
    ax_price.legend(loc="upper left", fontsize=8)
    ax_price.grid(alpha=0.2)

    ax_rsi.plot(x, rsi_vals, color="#534AB7", linewidth=1.2, label="RSI14")
    ax_rsi.axhline(70, color="#A32D2D", linestyle="--", linewidth=0.8)
    ax_rsi.axhline(30, color="#3B6D11", linestyle="--", linewidth=0.8)
    ax_rsi.set_ylim(0, 100)
    ax_rsi.set_ylabel("RSI")
    ax_rsi.grid(alpha=0.2)

    bar_colors = ["#888780"] + [
        "#639922" if closes[i] >= closes[i - 1] else "#E24B4A" for i in range(1, len(closes))
    ]
    ax_vol.bar(x, volumes, color=bar_colors, width=0.8)
    ax_vol.set_ylabel("Volume")
    ax_vol.set_xlabel("Tick")
    ax_vol.grid(alpha=0.2)

    fig.tight_layout()
    out_path = save_path or f"simulation_{symbol}_{scenario}.png"
    fig.savefig(out_path, dpi=130)
    if show:
        plt.show()
    plt.close(fig)
    return out_path


# --------------------------------------------------------------------------- #
# Biotech/pharma phase engine - the demo market's own behavior, no manual
# scenario picking. Long quiet accumulation, rumor-driven climbs, then a
# binary FDA-style event (rocket or implosion), then a cooldown - repeating
# on its own for as long as the chart runs.
# --------------------------------------------------------------------------- #

PHASES = ("accumulation", "clinical_trial_hype", "fda_binary_event", "correction")


class BiotechPhaseEngine:
    """Self-driving price engine modeled on small-cap biotech/pharma price
    action (e.g. Summit Therapeutics-style SMMT moves): long flat ranges,
    hype-driven run-ups, and sudden binary readouts that either rocket or
    implode the stock - entirely autonomous, no scenario input needed."""

    def __init__(self, base_price: float = 12.50, bar_minutes: int = 1, seed: Optional[int] = None):
        self.rng = random.Random(seed)
        self.price = base_price
        self.history: List[float] = []
        self.volumes: List[int] = []
        self.times: List[datetime] = []
        self.current_time = datetime.now()
        self.bar_minutes = bar_minutes
        self.phase = "accumulation"
        self.phase_ticks_left = self.rng.randint(30, 50)

    def tick(self) -> Tuple[float, datetime]:
        self.phase_ticks_left -= 1
        if self.phase_ticks_left <= 0:
            self.phase = self.rng.choice(PHASES)
            self.phase_ticks_left = self.rng.randint(20, 60)

        noise = self.rng.gauss(0, 0.15)
        if self.phase == "accumulation":
            move = self.rng.uniform(-0.08, 0.08)
        elif self.phase == "clinical_trial_hype":
            move = self.rng.uniform(0.05, 0.45)
        elif self.phase == "fda_binary_event":
            move = self.rng.uniform(2.0, 5.0) if self.rng.random() > 0.45 else self.rng.uniform(-4.0, -1.5)
            self.phase = "correction"
        else:  # correction
            move = self.rng.uniform(-0.2, 0.1)

        self.price = max(0.50, self.price + move + noise)
        self.current_time += timedelta(minutes=self.bar_minutes)
        volume = max(1000, int(self.rng.gauss(50000, 15000) * (1 + abs(move) * 2)))
        self.history.append(self.price)
        self.volumes.append(volume)
        self.times.append(self.current_time)
        return self.price, self.current_time


# --------------------------------------------------------------------------- #
# Live interactive simulator - single price+SMA line, real time/price axis
# labels like a brokerage app, Buy/Sell/Close/Pause only (the market's own
# behavior is autonomous - nothing to pick).
# --------------------------------------------------------------------------- #

def run_interactive(
    symbol: str = "SMMT",
    start_price: float = 12.50,
    window: int = 60,
    interval_ms: int = 1500,
    qty: int = 100,
) -> None:
    """Open a live matplotlib window styled like a real trading app: one
    price line with an SMA20 overlay, real price labels on the left and
    real bar timestamps along the bottom, advancing bar-by-bar (not rapid
    ticking). The market follows its own biotech-style phases - there is no
    scenario picker. Buy/Sell/Close/Pause trade the tape and track P&L."""
    import matplotlib.pyplot as plt
    from matplotlib.animation import FuncAnimation
    from matplotlib.widgets import Button

    engine = BiotechPhaseEngine(base_price=start_price)
    for _ in range(40):  # prime history so SMA20 renders from the first frame shown
        engine.tick()

    state = {"position": None, "realized": 0.0, "playing": True}

    plt.style.use("dark_background")
    fig = plt.figure(figsize=(11, 7.5))
    gs = fig.add_gridspec(2, 1, height_ratios=[3, 1], hspace=0.12)
    ax = fig.add_subplot(gs[0])
    ax_vol = fig.add_subplot(gs[1])
    fig.canvas.manager.set_window_title(f"{symbol} - simulated live feed")
    fig.subplots_adjust(left=0.09, right=0.97, top=0.86, bottom=0.22)

    line_close, = ax.plot([], [], color="#26a69a", linewidth=1.6, label="Price")
    line_sma, = ax.plot([], [], color="#ff9800", linestyle="--", linewidth=1.1, label="SMA20")
    ax.legend(loc="upper left", fontsize=8)
    ax.set_ylabel("Price ($)", fontsize=10, color="#9e9e9e")
    ax.yaxis.tick_left()
    ax.yaxis.set_label_position("left")
    ax.grid(alpha=0.2)
    ax.set_xticks([])

    ax_vol.set_ylabel("Volume", fontsize=10, color="#9e9e9e")
    ax_vol.grid(alpha=0.2)

    status_text = fig.text(0.09, 0.93, "", fontsize=10, color="#ffffff")
    pnl_text = fig.text(0.09, 0.90, "", fontsize=10, fontweight="bold")

    ax_buy = fig.add_axes([0.30, 0.06, 0.12, 0.06])
    ax_sell = fig.add_axes([0.44, 0.06, 0.12, 0.06])
    ax_close = fig.add_axes([0.58, 0.06, 0.15, 0.06])
    ax_pause = fig.add_axes([0.75, 0.06, 0.12, 0.06])
    btn_buy = Button(ax_buy, "Buy long", color="#2e7d32", hovercolor="#1b5e20")
    btn_sell = Button(ax_sell, "Sell short", color="#c62828", hovercolor="#b71c1c")
    btn_close = Button(ax_close, "Close position", color="#37474f", hovercolor="#455a64")
    btn_pause = Button(ax_pause, "Pause", color="#ef6c00", hovercolor="#e65100")

    def on_buy(_event):
        if state["position"] is None:
            state["position"] = {"side": "long", "entry": engine.price}

    def on_sell(_event):
        if state["position"] is None:
            state["position"] = {"side": "short", "entry": engine.price}

    def on_close(_event):
        pos = state["position"]
        if pos:
            pnl = (
                (engine.price - pos["entry"]) * qty
                if pos["side"] == "long"
                else (pos["entry"] - engine.price) * qty
            )
            state["realized"] += pnl
            state["position"] = None

    def on_pause(_event):
        state["playing"] = not state["playing"]
        btn_pause.label.set_text("Resume" if not state["playing"] else "Pause")

    btn_buy.on_clicked(on_buy)
    btn_sell.on_clicked(on_sell)
    btn_close.on_clicked(on_close)
    btn_pause.on_clicked(on_pause)

    def update(_frame):
        if state["playing"]:
            engine.tick()

        prices = engine.history[-window:]
        volumes = engine.volumes[-window:]
        times = engine.times[-window:]
        sma_full = sma_series(engine.history, 20)
        sma_win = [v if v is not None else float("nan") for v in sma_full[-window:]]

        xs = range(len(prices))
        line_close.set_data(xs, prices)
        line_sma.set_data(xs, sma_win)

        ax.set_xlim(0, max(1, len(prices) - 1))
        ax.set_ylim(min(prices) * 0.95, max(prices) * 1.05)

        ax_vol.clear()
        full_hist = engine.history
        start = len(full_hist) - len(prices)
        colors = [
            "#26a69a" if full_hist[start + i] >= (full_hist[start + i - 1] if start + i > 0 else full_hist[start + i]) else "#ef5350"
            for i in range(len(prices))
        ]
        ax_vol.bar(xs, volumes, color=colors, width=0.8)
        ax_vol.set_ylabel("Volume", fontsize=10, color="#9e9e9e")
        ax_vol.grid(alpha=0.2)
        step = max(1, len(prices) // 6)
        tick_pos = list(range(0, len(prices), step))
        ax_vol.set_xticks(tick_pos)
        ax_vol.set_xticklabels([times[i].strftime("%H:%M:%S") for i in tick_pos], rotation=15, fontsize=9)

        price = engine.price
        prev = engine.history[-2] if len(engine.history) > 1 else price
        change_pct = ((price - prev) / prev) * 100 if prev else 0.0
        status_text.set_text(
            f"{symbol}   price ${price:.2f}   change {change_pct:+.2f}%   phase {engine.phase.replace('_', ' ')}"
        )

        pos = state["position"]
        if pos:
            unreal = (
                (price - pos["entry"]) * qty
                if pos["side"] == "long"
                else (pos["entry"] - price) * qty
            )
            pnl_text.set_text(f"{pos['side'].upper()} @ ${pos['entry']:.2f}   open P&L ${unreal:+.2f}")
            pnl_text.set_color("#26a69a" if unreal >= 0 else "#ef5350")
        else:
            pnl_text.set_text(f"flat   realized P&L ${state['realized']:+.2f}")
            pnl_text.set_color(
                "#26a69a" if state["realized"] > 0 else "#ef5350" if state["realized"] < 0 else "#9e9e9e"
            )

        return line_close, line_sma

    ani = FuncAnimation(fig, update, interval=interval_ms, cache_frame_data=False)
    fig._sim_animation = ani  # keep a reference alive
    plt.show()


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

def _fmt(v: Optional[float]) -> str:
    return "n/a" if v is None else f"{v:.4f}"


def main() -> None:
    parser = argparse.ArgumentParser(description="Simulate a live market feed for trading_ai.")
    parser.add_argument("--symbol", default="AAPL")
    parser.add_argument("--scenario", choices=SCENARIOS, default="choppy")
    parser.add_argument("--start-price", type=float, default=100.0)
    parser.add_argument("--ticks", type=int, default=40)
    parser.add_argument("--interval", type=float, default=1.0)
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument("--plot", action="store_true", help="Render a price/RSI/volume chart instead of printing ticks")
    parser.add_argument("--save-plot", default=None, help="Output path for --plot (default: simulation_<symbol>_<scenario>.png)")
    parser.add_argument("--interactive", action="store_true", help="Open a live chart with Buy/Sell/Close buttons; market follows its own biotech-style phases, nothing to pick")
    parser.add_argument("--window", type=int, default=60, help="Number of bars shown on screen at once (--interactive)")
    parser.add_argument("--qty", type=int, default=100, help="Shares per trade (--interactive)")
    parser.add_argument("--interval-ms", type=int, default=1500, help="Milliseconds between bars (--interactive, bar-by-bar pace)")
    args = parser.parse_args()

    if args.interactive:
        run_interactive(
            symbol=args.symbol,
            start_price=args.start_price,
            window=args.window,
            interval_ms=args.interval_ms,
            qty=args.qty,
        )
        return

    if args.plot:
        path = plot_simulation(
            symbol=args.symbol,
            scenario=args.scenario,
            ticks=args.ticks,
            start_price=args.start_price,
            seed=args.seed,
            save_path=args.save_plot,
        )
        print(f"Saved chart to {path}")
        return

    sim = MarketSimulator(
        symbol=args.symbol,
        scenario=args.scenario,
        start_price=args.start_price,
        seed=args.seed,
    )

    print(f"Simulating {args.symbol} | scenario={args.scenario} | {args.ticks} ticks")
    for _ in range(args.ticks):
        q = sim.get_quote()
        ind = sim.get_indicators()
        print(
            f"[Sim] {q.symbol}: {q.price:.4f} (Δ {q.change_pct:+.3f}%) vol={q.volume} | "
            f"SMA20={_fmt(ind['sma20'])} RSI14={_fmt(ind['rsi14'])} "
            f"MACD={_fmt(ind['macd'])}/{_fmt(ind['macd_signal'])} "
            f"BB=[{_fmt(ind['bb_lower'])},{_fmt(ind['bb_mid'])},{_fmt(ind['bb_upper'])}] "
            f"ATR14={_fmt(ind['atr14'])} Stoch%K={_fmt(ind['stoch_k'])}"
        )
        if args.interval > 0:
            time.sleep(args.interval)


if __name__ == "__main__":
    main()