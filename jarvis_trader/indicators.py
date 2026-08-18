"""
Technical indicators computed from raw candle lists.
Every indicator also emits a directional vote in [-100, +100]
(+ = bullish, - = bearish) so the AI council can score them.
"""
import math

# ------------------------------------------------------------------ #
# Detailed descriptions of every indicator (served at /api/reference
# and shown in the dashboard so you always know WHAT each vote means).
# ------------------------------------------------------------------ #
INDICATOR_INFO = {
    "RSI": {
        "name": "Relative Strength Index (14)",
        "what": "Momentum oscillator 0-100 comparing average gains vs average losses over 14 bars.",
        "how_scored": "<30 oversold -> bullish vote scaled by depth; >70 overbought -> bearish vote; between, a mild momentum lean around the 50 line.",
        "detail": "In strong uptrends RSI stays 40-80; in downtrends 20-60. Divergence between RSI and price warns of reversal.",
    },
    "MACD": {
        "name": "Moving Average Convergence Divergence (12,26,9)",
        "what": "EMA(12)-EMA(26) with a 9-EMA signal line; the histogram is their gap.",
        "how_scored": "Histogram sign and size vs the MACD scale -> -100..+100. Fresh sign flips are the strongest events (MACDCross strategy scores those separately).",
        "detail": "Crosses far above/below the zero line carry more meaning than crosses at zero.",
    },
    "EMA_TREND": {
        "name": "EMA Stack 20/50/200",
        "what": "Exponential moving averages weighting recent price; the 20/50/200 stack defines trend structure.",
        "how_scored": "+35 if EMA20>EMA50 else -35; +/-25 for price above/below EMA200 (regime); +/-20 for price above/below EMA20.",
        "detail": "20>50>200 with price above all = healthy uptrend. EMA200 cross = regime change.",
    },
    "BOLLINGER": {
        "name": "Bollinger Bands (20, 2sd)",
        "what": "20-bar SMA +/- 2 standard deviations - a dynamic volatility envelope.",
        "how_scored": "Position within the band scaled to a vote; touches beyond +/-95% of the band flip to a mean-reversion vote against the extreme.",
        "detail": "Band squeeze precedes volatility expansion; riding the upper band is trend strength, not an automatic sell.",
    },
    "STOCH": {
        "name": "Stochastic Oscillator (14,3)",
        "what": "Where the close sits inside the 14-bar high-low range (%K) with a 3-bar smoothing (%D).",
        "how_scored": "<20 with %K crossing above %D -> bullish; >80 with %K below %D -> bearish; else mild lean from the 50 line.",
        "detail": "Best in ranges; in trends only take signals in the trend direction.",
    },
    "ADX_DMI": {
        "name": "Average Directional Index + DMI (14)",
        "what": "ADX measures trend STRENGTH (not direction); +DI/-DI give the direction.",
        "how_scored": "Direction from +DI vs -DI, scaled by ADX/25 (capped 1.5x). ADX<15 shrinks all trend votes.",
        "detail": "ADX>25 = trending (use trend strategies), <15 = chop (use mean reversion).",
    },
    "VWAP": {
        "name": "Volume Weighted Average Price",
        "what": "Average traded price weighted by volume over the last 100 bars - the institutional fair price.",
        "how_scored": "Signed distance of price from VWAP scaled to -100..+100.",
        "detail": "Above VWAP = buyers in control intraday; pullbacks to VWAP in trends are entry zones.",
    },
    "SUPERTREND": {
        "name": "Supertrend (10, 3x ATR)",
        "what": "ATR-band trailing regime detector: flags whether price is in an up or down volatility regime.",
        "how_scored": "+50 in up-regime, -50 in down-regime.",
        "detail": "Simple but effective regime filter; agrees with EMA stack in clean trends.",
    },
    "ATR": {
        "name": "Average True Range (14)",
        "what": "Average bar range including gaps - the volatility yardstick.",
        "how_scored": "Not a directional vote. Used to place SL (1.5x ATR), TP (3x ATR = 2R) and the trailing stop.",
        "detail": "Position size = risk amount / stop distance, so ATR directly controls quantity.",
    },
}

STRATEGY_INFO = {
    "TrendFollowing": "EMA20/50/200 alignment + ADX>25 confirmation. Buys strength in uptrends, sells weakness in downtrends; halves its vote in chop.",
    "MeanReversion": "Fades RSI extremes (<25/>75) at Bollinger band touches. Only meaningful in ranging markets.",
    "Breakout": "Donchian 40-bar high/low breaks, +15 bonus when volume surges 1.4x average. Inside the range it leans with range position.",
    "MACDCross": "Scores fresh MACD signal-line crosses at +/-70, otherwise leans with histogram sign.",
    "VWAPPullback": "In uptrends, buying the pullback to VWAP (and mirror for downtrends) - the institutional re-load zone.",
    "ABCD_Projection": "Finds swing A, B, pullback C and projects D=(BxC)/A - a Gann/Fib price-symmetry target. Votes toward D while price travels, neutral at D (needs confirmation), momentum-only once broken.",
    "OrderFlow": "OHLCV order-flow proxy: volume-weighted close-position delta (aggression), delta flips, absorption (big volume/small range) and high-volume wick rejections.",
    "MathModel": "Linear-regression channel slope + z-score stretch, variance-ratio regime test (trend vs mean-revert), momentum z-scores and Fibonacci retracement confluence.",
}


def _closes(c):  return [x["c"] for x in c]
def _highs(c):   return [x["h"] for x in c]
def _lows(c):    return [x["l"] for x in c]
def _vols(c):    return [x["v"] for x in c]


def sma(vals, n):
    if len(vals) < n:
        return None
    return sum(vals[-n:]) / n


def ema_series(vals, n):
    if len(vals) < n:
        return []
    k = 2 / (n + 1)
    out = [sum(vals[:n]) / n]
    for v in vals[n:]:
        out.append(v * k + out[-1] * (1 - k))
    return out


def ema(vals, n):
    s = ema_series(vals, n)
    return s[-1] if s else None


def rsi(vals, n=14):
    if len(vals) < n + 1:
        return None
    gains, losses = [], []
    for i in range(1, len(vals)):
        d = vals[i] - vals[i - 1]
        gains.append(max(d, 0))
        losses.append(max(-d, 0))
    ag = sum(gains[:n]) / n
    al = sum(losses[:n]) / n
    for i in range(n, len(gains)):
        ag = (ag * (n - 1) + gains[i]) / n
        al = (al * (n - 1) + losses[i]) / n
    if al == 0:
        return 100.0
    rs = ag / al
    return 100 - 100 / (1 + rs)


def macd(vals, fast=12, slow=26, signal=9):
    if len(vals) < slow + signal:
        return None
    ef = ema_series(vals, fast)
    es = ema_series(vals, slow)
    m = [a - b for a, b in zip(ef[-len(es):], es)]
    sig = ema_series(m, signal)
    if not sig:
        return None
    return {"macd": m[-1], "signal": sig[-1], "hist": m[-1] - sig[-1]}


def bollinger(vals, n=20, k=2.0):
    if len(vals) < n:
        return None
    mid = sma(vals, n)
    var = sum((v - mid) ** 2 for v in vals[-n:]) / n
    sd = math.sqrt(var)
    return {"mid": mid, "upper": mid + k * sd, "lower": mid - k * sd, "width": 2 * k * sd}


def atr(candles, n=14):
    if len(candles) < n + 1:
        return None
    trs = []
    for i in range(1, len(candles)):
        h, l, pc = candles[i]["h"], candles[i]["l"], candles[i - 1]["c"]
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    a = sum(trs[:n]) / n
    for t in trs[n:]:
        a = (a * (n - 1) + t) / n
    return a


def stochastic(candles, n=14, d=3):
    if len(candles) < n + d:
        return None
    ks = []
    for i in range(n - 1, len(candles)):
        window = candles[i - n + 1:i + 1]
        hh = max(x["h"] for x in window)
        ll = min(x["l"] for x in window)
        c = candles[i]["c"]
        ks.append(100 * (c - ll) / (hh - ll) if hh != ll else 50)
    dv = sum(ks[-d:]) / d
    return {"k": ks[-1], "d": dv}


def adx(candles, n=14):
    if len(candles) < 2 * n + 1:
        return None
    plus_dm, minus_dm, trs = [], [], []
    for i in range(1, len(candles)):
        up = candles[i]["h"] - candles[i - 1]["h"]
        dn = candles[i - 1]["l"] - candles[i]["l"]
        plus_dm.append(up if (up > dn and up > 0) else 0)
        minus_dm.append(dn if (dn > up and dn > 0) else 0)
        h, l, pc = candles[i]["h"], candles[i]["l"], candles[i - 1]["c"]
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))

    def smooth(x):
        s = [sum(x[:n])]
        for v in x[n:]:
            s.append(s[-1] - s[-1] / n + v)
        return s

    str_, spd, smd = smooth(trs), smooth(plus_dm), smooth(minus_dm)
    dxs = []
    for i in range(len(str_)):
        if str_[i] == 0:
            continue
        pdi = 100 * spd[i] / str_[i]
        mdi = 100 * smd[i] / str_[i]
        if pdi + mdi == 0:
            continue
        dxs.append(100 * abs(pdi - mdi) / (pdi + mdi))
    if len(dxs) < n:
        return None
    a = sum(dxs[:n]) / n
    for d in dxs[n:]:
        a = (a * (n - 1) + d) / n
    pdi = 100 * spd[-1] / str_[-1] if str_[-1] else 0
    mdi = 100 * smd[-1] / str_[-1] if str_[-1] else 0
    return {"adx": a, "pdi": pdi, "mdi": mdi}


def vwap(candles):
    num = den = 0.0
    for c in candles[-100:]:
        tp = (c["h"] + c["l"] + c["c"]) / 3
        num += tp * c["v"]
        den += c["v"]
    return num / den if den else None


def supertrend_dir(candles, n=10, mult=3.0):
    """Very light supertrend: returns +1 (up) / -1 (down) / 0."""
    a = atr(candles, n)
    if a is None or len(candles) < n + 2:
        return 0
    c = candles[-1]
    mid = (c["h"] + c["l"]) / 2
    upper = mid + mult * a
    lower = mid - mult * a
    price = c["c"]
    prev = candles[-2]["c"]
    if price > upper - mult * a * 1.5 and price > prev:
        return 1
    if price < lower + mult * a * 1.5 and price < prev:
        return -1
    return 1 if price > mid else -1


# --------------------------------------------------------------------------- #
#  Snapshot + directional votes
# --------------------------------------------------------------------------- #

def snapshot(candles):
    """Full indicator snapshot + per-indicator directional votes."""
    cl = _closes(candles)
    price = cl[-1]
    out = {"price": price}
    votes = {}

    r = rsi(cl)
    out["rsi14"] = r
    if r is not None:
        if r < 30:   votes["RSI"] = min(100, (30 - r) * 4)          # oversold -> bullish
        elif r > 70: votes["RSI"] = -min(100, (r - 70) * 4)         # overbought -> bearish
        else:        votes["RSI"] = (r - 50) * 1.2                  # momentum lean

    m = macd(cl)
    out["macd"] = m
    if m:
        scale = max(abs(m["macd"]), abs(m["signal"]), 1e-9)
        votes["MACD"] = max(-100, min(100, 100 * m["hist"] / scale))

    e20, e50, e200 = ema(cl, 20), ema(cl, 50), ema(cl, 200)
    out["ema20"], out["ema50"], out["ema200"] = e20, e50, e200
    if e20 and e50:
        v = 0
        v += 35 if e20 > e50 else -35
        if e200:
            v += 25 if price > e200 else -25
        v += 20 if price > e20 else -20
        votes["EMA_TREND"] = v

    bb = bollinger(cl)
    out["bollinger"] = bb
    if bb and bb["width"] > 0:
        pos = (price - bb["mid"]) / (bb["width"] / 2)   # -1 .. +1 approx
        # mean reversion vote at extremes, momentum in middle
        if pos > 0.95:    votes["BOLLINGER"] = -40
        elif pos < -0.95: votes["BOLLINGER"] = 40
        else:             votes["BOLLINGER"] = pos * 30

    st = stochastic(candles)
    out["stochastic"] = st
    if st:
        if st["k"] < 20:  votes["STOCH"] = 45 if st["k"] > st["d"] else 20
        elif st["k"] > 80: votes["STOCH"] = -45 if st["k"] < st["d"] else -20
        else:              votes["STOCH"] = (st["k"] - 50) * 0.6

    ax = adx(candles)
    out["adx"] = ax
    if ax:
        strength = min(1.5, ax["adx"] / 25)
        direction = 1 if ax["pdi"] > ax["mdi"] else -1
        votes["ADX_DMI"] = max(-100, min(100, direction * 40 * strength))

    vw = vwap(candles)
    out["vwap"] = vw
    if vw:
        votes["VWAP"] = max(-100, min(100, (price - vw) / vw * 4000))

    stdir = supertrend_dir(candles)
    out["supertrend"] = stdir
    votes["SUPERTREND"] = stdir * 50

    a = atr(candles)
    out["atr14"] = a

    out["votes"] = {k: round(v, 1) for k, v in votes.items()}
    out["indicator_score"] = round(sum(votes.values()) / max(len(votes), 1), 1)
    return out
