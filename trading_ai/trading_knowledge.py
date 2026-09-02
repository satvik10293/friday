"""
trading_ai/trading_knowledge.py — Athena's trading playbook.

signals_catalog.py DETECTS signals; this module EXPLAINS them: for every
indicator, trend, candlestick, and chart pattern — what it is, *why* it happens
(the crowd psychology / mechanics behind it), and how to trade it (entry,
take-profit, stop-loss). Plus a risk-management section: how to actually take
profit and cut losses.

It is knowledge, not a promise. Every setup is probabilistic; the edge is taking
good setups with defined risk, again and again. Query it:

    explain("RSI")            -> Lesson
    teach("hammer")           -> spoken-style explanation (what/why/entry/stop)
    by_category("candlestick")-> [Lesson]
    catalog()                 -> every name she knows
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

BULL, BEAR, NEUTRAL = 1, -1, 0


@dataclass
class Lesson:
    name: str
    category: str                 # indicator | trend | candlestick | chart_pattern | risk
    what: str
    why: str                      # why it happens — the psychology / mechanics
    entry: str = ""               # how to enter for profit
    profit: str = ""              # how to take profit / target
    stop: str = ""                # where the stop-loss goes
    apply: str = ""               # for craft lessons: what to actually DO about it
    bias: int = NEUTRAL
    reliability: str = ""
    aka: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        d = dict(self.__dict__)
        return d

    def teach(self) -> str:
        lines = [f"{self.name} ({self.category})", f"What: {self.what}", f"Why: {self.why}"]
        if self.entry:
            lines.append(f"Entry: {self.entry}")
        if self.profit:
            lines.append(f"Take profit: {self.profit}")
        if self.stop:
            lines.append(f"Stop-loss: {self.stop}")
        if self.apply:
            lines.append(f"Do: {self.apply}")
        if self.reliability:
            lines.append(f"Reliability: {self.reliability}")
        return "\n".join(lines)


# ── indicators ────────────────────────────────────────────────────────────────

_INDICATORS = [
    Lesson("RSI", "indicator",
           "Relative Strength Index (0-100) — speed and size of recent gains vs losses.",
           "Above 70 means buyers have pushed hard and may be exhausted; below 30 means "
           "sellers may be exhausted. Extremes reflect crowd emotion overshooting.",
           entry="In an uptrend, buy pullbacks as RSI turns up from ~40-50; oversold <30 "
                 "hints at a bounce (confirm with price).",
           profit="Trim into overbought >70 or at the next resistance.",
           stop="Below the swing low that produced the oversold reading.",
           reliability="Best as confluence, not alone; can stay 'overbought' in strong trends."),
    Lesson("RSI divergence", "indicator",
           "Price makes a new high/low but RSI does not.",
           "Momentum is fading even as price extends — the move is running on fewer "
           "participants, warning of a turn.",
           entry="Enter on the reversal confirmation candle after the divergence.",
           profit="Prior swing / structure level.",
           stop="Beyond the extreme that made the divergence.",
           reliability="Stronger on higher timeframes."),
    Lesson("MACD", "indicator",
           "Moving Average Convergence Divergence — the 12- vs 26-EMA gap and its 9-EMA signal line.",
           "It measures whether short-term momentum is pulling away from or back toward "
           "the longer trend; crossovers mark momentum shifting hands.",
           entry="Buy when MACD crosses above its signal line (bullish cross), ideally above zero.",
           profit="Exit or trail when it crosses back below the signal line.",
           stop="Below the recent swing low.",
           reliability="Lags; whipsaws in choppy ranges."),
    Lesson("moving average", "indicator",
           "The average price over N bars (SMA = simple, EMA = weights recent bars more).",
           "It smooths noise into the underlying direction; price tends to respect widely-"
           "watched averages (20/50/200) because so many traders act on them.",
           entry="Buy pullbacks to a rising MA; the 200-MA separates bull/bear regimes.",
           profit="Next resistance or a break back below the MA.",
           stop="A decisive close on the far side of the MA.",
           aka=["SMA", "EMA", "MA"]),
    Lesson("golden cross / death cross", "indicator",
           "The 50-MA crossing above (golden) or below (death) the 200-MA.",
           "A slow, high-conviction signal that the medium-term average has overtaken the "
           "long-term one — a regime shift many funds trade.",
           entry="Golden cross = trend-follow long; death cross = stand aside / short.",
           profit="Trail with the 50-MA.",
           stop="A close back through the crossed average.",
           reliability="Late but reliable on indices/large caps."),
    Lesson("Bollinger Bands", "indicator",
           "A 20-MA with bands at ±2 standard deviations.",
           "Price is statistically ~95% likely to sit inside the bands; a squeeze (narrow "
           "bands) means volatility is coiled and a big move is near.",
           entry="Trade the expansion out of a squeeze in the breakout's direction; in a "
                 "range, fade touches of the outer band back to the middle.",
           profit="Opposite band or the middle band.",
           stop="Just outside the band you entered against.",
           reliability="A band touch is not a signal by itself — pair with trend."),
    Lesson("Stochastic", "indicator",
           "Where price closed within its recent high-low range (%K and %D lines, 0-100).",
           "Closing near the top of the range shows strength, near the bottom weakness; "
           "turns from extremes catch short-term exhaustion.",
           entry="Buy when %K turns up from below 20 and crosses %D.",
           profit="Overbought >80 or next resistance.",
           stop="Below the local low."),
    Lesson("ADX", "indicator",
           "Average Directional Index (0-100) — trend STRENGTH, not direction.",
           "Rising ADX above 25 means a real trend is in force (worth trend-following); "
           "below 20 means chop where breakouts fail.",
           entry="Only take trend setups when ADX ≥ 25; avoid breakouts when ADX is low.",
           profit="While ADX rises, hold; falling ADX = trend tiring, tighten up.",
           stop="Structure-based (see stop-loss lesson)."),
    Lesson("ATR", "indicator",
           "Average True Range — the average size of a bar's move (volatility).",
           "It tells you how much this instrument normally moves, so stops and targets fit "
           "reality instead of being too tight (stopped by noise) or too wide.",
           entry="Not an entry tool.",
           profit="Set targets as a multiple of ATR (e.g. 2-3x).",
           stop="Place stops ~1.5-2x ATR from entry so normal noise doesn't hit them."),
    Lesson("volume", "indicator",
           "How many shares/contracts traded in a bar.",
           "Volume is conviction: a move on high volume has real participation behind it; a "
           "breakout on low volume is suspect and often fails.",
           entry="Favor breakouts confirmed by a volume surge.",
           profit="Watch for a volume climax (exhaustion) to take profit.",
           stop="Below the breakout base if volume doesn't follow."),
    Lesson("OBV", "indicator",
           "On-Balance Volume — a running total that adds volume on up days, subtracts on down days.",
           "It reveals whether volume is quietly accumulating (smart money buying) or "
           "distributing before price shows it.",
           entry="Rising OBV while price ranges hints at accumulation → prepare to buy the breakout.",
           profit="OBV rolling over ahead of price.",
           stop="Structure-based."),
    Lesson("VWAP", "indicator",
           "Volume-Weighted Average Price — the average price weighted by volume, intraday.",
           "It's the day's 'fair value' that institutions benchmark against; price above VWAP "
           "= buyers in control intraday, below = sellers.",
           entry="Day-trade long above VWAP on a reclaim; short below on a rejection.",
           profit="Prior high/low or a VWAP band.",
           stop="The far side of VWAP.",
           reliability="Intraday tool; resets each session."),
    Lesson("Fibonacci retracement", "indicator",
           "Horizontal levels (38.2%, 50%, 61.8%) of a prior move where pullbacks often pause.",
           "Not magic — so many traders place orders at these ratios that they become self-"
           "fulfilling support/resistance.",
           entry="Buy a pullback into 50-61.8% of an up-move with a reversal candle.",
           profit="Prior high (0% level) or extensions (1.272, 1.618).",
           stop="Below the 78.6% level (if it breaks, the move is likely over)."),
    Lesson("Ichimoku cloud", "indicator",
           "A system whose 'cloud' (Kumo) projects support/resistance and trend at a glance.",
           "Price above a rising cloud = bullish regime; inside the cloud = no-man's-land "
           "where trends are unclear.",
           entry="Trade in the cloud's direction only when price is clear of it.",
           profit="Opposite edge of a widening cloud.",
           stop="Back inside the cloud."),
    Lesson("Parabolic SAR", "indicator",
           "Dots that flip above/below price to mark trend and trailing stops.",
           "It assumes a trend accelerates; the flip marks momentum reversing.",
           entry="Enter when dots flip to the price's favored side in a trending market.",
           profit="Trail the stop on the SAR dots.",
           stop="The current SAR dot.",
           reliability="Whipsaws badly in ranges."),
    Lesson("CCI", "indicator",
           "Commodity Channel Index — how far price is from its average, measured in typical deviations.",
           "Above +100 is unusually stretched up (strong or overbought), below -100 unusually stretched down (weak or oversold).",
           entry="Fade extremes back toward zero in a range, or treat a cross above +100 as trend strength.",
           profit="A return to the zero line.",
           stop="Beyond the extreme that triggered you.",
           reliability="Best as a confirmation, not alone."),
    Lesson("Williams %R", "indicator",
           "Where the close sits in its recent range, from 0 (top) to -100 (bottom) — an inverted Stochastic.",
           "Above -20 is overbought, below -80 oversold — a short-term exhaustion read.",
           entry="Buy a turn up from below -80; sell a turn down from above -20.",
           profit="Mid-range or the next level.",
           stop="Just beyond the local extreme.",
           reliability="Noisy in strong trends — pair with the trend."),
]

# ── trend types ───────────────────────────────────────────────────────────────

_TRENDS = [
    Lesson("uptrend", "trend",
           "A sequence of higher highs and higher lows.",
           "Buyers keep stepping in earlier each dip — demand outweighs supply, so each "
           "pullback bottoms higher.", bias=BULL,
           entry="Buy pullbacks to support / a rising MA, not chases at the highs.",
           profit="Trail under each higher low; exit when a higher low breaks.",
           stop="Below the most recent higher low."),
    Lesson("downtrend", "trend",
           "A sequence of lower highs and lower lows.",
           "Sellers keep hitting bids earlier on each bounce — supply outweighs demand.",
           bias=BEAR,
           entry="Short bounces into resistance / a falling MA.",
           profit="Trail above each lower high; cover when a lower high breaks.",
           stop="Above the most recent lower high."),
    Lesson("range / sideways", "trend",
           "Price oscillating between horizontal support and resistance.",
           "Buyers and sellers are in balance; no side has control, so price ping-pongs.",
           bias=NEUTRAL,
           entry="Buy support, sell resistance — fade the edges.",
           profit="The opposite edge of the range.",
           stop="Just outside the range edge you entered at (a break = the range is over).",
           reliability="Avoid the middle of the range — it's noise."),
    Lesson("breakout", "trend",
           "Price forcing through a level that has held, on volume.",
           "Stops and breakout orders beyond the level trigger a cascade, and trapped "
           "traders on the wrong side add fuel.", bias=NEUTRAL,
           entry="Enter on the breakout close (or the retest of the broken level).",
           profit="Measured move = the range height projected from the breakout.",
           stop="Back inside the level (a failed breakout / 'fakeout')."),
    Lesson("pullback / retracement", "trend",
           "A temporary counter-move within a larger trend.",
           "Early buyers take profit and new buyers wait for a better price; the trend "
           "pauses, then resumes.", bias=NEUTRAL,
           entry="Buy the dip to support/MA/Fib in an uptrend, once it shows a turn.",
           profit="Prior swing high.",
           stop="Below the pullback low (if it breaks, it's not a pullback — it's a reversal)."),
    Lesson("reversal", "trend",
           "A trend ending and turning the other way.",
           "The dominant side runs out of new participants; a reversal pattern + divergence "
           "+ a broken structure mark the handover.", bias=NEUTRAL,
           entry="Wait for confirmation (structure break + reversal candle) — don't guess the top/bottom.",
           profit="The prior trend's structure levels.",
           stop="Beyond the reversal extreme.",
           reliability="Reversals are lower-odds than continuations — demand confirmation."),
    Lesson("consolidation", "trend",
           "A tight pause (flag/coil) after a strong move.",
           "The market digests a move as winners rest and latecomers position; energy "
           "builds for continuation.", bias=NEUTRAL,
           entry="Enter the breakout of the consolidation in the prior trend's direction.",
           profit="Measured move of the pole before the consolidation.",
           stop="The far side of the consolidation."),
]

# ── candlesticks (why the wick/body means what it means) ──────────────────────

_CANDLES = [
    Lesson("doji", "candlestick",
           "Open and close almost equal — a tiny body with wicks.",
           "Buyers and sellers fought to a draw; conviction vanished. After a strong move "
           "it warns the trend may pause or turn.", bias=NEUTRAL,
           entry="Trade the break of the doji's high (bull) or low (bear) in context.",
           profit="Next structure level.", stop="Opposite end of the doji."),
    Lesson("hammer", "candlestick",
           "Small body up top, long lower wick, at the bottom of a decline.",
           "Sellers drove price down but buyers slammed it back up by the close — demand "
           "just overwhelmed supply at the lows.", bias=BULL,
           entry="Buy the break of the hammer's high, confirming buyers followed through.",
           profit="Prior resistance / measured bounce.",
           stop="Below the hammer's low (buyers failed if that breaks).",
           reliability="Stronger at support and on volume."),
    Lesson("hanging man", "candlestick",
           "Same shape as a hammer but at the TOP of a rally.",
           "Buyers were tested and price recovered, but the deep intrabar sell-off shows "
           "supply arriving after a long climb.", bias=BEAR,
           entry="Short the break of its low.", profit="Prior support.",
           stop="Above the candle's high."),
    Lesson("shooting star", "candlestick",
           "Small body down low, long upper wick, at the top of a rally.",
           "Buyers pushed to new highs and were violently rejected — sellers took control "
           "into the close.", bias=BEAR,
           entry="Short the break of its low.", profit="Prior support/level.",
           stop="Above the upper wick."),
    Lesson("inverted hammer", "candlestick",
           "Long upper wick, small body, at the bottom of a decline.",
           "Buyers attempted a rally; even though they faded, the attempt after a downtrend "
           "hints sellers are weakening.", bias=BULL,
           entry="Buy confirmation the next candle.", profit="Prior resistance.",
           stop="Below the candle's low."),
    Lesson("marubozu", "candlestick",
           "A full-body candle with little or no wick.",
           "One side dominated the entire session end to end — pure conviction and "
           "continuation pressure.", bias=NEUTRAL,
           entry="Trade in the marubozu's direction on the next open.",
           profit="Next level.", stop="The candle's midpoint or opposite end."),
    Lesson("spinning top", "candlestick",
           "Small body with wicks on both sides.",
           "Lots of movement, no resolution — indecision, often a pause before continuation "
           "or a warning near a turn.", bias=NEUTRAL,
           entry="Wait for the next candle to pick a side.", stop="Opposite side of the range."),
    Lesson("bullish engulfing", "candlestick",
           "An up candle whose body fully engulfs the prior down candle.",
           "Buyers didn't just show up — they erased an entire session of selling in one "
           "bar. A decisive shift of control.", bias=BULL,
           entry="Buy the close of the engulfing candle or a small pullback.",
           profit="Prior resistance.", stop="Below the engulfing candle's low.",
           reliability="Strong at support / after a clean downtrend."),
    Lesson("bearish engulfing", "candlestick",
           "A down candle whose body fully engulfs the prior up candle.",
           "Sellers overwhelmed a full session of buying in one bar — control flipped.",
           bias=BEAR,
           entry="Short the close or a small bounce.", profit="Prior support.",
           stop="Above the engulfing candle's high."),
    Lesson("bullish harami", "candlestick",
           "A small up candle contained inside the prior large down candle.",
           "Selling momentum suddenly shrank — the trend is losing steam even before it turns.",
           bias=BULL, entry="Buy confirmation above the harami.", profit="Prior resistance.",
           stop="Below the mother candle's low."),
    Lesson("bearish harami", "candlestick",
           "A small down candle inside the prior large up candle.",
           "Buying momentum suddenly shrank — a stall that often precedes a turn down.",
           bias=BEAR, entry="Short confirmation below the harami.", profit="Prior support.",
           stop="Above the mother candle's high."),
    Lesson("piercing line", "candlestick",
           "A down candle, then an up candle closing above its midpoint.",
           "Buyers gapped down into weakness and bought aggressively, recovering more than "
           "half the loss — a demand shock.", bias=BULL,
           entry="Buy the close.", profit="Prior resistance.", stop="Below the two-candle low."),
    Lesson("dark cloud cover", "candlestick",
           "An up candle, then a down candle closing below its midpoint.",
           "Sellers gapped up into strength and dumped, erasing over half the gain — a "
           "supply shock.", bias=BEAR,
           entry="Short the close.", profit="Prior support.", stop="Above the two-candle high."),
    Lesson("morning star", "candlestick",
           "Down candle → small indecision candle → strong up candle: a 3-bar bottom.",
           "Selling exhausts (the small middle candle), then buyers seize control — a "
           "classic handover at a low.", bias=BULL,
           entry="Buy the close of the third candle.", profit="Prior swing high.",
           stop="Below the star's low.", reliability="High-quality reversal at support."),
    Lesson("evening star", "candlestick",
           "Up candle → small indecision candle → strong down candle: a 3-bar top.",
           "Buying exhausts, then sellers take over — a handover at a high.", bias=BEAR,
           entry="Short the third candle's close.", profit="Prior swing low.",
           stop="Above the star's high."),
    Lesson("three white soldiers", "candlestick",
           "Three strong rising up-candles in a row.",
           "Steady, broad buying with each open near the prior close — durable demand, not a spike.",
           bias=BULL, entry="Buy pullbacks; the trend is confirmed.", profit="Trail higher lows.",
           stop="Below the first soldier."),
    Lesson("three black crows", "candlestick",
           "Three strong falling down-candles in a row.",
           "Persistent, broad selling — durable supply.", bias=BEAR,
           entry="Short bounces.", profit="Trail lower highs.", stop="Above the first crow."),
    Lesson("tweezer top / bottom", "candlestick",
           "Two candles with matched highs (top) or matched lows (bottom).",
           "Price hit the exact same level twice and was rejected — a clear line buyers or "
           "sellers are defending.", bias=NEUTRAL,
           entry="Fade the level on the reversal candle.", profit="Prior structure.",
           stop="Just beyond the matched level."),
]

# ── chart patterns ────────────────────────────────────────────────────────────

_CHART_PATTERNS = [
    Lesson("head and shoulders", "chart_pattern",
           "Three peaks — a higher middle (head) between two lower shoulders — with a neckline.",
           "Each rally makes a lower peak: buyers are weakening. The neckline break confirms "
           "sellers have won.", bias=BEAR,
           entry="Short the neckline break (or its retest).",
           profit="Neckline minus the head's height (measured move).",
           stop="Above the right shoulder.", reliability="One of the more reliable reversals."),
    Lesson("inverse head and shoulders", "chart_pattern",
           "The same shape flipped — a bottoming pattern.",
           "Each sell-off makes a higher trough: sellers are weakening; the neckline break "
           "confirms buyers.", bias=BULL,
           entry="Buy the neckline break/retest.", profit="Neckline plus the head's depth.",
           stop="Below the right shoulder."),
    Lesson("double top", "chart_pattern",
           "Two peaks at about the same level ('M').",
           "Price tested resistance twice and failed — buyers can't break it, and their "
           "failure invites sellers.", bias=BEAR,
           entry="Short the break of the valley between the peaks.",
           profit="That depth projected down.", stop="Above the peaks."),
    Lesson("double bottom", "chart_pattern",
           "Two troughs at about the same level ('W').",
           "Sellers failed twice at support — their exhaustion invites buyers.", bias=BULL,
           entry="Buy the break of the peak between the troughs.",
           profit="That height projected up.", stop="Below the troughs."),
    Lesson("ascending triangle", "chart_pattern",
           "Flat resistance with rising support (higher lows).",
           "Buyers keep paying up (higher lows) while a wall of supply sits at one price — "
           "buyers usually win and break out.", bias=BULL,
           entry="Buy the breakout above the flat top.", profit="Triangle height projected up.",
           stop="Below the last higher low."),
    Lesson("descending triangle", "chart_pattern",
           "Flat support with falling resistance (lower highs).",
           "Sellers keep pressing (lower highs) into a support floor that usually cracks.",
           bias=BEAR, entry="Short the breakdown below the flat bottom.",
           profit="Height projected down.", stop="Above the last lower high."),
    Lesson("symmetrical triangle", "chart_pattern",
           "Converging lower highs and higher lows — a coil.",
           "Both sides compress as the market waits for a catalyst; energy releases on the break.",
           bias=NEUTRAL, entry="Trade the breakout in whichever direction it resolves.",
           profit="Widest triangle height projected.", stop="The opposite side of the triangle."),
    Lesson("bull flag / bear flag", "chart_pattern",
           "A sharp move (pole), then a small counter-trend channel (flag).",
           "A strong move, a brief orderly pause as the crowd catches its breath, then "
           "continuation.", bias=NEUTRAL,
           entry="Enter the flag's breakout in the pole's direction.",
           profit="Pole height projected from the breakout.", stop="The far side of the flag.",
           reliability="High-odds continuation pattern."),
    Lesson("pennant", "chart_pattern",
           "Like a flag but the pause is a small symmetrical triangle.",
           "Same idea as a flag — a tight consolidation of a strong move before continuation.",
           bias=NEUTRAL, entry="Breakout in the trend direction.",
           profit="Pole projected.", stop="Opposite side of the pennant."),
    Lesson("rising wedge / falling wedge", "chart_pattern",
           "Converging trendlines both sloping up (rising) or down (falling).",
           "A rising wedge shows buying that narrows and tires (bearish); a falling wedge "
           "shows selling that narrows and tires (bullish).", bias=NEUTRAL,
           entry="Trade the break AGAINST the wedge's slope.",
           profit="Back to the wedge's start.", stop="Beyond the last touch inside the wedge."),
    Lesson("cup and handle", "chart_pattern",
           "A rounded 'U' base, then a small pullback (handle) near the rim.",
           "A long, patient basing that shakes out weak holders, then a final shallow dip "
           "before a breakout to new highs.", bias=BULL,
           entry="Buy the breakout above the rim/handle.", profit="Cup depth projected up.",
           stop="Below the handle low."),
    Lesson("rectangle / channel", "chart_pattern",
           "Parallel support and resistance — a trending or flat channel.",
           "Two clear boundaries the crowd trades between until one gives way.", bias=NEUTRAL,
           entry="Buy the lower rail / sell the upper rail, or trade the breakout.",
           profit="Opposite rail (range) or channel height (breakout).",
           stop="Just outside the rail you traded."),
]

# ── risk management: how to actually take profit and cut losses ───────────────

_RISK = [
    Lesson("stop-loss", "risk",
           "A pre-set exit that caps the loss on a trade.",
           "You cannot know which trades fail, so you cap every one — one big uncapped loss "
           "erases many wins. The stop is decided BEFORE you enter, never moved wider.",
           entry="Place it where your idea is proven WRONG — beyond the pattern's invalidation "
                 "point, not at a random dollar amount.",
           stop="Structure stop = beyond the swing high/low; volatility stop = ~1.5-2x ATR."),
    Lesson("take-profit", "risk",
           "A pre-set exit that banks the gain.",
           "Profits are only real when taken; greed turns winners into losers. Define the "
           "target before entering so the trade has a plan, not a hope.",
           profit="At the next major level, a measured-move target, or a fixed reward multiple; "
                  "scale out — take partial profit, trail the rest."),
    Lesson("risk-reward ratio", "risk",
           "The ratio of what you risk to what you aim to make (e.g. 1:2).",
           "With 1:2, you can be right less than half the time and still profit. Only take "
           "trades where the reward to the target is at least ~2x the risk to the stop.",
           entry="Measure entry→stop (risk) and entry→target (reward); skip setups under ~1:1.5."),
    Lesson("position sizing", "risk",
           "How many shares/contracts to trade, from your stop distance.",
           "Risk a small fixed fraction of the account per trade (commonly ~1%). Size = "
           "(account × risk%) ÷ (entry − stop). This survives losing streaks that wipe out "
           "over-sized traders.",
           entry="Set risk% and stop first; the size falls out of the math — never the reverse."),
    Lesson("trailing stop", "risk",
           "A stop that follows price as the trade moves in your favor.",
           "It lets winners run while protecting gains — you give back a little to capture "
           "the fat part of a trend instead of exiting too early.",
           profit="Trail under higher lows (long) / above lower highs (short), or on ATR/SAR."),
    Lesson("cutting losses", "risk",
           "Exiting a losing trade at the plan, without hoping.",
           "Hope is not a strategy; a small loss is a cost of business, a big loss is an "
           "account risk. The market doesn't owe you a recovery.",
           stop="Honor the stop the instant it's hit — no averaging down into a loser."),
    Lesson("expectancy", "risk",
           "The average profit per trade over many trades: (win% × avg win) − (loss% × avg loss).",
           "A method is only worth trading if its expectancy is positive across a sample — "
           "one trade proves nothing; the edge shows over dozens.",
           entry="Track it honestly in the journal; trade the setups whose expectancy is positive."),
]


# ── trading psychology ────────────────────────────────────────────────────────

_PSYCHOLOGY = [
    Lesson("fear", "psychology",
           "The urge to freeze, cut winners early, or skip a valid setup.",
           "Loss aversion — the pain of a loss feels bigger than the pleasure of an equal "
           "gain, so the brain avoids risk exactly when the plan says to take it.",
           apply="Decide the trade before the moment: fixed entry, stop and size, then "
                 "execute the rules, not the feeling."),
    Lesson("greed", "psychology",
           "The urge to oversize, chase, or hold past the target for 'more'.",
           "Euphoria after wins convinces you the edge is bigger than it is; the market "
           "hands the gains back.",
           apply="Pre-set targets and keep risk per trade constant regardless of how good "
                 "you feel."),
    Lesson("FOMO", "psychology",
           "Fear of missing out — chasing a move that already ran.",
           "Watching price rip without you triggers regret, and you buy the top just as "
           "early money takes profit.",
           apply="Wait for YOUR setup. There is always another trade; a missed one costs "
                 "nothing, a chased one costs money.", aka=["fear of missing out", "chasing"]),
    Lesson("revenge trading", "psychology",
           "Trying to win a loss straight back, usually by oversizing.",
           "The loss feels like an insult, so you abandon the plan to 'get even' — and turn "
           "one small loss into a large one.",
           apply="After a loss, step away. A loss is a business cost, not a personal debt to "
                 "collect."),
    Lesson("discipline", "psychology",
           "Following your plan whether you feel like it or not.",
           "An edge only pays out over many trades; breaking rules on the ones that 'feel' "
           "different is how the edge leaks away.",
           apply="Rules over feelings, every time. Consistency is the edge."),
    Lesson("patience", "psychology",
           "Waiting for A+ setups and sitting out the rest.",
           "Most bars are noise; forcing trades in the gaps between good setups bleeds the "
           "account.",
           apply="No setup, no trade. Cash is a position."),
    Lesson("overconfidence", "psychology",
           "Sizing up or loosening rules after a winning streak.",
           "A run of wins feels like skill even when it was partly variance; the next loss "
           "arrives oversized.",
           apply="Keep risk per trade fixed. Your best streak is when you should be MOST "
                 "boring."),
    Lesson("confirmation bias", "psychology",
           "Seeing only the evidence that supports the trade you already want.",
           "Once positioned, the brain filters for agreement and ignores the warning signs.",
           apply="Before entering, argue the OTHER side out loud. If you can't, you don't "
                 "understand the trade."),
    Lesson("recency bias", "psychology",
           "Overweighting your last few trades.",
           "A couple of losses make a good method feel broken; a couple of wins make a bad "
           "one feel great.",
           apply="Judge by expectancy over a large sample, not the last three trades."),
    Lesson("loss aversion", "psychology",
           "Holding a loser and hoping it comes back.",
           "Taking the loss admits you were wrong, so the mind avoids it — and a small loss "
           "becomes an account risk.",
           apply="Honor the stop the instant it's hit. Hope is not a plan."),
    Lesson("anchoring", "psychology",
           "Fixating on your entry price when deciding to exit.",
           "The market doesn't know or care where you got in; anchoring to it distorts every "
           "exit decision.",
           apply="Manage from the CURRENT structure and risk, not from your cost basis."),
    Lesson("analysis paralysis", "psychology",
           "Over-analyzing until every setup passes you by.",
           "Chasing certainty in a probabilistic game freezes you; the perfect read never "
           "arrives.",
           apply="A solid plan acted on beats a perfect plan delayed. Decide, size small, "
                 "execute."),
]

# ── money management ──────────────────────────────────────────────────────────

_MONEY = [
    Lesson("risk per trade", "money_management",
           "The fraction of the account you'll lose if a trade hits its stop (commonly ~1%).",
           "Fixed small risk means no single trade — or losing streak — can seriously hurt "
           "you; it's what keeps you in the game long enough for the edge to show.",
           apply="Set risk% first; the position size falls out of (account × risk%) ÷ stop "
                 "distance."),
    Lesson("drawdown", "money_management",
           "The decline from an equity peak to a trough.",
           "Recovery is asymmetric — a 50% loss needs a 100% gain to get back — so deep "
           "drawdowns are far harder to climb out of than they look.",
           apply="Keep risk per trade small so a bad run stays a shallow dip, not a hole."),
    Lesson("risk of ruin", "money_management",
           "The probability of losing enough capital to be unable to continue.",
           "Even a positive edge blows up if bets are too large — variance strings losses "
           "together, and oversizing turns a normal streak fatal.",
           apply="Small risk per trade + positive expectancy drives risk of ruin toward zero."),
    Lesson("position sizing (advanced)", "money_management",
           "Turning your risk% and stop distance into a share/contract count.",
           "Sizing off the stop (not a gut feeling) makes every trade risk the same amount, "
           "so wins and losses are comparable and the edge is measurable.",
           apply="Size = (account × risk%) ÷ (entry − stop). Wider stop → smaller size."),
    Lesson("compounding", "money_management",
           "Reinvesting gains so returns build on returns.",
           "A small consistent edge, compounded, grows far faster than it feels — and one "
           "big drawdown sets the compounding clock way back.",
           apply="Protect the downside first; consistent small gains compound, blow-ups reset."),
    Lesson("Kelly criterion", "money_management",
           "A formula for the bet size that maximizes long-run growth given your edge.",
           "Full Kelly maximizes growth but with wild swings; most pros use a fraction "
           "(half-Kelly) to cut volatility for far less give-up in return.",
           apply="Use a FRACTION of Kelly. Full Kelly's drawdowns are brutal.",
           aka=["kelly"]),
    Lesson("correlation risk", "money_management",
           "Multiple positions that move together are really one big bet.",
           "Five tech longs aren't diversified — one market move hits them all at once, so "
           "your real risk is several times what each line implies.",
           apply="Count correlated positions as one; don't stack the same bet under different "
                 "tickers."),
    Lesson("max daily loss", "money_management",
           "A hard cap on how much you'll lose in a single day.",
           "Bad days spiral — losses trigger tilt, tilt triggers bigger losses; a daily stop "
           "cuts the spiral before it wrecks the week.",
           apply="Hit the daily limit → close the platform. Tomorrow is a fresh, calmer you."),
]

# ── execution & market mechanics ──────────────────────────────────────────────

_EXECUTION = [
    Lesson("spread", "execution",
           "The gap between the best bid and the best ask.",
           "You buy at the ask and sell at the bid, so the spread is a cost you pay on every "
           "round trip — wide on illiquid names, it quietly eats the edge.",
           apply="Favor liquid instruments with tight spreads; the spread is a tax on every "
                 "trade."),
    Lesson("slippage", "execution",
           "Getting filled at a worse price than you intended.",
           "In fast or thin markets the price moves between your decision and your fill; "
           "market orders 'take' whatever's there.",
           apply="Use limit orders to control price in fast markets; accept market orders "
                 "only when the fill matters more than the price."),
    Lesson("liquidity", "execution",
           "How easily you can enter and exit without moving the price.",
           "Thin instruments gap and trap — you can get in but not out at a fair price, "
           "especially when you most need to.",
           apply="Trade liquid names, and size to the liquidity, not just to your account."),
    Lesson("market sessions", "execution",
           "Pre-market, the open, midday, the close, after-hours — each behaves differently.",
           "Volatility and volume cluster at the open and the close; midday is often quiet "
           "chop where breakouts fail.",
           apply="Trade the active windows (open/close); be skeptical of midday breakouts."),
    Lesson("market vs limit order", "execution",
           "Market = fill now at any price; limit = fill only at your price or better.",
           "It's a trade-off: speed and certainty of fill versus control of price.",
           apply="Limit to control your entry/exit price; market only when getting filled "
                 "beats getting a good price."),
    Lesson("order flow", "execution",
           "Watching where volume is actually trading (bid vs ask, size).",
           "Price is the story after the fact; order flow shows who is aggressive — buyers "
           "lifting the ask or sellers hitting the bid — in real time.",
           apply="Confirm a move with volume trading in its direction, not price alone."),
]

# ── process & edge ────────────────────────────────────────────────────────────

_PROCESS = [
    Lesson("trading plan", "process",
           "Written rules for what you trade, and how you size, enter, and exit.",
           "Decisions made calmly in advance beat decisions made under live pressure; the "
           "plan is what keeps emotion out of the trade.",
           apply="Write it down. If a trade isn't in the plan, it isn't a trade."),
    Lesson("edge", "process",
           "A repeatable reason your trades make money over a large sample.",
           "Without a defined edge you're gambling; with one, the job is simply to execute "
           "it consistently and let the numbers play out.",
           apply="Know your edge in one sentence. Only take trades that express it."),
    Lesson("trading journal", "process",
           "A record of every trade: setup, reason, size, result, and how you felt.",
           "You can't improve what you don't measure; the journal turns vague impressions "
           "into patterns you can actually fix.",
           apply="Log every trade and review weekly — the leaks show up in the data."),
    Lesson("backtesting", "process",
           "Testing a method against historical data before risking money.",
           "It tells you whether an idea ever had an edge and how it behaves in drawdown, "
           "so you risk capital on evidence, not a hunch.",
           apply="Validate on history first; forward-test small before sizing up."),
    Lesson("probabilistic thinking", "process",
           "Treating any single trade as one draw from a distribution.",
           "A good trade can lose and a bad trade can win; judging your method by one "
           "outcome is how people abandon a working edge (or trust a broken one).",
           apply="Grade the PROCESS, not the single result. The edge shows over dozens."),
    Lesson("review", "process",
           "Periodically analyzing your own trades to find and cut mistakes.",
           "Most traders repeat the same handful of errors; a regular review surfaces them "
           "so they stop costing you.",
           apply="Weekly: what worked, what leaked, one thing to fix next week."),
]

# ── trade & position management ───────────────────────────────────────────────

_MANAGEMENT = [
    Lesson("scaling in", "management",
           "Building a position in pieces rather than all at once.",
           "Starting small and adding as the trade proves right lowers the cost of being "
           "wrong early while still sizing up when you're right.",
           apply="Add only as the trade confirms — never average DOWN into a loser."),
    Lesson("scaling out", "management",
           "Taking partial profit while leaving a piece to run.",
           "It banks real gains (beating the urge to round-trip a winner) while keeping "
           "exposure to a big move.",
           apply="Take some off at the first target; trail the remainder."),
    Lesson("move to breakeven", "management",
           "Trailing the stop to your entry once the trade is comfortably in profit.",
           "It converts a winning trade into a free option — you can no longer lose on it — "
           "which also calms the decision-making.",
           apply="Once price has moved ~1R in your favor, slide the stop to entry."),
    Lesson("letting winners run", "management",
           "Not cutting a working trade early.",
           "A few big winners pay for many small losers; clipping every winner short starves "
           "the strategy of the trades that actually make the year.",
           apply="Trail the stop and let structure take you out — don't guess the exact top."),
    Lesson("cutting losers fast", "management",
           "Exiting a losing trade at the plan, immediately.",
           "Small losses are the cost of doing business; the account killer is the loss you "
           "let run 'just a little longer'.",
           apply="Hit the stop → out, no negotiation, no adding down."),
    Lesson("pyramiding", "management",
           "Adding to a winner with progressively smaller size in a strong trend.",
           "It presses an advantage while keeping average risk in check — but only works "
           "when a real trend is in force.",
           apply="Add smaller each time and raise the stop under the whole position."),
    Lesson("when not to trade", "management",
           "Recognizing the times to stay in cash.",
           "No clear setup, choppy conditions, thin liquidity, big news pending, or being "
           "tired/tilted — forcing trades then is where accounts bleed.",
           apply="No edge on the screen or off it → don't trade. Cash is a position."),
]


# ── index + query API ─────────────────────────────────────────────────────────

ALL_LESSONS: List[Lesson] = (_INDICATORS + _TRENDS + _CANDLES + _CHART_PATTERNS + _RISK
                             + _PSYCHOLOGY + _MONEY + _EXECUTION + _PROCESS + _MANAGEMENT)
_BY_NAME = {lesson.name.lower(): lesson for lesson in ALL_LESSONS}
for _l in ALL_LESSONS:                                   # index aliases too
    for _a in _l.aka:
        _BY_NAME.setdefault(_a.lower(), _l)


def catalog() -> dict:
    """Every name Athena knows, grouped by category."""
    out: dict = {}
    for lesson in ALL_LESSONS:
        out.setdefault(lesson.category, []).append(lesson.name)
    return out


def by_category(category: str) -> List[Lesson]:
    return [lesson for lesson in ALL_LESSONS if lesson.category == category]


def explain(name: str) -> Optional[Lesson]:
    """Find a lesson by name or alias (fuzzy: substring match as a fallback)."""
    if not name:
        return None
    key = name.strip().lower()
    if key in _BY_NAME:
        return _BY_NAME[key]
    for lesson_key, lesson in _BY_NAME.items():           # fuzzy contains
        if key in lesson_key or lesson_key in key:
            return lesson
    for lesson in ALL_LESSONS:
        if key in lesson.what.lower():
            return lesson
    return None


def teach(name: str) -> str:
    """A spoken-style explanation of one concept — what, why, and how to trade it."""
    lesson = explain(name)
    return lesson.teach() if lesson else f"I don't have a lesson on '{name}' yet."


def counts() -> dict:
    return {cat: len(names) for cat, names in catalog().items()}


def explain_chart(df) -> dict:
    """Read a chart (via signals_catalog) AND attach the why + how-to-trade for
    every signal found — detection plus playbook in one call."""
    from signals_catalog import read_chart
    result = read_chart(df)
    for sig in result["signals"]:
        lesson = explain(sig["name"])
        if lesson is not None:
            sig["why"] = lesson.why
            sig["entry"] = lesson.entry
            sig["take_profit"] = lesson.profit
            sig["stop_loss"] = lesson.stop
    return result

