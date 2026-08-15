"""
Jarvis's built-in trading knowledge base.

This is the "full knowledge about trading, stocks, market movements,
indicators and strategies" that Jarvis boots with, before any online
self-training happens. It is used two ways:
  1. Injected into the Gemini/Groq prompts as expert context.
  2. Encoded as prior rules inside the Jarvis ML brain feature builder.
"""

KNOWLEDGE = {
    "market_structure": [
        "Markets move in trends (impulse) and ranges (consolidation). Trade WITH the higher timeframe trend.",
        "Higher highs + higher lows = uptrend. Lower highs + lower lows = downtrend.",
        "Support becomes resistance after a breakdown, and resistance becomes support after a breakout (role reversal).",
        "Liquidity sits above swing highs and below swing lows; price often sweeps these levels before reversing.",
        "Volume confirms moves: breakouts on rising volume are reliable, breakouts on falling volume often fail.",
    ],
    "indicators": [
        "RSI(14): <30 oversold, >70 overbought. In strong trends RSI can stay pinned - use 40/80 in uptrends, 20/60 in downtrends.",
        "MACD: histogram flipping sign signals momentum shift; crosses far from zero line are stronger.",
        "EMA 20/50/200 stack: 20>50>200 = healthy uptrend. Price crossing the 200 EMA is a regime change.",
        "Bollinger Bands: price riding the upper band = strong trend, not automatically a sell. Band squeeze precedes volatility expansion.",
        "ADX >25 = trending market (use trend strategies), <15 = chop (use mean reversion). +DI/-DI gives direction.",
        "Stochastic works best in ranges; in trends only take signals in the trend direction.",
        "ATR measures volatility - use it for stop placement (1.5-2x ATR) and position sizing, never fixed pips.",
        "VWAP is the institutional fair price intraday. Above VWAP = buyers in control.",
    ],
    "strategies": [
        "Trend following: buy pullbacks to EMA20/50 in uptrends with ADX>25. Cut fast if structure breaks.",
        "Mean reversion: fade RSI extremes at Bollinger bands ONLY in ranging markets (ADX<20).",
        "Breakout: trade Donchian/40-bar range breaks with volume; place stop inside the broken range.",
        "News momentum: strong headlines + technical alignment = highest probability trades. Never fade fresh high-impact news.",
        "A-B-C-D price projection (Gann/Fibonacci style): find swing A, swing B, pullback C; project D = (B x C) / A. D is a reaction/target zone - price often reaches and reacts there. The level alone is NOT a signal: wait for price behavior at D plus confirmation, and always use a stop-loss.",
        "Swing structure: a pivot high/low confirmed by lower highs/higher lows either side defines A-B-C legs; invalid if the pullback C leaves the A-B range.",
        "Session timing: forex moves most in London/NY overlap; indices at cash open; crypto is 24/7 but follows US hours.",
    ],
    "candlestick_patterns": [
        "Reversal candles need context: Hammer/Dragonfly Doji/Piercing/Morning Star/Tweezer Bottom matter AFTER a decline; Shooting Star/Hanging Man/Gravestone/Dark Cloud/Evening Star/Tweezer Top matter AFTER a rise.",
        "Engulfing and Kicker patterns are the strongest 1-2 bar signals - a full body takeover or gap-flip in sentiment. Harami and Inside Bars signal compression; trade the breakout of their range.",
        "Three White Soldiers / Three Black Crows show sustained conviction; Rising/Falling Three Methods and Separating Lines are continuation - the prior trend usually resumes.",
        "Gaps (Rising/Falling Windows) act as support/resistance; Tasuki Gaps and Side-by-Side White Lines confirm the gap holds and trend continues.",
        "A Doji alone means indecision, not reversal - after a strong jump it warns 'confusion, upside only slightly preferred'.",
    ],
    "chart_patterns": [
        "Double/Triple Tops and Head & Shoulders are reversal patterns - confirmed only when the neckline breaks; target = pattern height projected from the break.",
        "Double/Triple Bottoms and Inverse H&S mirror that to the upside.",
        "Rising Wedge is bearish, Falling Wedge is bullish; Ascending Triangle (flat top, rising lows) breaks up, Descending Triangle breaks down, Symmetrical Triangle breaks either way - wait for the break.",
        "Flags and Pennants are continuation: sharp pole, tight counter-drift, then continuation in the pole's direction; measure the pole for the target.",
        "Rectangles: trade the range break; Cup & Handle and Rounding Bottom are bullish accumulation bases.",
        "Diamond Tops (bearish) and Diamond Bottoms (bullish) show volatility expanding then contracting around a turn; Broadening Formations mean instability - reduce size.",
    ],
    "order_flow": [
        "Order flow = reading aggression: closes near the high of a bar on volume = buyers lifting offers; closes near the low = sellers hitting bids.",
        "Cumulative delta (net buy-sell aggression) leading price = continuation; delta diverging from price = exhaustion.",
        "Absorption: huge volume with tiny range means a passive side is soaking up aggression - the move often reverses.",
        "Long wicks on high volume are stop hunts / rejection: the market swept liquidity then snapped back.",
        "Imbalance flips (delta changing sign with force) mark the moment control changes hands.",
    ],
    "mathematical_models": [
        "Linear regression channel: trade the slope; z-score of price vs the regression line measures statistical stretch.",
        "Variance ratio: Var(k-bar returns)/(k*Var(1-bar)) > 1 = trending regime (ride momentum), < 1 = mean-reverting regime (fade extremes).",
        "Momentum z-score above +/-2 = statistically unusual move; in trends it continues, in ranges it reverts.",
        "Fibonacci retracements 38.2/50/61.8% of the last swing are confluence zones, strongest when they align with VWAP/EMA/structure.",
        "A-B-C-D projection D=(BxC)/A and measured moves (target = pattern height) are price symmetry mathematics.",
        "Position sizing is math too: qty = (equity x risk%) / stop distance. Expectancy = win% x avgWin - loss% x avgLoss must be > 0.",
    ],
    "market_timings": [
        "Crypto trades 24/7. Forex trades 24/5 (Sun 22:00 UTC - Fri 21:00 UTC); most volume in London/NY overlap 12:00-16:00 UTC.",
        "US stocks/ETFs/indices cash session: Mon-Fri 09:30-16:00 ET (13:30-20:00 UTC). NSE India: Mon-Fri 09:15-15:30 IST.",
        "CME futures (gold, oil) run nearly 24h Sun 22:00 - Fri 21:00 UTC with a daily 21:00-22:00 UTC break.",
        "Never analyze or place trades on a CLOSED market: prices are stale, gaps at reopen invalidate stops.",
        "First/last 30 minutes of a cash session are the most volatile; midday is thin and choppy.",
    ],
    "risk_management": [
        "Risk a fixed % of equity per trade (0.5-2%). Position size = risk_amount / stop_distance.",
        "Always set SL and TP at order time. Minimum reward:risk of 1.5:1, prefer 2:1.",
        "Move stop to breakeven after price travels 1R in your favor; trail with ATR after 1.5R.",
        "Avoid trading right into high-impact economic events (FOMC, NFP, CPI) - spreads widen and stops get swept.",
        "Max 2-3 correlated positions at once. EURUSD and GBPUSD count as one trade.",
        "After 3 consecutive losses, halve size. Drawdown control beats win-rate optimization.",
    ],
    "market_movement_causes": [
        "Rates & central banks: hawkish = strong currency, weak stocks/gold. Dovish = the opposite.",
        "Earnings beats/misses gap single stocks; guidance matters more than the headline number.",
        "Risk-on: stocks, crypto, AUD up; JPY, USD, gold down. Risk-off is the mirror image.",
        "Oil up = inflation pressure = yields up = growth stocks pressured.",
        "Crypto follows liquidity cycles and ETF flows; BTC leads, alts amplify beta.",
    ],
}


def as_prompt_context(max_chars=3600):
    """Flatten knowledge into a compact expert-context block for LLM prompts."""
    lines = []
    for section, tips in KNOWLEDGE.items():
        lines.append(f"[{section.upper().replace('_', ' ')}]")
        for t in tips:
            lines.append(f"- {t}")
    text = "\n".join(lines)
    return text[:max_chars]


def all_rules():
    out = []
    for tips in KNOWLEDGE.values():
        out.extend(tips)
    return out
